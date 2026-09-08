"""Compressed walking-skeleton ports, stubs, and trace tests."""

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta

import pytest

from mind_runtime.contracts import (
    ActionPolicyInput,
    ActionPolicyResult,
    DecisionContext,
    EmotionalTransitionInput,
    EmotionalTransitionResult,
    ExpressionContextItem,
    ExpressionContextKind,
    ExpressionDisposition,
    ExpressionGuardInput,
    ExpressionGuardResult,
    IntentEngineInput,
    Interaction,
    InteractionStatus,
    PolicyResources,
    ProviderExpressionContext,
    RuntimeState,
    Situation,
)
from mind_runtime.pipeline.ports import (
    ActionPolicyPort,
    AgentPort,
    EffectiveStatePort,
    EmotionalTransitionPort,
    ExpressionGuardPort,
    IntentEnginePort,
    SituationPort,
)
from mind_runtime.pipeline.stubs import (
    StubActionPolicy,
    StubContextRenderer,
    StubDecisionContextCompiler,
    StubEffectiveState,
    StubEmotionalTransition,
    StubExpressionCoordinator,
    StubExpressionGuard,
    StubIntentEngine,
    StubSituation,
)
from mind_runtime.pipeline.trace import TraceEntry, TraceRecorder
from mind_runtime.state.resolver import EffectiveStateView
from tests.golden.fixtures.common import make_evidence, make_scope, make_state
from tests.support.fake_clock import FakeClock

NOW = datetime(2026, 8, 20, 15, 0, tzinfo=UTC)


def make_situation_input() -> tuple[Interaction, EffectiveStateView]:
    interaction = Interaction(
        interaction_id="i-1",
        scope=make_scope(),
        channel="chat",
        session_id="session-1",
        turn_id="turn-1",
        started_at=NOW,
        committed_at=None,
        status=InteractionStatus.OPEN,
    )
    return interaction, EffectiveStateView(states=(make_state(),), resolved_at=NOW)


def make_context() -> Situation:
    interaction, view = make_situation_input()
    return StubSituation().build(
        interaction=interaction,
        effective_view=view,
        scope=make_scope(),
        clock=NOW,
    )


def make_transition_input() -> EmotionalTransitionInput:
    return EmotionalTransitionInput(
        interaction_id="i-1",
        scope=make_scope(),
        origin_runtime_id="runtime-1",
        context=make_context(),
        current_affect=(),
        elapsed=timedelta(0),
        persona_id="stub-persona",
        persona_version=1,
        persona=(),
        observations=(),
        semantic_candidates=(),
        history_context=None,
        clock=NOW,
        projection_scope=None,
    )


def test_all_port_protocols_accept_compressed_stubs() -> None:
    assert isinstance(StubEffectiveState(), EffectiveStatePort)
    assert isinstance(StubSituation(), SituationPort)
    assert isinstance(StubEmotionalTransition(clock=FakeClock(NOW)), EmotionalTransitionPort)
    assert isinstance(StubIntentEngine(), IntentEnginePort)
    assert isinstance(StubActionPolicy(), ActionPolicyPort)
    assert isinstance(StubExpressionGuard(), ExpressionGuardPort)


def test_stub_effective_state_returns_runtime_state() -> None:
    stub = StubEffectiveState()
    scope = make_scope()
    evidence = make_evidence(text="hello")
    result = stub.effective(
        interaction_id="interaction-1",
        evidence_refs=(evidence.id,),
        canonical_snapshot=(),
        scope=scope,
        clock=NOW,
    )
    assert isinstance(result, RuntimeState)
    assert result.scope == scope


def test_stub_situation_returns_factual_context() -> None:
    context = make_context()
    assert isinstance(context, Situation)
    assert context.derived_facts == (("stub", "pass"),)
    assert not any("allowed" in key for key, _value in context.derived_facts)


def test_stub_transition_returns_projection_events_and_trace() -> None:
    result = StubEmotionalTransition(clock=FakeClock(NOW)).transition(make_transition_input())
    assert isinstance(result, EmotionalTransitionResult)
    assert result.projected.committed is False
    assert result.accepted_events == ()
    assert result.assessment_trace.context_ref == "situation-i-1"


def test_stub_transition_timestamps_come_from_injected_clock() -> None:
    clock = FakeClock(NOW)
    stub = StubEmotionalTransition(clock=clock)
    first = stub.transition(make_transition_input())
    clock.advance(timedelta(minutes=5))
    second = stub.transition(make_transition_input())
    assert first.projected.projected_states[0].valid_from == NOW
    assert second.projected.projected_states[0].valid_from == NOW + timedelta(minutes=5)


def test_stub_policy_consumes_intent_and_context() -> None:
    transition = StubEmotionalTransition(clock=FakeClock(NOW)).transition(make_transition_input())
    engine_input = IntentEngineInput(
        interaction_id="i-1",
        scope=make_scope(),
        origin_runtime_id="runtime-1",
        context=make_context(),
        projected=transition.projected,
        accepted_events=(),
        clock=NOW,
    )
    intent = StubIntentEngine().evaluate(engine_input).candidates[0]
    result = StubActionPolicy().policy(
        ActionPolicyInput(
            intent=intent,
            context=make_context(),
            scope=make_scope(),
            clock=NOW,
            resources=PolicyResources(("respond",)),
        )
    )
    assert isinstance(result, ActionPolicyResult)
    assert result.intent_id == intent.intent_id
    assert result.reason_codes == ("stub",)


def test_stub_guard_returns_accepted_result() -> None:
    scope = make_scope()
    context = DecisionContext(
        "context-1",
        scope,
        "runtime-1",
        "interaction-1",
        "situation-1",
        "state-1",
        "projection-1",
        (),
        None,
        "assessment-1",
        "intent-1",
        "policy-1",
        None,
        (),
        "respond",
        "text_message",
        0,
        (
            ExpressionContextItem(
                "item-action",
                ExpressionContextKind.ACTION,
                "selected_action",
                "text_message",
                ("policy-1",),
                0,
            ),
        ),
    )
    result = StubExpressionGuard().guard(ExpressionGuardInput("draft-1", context, "hello", 0))
    assert isinstance(result, ExpressionGuardResult)
    assert result.disposition is ExpressionDisposition.ACCEPT


def test_stub_compiler_never_retries() -> None:
    scope = make_scope()
    context = DecisionContext(
        "context-1",
        scope,
        "runtime-1",
        "interaction-1",
        "situation-1",
        "state-1",
        "projection-1",
        (),
        None,
        "assessment-1",
        "intent-1",
        "policy-1",
        None,
        (),
        "respond",
        "text_message",
        0,
        (),
    )
    with pytest.raises(NotImplementedError, match="never retries"):
        StubDecisionContextCompiler().retry(context, ("prefix_duplicate",))


def test_stub_coordinator_guard_exception_fails_closed() -> None:
    scope = make_scope()
    context = DecisionContext(
        "context-1",
        scope,
        "runtime-1",
        "interaction-1",
        "situation-1",
        "state-1",
        "projection-1",
        (),
        None,
        "assessment-1",
        "intent-1",
        "policy-1",
        None,
        (),
        "respond",
        "text_message",
        0,
        (
            ExpressionContextItem(
                "item-action",
                ExpressionContextKind.ACTION,
                "selected_action",
                "text_message",
                ("policy-1",),
                0,
            ),
        ),
    )

    class ExplodingGuard:
        def guard(self, guard_input: ExpressionGuardInput) -> ExpressionGuardResult:
            raise RuntimeError("guard exploded")

    class StubAgent:
        def respond(self, provider_context: ProviderExpressionContext) -> str:
            return "hello"

    coordinator = StubExpressionCoordinator(
        renderer=StubContextRenderer(),
        agent=StubAgent(),
        guard=ExplodingGuard(),
    )
    outcome = coordinator.express(context)
    assert outcome.final_disposition is ExpressionDisposition.REJECT
    assert outcome.accepted_expression is None
    assert outcome.attempts[-1].reason_codes == ("guard_failure",)


def test_agent_port_is_protocol() -> None:
    assert hasattr(AgentPort, "respond")


def test_trace_recorder_records_in_order() -> None:
    recorder = TraceRecorder()
    recorder.record("i-1", "begin", ref="i-1", outcome="ok", at=NOW)
    recorder.record("i-1", "ingest", ref="evidence-1", outcome="ok", at=NOW)
    recorder.record("i-2", "begin", ref="i-2", outcome="ok", at=NOW)
    entries = recorder.trace("i-1")
    assert [entry.stage for entry in entries] == ["begin", "ingest"]
    assert all(isinstance(entry, TraceEntry) for entry in entries)


def test_trace_recorder_unknown_interaction_empty() -> None:
    assert TraceRecorder().trace("missing") == ()


def test_trace_entry_is_immutable() -> None:
    entry = TraceEntry(interaction_id="i-1", stage="begin", ref=None, outcome="ok", at=NOW)
    with pytest.raises(FrozenInstanceError):
        entry.stage = "other"  # type: ignore[misc]
