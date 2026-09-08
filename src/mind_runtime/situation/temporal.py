"""Temporal semantics: deterministic, replayable time derivation (D6.1).

Everything computable from the clock is pure code: daypart, elapsed time.
The same inputs + the same Clock always produce the same derivation
(D6 merge gate: situation fully replayable under FakeClock).
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum


class Daypart(StrEnum):
    """Frozen daypart vocabulary (D6.1)."""

    NIGHT = "night"
    MORNING = "morning"
    AFTERNOON = "afternoon"
    EVENING = "evening"


def daypart(now: datetime) -> Daypart:
    """Derive the daypart from an aware-UTC instant (replayable)."""
    if now.tzinfo is None or now.utcoffset() != timedelta(0):
        raise ValueError("daypart requires an aware UTC instant")
    hour = now.hour
    if hour < 6:
        return Daypart.NIGHT
    if hour < 12:
        return Daypart.MORNING
    if hour < 18:
        return Daypart.AFTERNOON
    return Daypart.EVENING


@dataclass(frozen=True)
class TemporalSemantics:
    """One deterministic time derivation bundle for a situation."""

    now: datetime
    daypart: Daypart

    def elapsed_since(self, then: datetime | None) -> timedelta | None:
        """Elapsed time from ``then`` to now; None when unknown."""
        if then is None:
            return None
        return self.now - then

    @classmethod
    def at(cls, now: datetime) -> "TemporalSemantics":
        """Build the semantics at one instant (pure, replayable)."""
        return cls(now=now, daypart=daypart(now))
