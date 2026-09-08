"""D3.C3 restart/replay semantics on the canonical orchestrator path.

The production TurnOrchestrator must keep the factual plane durable across
restarts: Evidence and Observation survive, replay stays idempotent,
provenance survives, and crash windows heal by idempotent replay.
"""

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from mind_runtime.contracts import Interaction, InteractionStatus, Scope
from mind_runtime.facts.persistence import SqliteFactBackend
from mind_runtime.facts.service import FactIngestService
from mind_runtime.facts.validators import AuthorityError
from mind_runtime.pipeline.orchestrator import TurnOrchestrator
from mind_runtime.pipeline.trace import TraceRecorder
from tests.golden.fixtures.common import make_evidence, make_scope
from tests.support.fake_clock import FakeClock

NOW = datetime(2026, 8, 21, 13, 0, tzinfo=UTC)


def make_interaction(
    *, scope: Scope | None = None, interaction_id: str = "interaction-1"
) -> Interaction:
    return Interaction(
        interaction_id=interaction_id,
        scope=scope or make_scope(),
        channel="chat",
        session_id="session-1",
        turn_id="turn-1",
        started_at=NOW,
        committed_at=None,
        status=InteractionStatus.OPEN,
    )


def make_orchestrator(path: str | Path) -> TurnOrchestrator:
    service = FactIngestService(clock=FakeClock(NOW), backend=SqliteFactBackend(path))
    return TurnOrchestrator(clock=FakeClock(NOW), trace=TraceRecorder(), fact_ingest=service)


def service_of(orchestrator: TurnOrchestrator) -> FactIngestService:
    assert isinstance(orchestrator.fact_ingest, FactIngestService)
    return orchestrator.fact_ingest


def test_restart_preserves_evidence_observation_and_provenance(tmp_path: Path) -> None:
    path = tmp_path / "facts.db"
    orchestrator = make_orchestrator(path)
    evidence = make_evidence(text="我刚睡醒")
    orchestrator.begin_turn(make_interaction())
    orchestrator.ingest(evidence)
    orchestrator.run()
    orchestrator.commit_turn()

    # Simulated restart: fresh orchestrator over the same backend file.
    restarted = make_orchestrator(path)
    service = service_of(restarted)
    assert service.evidence.count() == 1
    assert service.observations.count() == 1
    observation = service.observations.all()[0]
    assert observation.id == f"observation-{evidence.id}"
    assert observation.interaction_id == "interaction-1"
    provenance = service.provenance.all()
    assert len(provenance) == 1
    assert provenance[0].evidence_id == evidence.id


def test_replay_after_restart_stays_idempotent(tmp_path: Path) -> None:
    path = tmp_path / "facts.db"
    orchestrator = make_orchestrator(path)
    evidence = make_evidence(text="我刚睡醒")
    orchestrator.begin_turn(make_interaction())
    orchestrator.ingest(evidence)
    restarted = make_orchestrator(path)
    restarted.begin_turn(make_interaction(interaction_id="interaction-2"))
    restarted.ingest(evidence)
    service = service_of(restarted)
    assert service.evidence.count() == 1
    assert service.observations.count() == 1
    assert len(service.provenance.all()) == 1


def test_rejected_evidence_survives_restart_via_orchestrator(tmp_path: Path) -> None:
    path = tmp_path / "facts.db"
    orchestrator = make_orchestrator(path)
    assistant = make_evidence(
        text="感觉你有点累。", source_id="assistant-1", source_type="assistant_message"
    )
    orchestrator.begin_turn(make_interaction())
    with pytest.raises(AuthorityError, match="assistant"):
        orchestrator.ingest(assistant)
    restarted = make_orchestrator(path)
    assert service_of(restarted).evidence.count() == 1
    assert service_of(restarted).observations.count() == 0


def test_crash_window_healed_by_replay_via_orchestrator(tmp_path: Path) -> None:
    path = tmp_path / "facts.db"
    orchestrator = make_orchestrator(path)
    evidence = make_evidence(text="我刚睡醒")
    orchestrator.begin_turn(make_interaction())
    orchestrator.ingest(evidence)
    # Simulate a crash between evidence and observation inserts.
    conn = sqlite3.connect(path)
    conn.execute("DELETE FROM observations")
    conn.commit()
    conn.close()
    restarted = make_orchestrator(path)
    assert service_of(restarted).evidence.count() == 1
    assert service_of(restarted).observations.count() == 0
    restarted.begin_turn(make_interaction(interaction_id="interaction-2"))
    restarted.ingest(evidence)
    assert service_of(restarted).evidence.count() == 1
    assert service_of(restarted).observations.count() == 1
    # Evidence was not duplicated by the healing replay.
    conn = sqlite3.connect(path)
    rows = conn.execute("SELECT COUNT(*) FROM evidence").fetchone()
    conn.close()
    assert rows is not None
    assert rows[0] == 1


def test_duplicate_event_across_turns_never_duplicates(tmp_path: Path) -> None:
    path = tmp_path / "facts.db"
    orchestrator = make_orchestrator(path)
    evidence = make_evidence(text="我刚睡醒")
    for turn in ("turn-1", "turn-2", "turn-3"):
        orchestrator.begin_turn(make_interaction(interaction_id=f"interaction-{turn}"))
        orchestrator.ingest(evidence)
    service = service_of(orchestrator)
    assert service.evidence.count() == 1
    assert service.observations.count() == 1
    assert len(service.provenance.all()) == 1
