"""Simulation clock.

The prototype runs on simulated time, not wall-clock time: a tick advances
the world by a fixed number of simulated minutes so a 48-hour logistics
scenario can be demonstrated in a couple of minutes.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass(frozen=True, slots=True)
class ClockSnapshot:
    tick: int
    now: datetime
    tick_minutes: int
    elapsed_hours: float


class SimulationClock:
    """Monotonic simulated clock, safe to advance from multiple threads."""

    def __init__(self, start: datetime, tick_minutes: int = 15) -> None:
        if tick_minutes <= 0:
            raise ValueError("tick_minutes must be positive")

        self._start = start
        self._now = start
        self._tick_minutes = tick_minutes
        self._tick = 0
        self._lock = threading.RLock()

    def advance(self, ticks: int = 1) -> datetime:
        """Moves the clock forward and returns the new simulated time."""
        if ticks < 1:
            raise ValueError("ticks must be >= 1")

        with self._lock:
            self._tick += ticks
            self._now = self._start + timedelta(
                minutes=self._tick_minutes * self._tick
            )
            return self._now

    def reset(self, start: datetime | None = None) -> None:
        with self._lock:
            self._start = start or self._start
            self._now = self._start
            self._tick = 0

    @property
    def now(self) -> datetime:
        with self._lock:
            return self._now

    @property
    def tick(self) -> int:
        with self._lock:
            return self._tick

    @property
    def start(self) -> datetime:
        return self._start

    def snapshot(self) -> ClockSnapshot:
        with self._lock:
            return ClockSnapshot(
                tick=self._tick,
                now=self._now,
                tick_minutes=self._tick_minutes,
                elapsed_hours=round(
                    (self._now - self._start).total_seconds() / 3600.0, 3
                ),
            )
