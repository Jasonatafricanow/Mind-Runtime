"""D2S.1 additional orchestrator lifecycle tests (coverage closure)."""

from datetime import UTC, datetime

import pytest

from mind_runtime.contracts import (
    DeliveryStatus,
    Interaction,
    InteractionStatus,
)
from mind_runtime.pipeline.orchestrator import TurnOrchestrator, TurnState
from mind_runtime.pipeline.ports import AgentFailure
from mind_runtime.pipeline.trace import TraceRecorder
from tests.golden.fixtures.common import make_evidence, make_scope, make_state
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


def test_effective_state_uses_canonical_snapshot_when_present() -> None:
    from mind_runtime.pipeline.stubs import StubEffectiveState

    stub = StubEffectiveState()
    state = make_state()
    result = stub.effective(
        interaction_id="i-1",
        evidence_refs=(),
        canonical_snapshot=(state,),
        scope=make_scope(),
        clock=NOW,
    )
    assert result is state


def test_properties_return_none_without_turn() -> None:
    orchestrator = make_orchestrator()
    assert orchestrator.observations == ()
    assert orchestrator.decision_context is None
    assert orchestrator.action_receipt is None
    assert orchestrator.projected is None


def test_projected_available_after_run() -> None:
    orchestrator = make_orchestrator()
    orchestrator.begin_turn(make_interaction())
    orchestrator.ingest(make_evidence(text="hello"))
    orchestrator.run()
    assert orchestrator.projected is not None
    assert orchestrator.projected.committed is False


def test_commit_turn_applies_projection_to_canonical() -> None:
    orchestrator = make_orchestrator()
    orchestrator.begin_turn(make_interaction())
    orchestrator.ingest(make_evidence(text="hello"))
    orchestrator.run()
    assert orchestrator.state.value == "dispatching"
    orchestrator.commit_turn()
    assert orchestrator.state.value == "committed"
    assert orchestrator.canonical != ()
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
        "commit",
    ]


def test_abort_turn_discards_projection_keeps_canonical() -> None:
    orchestrator = make_orchestrator()
    orchestrator.begin_turn(make_interaction())
    orchestrator.ingest(make_evidence(text="hello"))
    orchestrator.run()
    canonical_before = orchestrator.canonical
    orchestrator.abort_turn()
    assert orchestrator.state is TurnState.ABORTED
    assert orchestrator.canonical == canonical_before
    assert orchestrator.factual_overlay == {}
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
        "abort",
    ]


def test_commit_without_projection_commits_empty() -> None:
    orchestrator = make_orchestrator()
    orchestrator.begin_turn(make_interaction())
    orchestrator.commit_turn()
    assert orchestrator.state is TurnState.COMMITTED
    assert orchestrator.canonical == ()


def test_commit_without_turn_raises() -> None:
    orchestrator = make_orchestrator()
    with pytest.raises(RuntimeError, match="begin_turn"):
        orchestrator.commit_turn()


def test_abort_without_turn_raises() -> None:
    orchestrator = make_orchestrator()
    with pytest.raises(RuntimeError, match="begin_turn"):
        orchestrator.abort_turn()


def test_default_agent_returns_stub_response() -> None:
    from mind_runtime.pipeline.orchestrator import _DefaultAgent

    orchestrator = make_orchestrator()
    orchestrator.begin_turn(make_interaction())
    orchestrator.ingest(make_evidence(text="hello"))
    orchestrator.run()
    assert orchestrator.state is TurnState.DISPATCHING
    assert orchestrator.action_receipt is not None
    assert orchestrator.action_receipt.delivery_status is DeliveryStatus.SENT
    assert _DefaultAgent().respond(orchestrator.decision_context) == "stub response"  # type: ignore[arg-type]


def test_agent_failure_trace_records_abort() -> None:
    class Boom:
        def respond(self, decision_context: object) -> str:
            raise AgentFailure("boom")

    orchestrator = make_orchestrator()
    orchestrator.agent = Boom()
    orchestrator.begin_turn(make_interaction())
    orchestrator.ingest(make_evidence(text="hello"))
    with pytest.raises(AgentFailure):
        orchestrator.run()
    assert orchestrator.state is TurnState.ABORTED
    stages = [entry.stage for entry in orchestrator.trace.trace("interaction-1")]
    assert stages == [
        "begin",
        "ingest",
        "process",
        "projection",
        "expression_context",
        "expression_compile",
        "abort",
    ]
