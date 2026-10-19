"""异常回收：把「超时 / 驳回 / 人员不可用」描述为状态机，并给出恢复动作。

核心不变量（来自 config/recovery_policy.json 的 invariants）
----------------------------------------------------------
* 每个异常事件都必须能匹配到一条 from 命中的迁移；匹配不到就抛错，绝不静默吞掉。
* 额度用尽时升级为人工接管（AWAITING_MANUAL）并带 SLA；人工也超时才进死信区。
* 进死信区的记录必须可检查：任务、原因、重试/改派次数、完整轨迹、恢复建议、下一状态。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .dispatch import DispatchEngine
from .model import ExceptionRecord, Policy, Task


class RecoveryError(RuntimeError):
    """异常事件在当前状态下没有定义迁移，或策略自相矛盾。"""


@dataclass
class TaskState:
    """一个任务在恢复状态机里的当前状态。"""

    task_id: str
    state: str = "ASSIGNED"
    assignee: str | None = None
    retry_count: int = 0
    reassign_count: int = 0
    history: list[ExceptionRecord] = field(default_factory=list)

    def snapshot(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "state": self.state,
            "assignee": self.assignee,
            "retry_count": self.retry_count,
            "reassign_count": self.reassign_count,
        }


class RecoveryController:
    """按策略驱动状态迁移，并真正执行恢复动作（重试 / 改派 / 升级 / 死信）。"""

    def __init__(self, policy: Policy, engine: DispatchEngine, recorder=None) -> None:
        self.policy = policy
        self.engine = engine
        self.recorder = recorder
        self.dead_letters: list[dict[str, Any]] = []
        self._by_event: dict[str, list[dict[str, Any]]] = {}
        for tr in policy.transitions:
            self._by_event.setdefault(str(tr["on"]), []).append(tr)

    # ---- 策略查询 ---------------------------------------------------------
    def transition_for(self, kind: str, state: str) -> dict[str, Any]:
        for tr in self._by_event.get(kind, []):
            if state in tr["from"]:
                return tr
        raise RecoveryError(f"事件 {kind} 在状态 {state} 下没有定义迁移（策略不完整）")

    def known_events(self) -> tuple[str, ...]:
        return tuple(sorted(self._by_event))

    # ---- 主入口 -----------------------------------------------------------
    def handle(self, task: Task, st: TaskState, kind: str, detail: str = "", at: str = "") -> ExceptionRecord:
        tr = self.transition_for(kind, st.state)
        limits = self.policy.limits
        action = str(tr["action"])
        to_state = str(tr["to"])
        extra: dict[str, Any] = {}

        if kind == "timeout":
            if st.retry_count < int(limits["max_retries"]):
                st.retry_count += 1
                backoff = list(limits.get("backoff_seconds", [30]))
                wait = backoff[min(st.retry_count - 1, len(backoff) - 1)]
                action = "retry_with_backoff"
                to_state = str(tr["to"])
                extra = {"retry_count": st.retry_count, "backoff_seconds": wait}
                detail = detail or f"第 {st.retry_count} 次超时，退避 {wait}s 后重试"
            else:
                action = str(tr.get("otherwise_action", "reassign_next_candidate"))
                to_state = str(tr.get("otherwise", "REASSIGNED"))
                detail = detail or f"重试额度已用尽（max_retries={limits['max_retries']}）→ 改派"

        elif kind == "rejected":
            if st.reassign_count < int(limits["max_reassigns"]):
                action = "reassign_next_candidate"
                to_state = str(tr["to"])
            else:
                action = str(tr.get("otherwise_action", "escalate_to_human"))
                to_state = str(tr.get("otherwise", "AWAITING_MANUAL"))
                detail = detail or f"改派额度已用尽（max_reassigns={limits['max_reassigns']}）→ 转人工"

        elif kind == "member_unavailable":
            others = [m for m in self.engine.available_members() if m.id != st.assignee]
            if others:
                action = "reassign_excluding_unavailable"
                to_state = str(tr["to"])
                detail = detail or f"当前执行人不可用，改派给 {others[0].id}"
            else:
                action = str(tr.get("otherwise_action", "escalate_to_human"))
                to_state = str(tr.get("otherwise", "AWAITING_MANUAL"))
                detail = detail or "当前执行人不可用且无其它可用候选 → 转人工"

        # ---- 执行动作 -----------------------------------------------------
        prev_assignee = st.assignee
        if action in ("retry_with_backoff",):
            pass  # 执行人不变，只累计重试与退避
        elif action in ("reassign_next_candidate", "reassign_excluding_unavailable"):
            # 任务既然要离开原执行人，就必须先释放他占用的容量。
            # 否则每次改派都白占一个名额，容量会单调泄漏，最终把「还有别人能接」
            # 误判成「没人可用」而错误升级到人工（本机实测：第 4 次改派就会触发）。
            if prev_assignee:
                self.engine.release(prev_assignee)
            st.reassign_count += 1
            decision = self.engine.assign(
                task,
                exclude=[prev_assignee] if prev_assignee else [],
                at=at,
                origin="reassign",
            )
            if decision.chosen:
                st.assignee = decision.chosen
                extra["reassigned_to"] = decision.chosen
                extra["candidate_count"] = len(decision.candidates)
            else:
                st.assignee = None
                action = "escalate_to_human"
                to_state = "AWAITING_MANUAL"
                extra["candidate_count"] = 0
        elif action == "escalate_to_human":
            # 任务进入人工队列后不再占用任何执行人容量。
            if prev_assignee:
                self.engine.release(prev_assignee)
                st.assignee = None
            extra["sla_hours"] = int(tr.get("sla_hours", limits["manual_sla_hours"]))
        elif action == "park_in_dead_letter":
            extra["inspectable"] = bool(tr.get("inspectable", True))
            extra["next_state"] = str(tr.get("next_state", "AWAITING_MANUAL"))
        elif action == "release_capacity":
            if prev_assignee:
                self.engine.release(prev_assignee)

        record = ExceptionRecord(
            task_id=task.id,
            kind=kind,
            at=at,
            from_state=st.state,
            to_state=to_state,
            action=action,
            detail=detail,
            extra=extra,
        )
        st.state = to_state
        st.history.append(record)

        if action == "park_in_dead_letter":
            self.dead_letters.append(self.dead_letter_record(task, st, record))

        if self.recorder is not None:
            self.recorder.record(
                "recovery",
                at=record.at,
                task_id=task.id,
                kind=kind,
                from_state=record.from_state,
                to_state=record.to_state,
                action=record.action,
                detail=record.detail,
                extra=extra,
                assignee=st.assignee,
            )
        return record

    # ---- 死信区 -----------------------------------------------------------
    def dead_letter_record(self, task: Task, st: TaskState, trigger: ExceptionRecord) -> dict[str, Any]:
        """构造一条可检查的死信记录（含恢复建议与明确的下一状态）。"""
        return {
            "task_id": task.id,
            "title": task.title,
            "reason": f"人工接管超时未处理（触发事件 {trigger.kind}）",
            "retry_count": st.retry_count,
            "reassign_count": st.reassign_count,
            "last_assignee": st.assignee,
            "trace": [
                {
                    "kind": r.kind,
                    "from": r.from_state,
                    "to": r.to_state,
                    "action": r.action,
                    "detail": r.detail,
                    "at": r.at,
                }
                for r in st.history
            ],
            "recovery_suggestion": "核对责任域规则表是否缺少可承接该域的成员；补人后从 AWAITING_MANUAL 重新派发。",
            "next_state": str(trigger.extra.get("next_state", "AWAITING_MANUAL")),
            "inspectable": True,
        }
