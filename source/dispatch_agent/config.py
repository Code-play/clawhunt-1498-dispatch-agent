"""配置加载与校验。

配置全部是 JSON（不是 YAML），刻意如此：本交付物只用 Python 标准库，
「一键复跑」不需要装任何第三方包。改配置即可换团队/换规则，无需改代码。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .model import Member, Policy, Rule


class ConfigError(ValueError):
    """配置缺失或非法。"""


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ConfigError(f"配置文件不存在: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:  # pragma: no cover - 只在坏配置时触发
        raise ConfigError(f"配置文件不是合法 JSON: {path} ({exc})") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"配置顶层必须是对象: {path}")
    return data


def load_team(path: Path) -> tuple[Member, ...]:
    """读团队花名册并校验。"""
    data = _read_json(path)
    members: list[Member] = []
    seen: set[str] = set()
    for raw in data.get("members", []):
        for key in ("id", "domains", "capacity"):
            if key not in raw:
                raise ConfigError(f"成员缺少字段 {key}: {raw}")
        mid = str(raw["id"])
        if mid in seen:
            raise ConfigError(f"成员 id 重复: {mid}")
        seen.add(mid)
        capacity = int(raw["capacity"])
        if capacity < 1:
            raise ConfigError(f"成员容量必须 >= 1: {mid}")
        members.append(
            Member(
                id=mid,
                display=str(raw.get("display", mid)),
                domains=tuple(raw["domains"]),
                skills=tuple(raw.get("skills", ())),
                capacity=capacity,
                available=bool(raw.get("available", True)),
            )
        )
    if not members:
        raise ConfigError(f"团队里没有任何成员: {path}")
    return tuple(members)


def load_rules(path: Path) -> tuple[tuple[Rule, ...], Rule]:
    """读「责任域 → 执行人」规则表，返回 (规则列表按优先级降序, 兜底规则)。"""
    data = _read_json(path)
    rules: list[Rule] = []
    seen: set[str] = set()
    for raw in data.get("rules", []):
        rid = str(raw["id"])
        if rid in seen:
            raise ConfigError(f"规则 id 重复: {rid}")
        seen.add(rid)
        rules.append(
            Rule(
                id=rid,
                name=str(raw.get("name", rid)),
                priority=int(raw.get("priority", 0)),
                when=dict(raw.get("when", {})),
                assign_to=dict(raw.get("assign_to", {})),
                on_no_candidate=str(raw.get("on_no_candidate", "escalate_manual")),
            )
        )
    if not rules:
        raise ConfigError(f"规则表为空: {path}")
    fallback_raw = data.get("default_rule")
    if not fallback_raw:
        raise ConfigError(f"规则表缺少 default_rule（兜底规则）: {path}")
    fallback = Rule(
        id=str(fallback_raw["id"]),
        name=str(fallback_raw.get("name", "兜底规则")),
        priority=int(fallback_raw.get("priority", 0)),
        when=dict(fallback_raw.get("when", {})),
        assign_to=dict(fallback_raw.get("assign_to", {})),
        on_no_candidate=str(fallback_raw.get("on_no_candidate", "escalate_manual")),
    )
    rules.sort(key=lambda r: r.priority, reverse=True)
    return tuple(rules), fallback


def load_policy(path: Path) -> Policy:
    """读异常恢复策略并校验状态机自洽性。"""
    data = _read_json(path)
    states = dict(data.get("states", {}))
    transitions = tuple(data.get("transitions", ()))
    if not states or not transitions:
        raise ConfigError(f"恢复策略缺少 states 或 transitions: {path}")
    known = set(states)
    for tr in transitions:
        for key in ("on", "from", "to", "action"):
            if key not in tr:
                raise ConfigError(f"迁移缺少字段 {key}: {tr}")
        for st in tr["from"]:
            if st not in known:
                raise ConfigError(f"迁移引用了未定义的状态 {st}（事件 {tr['on']}）")
        if tr["to"] not in known:
            raise ConfigError(f"迁移目标状态未定义: {tr['to']}")
        if tr.get("otherwise") and tr["otherwise"] not in known:
            raise ConfigError(f"迁移兜底状态未定义: {tr['otherwise']}")
    limits = dict(data.get("limits", {}))
    for key in ("max_retries", "max_reassigns", "manual_sla_hours"):
        if key not in limits:
            raise ConfigError(f"恢复策略缺少 limits.{key}")
    return Policy(
        states=states,
        limits=limits,
        transitions=transitions,
        invariants=tuple(data.get("invariants", ())),
    )


def load_config_dir(config_dir: Path) -> tuple[tuple[Member, ...], tuple[Rule, ...], Rule, Policy]:
    """一次读入整个 config/ 目录。"""
    config_dir = Path(config_dir)
    team = load_team(config_dir / "team.json")
    rules, fallback = load_rules(config_dir / "responsibilities.json")
    policy = load_policy(config_dir / "recovery_policy.json")
    return team, rules, fallback, policy
