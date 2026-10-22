"""Simulated time.

One tick is one simulated minute. In evaluation mode time only moves when the
agent acts (a fixed number of ticks per tool call), so a slower model faces
exactly the same state as a faster one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta


def parse_hhmm(value: str) -> int:
    hours, minutes = value.split(":")
    return int(hours) * 60 + int(minutes)


def format_minutes(total_minutes: int) -> str:
    total_minutes %= 24 * 60
    return f"{total_minutes // 60:02d}:{total_minutes % 60:02d}"


@dataclass
class SimClock:
    start_minutes: int
    trading_open: int
    trading_close: int
    minutes_per_tick: int = 1
    start_date: date = field(default_factory=lambda: date(2026, 11, 4))

    def minutes_at(self, tick: int) -> int:
        return self.start_minutes + tick * self.minutes_per_tick

    def label(self, tick: int) -> str:
        return format_minutes(self.minutes_at(tick))

    def timestamp(self, tick: int) -> str:
        """Date and time of a tick, e.g. "2026-11-04 10:05". Ticks may be negative (previous days)."""
        moment = datetime.combine(self.start_date, datetime.min.time()) + timedelta(minutes=self.minutes_at(tick))
        return moment.strftime("%Y-%m-%d %H:%M")

    def is_trading_session(self, tick: int) -> bool:
        minutes = self.minutes_at(tick) % (24 * 60)
        return self.trading_open <= minutes < self.trading_close
