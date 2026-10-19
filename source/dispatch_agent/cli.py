"""命令行入口。

一键复跑（验收要求的三样样例都在这里产出）：

    python -m dispatch_agent demo

其它：

    python -m dispatch_agent dispatch --task-json '{"id":"T-X","title":"临时任务","domain":"backend","task_type":"api","priority":4,"required_skills":["api"]}'

只依赖 Python 标准库，不需要装任何第三方包。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .config import load_config_dir
from .dispatch import DispatchEngine
from .model import Task
from .recovery import RecoveryController, TaskState
from .trace import TraceRecorder

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = ROOT / "config"
DEFAULT_TASKS = ROOT / "samples" / "tasks.jsonl"
DEFAULT_OUT = ROOT / "out"

# 异常演练脚本（确定性，覆盖投标承诺的三类异常 + 人工超时进死信）
EVENT_PLAN: tuple[tuple[str, str, str], ...] = (
    ("T-1001", "timeout", "执行人未在 SLA 内受理"),
    ("T-1001", "timeout", "第二次超时"),
    ("T-1001", "timeout", "第三次超时（重试额度用尽）"),
    ("T-1001", "rejected", "交付被驳回：缺少接口契约"),
    ("T-1001", "member_unavailable", "执行人临时请假"),
    ("T-1001", "rejected", "交付再次被驳回"),
    ("T-1001", "manual_timeout", "人工接管 4h 未处理"),
    ("T-1003", "rejected", "口径不符，驳回"),
    ("T-1003", "completed", "返工后通过"),
    ("T-1004", "member_unavailable", "唯一运维执行人不可用"),
)


class Printer:
    """同时打印与落盘，保证 expected_output.txt 与屏幕输出逐字一致。"""

    def __init__(self) -> None:
        self.lines: list[str] = []

    def __call__(self, text: str = "") -> None:
        self.lines.append(text)
        print(text)

    def text(self) -> str:
        return "\n".join(self.lines) + "\n"


def load_tasks(path: Path) -> list[Task]:
    tasks: list[Task] = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            tasks.append(Task.from_dict(json.loads(line)))
        except (json.JSONDecodeError, KeyError) as exc:
            raise SystemExit(f"{path}:{lineno} 任务不合法: {exc}") from exc
    if not tasks:
        raise SystemExit(f"{path} 里没有任何任务")
    return tasks


def _section(out: Printer, title: str) -> None:
    out("")
    out("=" * 78)
    out(title)
    out("=" * 78)


def _rule_summary(rule) -> str:
    when = rule.when or {}
    bits = [f"域={when.get('domain', '*')}"]
    if when.get("task_type_in"):
        bits.append(f"类型∈{when['task_type_in']}")
    if when.get("priority_at_least") is not None:
        bits.append(f"优先级>={when['priority_at_least']}")
    if when.get("tags_any"):
        bits.append(f"标签∈{when['tags_any']}")
    owner = rule.assign_to.get("domain_owner") or "-"
    preferred = rule.assign_to.get("preferred") or []
    return f"{'，'.join(bits)} → 责任域 {owner}，优先 {preferred}"


def cmd_demo(args: argparse.Namespace) -> int:
    config_dir = Path(args.config_dir)
    out_dir = Path(args.out_dir)
    out = Printer()

    members, rules, fallback, policy = load_config_dir(config_dir)
    tasks = load_tasks(Path(args.tasks))

    recorder = TraceRecorder()
    engine = DispatchEngine(members, rules, fallback, recorder=recorder)
    controller = RecoveryController(policy, engine, recorder=recorder)

    out(f"# 派单 Agent · 一键复跑演示")
    out(f"配置目录: {config_dir}")
    out(f"任务输入: {Path(args.tasks)}（合成/脱敏，{len(tasks)} 条）")
    out(f"团队规模: {len(members)} 人；规则 {len(rules)} 条 + 兜底 1 条；状态机事件 {len(controller.known_events())} 种")

    # ---------------- 1) 派单规则示例 ----------------
    _section(out, "1. 派单规则示例（「责任域 → 执行人」规则表）")
    out("")
    out(f"{'规则ID':<7} {'优先级':<6} 匹配条件 → 分派目标")
    out("-" * 78)
    for r in rules:
        out(f"{r.id:<7} {r.priority:<6} {_rule_summary(r)}")
    out(f"{fallback.id:<7} {fallback.priority:<6} {_rule_summary(fallback)}（兜底）")

    out("")
    out("逐任务命中结果：")
    states: dict[str, TaskState] = {}
    for task in tasks:
        decision = engine.assign(task)
        st = TaskState(task_id=task.id, state="ASSIGNED" if decision.chosen else "AWAITING_MANUAL", assignee=decision.chosen)
        states[task.id] = st
        out("")
        out(f"[{task.id}] {task.title}（域={task.domain} 类型={task.task_type} 优先级={task.priority} 技能={list(task.required_skills)}）")
        out(f"  命中规则: {decision.rule_id} {decision.rule_name}")
        out(f"  判定过程: {decision.reason}")
        if decision.candidates:
            out("  候选排序:")
            for i, c in enumerate(decision.candidates, 1):
                out(f"    {i}. {c.member_id}（{c.display}）score={c.score:g} | {c.reason}")
        else:
            out("  候选排序: 无（已升级人工分派，任务不会被静默丢弃）")
            recorder.record(
                "escalation",
                at=recorder.clock.now(),
                task_id=task.id,
                what=f"无候选，按规则 {decision.rule_id} 执行 {task.domain} 域升级",
                reason=decision.reason,
            )

    # ---------------- 2) 恢复规则示例 ----------------
    _section(out, "2. 恢复规则示例（异常状态机）")
    out("")
    out("状态定义：")
    for name, desc in policy.states.items():
        out(f"  {name:<16} {desc}")
    out("")
    out("迁移表（异常 → 迁移 → 恢复动作）：")
    out("")
    out(f"{'事件':<20} {'允许的当前状态':<34} {'目标状态':<16} 动作")
    out("-" * 100)
    for tr in policy.transitions:
        out(f"{tr['on']:<20} {','.join(tr['from']):<34} {tr['to']:<16} {tr['action']}")

    out("")
    out("异常演练（确定性脚本，逐步打印状态迁移与恢复动作）：")
    # 让 T-1004 的唯一运维执行人不可用，以演示「不可用且无替代」的路径
    engine.set_available("M-OPS-01", False)
    for task_id, kind, detail in EVENT_PLAN:
        task = next(t for t in tasks if t.id == task_id)
        st = states[task_id]
        before = st.snapshot()
        record = controller.handle(task, st, kind, detail=detail, at=recorder.clock.now())
        out("")
        out(f"[{task_id}] 事件 {kind}：{detail}")
        out(f"  {before['state']}({before['assignee']}) --{kind}--> {record.to_state}({st.assignee})")
        out(f"  恢复动作: {record.action}｜{record.detail}")
        if record.extra:
            out(f"  附加信息: {json.dumps(record.extra, ensure_ascii=False)}")

    out("")
    out("终态汇总：")
    for task_id in sorted(states):
        st = states[task_id]
        out(f"  {task_id}: state={st.state} assignee={st.assignee} retry={st.retry_count} reassign={st.reassign_count}")

    # ---------------- 3) 执行轨迹 ----------------
    _section(out, "3. 执行轨迹（完整一次）")
    out("")
    out(recorder.render_table())
    out("")
    out(f"轨迹条目统计: {json.dumps(recorder.summary(), ensure_ascii=False)}")

    # ---------------- 产物落盘 ----------------
    out_dir.mkdir(parents=True, exist_ok=True)
    trace_path = recorder.write_jsonl(out_dir / "dispatch_trace.jsonl")
    dead_path = out_dir / "dead_letters.json"
    dead_path.write_text(json.dumps(controller.dead_letters, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    out("")
    out("死信区记录（可检查，含恢复建议与下一状态）：")
    out(json.dumps(controller.dead_letters, ensure_ascii=False, indent=2))

    report_path = out_dir / "dispatch_report.md"
    report_path.write_text(_render_report(tasks, states, recorder, controller), encoding="utf-8")

    _section(out, "产物")
    out(f"  {trace_path}   （执行轨迹 JSONL，{len(recorder.entries)} 条）")
    out(f"  {dead_path}   （死信记录 {len(controller.dead_letters)} 条）")
    out(f"  {report_path}   （Markdown 报告）")
    out(f"  {out_dir / 'expected_output.txt'}   （本文件，用于一键复跑比对）")
    (out_dir / "expected_output.txt").write_text(out.text(), encoding="utf-8")
    return 0


def _render_report(tasks, states, recorder, controller) -> str:
    lines = ["# 派单执行报告（自动生成）", ""]
    lines.append(f"- 任务数：{len(tasks)}")
    lines.append(f"- 轨迹条目：{len(recorder.entries)}")
    lines.append(f"- 死信：{len(controller.dead_letters)}")
    lines.append("")
    lines.append("## 任务终态")
    lines.append("")
    lines.append("| 任务 | 标题 | 状态 | 执行人 | 重试 | 改派 |")
    lines.append("| --- | --- | --- | --- | --- | --- |")
    for t in tasks:
        st = states[t.id]
        lines.append(f"| {t.id} | {t.title} | {st.state} | {st.assignee or '-'} | {st.retry_count} | {st.reassign_count} |")
    lines.append("")
    lines.append("## 执行轨迹")
    lines.append("")
    lines.append(recorder.render_table())
    lines.append("")
    lines.append("## 死信区")
    lines.append("")
    lines.append("```json")
    lines.append(json.dumps(controller.dead_letters, ensure_ascii=False, indent=2))
    lines.append("```")
    return "\n".join(lines) + "\n"


def cmd_dispatch(args: argparse.Namespace) -> int:
    config_dir = Path(args.config_dir)
    members, rules, fallback, _policy = load_config_dir(config_dir)
    engine = DispatchEngine(members, rules, fallback)
    task = Task.from_dict(json.loads(args.task_json))
    decision = engine.assign(task)
    print(json.dumps(
        {
            "task": task.id,
            "rule": f"{decision.rule_id} {decision.rule_name}",
            "chosen": decision.chosen,
            "escalated": decision.escalated,
            "reason": decision.reason,
            "candidates": [
                {"member": c.member_id, "score": c.score, "reason": c.reason} for c in decision.candidates
            ],
        },
        ensure_ascii=False,
        indent=2,
    ))
    return 0


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # pragma: no cover - 某些宿主不支持
        pass

    parser = argparse.ArgumentParser(prog="dispatch_agent", description="按团队职责分派任务与异常回收的 Bot")
    sub = parser.add_subparsers(dest="cmd")

    p_demo = sub.add_parser("demo", help="一键复跑：派单规则 / 恢复规则 / 执行轨迹")
    p_demo.add_argument("--config-dir", default=str(DEFAULT_CONFIG))
    p_demo.add_argument("--tasks", default=str(DEFAULT_TASKS))
    p_demo.add_argument("--out-dir", default=str(DEFAULT_OUT))
    p_demo.set_defaults(func=cmd_demo)

    p_one = sub.add_parser("dispatch", help="只派一个任务，打印决策 JSON")
    p_one.add_argument("--config-dir", default=str(DEFAULT_CONFIG))
    p_one.add_argument("--task-json", required=True)
    p_one.set_defaults(func=cmd_dispatch)

    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 2
    return int(args.func(args))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
