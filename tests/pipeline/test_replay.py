"""D2S.4 smoke tests: replay reproduces the same stage trace."""

from datetime import UTC, datetime

from mind_runtime.contracts import Interaction, InteractionStatus
from mind_runtime.pipeline.fake_agent import FakeAgent
from mind_runtime.pipeline.orchestrator import TurnOrchestrator
from mind_runtime.pipeline.trace import TraceRecorder
from tests.golden.fixtures.common import make_evidence, make_scope
from tests.support.fake_clock import FakeClock

NOW = datetime(2026, 8, 20, 18, 0, tzinfo=UTC)


def make_interaction(interaction_id: str) -> Interaction:
    scope = make_scope()
    return Interaction(
        interaction_id=interaction_id,
        scope=scope,
        channel="chat",
        session_id="session-1",
        turn_id=f"turn-{interaction_id}",
        started_at=NOW,
        committed_at=None,
        status=InteractionStatus.OPEN,
    )


def run_once(interaction_id: str, agent: FakeAgent) -> TurnOrchestrator:
    orchestrator = TurnOrchestrator(
        clock=FakeClock(NOW),
        trace=TraceRecorder(),
        agent=agent,
    )
    orchestrator.begin_turn(make_interaction(interaction_id))
    orchestrator.ingest(make_evidence(text="我刚睡醒"))
    orchestrator.run()
    orchestrator.commit_turn()
    return orchestrator


def test_replay_same_input_same_stage_trace() -> None:
    """Replaying the same interaction reproduces the same stage order."""
    first = run_once("interaction-a", FakeAgent(["reply"]))
    second = run_once("interaction-a", FakeAgent(["reply"]))

    first_stages = [entry.stage for entry in first.trace.trace("interaction-a")]
    second_stages = [entry.stage for entry in second.trace.trace("interaction-a")]
    assert (
        first_stages
        == second_stages
        == [
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
    )

    # Different interactions are not conflated in the trace.
    assert first.trace.trace("interaction-other") == ()
