"""Injectable clock. Engines and services never call datetime.now() directly."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Protocol


class Clock(Protocol):
    def today(self) -> date: ...

    def now(self) -> datetime: ...


class SystemClock:
    def today(self) -> date:
        return datetime.now(UTC).date()

    def now(self) -> datetime:
        return datetime.now(UTC)


class FixedClock:
    """A clock pinned to one instant (tests, reproducible demos)."""

    def __init__(self, value: date | datetime):
        if isinstance(value, datetime):
            self._now = value if value.tzinfo else value.replace(tzinfo=UTC)
        else:
            self._now = datetime(value.year, value.month, value.day, 12, 0, tzinfo=UTC)

    def today(self) -> date:
        return self._now.date()

    def now(self) -> datetime:
        return self._now
