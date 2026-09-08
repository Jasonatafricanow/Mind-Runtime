"""D2S.4 smoke tests: full commit path driven by golden fixtures."""

from datetime import UTC, datetime

from mind_runtime.contracts import (
    DeliveryStatus,
    Interaction,
    InteractionStatus,
)
from mind_runtime.pipeline.fake_agent import FakeAgent
from mind_runtime.pipeline.orchestrator import TurnOrchestrator
from mind_runtime.pipeline.trace import TraceRecorder
from tests.golden.fixtures.common import make_evidence, make_scope
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


def test_smoke_full_lifecycle_to_commit() -> None:
    """One scenario walks begin_turn -> commit_turn end to end (G1-style)."""
    agent = FakeAgent(["刚睡醒的话，早安呀"])
    orchestrator = TurnOrchestrator(
        clock=FakeClock(NOW),
        trace=TraceRecorder(),
        agent=agent,
    )
    orchestrator.begin_turn(make_interaction())
    orchestrator.ingest(make_evidence(text="我刚睡醒"))
    orchestrator.run()
    assert orchestrator.action_receipt is not None
    assert orchestrator.action_receipt.delivery_status is DeliveryStatus.SENT
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
    assert agent.call_count == 1
