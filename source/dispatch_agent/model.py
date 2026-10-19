"""领域模型：任务、执行人、候选排序、派单决策、异常记录。

只依赖标准库。所有字段都是可解释的，便于在执行轨迹里逐条打印。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Task:
    """待派发的任务（合成/脱敏输入）。"""

    id: str
    title: str
    domain: str
    task_type: str
    priority: int = 3
    tags: tuple[str, ...] = ()
    required_skills: tuple[str, ...] = ()

    @staticmethod
    def from_dict(raw: dict[str, Any]) -> "Task":
        return Task(
            id=str(raw["id"]),
            title=str(raw.get("title", "")),
            domain=str(raw["domain"]),
            task_type=str(raw["task_type"]),
            priority=int(raw.get("priority", 3)),
            tags=tuple(raw.get("tags", ())),
            required_skills=tuple(raw.get("required_skills", ())),
        )


@dataclass
class Member:
    """团队执行人。容量 = 同时可承接的任务数。"""

    id: str
    display: str
    domains: tuple[str, ...]
    skills: tuple[str, ...]
    capacity: int
    available: bool = True
    load: int = 0

    @property
    def free_slots(self) -> int:
        return max(0, self.capacity - self.load)

    def can_take(self, domain: str) -> bool:
        return self.available and self.free_slots > 0 and domain in self.domains


@dataclass(frozen=True)
class Candidate:
    """候选执行人及其被选中的理由（规则表匹配过程的产物）。"""

    member_id: str
    display: str
    score: float
    matched_skills: tuple[str, ...]
    free_slots: int
    reason: str


@dataclass(frozen=True)
class DispatchDecision:
    """一次派单的结果。chosen 为空表示没有可用候选，已按规则升级处理。"""

    task_id: str
    rule_id: str
    rule_name: str
    chosen: str | None
    candidates: tuple[Candidate, ...]
    reason: str
    escalated: bool = False


@dataclass(frozen=True)
class Rule:
    id: str
    name: str
    priority: int
    when: dict[str, Any]
    assign_to: dict[str, Any]
    on_no_candidate: str


@dataclass(frozen=True)
class Policy:
    """异常恢复策略（从 config/recovery_policy.json 读入）。"""

    states: dict[str, str]
    limits: dict[str, Any]
    transitions: tuple[dict[str, Any], ...]
    invariants: tuple[str, ...]


@dataclass
class ExceptionRecord:
    """一条异常处置记录：从哪个状态、因何、迁到哪个状态、做了什么动作。"""

    task_id: str
    kind: str
    at: str
    from_state: str
    to_state: str
    action: str
    detail: str = ""
    extra: dict[str, Any] = field(default_factory=dict)
