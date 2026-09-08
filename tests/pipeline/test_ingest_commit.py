"""D2S.2 ingest vs turn-commit two-phase observability tests."""

from datetime import UTC, datetime

from mind_runtime.contracts import Interaction, InteractionStatus
from mind_runtime.pipeline.orchestrator import TurnOrchestrator, TurnState
from mind_runtime.pipeline.stubs import StubEffectiveState
from mind_runtime.pipeline.trace import TraceRecorder
from tests.golden.fixtures.common import make_evidence, make_scope
from tests.support.fake_clock import FakeClock

NOW = datetime(2026, 8, 20, 16, 0, tzinfo=UTC)


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


def test_ingest_shows_factual_overlay_before_projection() -> None:
    orchestrator = make_orchestrator()
    orchestrator.begin_turn(make_interaction())
    orchestrator.ingest(make_evidence(text="我刚睡醒"))
    # Factual read-your-writes: overlay visible immediately after ingest.
    assert "user_message.observed" in orchestrator.factual_overlay
    # Projected mind state is NOT present before run.
    assert orchestrator.projected is None
    assert orchestrator.state.value == "ingesting"


def test_run_creates_projection_but_canonical_unchanged() -> None:
    orchestrator = make_orchestrator()
    orchestrator.begin_turn(make_interaction())
    orchestrator.ingest(make_evidence(text="我刚睡醒"))
    canonical_before = orchestrator.canonical
    orchestrator.run()
    assert orchestrator.projected is not None
    assert orchestrator.projected.committed is False
    assert orchestrator.canonical == canonical_before


def test_commit_promotes_projection_to_canonical() -> None:
    orchestrator = make_orchestrator()
    orchestrator.begin_turn(make_interaction())
    orchestrator.ingest(make_evidence(text="我刚睡醒"))
    orchestrator.run()
    assert orchestrator.canonical == ()
    orchestrator.commit_turn()
    assert orchestrator.state.value == "committed"
    assert len(orchestrator.canonical) == 1


def test_abort_discards_projection_canonical_unchanged() -> None:
    orchestrator = make_orchestrator()
    orchestrator.begin_turn(make_interaction())
    orchestrator.ingest(make_evidence(text="我刚睡醒"))
    orchestrator.run()
    canonical_before = orchestrator.canonical
    orchestrator.abort_turn()
    assert orchestrator.state.value == "aborted"
    assert orchestrator.canonical == canonical_before
    assert orchestrator.factual_overlay == {}


def test_effective_state_consumes_factual_overlay() -> None:
    """D2S.1 carry-over: read-your-writes overlay feeds effective state."""
    orchestrator = make_orchestrator()
    orchestrator.begin_turn(make_interaction())
    evidence = make_evidence(text="我刚睡醒")
    orchestrator.ingest(evidence)
    orchestrator.run()
    # The effective state must reflect the ingested evidence refs.
    effective = orchestrator.effective_state.effective(
        interaction_id="interaction-1",
        evidence_refs=orchestrator.observations[0].evidence_refs,
        canonical_snapshot=orchestrator.canonical,
        scope=make_scope(),
        clock=NOW,
    )
    assert evidence.id in effective.evidence_refs


def test_awaiting_commit_is_reserved_for_d5() -> None:
    # AWAITING_COMMIT exists on the enum but D2S never enters it; D5 owns it.
    assert TurnState.AWAITING_COMMIT.value == "awaiting_commit"
    assert TurnState.AWAITING_COMMIT not in (
        TurnState.BEGIN,
        TurnState.INGESTING,
        TurnState.PROCESSING,
        TurnState.DISPATCHING,
        TurnState.COMMITTED,
        TurnState.ABORTED,
    )


def test_stub_effective_state_overlay_is_observable() -> None:
    stub = StubEffectiveState()
    assert stub.overlay_supported is True
