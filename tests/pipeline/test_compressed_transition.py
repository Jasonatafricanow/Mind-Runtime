"""Canonical orchestrator uses one compressed emotional-transition hop."""

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from mind_runtime.contracts import (
    ActionPolicyInput,
    ActionPolicyResult,
    EmotionalTransitionInput,
    EmotionalTransitionResult,
    IntentEngineInput,
    IntentEngineResult,
    Interaction,
    InteractionStatus,
    Scope,
    ScopeDomain,
)
from mind_runtime.pipeline.orchestrator import TurnOrchestrator
from mind_runtime.pipeline.stubs import (
    StubActionPolicy,
    StubEmotionalTransition,
    StubIntentEngine,
)
from mind_runtime.pipeline.trace import TraceRecorder
from tests.golden.fixtures.common import make_scope
from tests.support.fake_clock import FakeClock

NOW = datetime(2026, 8, 22, 12, 0, tzinfo=UTC)


class RecordingTransition:
    def __init__(self, clock: FakeClock) -> None:
        self.inputs: list[EmotionalTransitionInput] = []
        self._delegate = StubEmotionalTransition(clock=clock)

    def transition(self, transition_input: EmotionalTransitionInput) -> EmotionalTransitionResult:
        self.inputs.append(transition_input)
        return self._delegate.transition(transition_input)


class RecordingPolicy:
    def __init__(self) -> None:
        self.calls: list[ActionPolicyInput] = []
        self._delegate = StubActionPolicy()

    def policy(self, policy_input: ActionPolicyInput) -> ActionPolicyResult:
        self.calls.append(policy_input)
        return self._delegate.policy(policy_input)


def test_orchestrator_calls_one_transition_then_policy_with_candidate_intent() -> None:
    clock = FakeClock(NOW)
    transition = RecordingTransition(clock)
    policy = RecordingPolicy()
    orchestrator = TurnOrchestrator(
        clock=clock,
        trace=TraceRecorder(),
        emotional_transition=transition,
        action_policy=policy,
    )
    interaction = Interaction(
        interaction_id="interaction-1",
        scope=make_scope(),
        channel="chat",
        session_id="session-1",
        turn_id="turn-1",
        started_at=NOW,
        committed_at=None,
        status=InteractionStatus.OPEN,
    )
    orchestrator.begin_turn(interaction)
    orchestrator.run()

    assert len(transition.inputs) == 1
    transition_input = transition.inputs[0]
    assert transition_input.context == orchestrator.situation
    assert transition_input.elapsed.total_seconds() == 0
    assert len(policy.calls) == 1
    policy_input = policy.calls[0]
    intent = policy_input.intent
    assert orchestrator.intent is not None
    assert intent.intent_id == orchestrator.intent.intent_id
    assert intent.status.value == "candidate"
    assert orchestrator.intent.status.value == "allowed"
    assert policy_input.context == orchestrator.situation
    assert policy_input.scope == interaction.scope
    assert orchestrator.transition_result is not None
    assert orchestrator.decision_context is not None
    assert orchestrator.decision_context.intent_ref == intent.intent_id
    assert not hasattr(orchestrator, "appraisal")
    assert not hasattr(orchestrator, "dynamics")


class InvalidIntentEngine:
    def __init__(self, *, wrong_scope: bool) -> None:
        self._delegate = StubIntentEngine()
        self._wrong_scope = wrong_scope

    def evaluate(self, engine_input: IntentEngineInput) -> IntentEngineResult:
        result = self._delegate.evaluate(engine_input)
        if not self._wrong_scope:
            return replace(result, candidates=())
        other_scope = Scope(domain=ScopeDomain.USER, user_id="user-2")
        intent = result.candidates[0]
        return replace(
            result,
            candidates=(
                replace(
                    intent,
                    scope=other_scope,
                    sync=replace(intent.sync, scope=other_scope),
                ),
            ),
        )


def test_orchestrator_fails_closed_on_wrong_scope_intent_engine_candidate() -> None:
    clock = FakeClock(NOW)
    orchestrator = TurnOrchestrator(
        clock=clock,
        trace=TraceRecorder(),
        intent_engine=InvalidIntentEngine(wrong_scope=True),
    )
    interaction = Interaction(
        interaction_id="interaction-1",
        scope=make_scope(),
        channel="chat",
        session_id="session-1",
        turn_id="turn-1",
        started_at=NOW,
        committed_at=None,
        status=InteractionStatus.OPEN,
    )
    orchestrator.begin_turn(interaction)
    with pytest.raises(ValueError, match="scope"):
        orchestrator.run()
