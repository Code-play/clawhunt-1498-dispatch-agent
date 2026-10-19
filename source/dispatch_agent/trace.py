"""执行轨迹：把每一步（派单 / 恢复 / 收尾）记成结构化事件，可导出 JSONL。

验收标准要求「执行轨迹示例」，所以轨迹既是产物也是证据：
* 每条记录带 seq、step、时间、任务、规则/状态迁移与可读理由；
* 时间来自确定性时钟（固定起点 + 固定步长），保证「一键复跑」输出逐字节一致。
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


class SyntheticClock:
    """确定性时钟：固定起点，每次取时前进固定步长。"""

    def __init__(self, start: str = "2026-01-05T09:00:00Z", step_seconds: int = 90) -> None:
        self._t = datetime.strptime(start, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        self._step = timedelta(seconds=step_seconds)

    def now(self) -> str:
        value = self._t
        self._t = self._t + self._step
        return value.strftime("%Y-%m-%dT%H:%M:%SZ")


class TraceRecorder:
    """按顺序记录执行轨迹。"""

    def __init__(self, clock: SyntheticClock | None = None) -> None:
        self.clock = clock or SyntheticClock()
        self.entries: list[dict[str, Any]] = []

    def record(self, step: str, at: str | None = None, **fields: Any) -> dict[str, Any]:
        """记一条轨迹。传 at 时与调用方的时间戳共用一次时钟，避免同一步出现两个时间。"""
        entry: dict[str, Any] = {"seq": len(self.entries) + 1, "step": step, "at": at or self.clock.now()}
        entry.update(fields)
        self.entries.append(entry)
        return entry

    # ---- 导出 -------------------------------------------------------------
    def to_jsonl(self) -> str:
        return "\n".join(json.dumps(e, ensure_ascii=False, sort_keys=False) for e in self.entries) + "\n"

    def write_jsonl(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.to_jsonl(), encoding="utf-8")
        return path

    def render_table(self) -> str:
        """人可读的轨迹表。"""
        head = ["seq", "step", "at", "task", "what"]
        rows: list[list[str]] = []
        for e in self.entries:
            if e["step"] == "dispatch":
                tag = "改派" if e.get("origin") == "reassign" else "派单"
                what = f"{tag} 规则 {e.get('rule_id')} → {e.get('chosen') or '无候选(升级人工)'}"
            elif e["step"] == "recovery":
                what = f"{e.get('kind')}: {e.get('from_state')} → {e.get('to_state')} / {e.get('action')}"
            else:
                what = str(e.get("what", ""))
            rows.append([str(e["seq"]), str(e["step"]), str(e["at"]), str(e.get("task_id", "-")), what])

        widths = [len(h) for h in head]
        for r in rows:
            for i, cell in enumerate(r):
                widths[i] = max(widths[i], len(cell))

        def line(cells: list[str]) -> str:
            return "| " + " | ".join(c.ljust(widths[i]) for i, c in enumerate(cells)) + " |"

        sep = "|" + "|".join("-" * (w + 2) for w in widths) + "|"
        return "\n".join([line(head), sep] + [line(r) for r in rows])

    def summary(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for e in self.entries:
            counts[str(e["step"])] = counts.get(str(e["step"]), 0) + 1
        counts["total"] = len(self.entries)
        return counts
