"""D2S.1 TurnOrchestrator tests: lifecycle stages and injectable ports."""

from datetime import UTC, datetime

import pytest

from mind_runtime.contracts import (
    ActionReceipt,
    DecisionContext,
    DeliveryStatus,
    Interaction,
    InteractionStatus,
    Observation,
    ProviderExpressionContext,
)
from mind_runtime.pipeline.orchestrator import TurnOrchestrator, TurnState
from mind_runtime.pipeline.ports import AgentPort
from mind_runtime.pipeline.trace import TraceRecorder
from tests.golden.fixtures.common import make_evidence, make_scope
from tests.support.fake_clock import FakeClock

NOW = datetime(2026, 8, 20, 15, 0, tzinfo=UTC)


def make_interaction() -> Interaction:
    scope = make_scope()
    return Interaction(
        interaction_id="interaction-1",
        scope=scope,
        channel="chat",
        session_id="session-1",
        turn_id="turn-1",
        started_at=NOW,
        committed_at=None,
        status=InteractionStatus.OPEN,
    )


def make_orchestrator() -> TurnOrchestrator:
    return TurnOrchestrator(
        clock=FakeClock(NOW),
        trace=TraceRecorder(),
    )


def test_begin_turn_enters_begin_state() -> None:
    orchestrator = make_orchestrator()
    interaction = make_interaction()
    orchestrator.begin_turn(interaction)
    assert orchestrator.state is TurnState.BEGIN


def test_properties_are_none_before_begin_turn() -> None:
    orchestrator = make_orchestrator()
    assert orchestrator.expression_outcome is None
    assert orchestrator.policy_result is None


def test_ingest_records_observation_and_overlay() -> None:
    orchestrator = make_orchestrator()
    orchestrator.begin_turn(make_interaction())
    evidence = make_evidence(text="我刚睡醒")
    orchestrator.ingest(evidence)
    assert orchestrator.state is TurnState.INGESTING
    assert len(orchestrator.observations) == 1
    assert isinstance(orchestrator.observations[0], Observation)
    assert orchestrator.factual_overlay is not None


def test_ingest_before_begin_raises() -> None:
    orchestrator = make_orchestrator()
    with pytest.raises(RuntimeError, match="begin_turn"):
        orchestrator.ingest(make_evidence(text="x"))


def test_run_reaches_dispatching_with_context_and_receipt() -> None:
    orchestrator = make_orchestrator()
    orchestrator.begin_turn(make_interaction())
    orchestrator.ingest(make_evidence(text="hello"))
    orchestrator.run()
    assert orchestrator.state is TurnState.DISPATCHING
    assert isinstance(orchestrator.decision_context, DecisionContext)
    assert isinstance(orchestrator.action_receipt, ActionReceipt)
    assert orchestrator.action_receipt.delivery_status is DeliveryStatus.SENT


def test_run_before_begin_raises() -> None:
    orchestrator = make_orchestrator()
    with pytest.raises(RuntimeError, match="begin_turn"):
        orchestrator.run()


def test_ports_injectable_with_fakes() -> None:
    class FailingAgent:
        def respond(self, provider_context: ProviderExpressionContext) -> str:
            raise AgentFailure("agent boom")

    from mind_runtime.pipeline.ports import AgentFailure

    orchestrator = make_orchestrator()
    orchestrator.agent = FailingAgent()
    assert isinstance(orchestrator.agent, AgentPort)
    orchestrator.begin_turn(make_interaction())
    orchestrator.ingest(make_evidence(text="hello"))
    with pytest.raises(AgentFailure):
        orchestrator.run()


def test_trace_records_lifecycle_stages() -> None:
    orchestrator = make_orchestrator()
    orchestrator.begin_turn(make_interaction())
    orchestrator.ingest(make_evidence(text="hello"))
    orchestrator.run()
    stages = [entry.stage for entry in orchestrator.trace.trace("interaction-1")]
    assert stages == [
        "begin",
        "ingest",
        "process",
        "projection",
        "expression_context",
        "expression_compile",
        "expression",
        "dispatch",
    ]


def test_turn_state_values() -> None:
    assert {state.value for state in TurnState} == {
        "begin",
        "ingesting",
        "processing",
        "dispatching",
        "awaiting_commit",
        "committed",
        "aborted",
    }
