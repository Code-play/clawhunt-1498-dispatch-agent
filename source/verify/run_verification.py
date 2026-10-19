"""独立验证脚本（订单 #1498 · 派单 Agent）。

    python verify/run_verification.py

逐条断言「派单规则 / 恢复规则 / 执行轨迹」是否真的成立，并写：
  verify/verification_record.md    人可读记录
  verify/verification_result.json  机器可读结果

刻意不复用演示脚本的打印结果：这里重新加载配置、重新跑一遍状态机，
用独立断言去校验机制本身（包括两个已修复缺陷的回归断言）。
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dispatch_agent.config import load_config_dir  # noqa: E402
from dispatch_agent.dispatch import DispatchEngine, match_rule, rank_candidates  # noqa: E402
from dispatch_agent.model import Member, Task  # noqa: E402
from dispatch_agent.recovery import RecoveryController, RecoveryError, TaskState  # noqa: E402
from dispatch_agent.trace import TraceRecorder  # noqa: E402

CONFIG = ROOT / "config"
SAMPLES = ROOT / "samples" / "tasks.jsonl"
OUT = ROOT / "out"
PY = sys.executable


@dataclass
class Check:
    name: str
    expected: str
    actual: str
    passed: bool


def load_tasks() -> list[Task]:
    tasks = []
    for line in SAMPLES.read_text(encoding="utf-8").splitlines():
        if line.strip():
            tasks.append(Task.from_dict(json.loads(line)))
    return tasks


def fresh():
    members, rules, fallback, policy = load_config_dir(CONFIG)
    members = tuple(Member(m.id, m.display, m.domains, m.skills, m.capacity, m.available, 0) for m in members)
    engine = DispatchEngine(members, rules, fallback)
    return engine, rules, fallback, policy


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    checks: list[Check] = []
    lines: list[str] = []
    tasks = load_tasks()

    def add(name, expected, actual, ok):
        checks.append(Check(name, str(expected), str(actual), bool(ok)))

    lines.append("# 验证记录 · 派单 Agent（订单 #1498）\n")
    lines.append(f"生成时间（UTC）：{datetime.now(timezone.utc).isoformat()}")
    lines.append("复跑命令：`python verify/run_verification.py`\n")

    # ---------- 1. 配置 ----------
    lines.append("## 1. 配置加载与校验\n")
    engine, rules, fallback, policy = fresh()
    add("团队花名册加载", ">=4 人", len(engine.members), len(engine.members) >= 4)
    add("规则表加载", ">=3 条", len(rules), len(rules) >= 3)
    priorities = [r.priority for r in rules]
    add("规则按优先级降序", "降序", priorities, priorities == sorted(priorities, reverse=True))
    add("兜底规则存在", True, bool(fallback.id), bool(fallback.id))
    add("恢复策略含全部状态", ">=5 个", len(policy.states), len(policy.states) >= 5)
    add("恢复策略含额度限制", "max_retries/max_reassigns/manual_sla_hours",
        ",".join(sorted(k for k in policy.limits if k in ("max_retries", "max_reassigns", "manual_sla_hours"))),
        all(k in policy.limits for k in ("max_retries", "max_reassigns", "manual_sla_hours")))
    lines.append(f"- 团队 {len(engine.members)} 人；规则 {len(rules)} 条 + 兜底 1 条；状态 {len(policy.states)} 个\n")

    # ---------- 2. 派单规则 ----------
    lines.append("## 2. 派单规则（责任域 → 执行人）\n")
    decisions = []
    escalated = []
    for task in tasks:
        d = engine.assign(task)
        decisions.append(d)
        if d.escalated:
            escalated.append(task.id)
        add(f"{task.id} 命中规则", True, bool(d.rule_id), bool(d.rule_id))
        add(f"{task.id} 判定可解释", True, bool(d.reason), bool(d.reason))

    no_rule = [t for t in tasks if t.domain == "security"]
    rule, why = match_rule(rules, fallback, no_rule[0])
    add("无匹配任务走兜底规则", fallback.id, rule.id, rule.id == fallback.id)
    add("无候选任务被升级而非丢弃", "T-1006", ",".join(escalated), escalated == ["T-1006"])

    # 候选排序：技能命中（10 分/项）压过偏好位次（5 分/位）
    r010 = next(r for r in rules if r.id == "R-010")
    ranked = rank_candidates(
        Task("T", "t", "backend", "api", required_skills=("api", "db")),
        r010,
        (Member("M-BE-01", "a", ("backend",), ("api",), 2), Member("M-BE-02", "b", ("backend",), ("api", "db"), 2)),
    )
    add("技能命中压过偏好位次", "M-BE-02 第一", ranked[0].member_id, ranked[0].member_id == "M-BE-02")
    add("候选排序给出理由", True, bool(ranked[0].reason), bool(ranked[0].reason))

    # 容量约束
    engine2, _r, _f, _p = fresh()
    engine2.assign(Task("A", "a", "data", "etl"))
    d2 = engine2.assign(Task("B", "b", "data", "etl"))
    add("容量满后轮到下一人", "M-DATA-02", d2.chosen, d2.chosen == "M-DATA-02")
    lines.append(f"- 逐任务命中与候选排序均已给出（{len(decisions)} 条决策）")
    lines.append(f"- 无候选升级：{escalated or '无'}\n")

    # ---------- 3. 恢复规则 ----------
    lines.append("## 3. 恢复规则（异常状态机）\n")
    engine3, _r, _f, policy3 = fresh()
    ctrl = RecoveryController(policy3, engine3)

    backend = Task("T-1", "后端接口", "backend", "api", priority=4, required_skills=("api", "db"))
    engine3.assign(backend)
    st = TaskState("T-1", assignee="M-BE-01")
    r1 = ctrl.handle(backend, st, "timeout", at="2026-01-01T00:00:00Z")
    r2 = ctrl.handle(backend, st, "timeout")
    add("超时→退避重试", "retry_with_backoff", r1.action, r1.action == "retry_with_backoff")
    add("退避第一档 30s", 30, r1.extra.get("backoff_seconds"), r1.extra.get("backoff_seconds") == 30)
    add("退避第二档 120s", 120, r2.extra.get("backoff_seconds"), r2.extra.get("backoff_seconds") == 120)
    r3 = ctrl.handle(backend, st, "timeout")
    add("重试额度用尽→改派", "REASSIGNED", r3.to_state, r3.to_state == "REASSIGNED")
    add("回归：改派释放原执行人容量", 0, engine3.member("M-BE-01").load, engine3.member("M-BE-01").load == 0)

    while st.state != "AWAITING_MANUAL":
        ctrl.handle(backend, st, "rejected")
    add("驳回额度用尽→转人工", "AWAITING_MANUAL", st.state, st.state == "AWAITING_MANUAL")
    add("转人工带 SLA", 4, st.history[-1].extra.get("sla_hours"), st.history[-1].extra.get("sla_hours") == 4)
    ctrl.handle(backend, st, "manual_timeout")
    add("人工超时→死信区", "DEAD_LETTER", st.state, st.state == "DEAD_LETTER")
    add("死信记录可检查", True, bool(ctrl.dead_letters and ctrl.dead_letters[0].get("inspectable")),
        bool(ctrl.dead_letters and ctrl.dead_letters[0].get("inspectable")))
    dl = ctrl.dead_letters[0]
    required = ("task_id", "reason", "retry_count", "reassign_count", "trace", "recovery_suggestion", "next_state")
    add("死信记录字段齐全", ",".join(required), ",".join(k for k in required if k in dl),
        all(k in dl for k in required))

    # 人员不可用：有替代 vs 无替代
    engine4, _r, _f, policy4 = fresh()
    ctrl4 = RecoveryController(policy4, engine4)
    engine4.assign(backend)
    st4 = TaskState("T-1", assignee="M-BE-01")
    ru = ctrl4.handle(backend, st4, "member_unavailable")
    add("不可用且有替代→改派", "REASSIGNED", ru.to_state, ru.to_state == "REASSIGNED")

    engine5, _r, _f, policy5 = fresh()
    ctrl5 = RecoveryController(policy5, engine5)
    ops = Task("T-3", "运维发布", "ops", "deploy", priority=5)
    engine5.assign(ops)
    engine5.set_available("M-OPS-01", False)
    st5 = TaskState("T-3", assignee="M-OPS-01")
    ru5 = ctrl5.handle(ops, st5, "member_unavailable")
    add("不可用且无替代→转人工", "AWAITING_MANUAL", ru5.to_state, ru5.to_state == "AWAITING_MANUAL")

    # 非法事件必须报错而不是静默
    try:
        ctrl5.handle(ops, TaskState("T-x"), "not_an_event")
        err = "无异常"
    except RecoveryError:
        err = "RecoveryError"
    add("未定义事件抛错（不静默吞掉）", "RecoveryError", err, err == "RecoveryError")

    # 完成释放容量
    engine6, _r, _f, policy6 = fresh()
    ctrl6 = RecoveryController(policy6, engine6)
    data = Task("T-2", "数据 ETL", "data", "etl")
    engine6.assign(data)
    st6 = TaskState("T-2", assignee="M-DATA-01")
    rc = ctrl6.handle(data, st6, "completed")
    add("完成→DONE 并释放容量", "DONE/0", f"{rc.to_state}/{engine6.member('M-DATA-01').load}",
        rc.to_state == "DONE" and engine6.member("M-DATA-01").load == 0)
    lines.append("- 覆盖：超时退避 / 重试用尽改派 / 驳回用尽转人工 / 人员不可用（有替代·无替代）/ 人工超时进死信 / 完成释放容量")
    lines.append("- 回归断言：改派必须释放原执行人容量（否则容量单调泄漏导致误升级）\n")

    # ---------- 4. 执行轨迹 ----------
    lines.append("## 4. 执行轨迹\n")
    rec = TraceRecorder()
    rec.record("dispatch", task_id="T1", rule_id="R-010", chosen="M-BE-01")
    rec.record("recovery", at="2026-01-05T09:01:30Z", task_id="T1", kind="timeout", from_state="ASSIGNED", to_state="RETRYING", action="retry_with_backoff")
    rows = [json.loads(ln) for ln in rec.to_jsonl().splitlines() if ln.strip()]
    add("轨迹为可解析 JSONL", 2, len(rows), len(rows) == 2)
    add("seq 连续", "[1,2]", [r["seq"] for r in rows], [r["seq"] for r in rows] == [1, 2])
    stamps = [r["at"] for r in rows]
    add("时间戳单调不减", "非递减", ",".join(stamps), stamps == sorted(stamps))

    # 真实 demo 产出的轨迹：时序必须与 seq 同序
    trace_path = OUT / "dispatch_trace.jsonl"
    if trace_path.is_file():
        real = [json.loads(ln) for ln in trace_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
        real_stamps = [r["at"] for r in real]
        add("demo 轨迹时间戳单调不减", "非递减", f"{len(real)} 条", real_stamps == sorted(real_stamps))
        add("demo 轨迹含三类步骤", "dispatch/escalation/recovery",
            ",".join(sorted({r["step"] for r in real})),
            {"dispatch", "recovery", "escalation"} <= {r["step"] for r in real})
    else:
        add("demo 轨迹文件存在", True, False, False)

    # ---------- 5. 确定性 ----------
    lines.append("\n## 5. 一键复跑确定性\n")
    before = {p.name: sha(p) for p in (OUT / "dispatch_trace.jsonl", OUT / "expected_output.txt") if p.is_file()}
    proc = subprocess.run([PY, "-m", "dispatch_agent", "demo"], cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8")
    add("demo 复跑退出码", 0, proc.returncode, proc.returncode == 0)
    after = {p.name: sha(p) for p in (OUT / "dispatch_trace.jsonl", OUT / "expected_output.txt") if p.is_file()}
    add("两次运行产物逐字节一致", "哈希相同", ",".join(f"{k}:{'同' if before.get(k) == v else '异'}" for k, v in after.items()),
        bool(before) and before == after)

    # ---------- 6. 单元测试 ----------
    lines.append("\n## 6. 单元测试\n")
    ut = subprocess.run([PY, "-m", "unittest", "discover", "-s", "tests", "-t", "."], cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8")
    add("单元测试全部通过", "returncode 0", ut.returncode, ut.returncode == 0)
    tail = (ut.stderr or ut.stdout).strip().splitlines()
    lines.append("```")
    lines.extend(tail[-4:])
    lines.append("```")

    # ---------- 结论 ----------
    failed = [c for c in checks if not c.passed]
    lines.append("\n## 结论\n")
    lines.append(f"- 断言总数：{len(checks)}；通过：{len(checks) - len(failed)}；失败：{len(failed)}")
    lines.append(f"- 结果：**{'全部通过' if not failed else '存在失败项'}**\n")
    lines.append("| 断言 | 预期 | 实际 | 结果 |")
    lines.append("|---|---|---|---|")
    for c in checks:
        lines.append(f"| {c.name} | {c.expected} | {c.actual} | {'通过' if c.passed else '失败'} |")

    body = "\n".join(lines)
    (ROOT / "verify" / "verification_record.md").write_text(body, encoding="utf-8")
    (ROOT / "verify" / "verification_result.json").write_text(
        json.dumps(
            {
                "order": 1498,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "checks_total": len(checks),
                "checks_passed": len(checks) - len(failed),
                "checks_failed": len(failed),
                "all_passed": not failed,
                "checks": [c.__dict__ for c in checks],
            },
            ensure_ascii=False,
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )
    print(body)
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
