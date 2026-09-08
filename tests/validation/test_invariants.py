"""Pure D11S invariant checks over captured authoritative records."""

import tempfile
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from typing import Any, cast

import pytest

from mind_runtime.contracts import AssessmentContribution
from mind_runtime.validation import HorizonDayCapture, HorizonRun, HorizonRunner
from mind_runtime.validation import invariants as invariant_subject
from mind_runtime.validation.invariants import (
    CapturedContribution,
    FalseHistoryInvariantResult,
    HistoryStepCapture,
    check_boundedness,
    check_false_history_reversible,
    check_no_self_excitation,
    check_registered_time_dynamics,
    check_replay,
)
from tests.validation.test_horizon import make_factory, make_plan


@pytest.fixture(scope="module")
def captured_run() -> HorizonRun:
    root = Path(tempfile.mkdtemp(prefix="d11s-invariants-"))
    return HorizonRunner(make_factory(root)).run(make_plan(30))


@pytest.fixture(scope="module")
def history_control_run() -> HorizonRun:
    """Independent root executing every event with only the false-history
    bundle withheld (ADR-0009: the duplicate event still runs normally)."""
    root = Path(tempfile.mkdtemp(prefix="d11s-history-control-"))
    plan = make_plan(30)
    false_event = next(event for event in plan.events if event.expected_path == "false_history")
    return HorizonRunner(make_factory(root))._run_with_history_control(
        plan,
        history_control_event_id=false_event.event_id,
    )


@pytest.fixture(scope="module")
def no_duplicate_control_run() -> HorizonRun:
    """Independent root derived from the exact verified template with the
    duplicate event removed (never built from the treatment trajectory)."""
    root = Path(tempfile.mkdtemp(prefix="d11s-no-duplicate-control-"))
    plan = make_plan(30)
    duplicate_event = next(
        event for event in plan.events if event.expected_path == "idempotent_replay"
    )
    control_plan = replace(
        plan,
        events=tuple(event for event in plan.events if event.event_id != duplicate_event.event_id),
    )
    return HorizonRunner(make_factory(root))._run_with_excluded_events(
        control_plan,
        excluded_event_ids=frozenset({duplicate_event.event_id}),
    )


def _with_state_value(capture: HorizonDayCapture, value: float) -> HorizonDayCapture:
    state = capture.records.canonical_states[0]
    records = replace(
        capture.records,
        canonical_states=(replace(state, value=value), *capture.records.canonical_states[1:]),
    )
    return replace(capture, records=records)


def _state_float(capture: HorizonDayCapture, index: int = 0) -> float:
    value = capture.records.canonical_states[index].value
    assert isinstance(value, float)
    return value


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf"), 1.01])
def test_non_finite_and_out_of_bounds_states_fail(captured_run: HorizonRun, value: float) -> None:
    result = check_boundedness(_with_state_value(captured_run.daily_captures[0], value))

    assert not result.passed
    assert result.evidence_refs


@pytest.mark.parametrize("value", [0.0, 1.0])
def test_bound_equality_is_accepted(captured_run: HorizonRun, value: float) -> None:
    capture = _with_state_value(captured_run.daily_captures[0], value)

    assert check_boundedness(capture).passed


def test_state_without_a_definition_fails(captured_run: HorizonRun) -> None:
    capture = captured_run.daily_captures[0]
    records = replace(capture.records, state_definitions=capture.records.state_definitions[1:])

    result = check_boundedness(replace(capture, records=records))

    assert not result.passed
    assert capture.records.canonical_states[0].state_id in result.evidence_refs


def test_duplicate_definitions_fail_closed(captured_run: HorizonRun) -> None:
    capture = captured_run.daily_captures[0]
    duplicate = capture.records.state_definitions[0]
    records = replace(
        capture.records,
        state_definitions=(*capture.records.state_definitions, duplicate),
    )

    assert not check_boundedness(replace(capture, records=records)).passed


@pytest.mark.parametrize("bounds", [None, (0.0,), (False, 1.0), (0.0, float("nan")), (1.0, 0.0)])
def test_invalid_definition_bounds_fail(captured_run: HorizonRun, bounds: object) -> None:
    capture = captured_run.daily_captures[0]
    state = capture.records.canonical_states[0]
    definitions = tuple(
        replace(item, bounds=bounds) if item.key == state.dimension else item
        for item in capture.records.state_definitions
    )
    records = replace(capture.records, state_definitions=definitions)

    assert not check_boundedness(replace(capture, records=records)).passed


def test_non_scalar_definition_is_not_treated_as_a_scalar_bound(
    captured_run: HorizonRun,
) -> None:
    from mind_runtime.contracts import StateValueType

    capture = captured_run.daily_captures[0]
    state = capture.records.canonical_states[0]
    definitions = tuple(
        replace(item, value_type=StateValueType.BOOLEAN, bounds=None)
        if item.key == state.dimension
        else item
        for item in capture.records.state_definitions
    )
    records = replace(
        capture.records,
        state_definitions=definitions,
        canonical_states=(replace(state, value=True), *capture.records.canonical_states[1:]),
    )

    assert check_boundedness(replace(capture, records=records)).passed


def test_scalar_state_must_be_numeric(captured_run: HorizonRun) -> None:
    capture = captured_run.daily_captures[0]
    state = capture.records.canonical_states[0]
    records = replace(
        capture.records,
        canonical_states=(
            replace(state, value="not-a-number"),
            *capture.records.canonical_states[1:],
        ),
    )

    assert not check_boundedness(replace(capture, records=records)).passed


def test_empty_state_capture_still_has_record_evidence(captured_run: HorizonRun) -> None:
    capture = captured_run.daily_captures[0]
    records = replace(capture.records, canonical_states=())

    result = check_boundedness(replace(capture, records=records))

    assert result.passed
    assert result.evidence_refs[0].startswith("daily-record:0:")


def test_boundedness_accepts_a_whole_run(captured_run: HorizonRun) -> None:
    assert check_boundedness(captured_run).passed


def _swap_digest_payloads(run: HorizonRun) -> HorizonRun:
    first, second, *tail = run.daily_digests
    changed = (
        replace(
            first,
            canonical_state_hash=second.canonical_state_hash,
            pending_intent_hash=second.pending_intent_hash,
            transition_trace_hash=second.transition_trace_hash,
            policy_decision_hash=second.policy_decision_hash,
            checkpoint_recovery_hash=second.checkpoint_recovery_hash,
        ),
        replace(
            second,
            canonical_state_hash=first.canonical_state_hash,
            pending_intent_hash=first.pending_intent_hash,
            transition_trace_hash=first.transition_trace_hash,
            policy_decision_hash=first.policy_decision_hash,
            checkpoint_recovery_hash=first.checkpoint_recovery_hash,
        ),
        *tail,
    )
    return replace(run, daily_digests=changed)


def test_replay_requires_every_daily_digest_in_order(captured_run: HorizonRun) -> None:
    result = check_replay(captured_run, _swap_digest_payloads(captured_run))

    assert not result.passed
    assert result.evidence_refs


@pytest.mark.parametrize("field", ["pending_intent_hash", "checkpoint_recovery_hash"])
def test_replay_rejects_different_intent_or_checkpoint_digest(
    captured_run: HorizonRun, field: str
) -> None:
    digest = captured_run.daily_digests[5]
    changed = (
        replace(digest, pending_intent_hash="f" * 64)
        if field == "pending_intent_hash"
        else replace(digest, checkpoint_recovery_hash="f" * 64)
    )
    replay = replace(
        captured_run,
        daily_digests=(*captured_run.daily_digests[:5], changed, *captured_run.daily_digests[6:]),
    )

    assert not check_replay(captured_run, replay).passed


def test_replay_rejects_extra_full_authority_record_even_with_same_digest(
    captured_run: HorizonRun,
) -> None:
    capture = captured_run.daily_captures[0]
    extra = captured_run.daily_captures[1].records.evidence[0]
    records = replace(capture.records, evidence=(*capture.records.evidence, extra))
    changed_capture = replace(capture, records=records)
    replay = replace(
        captured_run,
        daily_captures=(changed_capture, *captured_run.daily_captures[1:]),
    )

    assert not check_replay(captured_run, replay).passed


def test_replay_ignores_measured_wall_clock_metadata(captured_run: HorizonRun) -> None:
    replay = replace(
        captured_run,
        wall_clock_execution_seconds=captured_run.wall_clock_execution_seconds + 10.0,
    )

    assert check_replay(captured_run, replay).passed


def test_replay_includes_virtual_capture_timestamp(captured_run: HorizonRun) -> None:
    capture = captured_run.daily_captures[5]
    changed = replace(capture, captured_at=capture.captured_at + timedelta(seconds=1))
    replay = replace(
        captured_run,
        daily_captures=(
            *captured_run.daily_captures[:5],
            changed,
            *captured_run.daily_captures[6:],
        ),
    )

    assert not check_replay(captured_run, replay).passed


def test_replay_rejects_missing_capture_records_on_either_side(captured_run: HorizonRun) -> None:
    shortened = replace(captured_run)
    object.__setattr__(shortened, "daily_captures", shortened.daily_captures[:-1])

    assert not check_replay(captured_run, shortened).passed
    assert not check_replay(shortened, captured_run).passed


def test_no_false_history_control_uses_own_run_and_withholds_only_history(
    captured_run: HorizonRun,
    history_control_run: HorizonRun,
) -> None:
    treatment_false = captured_run.daily_captures[4]
    control_false = history_control_run.daily_captures[4]
    treatment_correction = captured_run.daily_captures[5]
    control_correction = history_control_run.daily_captures[5]

    assert treatment_false.records.transition_results[0].assessment_trace.history_refs
    assert control_false.records.transition_results[0].assessment_trace.history_refs == ()
    assert treatment_false.records.evidence == control_false.records.evidence
    assert treatment_correction.records.transition_results == (
        control_correction.records.transition_results
    )


def test_no_event_day_allows_no_change(captured_run: HorizonRun) -> None:
    result = check_registered_time_dynamics(
        captured_run.daily_captures[8],
        captured_run.daily_captures[9],
        accepted_event_refs=(),
    )

    assert result.passed


def _with_registered_recovery(
    before: HorizonDayCapture, after: HorizonDayCapture, *, policy: str
) -> HorizonDayCapture:
    state = before.records.canonical_states[0]
    changed_value = _state_float(before) + 0.01
    changed_state = replace(
        state,
        state_id=f"{state.state_id}-recovered",
        value=changed_value,
        version=state.version + 1,
        sync=replace(
            state.sync,
            object_id=f"{state.state_id}-recovered",
            version=state.version + 1,
            idempotency_key=f"{state.sync.idempotency_key}-recovered",
        ),
    )
    transition = before.records.transition_results[0]
    contribution = AssessmentContribution(
        dimension=state.dimension,
        source_kind="recovery",
        source_ref="recovery",
        amount=0.01,
        confidence=1.0,
        applied=True,
        reason_code=None,
    )
    trace = replace(
        transition.assessment_trace,
        trace_id=f"{transition.assessment_trace.trace_id}-recovery",
        state_before=tuple(
            (item.dimension, float(cast(float, item.value)))
            for item in before.records.canonical_states
        ),
        state_after=tuple(
            (
                item.dimension,
                (
                    changed_value
                    if item.dimension == state.dimension
                    else float(cast(float, item.value))
                ),
            )
            for item in before.records.canonical_states
        ),
        contributions=(contribution,),
        evidence_refs=(),
        history_refs=(),
        created_at=after.captured_at,
    )
    definition = next(
        item for item in before.records.state_definitions if item.key == state.dimension
    )
    definitions = tuple(
        replace(item, dynamics_policy=policy) if item.key == definition.key else item
        for item in before.records.state_definitions
    )
    records = replace(
        after.records,
        state_definitions=definitions,
        canonical_states=(changed_state, *before.records.canonical_states[1:]),
        transition_results=(replace(transition, assessment_trace=trace),),
    )
    return replace(after, records=records)


def test_no_event_day_allows_only_registered_recovery(captured_run: HorizonRun) -> None:
    before = captured_run.daily_captures[8]
    after = _with_registered_recovery(
        before, captured_run.daily_captures[9], policy="deterministic_affect"
    )

    assert check_registered_time_dynamics(before, after, accepted_event_refs=()).passed


def test_no_event_day_derives_policy_registration_from_captured_definitions(
    captured_run: HorizonRun,
) -> None:
    before = captured_run.daily_captures[8]
    state = before.records.canonical_states[0]
    policy = "manifest_registered_recovery"
    definitions = tuple(
        replace(item, dynamics_policy=policy) if item.key == state.dimension else item
        for item in before.records.state_definitions
    )
    registered_before = replace(
        before, records=replace(before.records, state_definitions=definitions)
    )
    after = _with_registered_recovery(
        registered_before,
        captured_run.daily_captures[9],
        policy=policy,
    )

    assert check_registered_time_dynamics(registered_before, after, ()).passed


@pytest.mark.parametrize("mutation", ["state_before", "state_after", "amount"])
def test_registered_recovery_reconciles_trace_to_actual_state_delta(
    captured_run: HorizonRun, mutation: str
) -> None:
    before = captured_run.daily_captures[8]
    after = _with_registered_recovery(
        before,
        captured_run.daily_captures[9],
        policy="deterministic_affect",
    )
    transition = after.records.transition_results[0]
    trace = transition.assessment_trace
    if mutation == "state_before":
        trace = replace(
            trace, state_before=((trace.state_before[0][0], trace.state_before[0][1] + 0.1),)
        )
    elif mutation == "state_after":
        trace = replace(
            trace, state_after=((trace.state_after[0][0], trace.state_after[0][1] + 0.1),)
        )
    else:
        contribution = replace(trace.contributions[0], amount=trace.contributions[0].amount + 0.1)
        trace = replace(trace, contributions=(contribution,))
    records = replace(
        after.records,
        transition_results=(replace(transition, assessment_trace=trace),),
    )

    assert not check_registered_time_dynamics(before, replace(after, records=records), ()).passed


def test_no_event_day_rejects_unregistered_or_untraced_change(captured_run: HorizonRun) -> None:
    before = captured_run.daily_captures[8]
    after = captured_run.daily_captures[9]
    unregistered = _with_registered_recovery(before, after, policy="invented_recovery")
    untraced = _with_state_value(after, _state_float(before) + 0.01)

    assert not check_registered_time_dynamics(before, unregistered, ()).passed
    assert not check_registered_time_dynamics(before, untraced, ()).passed
    assert not check_registered_time_dynamics(before, after, ("unexpected-event",)).passed


def test_repeated_idempotent_input_has_no_excitation(
    captured_run: HorizonRun,
    no_duplicate_control_run: HorizonRun,
) -> None:
    result = check_no_self_excitation(
        captured_run,
        make_plan(30).events,
        no_duplicate_control_run,
    )
    before = captured_run.daily_captures[2]
    repeat = captured_run.daily_captures[3]
    control_before = no_duplicate_control_run.daily_captures[2]
    control_repeat = no_duplicate_control_run.daily_captures[3]

    assert result.passed
    # The replay turn retains exactly one audit Interaction (ADR-0009 §3)
    # and adds no durable Evidence/Observation rows.
    assert len(repeat.records.interactions) == len(before.records.interactions) + 1
    assert repeat.records.interactions[-1].interaction_id.endswith("day-03-idempotent:interaction")
    assert repeat.records.evidence == before.records.evidence
    assert repeat.records.observations == before.records.observations
    # The no-duplicate control ran no turn at all: no interaction, no state
    # movement, no transition records, and its State equals the treatment's
    # pre-turn State.
    assert control_repeat.records.interactions == control_before.records.interactions
    assert control_repeat.records.canonical_states == control_before.records.canonical_states
    assert control_repeat.records.transition_results == control_before.records.transition_results
    assert control_repeat.records.canonical_states == before.records.canonical_states


def test_repeated_input_must_retain_its_audit_interaction(
    captured_run: HorizonRun,
    no_duplicate_control_run: HorizonRun,
) -> None:
    repeat = captured_run.daily_captures[3]
    records = replace(
        repeat.records,
        interactions=tuple(
            item
            for item in repeat.records.interactions
            if not item.interaction_id.endswith("day-03-idempotent:interaction")
        ),
    )
    changed = replace(
        captured_run,
        daily_captures=(
            *captured_run.daily_captures[:3],
            replace(repeat, records=records),
            *captured_run.daily_captures[4:],
        ),
    )

    result = check_no_self_excitation(changed, make_plan(30).events, no_duplicate_control_run)

    assert not result.passed
    assert "duplicate_audit_interaction" in result.observed


def test_repeated_input_requires_an_independent_no_duplicate_control(
    captured_run: HorizonRun,
) -> None:
    result = check_no_self_excitation(captured_run, make_plan(30).events)
    self_control = check_no_self_excitation(
        captured_run,
        make_plan(30).events,
        captured_run,
    )

    assert not result.passed
    assert not self_control.passed
    assert "duplicate_control_missing" in result.observed
    assert "duplicate_control_missing" in self_control.observed


def _with_net_zero_duplicate_reapplication(run: HorizonRun) -> HorizonRun:
    before = run.daily_captures[2]
    repeat = run.daily_captures[3]
    transition = repeat.records.transition_results[0]
    trace = transition.assessment_trace
    recovery = next(
        item
        for item in trace.contributions
        if item.applied and item.source_kind == "recovery" and item.amount != 0
    )
    replayed_event = replace(
        recovery,
        source_kind="event",
        source_ref="reapplied-duplicate-event",
        amount=-recovery.amount,
    )
    state_values = tuple(
        (state.dimension, float(cast(float, state.value)))
        for state in before.records.canonical_states
    )
    changed_trace = replace(
        trace,
        trace_id=f"{trace.trace_id}-reapplied",
        state_before=state_values,
        state_after=state_values,
        contributions=(recovery, replayed_event),
        evidence_refs=(make_plan(30).events[2].evidence[0].id,),
        created_at=repeat.captured_at,
    )
    records = replace(
        repeat.records,
        transition_results=(replace(transition, assessment_trace=changed_trace),),
    )
    return replace(
        run,
        daily_captures=(
            *run.daily_captures[:3],
            replace(repeat, records=records),
            *run.daily_captures[4:],
        ),
    )


def test_net_zero_event_reapplication_cannot_cancel_registered_recovery(
    captured_run: HorizonRun,
    no_duplicate_control_run: HorizonRun,
) -> None:
    changed = _with_net_zero_duplicate_reapplication(captured_run)

    result = check_no_self_excitation(
        changed,
        make_plan(30).events,
        no_duplicate_control_run,
    )

    assert not result.passed
    assert "duplicate_event_reapplied" in result.observed


def test_no_duplicate_control_rejects_event_pollution(
    captured_run: HorizonRun,
    no_duplicate_control_run: HorizonRun,
) -> None:
    # Fabricate an event reapplication inside the independent control's
    # duplicate-day capture: the control must stay clean.
    polluted_control = _with_fabricated_event_contribution(no_duplicate_control_run)

    result = check_no_self_excitation(
        captured_run,
        make_plan(30).events,
        polluted_control,
    )

    assert not result.passed
    assert "duplicate_control_polluted" in result.observed


def _with_fabricated_event_contribution(run: HorizonRun) -> HorizonRun:
    """Inject a bogus event-contribution transition into the control's
    duplicate-day capture (the control runs no turn there, so the pollution
    must be constructed rather than derived from a real trace)."""
    before = run.daily_captures[2]
    repeat = run.daily_captures[3]
    transition = before.records.transition_results[0]
    trace = transition.assessment_trace
    fabricated = replace(
        trace,
        trace_id=f"{trace.trace_id}-fabricated-event",
        contributions=(
            AssessmentContribution(
                dimension="agent.affect.anxiety",
                source_kind="event",
                source_ref="reapplied-duplicate-event",
                amount=0.14,
                confidence=1.0,
                applied=True,
                reason_code=None,
            ),
        ),
        evidence_refs=(make_plan(30).events[2].evidence[0].id,),
        created_at=repeat.captured_at,
    )
    records = replace(
        repeat.records,
        transition_results=(replace(transition, assessment_trace=fabricated),),
    )
    return replace(
        run,
        daily_captures=(
            *run.daily_captures[:3],
            replace(repeat, records=records),
            *run.daily_captures[4:],
        ),
    )


def test_repeated_idempotency_key_with_changed_value_fails(
    captured_run: HorizonRun,
    no_duplicate_control_run: HorizonRun,
) -> None:
    capture = _with_state_value(
        captured_run.daily_captures[3],
        _state_float(captured_run.daily_captures[2]) + 0.1,
    )
    changed = replace(
        captured_run,
        daily_captures=(
            *captured_run.daily_captures[:3],
            capture,
            *captured_run.daily_captures[4:],
        ),
    )

    assert not check_no_self_excitation(
        changed, make_plan(30).events, no_duplicate_control_run
    ).passed


def test_repeated_idempotency_trace_amount_must_reconcile_zero_delta(
    captured_run: HorizonRun,
    no_duplicate_control_run: HorizonRun,
) -> None:
    repeat = captured_run.daily_captures[3]
    transition = repeat.records.transition_results[0]
    trace = transition.assessment_trace
    contribution = replace(trace.contributions[0], amount=trace.contributions[0].amount + 0.01)
    records = replace(
        repeat.records,
        transition_results=(
            replace(
                transition,
                assessment_trace=replace(
                    trace, contributions=(contribution, *trace.contributions[1:])
                ),
            ),
        ),
    )
    changed = replace(
        captured_run,
        daily_captures=(
            *captured_run.daily_captures[:3],
            replace(repeat, records=records),
            *captured_run.daily_captures[4:],
        ),
    )

    assert not check_no_self_excitation(
        changed, make_plan(30).events, no_duplicate_control_run
    ).passed


def test_assistant_expression_cannot_enter_evidence(
    captured_run: HorizonRun,
    no_duplicate_control_run: HorizonRun,
) -> None:
    final = captured_run.daily_captures[-1]
    evidence, interaction_id = final.records.evidence[0]
    polluted = replace(evidence, source_type="assistant_expression")
    records = replace(
        final.records,
        evidence=((polluted, interaction_id), *final.records.evidence[1:]),
    )
    changed = replace(
        captured_run,
        daily_captures=(*captured_run.daily_captures[:-1], replace(final, records=records)),
    )

    result = check_no_self_excitation(changed, make_plan(30).events, no_duplicate_control_run)

    assert not result.passed
    assert evidence.id in result.evidence_refs


def test_assistant_expression_payload_and_non_mapping_payload_are_audited(
    captured_run: HorizonRun,
    no_duplicate_control_run: HorizonRun,
) -> None:
    final = captured_run.daily_captures[-1]
    evidence, interaction_id = final.records.evidence[0]
    polluted = replace(evidence, payload={"kind": "assistant_expression"})
    non_mapping = replace(final.records.evidence[1][0], payload="plain text")
    records = replace(
        final.records,
        evidence=(
            (polluted, interaction_id),
            (non_mapping, final.records.evidence[1][1]),
            *final.records.evidence[2:],
        ),
    )
    changed = replace(
        captured_run,
        daily_captures=(*captured_run.daily_captures[:-1], replace(final, records=records)),
    )

    assert not check_no_self_excitation(
        changed, make_plan(30).events, no_duplicate_control_run
    ).passed


def test_repeated_idempotency_key_cannot_add_an_evidence_row(
    captured_run: HorizonRun,
    no_duplicate_control_run: HorizonRun,
) -> None:
    repeat = captured_run.daily_captures[3]
    evidence, interaction_id = repeat.records.evidence[0]
    duplicate = replace(
        evidence,
        id=f"{evidence.id}-duplicate",
        sync=replace(evidence.sync, object_id=f"{evidence.id}-duplicate"),
    )
    records = replace(
        repeat.records,
        evidence=(*repeat.records.evidence, (duplicate, interaction_id)),
    )
    changed = replace(
        captured_run,
        daily_captures=(
            *captured_run.daily_captures[:3],
            replace(repeat, records=records),
            *captured_run.daily_captures[4:],
        ),
    )

    assert not check_no_self_excitation(
        changed, make_plan(30).events, no_duplicate_control_run
    ).passed


def test_old_history_ref_cannot_reappear_without_explicit_resupply(
    captured_run: HorizonRun,
    no_duplicate_control_run: HorizonRun,
) -> None:
    correction = captured_run.daily_captures[5]
    transition = correction.records.transition_results[0]
    trace = replace(transition.assessment_trace, history_refs=("h30-false-item",))
    records = replace(
        correction.records,
        transition_results=(replace(transition, assessment_trace=trace),),
    )
    changed = replace(
        captured_run,
        daily_captures=(
            *captured_run.daily_captures[:5],
            replace(correction, records=records),
            *captured_run.daily_captures[6:],
        ),
    )

    assert not check_no_self_excitation(
        changed, make_plan(30).events, no_duplicate_control_run
    ).passed


def _history_steps() -> tuple[HistoryStepCapture, HistoryStepCapture, HistoryStepCapture]:
    before_values = (("agent.affect.anxiety", 0.35), ("agent.affect.excitement", 0.3))
    values = (("agent.affect.anxiety", 0.25), ("agent.affect.excitement", 0.3))
    false_step = HistoryStepCapture(
        capture_ref="assessment-false",
        direct_state_write_refs=(),
        contribution_count=1,
        authoritative_evidence_refs=(),
        trace_refs=("assessment-false", "history-item", "history-summary"),
        supplied_history_refs=("history-item", "history-summary"),
        state_before_values=before_values,
        state_values=values,
        contributions=(
            CapturedContribution(
                "agent.affect.anxiety",
                "recovery",
                "recovery",
                -0.1,
            ),
        ),
        elapsed_days=0,
    )
    correction = HistoryStepCapture(
        capture_ref="assessment-correction",
        direct_state_write_refs=(),
        contribution_count=1,
        authoritative_evidence_refs=("evidence-correction",),
        trace_refs=("assessment-correction", "evidence-correction"),
        supplied_history_refs=(),
        state_before_values=values,
        state_values=values,
        contributions=(CapturedContribution("agent.affect.anxiety", "event", "correction", 0.0),),
        elapsed_days=25,
    )
    control = HistoryStepCapture(
        capture_ref="state-control",
        direct_state_write_refs=(),
        contribution_count=0,
        authoritative_evidence_refs=("evidence-correction",),
        trace_refs=("state-control", "evidence-correction"),
        supplied_history_refs=(),
        state_before_values=values,
        state_values=values,
        contributions=(),
        elapsed_days=0,
    )
    return false_step, correction, control


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"dimension": ""}, "dimension"),
        ({"source_kind": ""}, "source"),
        ({"source_ref": ""}, "source"),
        ({"amount": True}, "amount"),
        ({"amount": "not-numeric"}, "amount"),
        ({"amount": float("nan")}, "amount"),
        ({"applied": "yes"}, "applied"),
    ],
)
def test_captured_contribution_rejects_malformed_records(
    changes: dict[str, object], message: str
) -> None:
    valid = CapturedContribution("agent.affect.anxiety", "recovery", "recovery", -0.1)

    with pytest.raises(ValueError, match=message):
        replace(valid, **cast(Any, changes))


def test_false_history_cannot_write_state_and_current_evidence_reverses_it() -> None:
    false_step, correction, control = _history_steps()

    result = check_false_history_reversible(
        false_step,
        correction,
        control,
        recovery_horizon_days=30,
        tolerance="0.01",
    )

    assert result.passed
    assert false_step.direct_state_write_refs == ()
    assert false_step.contribution_count == 1
    assert correction.authoritative_evidence_refs
    assert not set(correction.trace_refs) & {"history-item", "history-summary"}
    assert result.within_control_bound


def test_false_history_rejects_treatment_capture_as_control() -> None:
    false_step, correction, _control = _history_steps()

    result = check_false_history_reversible(false_step, correction, false_step, 30, "0.01")

    assert not result.passed


def test_false_history_requires_exact_contribution_count_and_magnitude() -> None:
    false_step, correction, control = _history_steps()
    zero = replace(false_step, contribution_count=0, contributions=())
    wrong_amount = replace(
        false_step,
        contributions=(replace(false_step.contributions[0], amount=-0.05),),
    )
    unknown_dimension = replace(
        false_step,
        contributions=(replace(false_step.contributions[0], dimension="agent.affect.unknown"),),
    )
    unapplied = replace(
        false_step,
        contributions=(replace(false_step.contributions[0], applied=False),),
    )

    assert not check_false_history_reversible(zero, correction, control, 30, "0.01").passed
    assert not check_false_history_reversible(wrong_amount, correction, control, 30, "0.01").passed
    assert not check_false_history_reversible(
        unknown_dimension, correction, control, 30, "0.01"
    ).passed
    assert not check_false_history_reversible(unapplied, correction, control, 30, "0.01").passed


def test_false_history_requires_correction_trace_to_link_authoritative_evidence() -> None:
    false_step, correction, control = _history_steps()
    unlinked = replace(
        correction,
        authoritative_evidence_refs=("fabricated-authority",),
        trace_refs=("assessment-correction",),
    )

    assert not check_false_history_reversible(false_step, unlinked, control, 30, "0.01").passed


def test_no_false_history_control_cannot_retain_withheld_history() -> None:
    false_step, correction, control = _history_steps()
    polluted_control = replace(control, trace_refs=(*control.trace_refs, "history-item"))

    assert not check_false_history_reversible(
        false_step, correction, polluted_control, 30, "0.01"
    ).passed


@pytest.mark.parametrize(
    "change",
    [
        lambda false, correction: (
            replace(false, direct_state_write_refs=("history-item",)),
            correction,
        ),
        lambda false, correction: (replace(false, contribution_count=2), correction),
        lambda false, correction: (false, replace(correction, authoritative_evidence_refs=())),
        lambda false, correction: (
            false,
            replace(correction, trace_refs=(*correction.trace_refs, "history-summary")),
        ),
        lambda false, correction: (
            false,
            replace(
                correction,
                state_values=(("agent.affect.anxiety", 0.27), ("agent.affect.excitement", 0.3)),
            ),
        ),
        lambda false, correction: (false, replace(correction, elapsed_days=31)),
    ],
)
def test_false_history_fails_closed_on_pollution_or_late_convergence(change) -> None:  # type: ignore[no-untyped-def]
    false_step, correction, control = _history_steps()
    false_step, correction = change(false_step, correction)

    result = check_false_history_reversible(false_step, correction, control, 30, "0.01")

    assert not result.passed
    assert result.evidence_refs


def test_false_history_rejects_invalid_tolerance_and_mismatched_dimensions() -> None:
    false_step, correction, control = _history_steps()

    invalid = check_false_history_reversible(false_step, correction, control, 30, "invalid")
    mismatched = check_false_history_reversible(
        false_step,
        replace(correction, state_values=(("agent.affect.anxiety", 0.25),)),
        control,
        30,
        "0.01",
    )

    assert not invalid.passed
    assert not mismatched.passed


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"capture_ref": ""}, "capture_ref"),
        ({"direct_state_write_refs": []}, "immutable tuple"),
        ({"authoritative_evidence_refs": []}, "immutable tuple"),
        ({"trace_refs": []}, "immutable tuple"),
        ({"supplied_history_refs": []}, "immutable tuple"),
        ({"state_values": []}, "immutable tuple"),
        ({"state_before_values": []}, "immutable tuple"),
        ({"contributions": []}, "immutable tuple"),
        ({"direct_state_write_refs": ("",)}, "refs"),
        ({"authoritative_evidence_refs": ("",)}, "refs"),
        ({"trace_refs": ("",)}, "refs"),
        ({"supplied_history_refs": ("",)}, "refs"),
        ({"contribution_count": -1}, "contribution_count"),
        ({"contribution_count": True}, "contribution_count"),
        ({"elapsed_days": -1}, "elapsed_days"),
        ({"elapsed_days": True}, "elapsed_days"),
        ({"state_values": (("", 0.0),)}, "dimensions"),
        ({"state_values": (("agent.x", 0.0), ("agent.x", 0.1))}, "unique"),
        ({"state_before_values": (("agent.x", 0.0), ("agent.x", 0.1))}, "unique"),
        ({"state_before_values": (("agent.x", float("nan")),)}, "finite"),
        ({"state_values": (("agent.x", True),)}, "finite"),
        ({"contributions": (cast(Any, object()),)}, "CapturedContribution"),
    ],
)
def test_history_step_capture_rejects_malformed_records(
    changes: dict[str, object], message: str
) -> None:
    false_step, _correction, _control = _history_steps()

    with pytest.raises(ValueError, match=message):
        replace(false_step, **cast(Any, changes))


def test_false_history_result_requires_boolean_control_verdict() -> None:
    false_step, correction, control = _history_steps()
    result = check_false_history_reversible(false_step, correction, control, 30, "0.01")

    with pytest.raises(ValueError, match="within_control_bound"):
        replace(result, within_control_bound=cast(Any, "yes"))


def test_false_history_result_is_an_invariant_result() -> None:
    false_step, correction, control = _history_steps()

    assert isinstance(
        check_false_history_reversible(false_step, correction, control, 30, "0.01"),
        FalseHistoryInvariantResult,
    )


def test_merged_invariant_requires_real_captured_results() -> None:
    with pytest.raises(ValueError, match="captured invariant"):
        invariant_subject._merge_invariants("test.empty", ())
