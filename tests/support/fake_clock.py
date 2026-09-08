"""Deterministic clock for tests."""

from datetime import UTC, datetime, timedelta


class FakeClock:
    """A manually controlled aware-UTC clock."""

    def __init__(self, initial_now: datetime) -> None:
        self._current = self._as_utc(initial_now)

    def now(self) -> datetime:
        return self._current

    def set(self, now: datetime) -> None:
        self._current = self._as_utc(now)

    def advance(self, delta: timedelta) -> None:
        self._current += delta

    @staticmethod
    def _as_utc(value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("clock values must be timezone-aware")
        return value.astimezone(UTC)
