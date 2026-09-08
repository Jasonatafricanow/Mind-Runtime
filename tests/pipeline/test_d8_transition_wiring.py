"""The canonical orchestrator supplies complete D8 transition inputs."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from mind_runtime.contracts import (
    AffectiveDimensionProfile,
    EmotionalTransitionInput,
    EmotionalTransitionResult,
    Evidence,
    HistoricalContextBundle,
    Interaction,
    InteractionStatus,
    Observation,
    RuntimeState,
    Scope,
    ScopeDomain,
    SemanticEventCandidate,
    Situation,
    SyncFields,
)
from mind_runtime.dynamics.engine import DynamicsEngine
from mind_runtime.dynamics.persona import PersonaProfile
from mind_runtime.dynamics.ports import EngineEmotionalTransitionPort
from mind_runtime.emotional_transition.effects import EventEffectRule
from mind_runtime.emotional_transition.semantic import SemanticRouter
from mind_runtime.pipeline.orchestrator import TurnOrchestrator
from mind_runtime.pipeline.trace import TraceRecorder
from tests.golden.fixtures.common import make_evidence
from tests.support.fake_clock import FakeClock

NOW = datetime(2026, 8, 22, 12, 0, tzinfo=UTC)
USER_SCOPE = Scope(domain=ScopeDomain.USER, user_id="user-1")
AGENT_SCOPE = Scope(domain=ScopeDomain.AGENT, agent_id="test", persona_id="test")


def sync(scope: Scope, object_id: str, *, version: int = 1) -> SyncFields:
    return SyncFields(scope, "runtime-1", object_id, version, f"idem-{object_id}")


def persona() -> PersonaProfile:
    return PersonaProfile(
        persona_id="test",
        dimensions=(
            AffectiveDimensionProfile(
                dimension="agent.affect.anxiety",
                baseline=0.25,
                initial_value=0.25,
                sensitivity=0.5,
                recovery_rate=0.2,
                ceiling=1.0,
                floor=0.0,
                growth_profile=(),
                coupling_profile=(),
            ),
        ),
    )


def affect_state(*, updated_at: datetime = NOW - timedelta(minutes=5)) -> RuntimeState:
    return RuntimeState(
        state_id="agent.affect.anxiety:1",
        scope=AGENT_SCOPE,
        origin_runtime_id="runtime-1",
        dimension="agent.affect.anxiety",
        value=0.25,
        status="active",
        valid_from=updated_at,
        valid_until=None,
        relevant_until=None,
        last_observed_at=updated_at,
        evidence_refs=(),
        transition_refs=(),
        updated_at=updated_at,
        version=1,
        sync=sync(AGENT_SCOPE, "agent.affect.anxiety:1"),
    )


def history_bundle() -> HistoricalContextBundle:
    return HistoricalContextBundle(
        bundle_id="history-1",
        scope=USER_SCOPE,
        origin_runtime_id="runtime-1",
        episodes=(),
        stable_facts=(),
        relationship_events=(),
        pattern_summaries=(),
        source_refs=("old-evidence",),
        provider_trace="fixture",
    )


class RecordingHistory:
    def __init__(self, result: HistoricalContextBundle | None) -> None:
        self.result = result
        self.calls = 0

    def read(
        self,
        *,
        interaction_id: str,
        context: Situation,
        observations: tuple[Observation, ...],
        scope: Scope,
        clock: datetime,
    ) -> HistoricalContextBundle | None:
        del interaction_id, context, observations, clock
        assert scope == USER_SCOPE
        self.calls += 1
        return self.result


class RecordingTransition:
    def __init__(self, delegate: EngineEmotionalTransitionPort) -> None:
        self.delegate = delegate
        self.inputs: list[EmotionalTransitionInput] = []

    def transition(self, transition_input: EmotionalTransitionInput) -> EmotionalTransitionResult:
        self.inputs.append(transition_input)
        return self.delegate.transition(transition_input)


class CountingSemanticProvider:
    def __init__(self, result: tuple[SemanticEventCandidate, ...] = ()) -> None:
        self.result = result
        self.calls = 0

    def propose(
        self,
        *,
        observations: tuple[Observation, ...],
        context: Situation,
        scope: Scope,
    ) -> tuple[SemanticEventCandidate, ...]:
        del observations, context
        assert scope == USER_SCOPE
        self.calls += 1
        return self.result


def interaction() -> Interaction:
    return Interaction(
        interaction_id="interaction-1",
        scope=USER_SCOPE,
        channel="chat",
        session_id="session-1",
        turn_id="turn-1",
        started_at=NOW,
        committed_at=None,
        status=InteractionStatus.OPEN,
    )


def typed_evidence() -> Evidence:
    return replace(
        make_evidence(text="cancelled", occurred_at=NOW, received_at=NOW),
        source_type="typed_event",
        payload={"kind": "plan_cancelled", "attributes": {"recurrence": "2"}},
    )


def make_transition(provider: CountingSemanticProvider) -> RecordingTransition:
    return RecordingTransition(
        EngineEmotionalTransitionPort(
            engine=DynamicsEngine(persona=persona()),
            effect_rules=(
                EventEffectRule(
                    event_kind="plan_cancelled",
                    dimension="agent.affect.anxiety",
                    base_amount=0.2,
                ),
            ),
            semantic_router=SemanticRouter(provider=provider),
        )
    )


def effect_rule() -> EventEffectRule:
    return EventEffectRule(
        event_kind="plan_cancelled",
        dimension="agent.affect.anxiety",
        base_amount=0.2,
    )


def test_orchestrator_passes_observations_history_and_elapsed_once() -> None:
    history = RecordingHistory(history_bundle())
    provider = CountingSemanticProvider()
    transition = make_transition(provider)
    orchestrator = TurnOrchestrator(
        clock=FakeClock(NOW),
        trace=TraceRecorder(),
        persona=persona(),
        emotional_transition=transition,
        historical_context=history,
        canonical_snapshot=(affect_state(),),
    )
    orchestrator.begin_turn(interaction())
    orchestrator.ingest(typed_evidence())
    orchestrator.run()

    assert history.calls == 1
    assert len(transition.inputs) == 1
    transition_input = transition.inputs[0]
    assert transition_input.observations[0].key == "typed_event.observed"
    assert transition_input.history_context == history.result
    assert transition_input.context.historical_context == history.result
    assert transition_input.elapsed == timedelta(minutes=5)
    assert provider.calls == 0
    assert orchestrator.transition_result is not None
    assert orchestrator.transition_result.assessment_trace.route_decision.path.value == (
        "typed_mapping"
    )


def test_absent_history_and_semantic_provider_do_not_break_deterministic_turn() -> None:
    history = RecordingHistory(None)
    orchestrator = TurnOrchestrator(
        clock=FakeClock(NOW),
        trace=TraceRecorder(),
        persona=persona(),
        historical_context=history,
        canonical_snapshot=(affect_state(),),
    )
    orchestrator.begin_turn(interaction())
    orchestrator.run()

    assert history.calls == 1
    assert orchestrator.transition_result is not None
    trace = orchestrator.transition_result.assessment_trace
    assert trace.route_decision.reason_codes == ("no_semantic_event",)
    assert trace.history_refs == ()


def test_future_affect_timestamp_fails_closed_instead_of_negative_elapsed() -> None:
    transition = make_transition(CountingSemanticProvider())
    orchestrator = TurnOrchestrator(
        clock=FakeClock(NOW),
        trace=TraceRecorder(),
        persona=persona(),
        emotional_transition=transition,
        canonical_snapshot=(affect_state(updated_at=NOW + timedelta(seconds=1)),),
    )
    orchestrator.begin_turn(interaction())

    with pytest.raises(ValueError, match="future"):
        orchestrator.run()
    assert transition.inputs == []


def test_auto_wired_optional_provider_remains_candidate_only() -> None:
    provider_candidate = SemanticEventCandidate(
        candidate_id="provider-1",
        scope=USER_SCOPE,
        origin_runtime_id="runtime-1",
        kind="plan_cancelled",
        attributes=(),
        confidence=0.8,
        evidence_refs=("evidence-1",),
    )
    provider = CountingSemanticProvider((provider_candidate,))
    orchestrator = TurnOrchestrator(
        clock=FakeClock(NOW),
        trace=TraceRecorder(),
        persona=persona(),
        semantic_provider=provider,
        effect_rules=(effect_rule(),),
        canonical_snapshot=(affect_state(),),
    )
    orchestrator.begin_turn(interaction())
    orchestrator.ingest(make_evidence(text="要不下周再约？", occurred_at=NOW, received_at=NOW))
    orchestrator.run()

    assert provider.calls == 1
    assert orchestrator.transition_result is not None
    result = orchestrator.transition_result
    assert result.assessment_trace.route_decision.path.value == "llm"
    assert result.projected.projected_states[0].value == pytest.approx(0.33)
