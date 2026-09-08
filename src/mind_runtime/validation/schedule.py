"""Fixed UTC clock and immutable D11S event schedule validation."""

from datetime import datetime, timedelta

from mind_runtime.validation.contracts import CertificationPlan, SimulationEvent


def _require_utc(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("simulation time must be aware UTC")


class SimulationClock:
    """An explicitly advanced Clock with no system-time fallback."""

    def __init__(self, started_at: datetime) -> None:
        _require_utc(started_at)
        self._current = started_at

    def now(self) -> datetime:
        return self._current

    def set(self, value: datetime) -> None:
        self.advance_to(value)

    def advance(self, elapsed: timedelta) -> None:
        if elapsed < timedelta(0):
            raise ValueError("elapsed must be non-negative")
        self.advance_to(self._current + elapsed)

    def advance_to(self, value: datetime) -> None:
        _require_utc(value)
        if value < self._current:
            raise ValueError("simulation clock cannot move backward")
        self._current = value


def ordered_events(plan: CertificationPlan) -> tuple[SimulationEvent, ...]:
    """Validate and return the stable ``(offset, event_id)`` event order."""
    if not isinstance(plan, CertificationPlan):
        raise ValueError("plan must be a CertificationPlan")
    if not isinstance(plan.events, tuple):
        raise ValueError("schedule must be an immutable tuple")
    event_ids = tuple(event.event_id for event in plan.events)
    if len(event_ids) != len(set(event_ids)):
        raise ValueError("event IDs must be unique")
    horizon = timedelta(days=plan.horizon_days)
    if any(event.at_offset < timedelta(0) or event.at_offset > horizon for event in plan.events):
        raise ValueError("events must remain within the horizon")
    if horizon % plan.checkpoint_interval != timedelta(0):
        raise ValueError("checkpoint interval must land on the final horizon boundary")
    return tuple(sorted(plan.events, key=lambda event: (event.at_offset, event.event_id)))
