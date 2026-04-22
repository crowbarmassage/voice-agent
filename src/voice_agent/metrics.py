"""Basic metrics counters and timers.

Lightweight in-process metrics for Phase 0. Counters and timers are
thread-safe. Designed to be replaced or augmented with Prometheus/StatsD
when the monitoring stack matures.

Usage:
    from voice_agent.metrics import metrics

    metrics.inc("calls_placed", payor="UHC")
    metrics.inc("ivr_navigation_success")

    with metrics.timer("stt_latency_ms"):
        transcript = await stt.transcribe(...)

    # Read current values
    metrics.get("calls_placed")  # → 5
    metrics.get_timer_avg("stt_latency_ms")  # → 342.1
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict
from contextlib import contextmanager
from dataclasses import dataclass, field


@dataclass
class TimerStats:
    count: int = 0
    total_ms: float = 0.0
    min_ms: float = float("inf")
    max_ms: float = 0.0

    @property
    def avg_ms(self) -> float:
        return self.total_ms / self.count if self.count else 0.0


class Metrics:
    """Thread-safe counters and timers."""

    def __init__(self):
        self._lock = threading.Lock()
        self._counters: dict[str, int] = defaultdict(int)
        self._timers: dict[str, TimerStats] = defaultdict(TimerStats)

    def inc(self, name: str, amount: int = 1, **tags) -> None:
        """Increment a counter."""
        key = self._key(name, tags)
        with self._lock:
            self._counters[key] += amount

    def get(self, name: str, **tags) -> int:
        """Get current counter value."""
        key = self._key(name, tags)
        with self._lock:
            return self._counters[key]

    @contextmanager
    def timer(self, name: str, **tags):
        """Context manager that records elapsed time in milliseconds."""
        start = time.monotonic()
        try:
            yield
        finally:
            elapsed_ms = (time.monotonic() - start) * 1000
            key = self._key(name, tags)
            with self._lock:
                stats = self._timers[key]
                stats.count += 1
                stats.total_ms += elapsed_ms
                stats.min_ms = min(stats.min_ms, elapsed_ms)
                stats.max_ms = max(stats.max_ms, elapsed_ms)

    def record_timer(self, name: str, elapsed_ms: float, **tags) -> None:
        """Record a timer value directly (when context manager isn't suitable)."""
        key = self._key(name, tags)
        with self._lock:
            stats = self._timers[key]
            stats.count += 1
            stats.total_ms += elapsed_ms
            stats.min_ms = min(stats.min_ms, elapsed_ms)
            stats.max_ms = max(stats.max_ms, elapsed_ms)

    def get_timer(self, name: str, **tags) -> TimerStats:
        """Get timer statistics."""
        key = self._key(name, tags)
        with self._lock:
            return self._timers[key]

    def snapshot(self) -> dict:
        """Return a snapshot of all counters and timers for reporting."""
        with self._lock:
            return {
                "counters": dict(self._counters),
                "timers": {
                    k: {
                        "count": v.count,
                        "avg_ms": v.avg_ms,
                        "min_ms": v.min_ms if v.count else 0,
                        "max_ms": v.max_ms,
                        "total_ms": v.total_ms,
                    }
                    for k, v in self._timers.items()
                },
            }

    def reset(self) -> None:
        """Reset all counters and timers."""
        with self._lock:
            self._counters.clear()
            self._timers.clear()

    @staticmethod
    def _key(name: str, tags: dict) -> str:
        if not tags:
            return name
        tag_str = ",".join(f"{k}={v}" for k, v in sorted(tags.items()))
        return f"{name}{{{tag_str}}}"


# Global metrics instance
metrics = Metrics()
