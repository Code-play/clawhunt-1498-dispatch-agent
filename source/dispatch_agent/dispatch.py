"""派单引擎：按「责任域 → 执行人」规则表把任务分派给团队成员。

设计要点
--------
1. 规则表驱动：命中哪条规则、为什么命中，都要能打印出来（验收要求「派单规则示例」）。
2. 候选排序可解释：分数由「规则偏好顺序 + 技能命中 + 剩余容量」合成，逐项给理由。
3. 没有候选时不静默丢弃：按规则里的 on_no_candidate 升级为人工分派。
"""

from __future__ import annotations

from typing import Iterable

from .model import Candidate, DispatchDecision, Member, Rule, Task


def rule_matches(rule: Rule, task: Task) -> tuple[bool, str]:
    """判断规则是否命中，并返回可读的命中理由。"""
    when = rule.when or {}
    reasons: list[str] = []

    domain = when.get("domain")
    if domain and domain != "*" and domain != task.domain:
        return False, f"责任域不符（规则要 {domain}，任务为 {task.domain}）"
    reasons.append(f"责任域={task.domain}")

    types = when.get("task_type_in") or []
    if types and task.task_type not in types:
        return False, f"任务类型 {task.task_type} 不在 {types} 内"
    if types:
        reasons.append(f"任务类型 {task.task_type} ∈ {types}")

    floor = when.get("priority_at_least")
    if floor is not None and task.priority < int(floor):
        return False, f"优先级 {task.priority} 低于下限 {floor}"
    if floor is not None:
        reasons.append(f"优先级 {task.priority} >= {floor}")

    tags_any = when.get("tags_any") or []
    if tags_any:
        hit = [t for t in task.tags if t in tags_any]
        if not hit:
            return False, f"标签 {list(task.tags)} 未命中 {tags_any}"
        reasons.append(f"标签命中 {hit}")

    return True, "，".join(reasons) if reasons else "无条件命中"


def match_rule(rules: Iterable[Rule], fallback: Rule, task: Task) -> tuple[Rule, str]:
    """按优先级顺序取第一条命中的规则；都不命中则用兜底规则。"""
    for rule in rules:
        ok, why = rule_matches(rule, task)
        if ok:
            return rule, why
    return fallback, "没有任何规则命中 → 使用兜底规则"


def rank_candidates(
    task: Task,
    rule: Rule,
    members: Iterable[Member],
    exclude: Iterable[str] = (),
) -> tuple[Candidate, ...]:
    """给可用成员打分并降序排列。不可用 / 无容量 / 责任域不符的成员直接排除。"""
    excluded = set(exclude)
    preferred = [str(x) for x in (rule.assign_to.get("preferred") or [])]
    owner_domain = rule.assign_to.get("domain_owner")
    wanted_domain = str(owner_domain) if owner_domain else task.domain

    out: list[Candidate] = []
    for m in members:
        if m.id in excluded:
            continue
        if not m.available:
            continue
        if m.free_slots <= 0:
            continue
        if wanted_domain not in m.domains:
            continue

        score = 0.0
        why: list[str] = []
        if m.id in preferred:
            bonus = 40.0 - 5.0 * preferred.index(m.id)
            score += bonus
            why.append(f"规则偏好第 {preferred.index(m.id) + 1} 位(+{bonus:g})")
        matched = tuple(s for s in task.required_skills if s in m.skills)
        if matched:
            score += 10.0 * len(matched)
            why.append(f"技能命中 {list(matched)}(+{10 * len(matched)})")
        if m.free_slots:
            score += 5.0 * m.free_slots
            why.append(f"剩余容量 {m.free_slots}(+{5 * m.free_slots:g})")

        out.append(
            Candidate(
                member_id=m.id,
                display=m.display,
                score=score,
                matched_skills=matched,
                free_slots=m.free_slots,
                reason="；".join(why) if why else "责任域匹配",
            )
        )
    out.sort(key=lambda c: (-c.score, c.member_id))
    return tuple(out)


class DispatchEngine:
    """把规则表套到团队上，产出派单决策并维护执行人负载。"""

    def __init__(
        self,
        members: Iterable[Member],
        rules: Iterable[Rule],
        fallback: Rule,
        recorder=None,
    ) -> None:
        self.members = {m.id: m for m in members}
        self.rules = tuple(rules)
        self.fallback = fallback
        self.recorder = recorder

    # ---- 查询 -------------------------------------------------------------
    def member(self, member_id: str) -> Member:
        return self.members[member_id]

    def available_members(self) -> tuple[Member, ...]:
        return tuple(m for m in self.members.values() if m.available and m.free_slots > 0)

    # ---- 派单 -------------------------------------------------------------
    def assign(self, task: Task, exclude: Iterable[str] = (), at: str | None = None, origin: str = "initial") -> DispatchDecision:
        """派单。at 用于让「改派」与触发它的那次状态迁移共用同一个时间戳。"""
        rule, why_rule = match_rule(self.rules, self.fallback, task)
        candidates = rank_candidates(task, rule, self.members.values(), exclude=exclude)

        if candidates:
            chosen = candidates[0]
            member = self.members[chosen.member_id]
            member.load += 1
            decision = DispatchDecision(
                task_id=task.id,
                rule_id=rule.id,
                rule_name=rule.name,
                chosen=member.id,
                candidates=candidates,
                reason=f"命中 {rule.id}（{why_rule}）→ 选中 {member.id}（{chosen.reason}）",
            )
        else:
            decision = DispatchDecision(
                task_id=task.id,
                rule_id=rule.id,
                rule_name=rule.name,
                chosen=None,
                candidates=(),
                reason=(
                    f"命中 {rule.id}（{why_rule}）但责任域 {rule.assign_to.get('domain_owner') or task.domain} "
                    f"下没有可用候选 → 按规则执行 {rule.on_no_candidate}"
                ),
                escalated=True,
            )

        if self.recorder is not None:
            self.recorder.record(
                "dispatch",
                at=at,
                origin=origin,
                task_id=task.id,
                rule_id=decision.rule_id,
                rule_name=decision.rule_name,
                chosen=decision.chosen,
                escalated=decision.escalated,
                candidates=[
                    {"member": c.member_id, "score": c.score, "reason": c.reason} for c in decision.candidates
                ],
                reason=decision.reason,
            )
        return decision

    # ---- 负载维护 ---------------------------------------------------------
    def release(self, member_id: str) -> None:
        m = self.members[member_id]
        m.load = max(0, m.load - 1)

    def set_available(self, member_id: str, available: bool) -> None:
        self.members[member_id].available = available
