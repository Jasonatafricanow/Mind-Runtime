from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from typing import Any, cast

import pytest

from mind_runtime.validation import CertificationPlan, SimulationEvent
from mind_runtime.validation.schedule import SimulationClock, ordered_events

NOW = datetime(2026, 1, 1, 8, 0, tzinfo=UTC)
HEAD = "1" * 40
MANIFEST_SHA = "2" * 64


def make_event(
    event_id: str = "event-1", *, at_offset: timedelta = timedelta(0)
) -> SimulationEvent:
    return SimulationEvent(event_id, at_offset, (), None, "neutral_noop")


def make_plan(
    *,
    events: tuple[SimulationEvent, ...] = (make_event(),),
    checkpoint_interval: timedelta = timedelta(days=1),
) -> CertificationPlan:
    return CertificationPlan(
        certification_id="certification-1",
        source_head=HEAD,
        persona_version="kayla_v0",
        runtime_config_manifest_sha256=MANIFEST_SHA,
        horizon_days=30,
        started_at=NOW,
        events=events,
        checkpoint_interval=checkpoint_interval,
    )


def test_clock_advances_only_forward_and_stays_utc() -> None:
    clock = SimulationClock(NOW)

    clock.advance(timedelta(hours=12))
    clock.advance_to(NOW + timedelta(days=1))

    assert clock.now() == NOW + timedelta(days=1)
    with pytest.raises(ValueError, match="backward"):
        clock.advance_to(NOW)
    with pytest.raises(ValueError, match="backward"):
        clock.set(NOW)
    with pytest.raises(ValueError, match="non-negative"):
        clock.advance(timedelta(microseconds=-1))


@pytest.mark.parametrize(
    "invalid",
    [
        datetime(2026, 1, 1, 8, 0),
        datetime(2026, 1, 1, 10, 0, tzinfo=timezone(timedelta(hours=2))),
    ],
)
def test_clock_rejects_naive_or_non_utc_values(invalid: datetime) -> None:
    with pytest.raises(ValueError, match="aware UTC"):
        SimulationClock(invalid)

    clock = SimulationClock(NOW)
    with pytest.raises(ValueError, match="aware UTC"):
        clock.advance_to(invalid)


def test_schedule_orders_same_offset_by_event_id_without_mutating_plan() -> None:
    event_b = make_event("b", at_offset=timedelta(days=1))
    event_a = make_event("a", at_offset=timedelta(days=1))
    plan = make_plan(events=(event_b, event_a))

    assert ordered_events(plan) == (event_a, event_b)
    assert plan.events == (event_b, event_a)


@pytest.mark.parametrize(
    ("events", "message"),
    [
        ([make_event()], "immutable tuple"),
        ((make_event("duplicate"), make_event("duplicate")), "unique"),
        ((make_event(at_offset=timedelta(days=31)),), "horizon"),
    ],
)
def test_schedule_revalidates_tampered_plan_events(events: object, message: str) -> None:
    plan = make_plan()
    object.__setattr__(plan, "events", cast(Any, events))

    with pytest.raises(ValueError, match=message):
        ordered_events(plan)


def test_schedule_requires_checkpoint_interval_to_land_on_final_boundary() -> None:
    plan = make_plan(checkpoint_interval=timedelta(hours=7))

    with pytest.raises(ValueError, match="final horizon boundary"):
        ordered_events(plan)


def test_schedule_rejects_non_plan_and_clock_has_no_system_fallback() -> None:
    with pytest.raises(ValueError, match="CertificationPlan"):
        ordered_events(cast(Any, object()))
    with pytest.raises(TypeError):
        SimulationClock()  # type: ignore[call-arg]


def test_schedule_accepts_a_valid_shorter_checkpoint_interval() -> None:
    plan = replace(make_plan(), checkpoint_interval=timedelta(hours=6))

    assert ordered_events(plan) == plan.events
