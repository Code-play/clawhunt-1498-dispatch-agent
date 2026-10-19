"""dispatch_agent —— 按团队职责分派任务与异常回收的 Bot（ClawHunt #1498）。

模块划分
--------
- ``config``     JSON 配置加载与校验（团队花名册 / 责任域规则表 / 恢复策略）
- ``model``      领域模型：任务、执行人、候选、派单决策、异常记录
- ``dispatch``   规则匹配与候选排序（派单规则）
- ``recovery``   异常状态机与死信区（恢复规则）
- ``trace``      执行轨迹记录与渲染（执行轨迹）
- ``cli``        命令行入口，一键复跑 demo

只依赖 Python 标准库。
"""

from __future__ import annotations

from .config import ConfigError, load_config_dir
from .dispatch import DispatchEngine, match_rule, rank_candidates
from .model import Candidate, DispatchDecision, ExceptionRecord, Member, Policy, Rule, Task
from .recovery import RecoveryController, RecoveryError, TaskState
from .trace import SyntheticClock, TraceRecorder

__all__ = [
    "ConfigError",
    "load_config_dir",
    "DispatchEngine",
    "match_rule",
    "rank_candidates",
    "Candidate",
    "DispatchDecision",
    "ExceptionRecord",
    "Member",
    "Policy",
    "Rule",
    "Task",
    "RecoveryController",
    "RecoveryError",
    "TaskState",
    "SyntheticClock",
    "TraceRecorder",
]

__version__ = "1.0.0"
