from __future__ import annotations

from collections import defaultdict
from contextlib import contextmanager
from time import perf_counter_ns
from typing import Any, Iterator


class PerformanceProbe:
    """无依赖的小型探针，用于可复现的离线实验。"""

    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled
        self._started_ns = perf_counter_ns()
        self._stage_ms: dict[str, float] = defaultdict(float)
        self._stage_calls: dict[str, int] = defaultdict(int)
        self._counters: dict[str, int | float] = {}
        self._notes: list[str] = []

    @contextmanager
    def measure(self, stage: str) -> Iterator[None]:
        if not self.enabled:
            yield
            return
        started_ns = perf_counter_ns()
        try:
            yield
        finally:
            elapsed_ms = (perf_counter_ns() - started_ns) / 1_000_000
            self._stage_ms[stage] += elapsed_ms
            self._stage_calls[stage] += 1

    def set_counter(self, name: str, value: int | float) -> None:
        if self.enabled:
            self._counters[name] = value

    def increment(self, name: str, amount: int | float = 1) -> None:
        if self.enabled:
            self._counters[name] = self._counters.get(name, 0) + amount

    def note(self, message: str) -> None:
        if self.enabled and message not in self._notes:
            self._notes.append(message)

    def duration(self, stage: str) -> float:
        return round(self._stage_ms.get(stage, 0.0), 3)

    def snapshot(self) -> dict[str, Any]:
        total_ms = (perf_counter_ns() - self._started_ns) / 1_000_000
        measured_ms = sum(self._stage_ms.values())
        return {
            "clock": "time.perf_counter_ns",
            "total_ms": round(total_ms, 3) if self.enabled else None,
            "measured_stage_ms": round(measured_ms, 3) if self.enabled else None,
            "stages": [
                {
                    "name": name,
                    "duration_ms": round(duration, 3),
                    "calls": self._stage_calls[name],
                }
                for name, duration in self._stage_ms.items()
            ],
            "counters": dict(self._counters),
            "notes": list(self._notes),
            "scope": (
                "本地进程墙钟时间；不含真实大模型 token、网络延迟或 GPU 指标。"
                if self.enabled
                else "探针已关闭。"
            ),
        }
