"""D5.1 TransitionIntent commit_phase tests: ingest vs turn_commit separation."""

from datetime import UTC, datetime

import pytest

from mind_runtime.contracts import StateTransition, SyncFields, TransitionIntent
from mind_runtime.state.intents import (
    INGEST_PHASE,
    TURN_COMMIT_PHASE,
    build_ingest_intent,
    build_turn_commit_intent,
    ingest_intents_from_transitions,
)
from tests.golden.fixtures.common import make_scope, make_state

NOW = datetime(2026, 8, 22, 9, 0, tzinfo=UTC)


def make_transition(
    *, before_value: str = "sleeping", after_value: str = "awake"
) -> StateTransition:
    scope = make_scope()
    before = make_state(
        dimension="user.sleep.phase", value=before_value, status="active", state_id="s-1"
    )
    after = make_state(
        dimension="user.sleep.phase", value=after_value, status="active", state_id="s-2"
    )
    return StateTransition(
        transition_id="transition:user.sleep.phase:2",
        scope=scope,
        origin_runtime_id="runtime-1",
        intent_id="intent:user.sleep.phase:2",
        from_state=before,
        to_state=after,
        committed_at=NOW,
        sync=SyncFields(scope, "runtime-1", "transition:user.sleep.phase:2", 1, "idem"),
    )


def test_ingest_intent_carries_ingest_phase() -> None:
    scope = make_scope()
    before = make_state(dimension="user.sleep.phase", value="sleeping", status="active")
    after = make_state(dimension="user.sleep.phase", value="awake", status="active")
    intent = build_ingest_intent(
        interaction_id="interaction-1",
        scope=scope,
        origin_runtime_id="runtime-1",
        target_dimension="user.sleep.phase",
        before=before,
        proposed_after=after,
        cause_refs=("evidence-1",),
    )
    assert isinstance(intent, TransitionIntent)
    assert intent.commit_phase == INGEST_PHASE
    assert intent.interaction_id == "interaction-1"
    assert intent.before is before
    assert intent.proposed_after is after
    assert intent.cause_refs == ("evidence-1",)
    assert intent.intent_id == "ingest:interaction-1:user.sleep.phase:1"
    assert intent.scope == scope


def test_turn_commit_intent_carries_turn_commit_phase() -> None:
    from mind_runtime.contracts import Scope, ScopeDomain

    scope = Scope(domain=ScopeDomain.AGENT, agent_id="kayla", persona_id="persona-kayla")
    before = make_state(dimension="agent.affect.longing", value=0.42, status="active", scope=scope)
    after = make_state(dimension="agent.affect.longing", value=0.55, status="active", scope=scope)
    intent = build_turn_commit_intent(
        interaction_id="interaction-1",
        scope=scope,
        origin_runtime_id="runtime-1",
        target_dimension="agent.affect.longing",
        before=before,
        proposed_after=after,
        cause_refs=("observation-1",),
        confidence=0.8,
    )
    assert intent.commit_phase == TURN_COMMIT_PHASE
    assert intent.intent_id == "turn_commit:interaction-1:agent.affect.longing:1"
    assert intent.confidence == 0.8


def test_ingest_intents_derived_from_reconcile_transitions() -> None:
    transition = make_transition()
    intents = ingest_intents_from_transitions(
        interaction_id="interaction-1",
        transitions=(transition,),
        origin_runtime_id="runtime-1",
    )
    assert len(intents) == 1
    intent = intents[0]
    assert intent.commit_phase == INGEST_PHASE
    assert intent.before is transition.from_state
    assert intent.proposed_after is transition.to_state
    assert intent.target_dimension == "user.sleep.phase"
    assert intent.intent_id == "ingest:interaction-1:user.sleep.phase:1"


def test_ingest_intents_deterministic_for_replay() -> None:
    transition = make_transition()
    first = ingest_intents_from_transitions(
        interaction_id="i-1", transitions=(transition,), origin_runtime_id="runtime-1"
    )
    second = ingest_intents_from_transitions(
        interaction_id="i-1", transitions=(transition,), origin_runtime_id="runtime-1"
    )
    assert first == second


def test_ingest_intents_empty_for_empty_transitions() -> None:
    assert (
        ingest_intents_from_transitions(
            interaction_id="i-1", transitions=(), origin_runtime_id="runtime-1"
        )
        == ()
    )


def test_phase_separation_contract() -> None:
    """ingest intents may commit before turn_commit; the reverse is illegal."""
    ingest = build_ingest_intent(
        interaction_id="i-1",
        scope=make_scope(),
        origin_runtime_id="runtime-1",
        target_dimension="user.sleep.phase",
        before=make_state(dimension="user.sleep.phase", value="a", status="active"),
        proposed_after=make_state(dimension="user.sleep.phase", value="b", status="active"),
        cause_refs=(),
    )
    assert ingest.commit_phase == INGEST_PHASE
    with pytest.raises(ValueError, match="ingest or turn_commit"):
        TransitionIntent(
            intent_id="x",
            interaction_id="i-1",
            scope=make_scope(),
            origin_runtime_id="runtime-1",
            target_dimension="user.sleep.phase",
            before=make_state(dimension="user.sleep.phase", value="a", status="active"),
            proposed_after=make_state(dimension="user.sleep.phase", value="b", status="active"),
            cause_refs=(),
            policy="reconciler",
            confidence=1.0,
            commit_phase="other",
        )


def test_turn_commit_requires_agent_scope_dimension_consistency() -> None:
    scope = make_scope()
    before = make_state(dimension="user.sleep.phase", value="a", status="active")
    after = make_state(dimension="user.sleep.phase", value="b", status="active")
    with pytest.raises(ValueError, match="approved"):
        build_ingest_intent(
            interaction_id="i-1",
            scope=scope,
            origin_runtime_id="runtime-1",
            target_dimension="agent.affect.longing",  # mismatch with states
            before=before,
            proposed_after=after,
            cause_refs=(),
        )
