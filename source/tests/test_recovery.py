"""异常回收状态机与死信区的单元测试。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dispatch_agent.config import load_config_dir  # noqa: E402
from dispatch_agent.dispatch import DispatchEngine  # noqa: E402
from dispatch_agent.model import Member, Task  # noqa: E402
from dispatch_agent.recovery import RecoveryController, RecoveryError, TaskState  # noqa: E402


def setup():
    members, rules, fallback, policy = load_config_dir(ROOT / "config")
    members = tuple(Member(m.id, m.display, m.domains, m.skills, m.capacity, m.available, 0) for m in members)
    engine = DispatchEngine(members, rules, fallback)
    controller = RecoveryController(policy, engine)
    return engine, controller


BACKEND_TASK = Task("T-1", "后端接口", "backend", "api", priority=4, required_skills=("api", "db"))
DATA_TASK = Task("T-2", "数据 ETL", "data", "etl", required_skills=("etl", "sql"))
OPS_TASK = Task("T-3", "运维发布", "ops", "deploy", priority=5, required_skills=("deploy",))


class TestTransitions(unittest.TestCase):
    def test_unknown_event_raises(self):
        _engine, controller = setup()
        with self.assertRaises(RecoveryError):
            controller.handle(BACKEND_TASK, TaskState("T-1"), "unknown_event")

    def test_event_not_allowed_from_state_raises(self):
        _engine, controller = setup()
        with self.assertRaises(RecoveryError):
            controller.handle(BACKEND_TASK, TaskState("T-1", state="DEAD_LETTER"), "timeout")

    def test_timeout_retries_with_backoff_then_reassigns(self):
        engine, controller = setup()
        engine.assign(BACKEND_TASK)
        st = TaskState("T-1", assignee="M-BE-01")

        r1 = controller.handle(BACKEND_TASK, st, "timeout", at="2026-01-01T00:00:00Z")
        self.assertEqual(("RETRYING", "retry_with_backoff"), (r1.to_state, r1.action))
        self.assertEqual(30, r1.extra["backoff_seconds"])

        r2 = controller.handle(BACKEND_TASK, st, "timeout")
        self.assertEqual(120, r2.extra["backoff_seconds"], "第二次退避取第二个档位")

        r3 = controller.handle(BACKEND_TASK, st, "timeout")
        self.assertEqual("REASSIGNED", r3.to_state)
        self.assertEqual("reassign_next_candidate", r3.action)
        self.assertEqual("M-BE-02", st.assignee)

    def test_reassign_releases_previous_capacity(self):
        """回归用例：改派必须释放原执行人的容量，否则容量单调泄漏。"""
        engine, controller = setup()
        engine.assign(BACKEND_TASK)
        st = TaskState("T-1", assignee="M-BE-01")
        self.assertEqual(1, engine.member("M-BE-01").load)

        for _ in range(2):
            controller.handle(BACKEND_TASK, st, "timeout")
        controller.handle(BACKEND_TASK, st, "timeout")  # 额度用尽 → 改派
        self.assertEqual(0, engine.member("M-BE-01").load, "原执行人的名额必须被释放")
        self.assertEqual(1, engine.member("M-BE-02").load)

    def test_rejected_reassigns_then_escalates_when_exhausted(self):
        engine, controller = setup()
        engine.assign(BACKEND_TASK)
        st = TaskState("T-1", assignee="M-BE-01")

        r1 = controller.handle(BACKEND_TASK, st, "rejected")
        self.assertEqual("REASSIGNED", r1.to_state)
        self.assertEqual(1, st.reassign_count)

        r2 = controller.handle(BACKEND_TASK, st, "rejected")
        self.assertEqual("REASSIGNED", r2.to_state)
        self.assertEqual(2, st.reassign_count)

        r3 = controller.handle(BACKEND_TASK, st, "rejected")
        self.assertEqual("AWAITING_MANUAL", r3.to_state)
        self.assertEqual("escalate_to_human", r3.action)
        self.assertEqual(4, r3.extra["sla_hours"], "转人工必须带 SLA")
        self.assertIsNone(st.assignee)
        self.assertEqual(0, engine.member("M-BE-02").load, "进人工队列后不占任何容量")

    def test_member_unavailable_reassigns_when_alternative_exists(self):
        engine, controller = setup()
        engine.assign(BACKEND_TASK)
        st = TaskState("T-1", assignee="M-BE-01")
        r = controller.handle(BACKEND_TASK, st, "member_unavailable")
        self.assertEqual(("REASSIGNED", "reassign_excluding_unavailable"), (r.to_state, r.action))
        self.assertEqual("M-BE-02", st.assignee)

    def test_member_unavailable_escalates_when_no_alternative(self):
        engine, controller = setup()
        engine.assign(OPS_TASK)
        engine.set_available("M-OPS-01", False)
        st = TaskState("T-3", assignee="M-OPS-01")
        r = controller.handle(OPS_TASK, st, "member_unavailable")
        self.assertEqual("AWAITING_MANUAL", r.to_state)
        self.assertEqual("escalate_to_human", r.action)

    def test_completed_releases_capacity_and_finishes(self):
        engine, controller = setup()
        engine.assign(DATA_TASK)
        st = TaskState("T-2", assignee="M-DATA-01")
        r = controller.handle(DATA_TASK, st, "completed")
        self.assertEqual(("DONE", "release_capacity"), (r.to_state, r.action))
        self.assertEqual(0, engine.member("M-DATA-01").load)


class TestDeadLetter(unittest.TestCase):
    def test_manual_timeout_parks_in_dead_letter_with_inspectable_record(self):
        engine, controller = setup()
        engine.assign(OPS_TASK)
        st = TaskState("T-3", assignee="M-OPS-01", state="AWAITING_MANUAL")
        r = controller.handle(OPS_TASK, st, "manual_timeout")
        self.assertEqual(("DEAD_LETTER", "park_in_dead_letter"), (r.to_state, r.action))
        self.assertEqual(1, len(controller.dead_letters))

        rec = controller.dead_letters[0]
        for key in ("task_id", "reason", "retry_count", "reassign_count", "trace", "recovery_suggestion", "next_state"):
            self.assertIn(key, rec, f"死信记录必须含 {key}")
        self.assertTrue(rec["inspectable"])
        self.assertEqual("AWAITING_MANUAL", rec["next_state"], "死信必须带明确的下一状态，而不是消失")

    def test_full_chain_reaches_dead_letter(self):
        """超时×3（末次改派）→ 驳回（改派）→ 驳回（额度用尽转人工）→ 人工超时 → 死信区。"""
        engine, controller = setup()
        engine.assign(BACKEND_TASK)
        st = TaskState("T-1", assignee="M-BE-01")
        for _ in range(3):
            controller.handle(BACKEND_TASK, st, "timeout")
        self.assertEqual(1, st.reassign_count, "第三次超时改派一次")

        while st.state != "AWAITING_MANUAL":
            controller.handle(BACKEND_TASK, st, "rejected")
        self.assertEqual("AWAITING_MANUAL", st.state)

        controller.handle(BACKEND_TASK, st, "manual_timeout")
        self.assertEqual("DEAD_LETTER", st.state)
        self.assertEqual(1, len(controller.dead_letters))
        self.assertEqual(2, st.retry_count)
        self.assertEqual(2, st.reassign_count, "改派额度 max_reassigns=2 用尽后转人工")


if __name__ == "__main__":
    unittest.main()
