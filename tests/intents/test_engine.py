"""Configuration-owned deterministic Intent scoring."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import cast

import pytest

from mind_runtime.contracts import (
    IntentEngineInput,
    ProjectedMindState,
    ReconsiderationPolicy,
    RuntimeState,
    Scope,
    ScopeDomain,
    SemanticEventCandidate,
    Situation,
    SyncFields,
)
from mind_runtime.intents.engine import DeterministicIntentEngine, IntentRule

NOW = datetime(2026, 8, 22, 12, 0, tzinfo=UTC)
USER_SCOPE = Scope(domain=ScopeDomain.USER, user_id="user-1")
AGENT_SCOPE = Scope(domain=ScopeDomain.AGENT, agent_id="agent-1", persona_id="persona-1")


def sync(scope: Scope, object_id: str, version: int = 1) -> SyncFields:
    return SyncFields(scope, "runtime-1", object_id, version, f"idem-{object_id}-v{version}")


def state(dimension: str, value: object, index: int) -> RuntimeState:
    state_id = f"{dimension}:{index}"
    return RuntimeState(
        state_id=state_id,
        scope=AGENT_SCOPE,
        origin_runtime_id="runtime-1",
        dimension=dimension,
        value=value,
        status="active",
        valid_from=NOW,
        valid_until=None,
        relevant_until=None,
        last_observed_at=NOW,
        evidence_refs=("evidence-1",),
        transition_refs=(),
        updated_at=NOW,
        version=1,
        sync=sync(AGENT_SCOPE, state_id),
    )


def projected(
    values: tuple[tuple[str, object], ...] = (
        ("agent.affect.longing", 0.8),
        ("agent.drive.photo_share", 0.9),
    ),
) -> ProjectedMindState:
    states = tuple(
        state(dimension, value, index) for index, (dimension, value) in enumerate(values)
    )
    return ProjectedMindState(
        projection_id="projection-1",
        scope=AGENT_SCOPE,
        origin_runtime_id="runtime-1",
        projected_states=states,
        sync=sync(AGENT_SCOPE, "projection-1"),
    )


def situation() -> Situation:
    return Situation(
        situation_id="situation-1",
        scope=USER_SCOPE,
        origin_runtime_id="runtime-1",
        derived_facts=(),
        effective_state_ref="effective-1",
        observed_at=NOW,
        historical_context=None,
        persona_id="persona-1",
        relationship_ids=(),
        evidence_refs=("evidence-1",),
    )


def event(
    candidate_id: str = "event-1",
    *,
    kind: str = "follow_up_due",
    attributes: tuple[tuple[str, str], ...] = (("due_at", "2026-08-23T10:00:00+00:00"),),
) -> SemanticEventCandidate:
    return SemanticEventCandidate(
        candidate_id=candidate_id,
        scope=USER_SCOPE,
        origin_runtime_id="runtime-1",
        kind=kind,
        attributes=attributes,
        confidence=0.9,
        evidence_refs=("evidence-1",),
    )


def engine_input(
    *,
    projection: ProjectedMindState | None = None,
    events: tuple[SemanticEventCandidate, ...] = (),
    clock: datetime = NOW,
) -> IntentEngineInput:
    return IntentEngineInput(
        interaction_id="interaction-1",
        scope=USER_SCOPE,
        origin_runtime_id="runtime-1",
        context=situation(),
        projected=projection or projected(),
        accepted_events=events,
        clock=clock,
    )


def rule(
    rule_id: str,
    kind: str,
    *,
    base: float,
    weights: tuple[tuple[str, float], ...] = (),
    event_kind: str | None = None,
    event_bonus: float = 0.0,
    minimum: float = 0.0,
    due_at_attribute: str | None = None,
    expires_after: timedelta | None = None,
    reconsideration: ReconsiderationPolicy = ReconsiderationPolicy.ON_CONTEXT_CHANGE,
) -> IntentRule:
    return IntentRule(
        rule_id=rule_id,
        kind=kind,
        base_strength=base,
        dimension_weights=weights,
        event_kind=event_kind,
        event_bonus=event_bonus,
        minimum_strength=minimum,
        due_at_attribute=due_at_attribute,
        expires_after=expires_after,
        reconsideration_policy=reconsideration,
    )


def test_scores_dimension_rules_with_literal_values_and_stable_order() -> None:
    contact = rule(
        "contact",
        "contact_user",
        base=0.10,
        weights=(("agent.affect.longing", 0.75),),
    )
    photo = rule(
        "photo",
        "share_photo",
        base=0.05,
        weights=(("agent.drive.photo_share", 0.90),),
    )

    result = DeterministicIntentEngine((contact, photo), "runtime-1").evaluate(engine_input())

    assert [(candidate.kind, candidate.strength) for candidate in result.candidates] == [
        ("share_photo", 0.86),
        ("contact_user", 0.7),
    ]
    contact_trace = next(trace for trace in result.traces if trace.rule_id == "contact")
    assert [
        (item.source_kind, item.source_ref, item.amount) for item in contact_trace.contributions
    ] == [
        ("base", "contact", 0.1),
        ("dimension", "agent.affect.longing", 0.6),
    ]
    assert contact_trace.unclamped_score == 0.7
    assert contact_trace.final_strength == 0.7


def test_applies_one_typed_event_bonus_and_uses_its_due_at_schedule() -> None:
    follow_up = rule(
        "follow-up",
        "scheduled_follow_up",
        base=0.20,
        event_kind="follow_up_due",
        event_bonus=0.40,
        minimum=0.5,
        due_at_attribute="due_at",
        expires_after=timedelta(hours=4),
        reconsideration=ReconsiderationPolicy.ON_DUE,
    )
    first = event("event-1")
    second = event(
        "event-2",
        attributes=(("due_at", "2026-08-24T10:00:00+00:00"),),
    )

    result = DeterministicIntentEngine((follow_up,), "runtime-1").evaluate(
        engine_input(events=(first, second))
    )

    candidate = result.candidates[0]
    due_at = datetime(2026, 8, 23, 10, 0, tzinfo=UTC)
    assert candidate.strength == 0.6
    assert candidate.earliest_at == due_at
    assert candidate.due_at == due_at
    assert candidate.expires_at == due_at + timedelta(hours=4)
    assert candidate.cause_refs == ("situation-1", "event-1")
    assert candidate.state_refs == ("projection-1",)
    assert [item.amount for item in result.traces[0].contributions] == [0.2, 0.4]


def test_clamps_scores_and_keeps_below_threshold_trace_without_candidate() -> None:
    clamped = rule(
        "clamped",
        "high_drive",
        base=0.8,
        weights=(("agent.affect.longing", 0.75),),
    )
    excluded = rule(
        "excluded",
        "low_drive",
        base=0.1,
        weights=(("agent.affect.missing", 0.9),),
        minimum=0.2,
    )

    result = DeterministicIntentEngine((excluded, clamped), "runtime-1").evaluate(engine_input())

    assert [(candidate.kind, candidate.strength) for candidate in result.candidates] == [
        ("high_drive", 1.0)
    ]
    excluded_trace = next(trace for trace in result.traces if trace.rule_id == "excluded")
    assert excluded_trace.admitted is False
    assert excluded_trace.reason_codes == ("below_minimum_strength",)
    assert excluded_trace.contributions[-1].amount == 0.0


def test_missing_and_non_numeric_dimensions_contribute_zero() -> None:
    weighted = rule(
        "weighted",
        "inspect_dimensions",
        base=0.3,
        weights=(
            ("agent.affect.missing", 0.5),
            ("agent.affect.label", 0.7),
        ),
    )
    non_numeric_projection = projected((("agent.affect.label", "high"),))

    result = DeterministicIntentEngine((weighted,), "runtime-1").evaluate(
        engine_input(projection=non_numeric_projection)
    )

    assert result.candidates[0].strength == 0.3
    assert [item.amount for item in result.traces[0].contributions] == [0.3, 0.0, 0.0]


def test_order_ties_by_kind_then_stable_intent_id() -> None:
    zeta = rule("zeta", "same_kind", base=0.5)
    alpha = rule("alpha", "another_kind", base=0.5)

    result = DeterministicIntentEngine((zeta, alpha), "runtime-1").evaluate(engine_input())

    assert [candidate.intent_id for candidate in result.candidates] == [
        "intent-interaction-1-alpha",
        "intent-interaction-1-zeta",
    ]


@pytest.mark.parametrize(
    ("rules", "message"),
    [
        (
            (rule("duplicate", "one", base=0.1), rule("duplicate", "two", base=0.2)),
            "rule_id",
        ),
        (
            (rule("one", "duplicate", base=0.1), rule("two", "duplicate", base=0.2)),
            "kind",
        ),
    ],
)
def test_rejects_duplicate_rule_id_or_kind(rules: tuple[IntentRule, ...], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        DeterministicIntentEngine(rules, "runtime-1")


def test_rule_validation_rejects_ambiguous_or_non_deterministic_configuration() -> None:
    with pytest.raises(ValueError, match="dimension"):
        replace(
            rule("bad", "bad", base=0.1),
            dimension_weights=(("agent.affect.longing", 0.2), ("agent.affect.longing", 0.3)),
        )
    with pytest.raises(ValueError, match="numeric"):
        replace(rule("bad", "bad", base=0.1), base_strength=True)
    with pytest.raises(ValueError, match="minimum_strength"):
        replace(rule("bad", "bad", base=0.1), minimum_strength=1.1)
    with pytest.raises(ValueError, match="event_bonus"):
        replace(rule("bad", "bad", base=0.1), event_bonus=0.1)
    with pytest.raises(ValueError, match="event_kind"):
        replace(rule("bad", "bad", base=0.1), due_at_attribute="due_at")
    with pytest.raises(ValueError, match="expires_after"):
        replace(rule("bad", "bad", base=0.1), expires_after=timedelta(0))
    with pytest.raises(ValueError, match="ReconsiderationPolicy"):
        replace(
            rule("bad", "bad", base=0.1),
            reconsideration_policy=cast(ReconsiderationPolicy, "never"),
        )


@pytest.mark.parametrize(
    "attributes",
    [
        (),
        (("due_at", "tomorrow morning"),),
        (("due_at", "2026-08-23T10:00:00+02:00"),),
        (
            ("due_at", "2026-08-23T10:00:00+00:00"),
            ("due_at", "2026-08-24T10:00:00+00:00"),
        ),
    ],
)
def test_due_rule_abstains_on_missing_malformed_non_utc_or_conflicting_attribute(
    attributes: tuple[tuple[str, str], ...],
) -> None:
    follow_up = rule(
        "follow-up",
        "scheduled_follow_up",
        base=0.2,
        event_kind="follow_up_due",
        event_bonus=0.4,
        due_at_attribute="due_at",
        reconsideration=ReconsiderationPolicy.ON_DUE,
    )

    result = DeterministicIntentEngine((follow_up,), "runtime-1").evaluate(
        engine_input(events=(event(attributes=attributes),))
    )

    assert result.candidates == ()
    assert result.traces[0].admitted is False
    assert result.traces[0].reason_codes == ("invalid_due_at",)


def test_replay_with_same_input_is_byte_equivalent() -> None:
    contact = rule(
        "contact",
        "contact_user",
        base=0.1,
        weights=(("agent.affect.longing", 0.75),),
    )
    engine = DeterministicIntentEngine((contact,), "runtime-1")
    scoring_input = engine_input(clock=NOW)

    first = engine.evaluate(scoring_input)
    second = engine.evaluate(scoring_input)

    assert first == second
    assert repr(first).encode("utf-8") == repr(second).encode("utf-8")


def test_engine_rejects_runtime_origin_mismatch() -> None:
    contact = rule("contact", "contact_user", base=0.5)
    mismatched = replace(engine_input(), origin_runtime_id="other-runtime")

    with pytest.raises(ValueError, match="origin"):
        DeterministicIntentEngine((contact,), "runtime-1").evaluate(mismatched)


def test_non_finite_dimension_is_traced_as_zero() -> None:
    weighted = rule(
        "weighted",
        "inspect_dimensions",
        base=0.3,
        weights=(("agent.affect.longing", 0.5),),
    )
    non_finite = projected((("agent.affect.longing", float("nan")),))

    result = DeterministicIntentEngine((weighted,), "runtime-1").evaluate(
        engine_input(projection=non_finite)
    )

    assert result.candidates[0].strength == 0.3
    assert result.traces[0].contributions[-1].amount == 0.0


def test_due_rule_without_matching_event_and_past_expiry_both_abstain() -> None:
    scheduled = rule(
        "scheduled",
        "scheduled_follow_up",
        base=0.6,
        event_kind="follow_up_due",
        due_at_attribute="due_at",
        expires_after=timedelta(hours=1),
        reconsideration=ReconsiderationPolicy.ON_DUE,
    )
    engine = DeterministicIntentEngine((scheduled,), "runtime-1")

    missing_event = engine.evaluate(engine_input())
    expired_event = engine.evaluate(
        engine_input(
            events=(
                event(
                    attributes=(("due_at", "2026-08-22T09:00:00+00:00"),),
                ),
            )
        )
    )

    assert missing_event.candidates == ()
    assert missing_event.traces[0].reason_codes == ("invalid_due_at",)
    assert expired_event.candidates == ()
    assert expired_event.traces[0].reason_codes == ("invalid_due_at",)
