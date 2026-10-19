"""配置校验与执行轨迹的单元测试。"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dispatch_agent.config import ConfigError, load_config_dir, load_policy, load_rules, load_team  # noqa: E402
from dispatch_agent.trace import SyntheticClock, TraceRecorder  # noqa: E402

CONFIG = ROOT / "config"


class TestConfig(unittest.TestCase):
    def test_loads_bundled_config(self):
        members, rules, fallback, policy = load_config_dir(CONFIG)
        self.assertGreaterEqual(len(members), 4)
        self.assertGreaterEqual(len(rules), 3)
        self.assertTrue(fallback.id)
        self.assertIn("ASSIGNED", policy.states)
        self.assertIn("max_retries", policy.limits)

    def test_rules_sorted_by_priority(self):
        _members, rules, _fallback, _policy = load_config_dir(CONFIG)
        priorities = [r.priority for r in rules]
        self.assertEqual(priorities, sorted(priorities, reverse=True))

    def _write(self, tmp: Path, name: str, payload) -> Path:
        path = tmp / name
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return path

    def test_missing_file_raises(self):
        with self.assertRaises(ConfigError):
            load_team(Path("does-not-exist.json"))

    def test_duplicate_member_id_raises(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            path = self._write(tmp, "team.json", {"members": [
                {"id": "A", "domains": ["x"], "capacity": 1},
                {"id": "A", "domains": ["x"], "capacity": 1},
            ]})
            with self.assertRaises(ConfigError):
                load_team(path)

    def test_zero_capacity_raises(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            path = self._write(tmp, "team.json", {"members": [{"id": "A", "domains": ["x"], "capacity": 0}]})
            with self.assertRaises(ConfigError):
                load_team(path)

    def test_transition_to_unknown_state_raises(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            path = self._write(tmp, "policy.json", {
                "states": {"ASSIGNED": "x"},
                "limits": {"max_retries": 1, "max_reassigns": 1, "manual_sla_hours": 1},
                "transitions": [{"on": "timeout", "from": ["ASSIGNED"], "to": "NOPE", "action": "a"}],
            })
            with self.assertRaises(ConfigError):
                load_policy(path)

    def test_missing_limits_raises(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            path = self._write(tmp, "policy.json", {
                "states": {"ASSIGNED": "x"},
                "limits": {"max_retries": 1},
                "transitions": [{"on": "timeout", "from": ["ASSIGNED"], "to": "ASSIGNED", "action": "a"}],
            })
            with self.assertRaises(ConfigError):
                load_policy(path)

    def test_missing_default_rule_raises(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            path = self._write(tmp, "rules.json", {"rules": [
                {"id": "R", "priority": 1, "when": {}, "assign_to": {}, "on_no_candidate": "escalate_manual"},
            ]})
            with self.assertRaises(ConfigError):
                load_rules(path)

    def test_broken_json_raises(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            path = tmp / "team.json"
            path.write_text("{not json", encoding="utf-8")
            with self.assertRaises(ConfigError):
                load_team(path)


class TestTrace(unittest.TestCase):
    def test_deterministic_output(self):
        """同一脚本复跑必须逐字节一致（一键复跑比对的前提）。"""
        a = TraceRecorder()
        b = TraceRecorder()
        for rec in (a, b):
            rec.record("dispatch", task_id="T", rule_id="R", chosen="M")
            rec.record("recovery", task_id="T", kind="timeout", from_state="ASSIGNED", to_state="RETRYING", action="retry_with_backoff")
        self.assertEqual(a.to_jsonl(), b.to_jsonl())

    def test_clock_is_monotonic(self):
        clock = SyntheticClock(start="2026-01-05T09:00:00Z", step_seconds=90)
        stamps = [clock.now() for _ in range(3)]
        self.assertEqual(["2026-01-05T09:00:00Z", "2026-01-05T09:01:30Z", "2026-01-05T09:03:00Z"], stamps)

    def test_jsonl_is_parseable_and_sequential(self):
        rec = TraceRecorder()
        rec.record("dispatch", task_id="T1", rule_id="R-010", chosen="M-BE-01")
        rec.record("recovery", task_id="T1", kind="timeout", from_state="ASSIGNED", to_state="RETRYING", action="retry_with_backoff")
        lines = [ln for ln in rec.to_jsonl().splitlines() if ln]
        self.assertEqual(2, len(lines))
        parsed = [json.loads(ln) for ln in lines]
        self.assertEqual([1, 2], [p["seq"] for p in parsed])
        self.assertEqual(["dispatch", "recovery"], [p["step"] for p in parsed])

    def test_explicit_at_does_not_consume_clock(self):
        rec = TraceRecorder()
        rec.record("recovery", at="2026-01-05T10:00:00Z", task_id="T", kind="timeout")
        self.assertEqual("2026-01-05T10:00:00Z", rec.entries[0]["at"])
        self.assertEqual("2026-01-05T09:00:00Z", rec.clock.now(), "显式时间不应消耗时钟")

    def test_render_table_has_one_row_per_entry(self):
        rec = TraceRecorder()
        rec.record("dispatch", task_id="T1", rule_id="R-010", chosen="M-BE-01")
        rec.record("recovery", task_id="T1", kind="timeout", from_state="ASSIGNED", to_state="RETRYING", action="retry_with_backoff")
        table = rec.render_table()
        self.assertEqual(4, len(table.splitlines()), "表头 + 分隔 + 2 行")

    def test_render_table_marks_reassign_origin(self):
        rec = TraceRecorder()
        rec.record("dispatch", task_id="T1", rule_id="R-010", chosen="M-BE-01", origin="reassign")
        self.assertIn("改派", rec.render_table())
        rec2 = TraceRecorder()
        rec2.record("dispatch", task_id="T1", rule_id="R-010", chosen="M-BE-01", origin="initial")
        self.assertIn("派单", rec2.render_table())


if __name__ == "__main__":
    unittest.main()
