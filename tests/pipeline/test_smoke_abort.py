"""D2S.4 smoke tests: abort path leaves canonical untouched (G13b-style)."""

from datetime import UTC, datetime

from mind_runtime.contracts import (
    Interaction,
    InteractionStatus,
)
from mind_runtime.pipeline.fake_agent import FakeAgent
from mind_runtime.pipeline.orchestrator import TurnOrchestrator
from mind_runtime.pipeline.ports import AgentFailure
from mind_runtime.pipeline.trace import TraceRecorder
from tests.golden.fixtures.common import make_evidence, make_scope, make_state
from tests.support.fake_clock import FakeClock

NOW = datetime(2026, 8, 20, 18, 0, tzinfo=UTC)


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


def test_smoke_agent_failure_aborts_without_polluting_canonical() -> None:
    """G13b-style: LLM/agent failure aborts the turn; canonical stays clean."""
    canonical_before = (make_state(dimension="user.sleep.phase", value="sleeping"),)
    agent = FakeAgent([AgentFailure("llm failure")])
    orchestrator = TurnOrchestrator(
        clock=FakeClock(NOW),
        trace=TraceRecorder(),
        agent=agent,
        canonical_snapshot=canonical_before,
    )
    orchestrator.begin_turn(make_interaction())
    orchestrator.ingest(make_evidence(text="我刚睡醒"))

    try:
        orchestrator.run()
    except AgentFailure:
        pass

    assert orchestrator.state.value == "aborted"
    # Canonical unchanged: still exactly the pre-turn snapshot.
    assert orchestrator.canonical == canonical_before
    # No receipt was produced (nothing dispatched).
    assert orchestrator.action_receipt is None
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


def test_smoke_manual_abort_after_run_keeps_canonical() -> None:
    canonical_before = (make_state(dimension="user.sleep.phase", value="sleeping"),)
    orchestrator = TurnOrchestrator(
        clock=FakeClock(NOW),
        trace=TraceRecorder(),
        agent=FakeAgent(["ok"]),
        canonical_snapshot=canonical_before,
    )
    orchestrator.begin_turn(make_interaction())
    orchestrator.ingest(make_evidence(text="我刚睡醒"))
    orchestrator.run()
    assert orchestrator.canonical == canonical_before
    orchestrator.abort_turn()
    assert orchestrator.state.value == "aborted"
    assert orchestrator.canonical == canonical_before
    assert orchestrator.factual_overlay == {}
