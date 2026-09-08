"""Fixed-clock execution of immutable D11S horizon plans."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from math import isfinite
from time import perf_counter

from mind_runtime.validation.composition import (
    CanonicalCertificationComposition,
    _DailyAuthorityRecords,
)
from mind_runtime.validation.contracts import (
    CertificationPlan,
    DailyDecisionDigest,
    DecisionAuthoritySnapshot,
)
from mind_runtime.validation.digest import canonical_json_bytes, sha256_bytes
from mind_runtime.validation.schedule import SimulationClock, ordered_events

CompositionFactory = Callable[
    [CertificationPlan, SimulationClock], CanonicalCertificationComposition
]


@dataclass(frozen=True, slots=True)
class HorizonDayCapture:
    virtual_day: int
    captured_at: datetime
    snapshot: DecisionAuthoritySnapshot
    records: _DailyAuthorityRecords

    def __post_init__(self) -> None:
        if isinstance(self.virtual_day, bool) or self.virtual_day < 0:
            raise ValueError("virtual_day must be non-negative")
        if self.captured_at.tzinfo is None or self.captured_at.utcoffset() != timedelta(0):
            raise ValueError("captured_at must be aware UTC")
        if not isinstance(self.snapshot, DecisionAuthoritySnapshot):
            raise ValueError("snapshot must be DecisionAuthoritySnapshot")
        if not isinstance(self.records, _DailyAuthorityRecords):
            raise ValueError("records must be full daily authority records")
        if self.records.snapshot != self.snapshot:
            raise ValueError("records snapshot must match the captured snapshot")


@dataclass(frozen=True, slots=True)
class HorizonRun:
    virtual_horizon_days: int
    daily_captures: tuple[HorizonDayCapture, ...]
    daily_digests: tuple[DailyDecisionDigest, ...]
    wall_clock_execution_seconds: float

    def __post_init__(self) -> None:
        if self.virtual_horizon_days not in (30, 90):
            raise ValueError("virtual_horizon_days must be exactly 30 or 90")
        if not isinstance(self.daily_captures, tuple) or not isinstance(self.daily_digests, tuple):
            raise ValueError("daily horizon records must be immutable tuples")
        expected_days = tuple(range(self.virtual_horizon_days + 1))
        if tuple(item.virtual_day for item in self.daily_captures) != expected_days:
            raise ValueError("daily captures must cover day zero through the final day")
        if tuple(item.virtual_day for item in self.daily_digests) != expected_days:
            raise ValueError("daily digests must cover day zero through the final day")
        if (
            isinstance(self.wall_clock_execution_seconds, bool)
            or not isinstance(self.wall_clock_execution_seconds, (int, float))
            or not isfinite(self.wall_clock_execution_seconds)
            or self.wall_clock_execution_seconds < 0
        ):
            raise ValueError("wall_clock_execution_seconds must be non-negative and finite")


class HorizonRunner:
    """Drive one canonical composition without system time, sleep, or background work."""

    def __init__(self, factory: CompositionFactory) -> None:
        if not callable(factory):
            raise ValueError("factory must be callable")
        self._factory = factory

    def run(self, plan: CertificationPlan) -> HorizonRun:
        """Execute every exact decoded event through the canonical pipeline.

        There is no validation-side duplicate detection or suppression here
        (ADR-0009): a repeated Evidence is admitted by the factual plane as
        REPLAY, so the event's turn runs normally — the audit Interaction is
        retained and registered recovery executes, while no Observation
        enters the turn. The verified schedule and virtual clock boundary
        are never skipped.
        """
        return self._run(plan, history_control_event_id=None)

    def _run_with_history_control(
        self,
        plan: CertificationPlan,
        *,
        history_control_event_id: str,
    ) -> HorizonRun:
        """Run verified events with the named event's history input withheld.

        The false-history control executes the exact same event (Evidence
        included) from an independent empty durable root; only the
        historical-context bundle of the named event is withheld, so the
        control differs from the treatment only by that counterfactual input.
        """
        if not history_control_event_id:
            raise ValueError("history control requires a named withheld event id")
        return self._run(
            plan,
            history_control_event_id=history_control_event_id,
            excluded_event_ids=frozenset(),
        )

    def _run_with_excluded_events(
        self,
        plan: CertificationPlan,
        *,
        excluded_event_ids: frozenset[str],
    ) -> HorizonRun:
        """Run a derived control plan against the verified template.

        The no-duplicate control plan carries the exact verified events minus
        the named duplicate event; ``_verify_plan`` re-binds the plan to the
        manifest-verified template bytes with that explicit exclusion. Nothing
        else may be dropped or altered.
        """
        if not excluded_event_ids:
            raise ValueError("excluded events control requires at least one named event")
        return self._run(
            plan,
            history_control_event_id=None,
            excluded_event_ids=excluded_event_ids,
        )

    def _run(
        self,
        plan: CertificationPlan,
        *,
        history_control_event_id: str | None,
        excluded_event_ids: frozenset[str] = frozenset(),
    ) -> HorizonRun:
        wall_started = perf_counter()
        events = ordered_events(plan)
        clock = SimulationClock(plan.started_at)
        composition = self._factory(plan, clock)
        if not isinstance(composition, CanonicalCertificationComposition):
            raise ValueError("factory must return CanonicalCertificationComposition")
        captures: list[HorizonDayCapture] = []
        digests: list[DailyDecisionDigest] = []
        event_index = 0
        try:
            composition._verify_plan(plan, excluded_event_ids=excluded_event_ids)
            for virtual_day in range(plan.horizon_days + 1):
                boundary = plan.started_at + timedelta(days=virtual_day)
                while (
                    event_index < len(events)
                    and plan.started_at + events[event_index].at_offset <= boundary
                ):
                    event = events[event_index]
                    clock.advance_to(plan.started_at + event.at_offset)
                    if event.event_id == history_control_event_id:
                        composition._apply_event_without_history(event)
                    else:
                        composition.apply_event(event)
                    event_index += 1
                clock.advance_to(boundary)
                composition.tick()
                records = composition._capture_daily_records()
                captures.append(HorizonDayCapture(virtual_day, boundary, records.snapshot, records))
                digests.append(_daily_digest(virtual_day, records))
        finally:
            composition.close()
        return HorizonRun(
            virtual_horizon_days=plan.horizon_days,
            daily_captures=tuple(captures),
            daily_digests=tuple(digests),
            wall_clock_execution_seconds=perf_counter() - wall_started,
        )


def _hash(value: object) -> str:
    return sha256_bytes(canonical_json_bytes(value))


def _daily_digest(virtual_day: int, records: _DailyAuthorityRecords) -> DailyDecisionDigest:
    return DailyDecisionDigest(
        virtual_day=virtual_day,
        canonical_state_hash=_hash(records.canonical_states),
        pending_intent_hash=_hash(
            (records.current_intents, records.intent_history, records.intent_transitions)
        ),
        transition_trace_hash=_hash((records.transition_results, records.state_transitions)),
        policy_decision_hash=_hash(records.policy_results),
        checkpoint_recovery_hash=_hash((records.checkpoint, records.recovery)),
    )
