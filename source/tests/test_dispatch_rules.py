"""派单规则与候选排序的单元测试。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dispatch_agent.config import load_config_dir  # noqa: E402
from dispatch_agent.dispatch import DispatchEngine, match_rule, rank_candidates, rule_matches  # noqa: E402
from dispatch_agent.model import Member, Rule, Task  # noqa: E402

CONFIG = ROOT / "config"


def fresh_engine(recorder=None):
    members, rules, fallback, policy = load_config_dir(CONFIG)
    # 每个测试用独立副本，避免互相污染负载
    members = tuple(
        Member(m.id, m.display, m.domains, m.skills, m.capacity, m.available, 0) for m in members
    )
    return DispatchEngine(members, rules, fallback, recorder=recorder), rules, fallback, policy


class TestRuleMatching(unittest.TestCase):
    def test_domain_mismatch_rejects(self):
        rule = Rule("R", "n", 1, {"domain": "backend"}, {"domain_owner": "backend"}, "escalate_manual")
        task = Task("T", "t", "data", "etl")
        ok, why = rule_matches(rule, task)
        self.assertFalse(ok)
        self.assertIn("责任域不符", why)

    def test_task_type_whitelist(self):
        rule = Rule("R", "n", 1, {"task_type_in": ["api"]}, {"domain_owner": "backend"}, "escalate_manual")
        self.assertTrue(rule_matches(rule, Task("T", "t", "backend", "api"))[0])
        self.assertFalse(rule_matches(rule, Task("T", "t", "backend", "queue"))[0])

    def test_priority_floor(self):
        rule = Rule("R", "n", 1, {"priority_at_least": 4}, {"domain_owner": "ops"}, "escalate_manual")
        self.assertFalse(rule_matches(rule, Task("T", "t", "ops", "deploy", priority=3))[0])
        self.assertTrue(rule_matches(rule, Task("T", "t", "ops", "deploy", priority=4))[0])

    def test_tags_any(self):
        rule = Rule("R", "n", 1, {"tags_any": ["cross-team"]}, {"domain_owner": "qa"}, "escalate_manual")
        self.assertTrue(rule_matches(rule, Task("T", "t", "backend", "review", tags=("cross-team",)))[0])
        self.assertFalse(rule_matches(rule, Task("T", "t", "backend", "review", tags=("x",)))[0])

    def test_highest_priority_rule_wins(self):
        _, rules, fallback, _ = fresh_engine()
        task = Task("T", "t", "backend", "api", priority=4)
        rule, _why = match_rule(rules, fallback, task)
        self.assertEqual("R-010", rule.id)

    def test_fallback_used_when_nothing_matches(self):
        _, rules, fallback, _ = fresh_engine()
        task = Task("T", "t", "security", "audit")
        rule, why = match_rule(rules, fallback, task)
        self.assertEqual(fallback.id, rule.id)
        self.assertIn("兜底", why)


class TestCandidateRanking(unittest.TestCase):
    def test_skill_hit_outweighs_preference_rank(self):
        """打分权重：偏好位次 5 分/位，技能命中 10 分/项。

        所以「偏好第 1 位但少命中一个技能」会输给「偏好第 2 位但多命中一个技能」。
        这是刻意设计：规则表给的是倾向，技能匹配才是硬证据。
        """
        _, rules, _fallback, _ = fresh_engine()
        rule = next(r for r in rules if r.id == "R-010")  # preferred = [M-BE-01, M-BE-02]
        members = (
            Member("M-BE-01", "a", ("backend",), ("api",), 2),
            Member("M-BE-02", "b", ("backend",), ("api", "db", "queue"), 2),
        )
        ranked = rank_candidates(Task("T", "t", "backend", "api", required_skills=("api", "db")), rule, members)
        self.assertEqual(["M-BE-02", "M-BE-01"], [c.member_id for c in ranked])
        self.assertEqual(65.0, ranked[0].score)
        self.assertEqual(60.0, ranked[1].score)

    def test_preference_decides_when_skills_equal(self):
        _, rules, _fallback, _ = fresh_engine()
        rule = next(r for r in rules if r.id == "R-010")
        members = (
            Member("M-BE-01", "a", ("backend",), ("api",), 2),
            Member("M-BE-02", "b", ("backend",), ("api",), 2),
        )
        ranked = rank_candidates(Task("T", "t", "backend", "api", required_skills=("api",)), rule, members)
        self.assertEqual(["M-BE-01", "M-BE-02"], [c.member_id for c in ranked])
        self.assertIn("规则偏好第 1 位", ranked[0].reason)
        self.assertIn("规则偏好第 2 位", ranked[1].reason)

    def test_unavailable_and_full_members_are_excluded(self):
        _, rules, _fallback, _ = fresh_engine()
        rule = next(r for r in rules if r.id == "R-010")
        members = (
            Member("A", "a", ("backend",), ("api",), 2, available=False),
            Member("B", "b", ("backend",), ("api",), 1, available=True, load=1),
            Member("C", "c", ("backend",), ("api",), 2, available=True, load=0),
        )
        ranked = rank_candidates(Task("T", "t", "backend", "api"), rule, members)
        self.assertEqual(["C"], [c.member_id for c in ranked])

    def test_exclude_removes_member(self):
        _, rules, _fallback, _ = fresh_engine()
        rule = next(r for r in rules if r.id == "R-010")
        members = (
            Member("A", "a", ("backend",), ("api",), 2),
            Member("B", "b", ("backend",), ("api",), 2),
        )
        ranked = rank_candidates(Task("T", "t", "backend", "api"), rule, members, exclude=["A"])
        self.assertEqual(["B"], [c.member_id for c in ranked])


class TestDispatchEngine(unittest.TestCase):
    def test_assign_consumes_capacity(self):
        engine, _rules, _fallback, _ = fresh_engine()
        task = Task("T", "t", "data", "etl", required_skills=("etl", "sql"))
        d1 = engine.assign(task)
        self.assertEqual("M-DATA-01", d1.chosen)
        self.assertEqual(1, engine.member("M-DATA-01").load)
        d2 = engine.assign(Task("T2", "t", "data", "etl"))
        self.assertEqual("M-DATA-02", d2.chosen, "第一个人已满容量，应轮到第二个人")

    def test_no_candidate_escalates_instead_of_dropping(self):
        engine, _rules, _fallback, _ = fresh_engine()
        decision = engine.assign(Task("T", "t", "security", "audit"))
        self.assertTrue(decision.escalated)
        self.assertIsNone(decision.chosen)
        self.assertIn("escalate_manual", decision.reason)

    def test_release_frees_capacity(self):
        engine, _rules, _fallback, _ = fresh_engine()
        engine.assign(Task("T", "t", "ops", "deploy", priority=5))
        self.assertEqual(1, engine.member("M-OPS-01").load)
        engine.release("M-OPS-01")
        self.assertEqual(0, engine.member("M-OPS-01").load)

    def test_decision_is_explainable(self):
        engine, _rules, _fallback, _ = fresh_engine()
        d = engine.assign(Task("T", "t", "backend", "queue", required_skills=("queue",)))
        self.assertEqual("R-011", d.rule_id)
        self.assertIn("规则偏好第 1 位", d.reason)
        self.assertTrue(d.candidates[0].reason)


if __name__ == "__main__":
    unittest.main()
