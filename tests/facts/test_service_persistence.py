"""D3.C2/C3 service-level restart and replay semantics over a durable backend."""

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from mind_runtime.facts.persistence import SqliteFactBackend
from mind_runtime.facts.ports import FactAdmissionDisposition
from mind_runtime.facts.service import FactAdmissionConflictError, FactIngestService
from mind_runtime.facts.validators import AuthorityError
from tests.golden.fixtures.common import make_evidence
from tests.support.fake_clock import FakeClock

NOW = datetime(2026, 8, 21, 11, 0, tzinfo=UTC)


def make_service(path: str | Path) -> FactIngestService:
    return FactIngestService(clock=FakeClock(NOW), backend=SqliteFactBackend(path))


def test_evidence_and_observation_survive_restart(tmp_path: Path) -> None:
    path = tmp_path / "facts.db"
    service = make_service(path)
    evidence = make_evidence(text="hello")
    service.admit(
        evidence,
        interaction_id="interaction-1",
        writing_runtime="runtime-1",
        writing_persona_id=None,
    )
    # Simulated restart: a brand-new service over the same backend file.
    restarted = make_service(path)
    assert restarted.evidence.count() == 1
    assert restarted.observations.count() == 1
    observation = restarted.observations.all()[0]
    assert observation.id == f"observation-{evidence.id}"
    assert observation.interaction_id == "interaction-1"


def test_replay_after_restart_stays_idempotent(tmp_path: Path) -> None:
    path = tmp_path / "facts.db"
    service = make_service(path)
    evidence = make_evidence(text="hello")
    service.admit(
        evidence,
        interaction_id="interaction-1",
        writing_runtime="runtime-1",
        writing_persona_id=None,
    )
    restarted = make_service(path)
    restarted.admit(
        evidence,
        interaction_id="interaction-1",
        writing_runtime="runtime-1",
        writing_persona_id=None,
    )
    assert restarted.evidence.count() == 1
    assert restarted.observations.count() == 1
    assert len(restarted.provenance.all()) == 1


def test_provenance_survives_restart_with_distinct_times(tmp_path: Path) -> None:
    from datetime import timedelta

    path = tmp_path / "facts.db"
    service = make_service(path)
    occurred = NOW - timedelta(hours=2)
    evidence = make_evidence(text="hello", occurred_at=occurred, received_at=NOW)
    service.admit(
        evidence,
        interaction_id="interaction-1",
        writing_runtime="runtime-1",
        writing_persona_id=None,
    )
    restarted = make_service(path)
    entries = restarted.provenance.all()
    assert len(entries) == 1
    entry = entries[0]
    assert entry.interaction_id == "interaction-1"
    assert entry.evidence_id == evidence.id
    assert entry.occurred_at == occurred
    assert entry.received_at == NOW
    assert entry.occurred_at != entry.received_at


def test_rejected_evidence_survives_restart_for_audit(tmp_path: Path) -> None:
    path = tmp_path / "facts.db"
    service = make_service(path)
    evidence = make_evidence(
        text="感觉你有点累。", source_id="assistant-1", source_type="assistant_message"
    )
    with pytest.raises(AuthorityError):
        service.admit(
            evidence,
            interaction_id="interaction-1",
            writing_runtime="runtime-1",
            writing_persona_id=None,
        )
    restarted = make_service(path)
    # Rejected evidence is durably auditable; no observation was produced.
    assert restarted.evidence.count() == 1
    assert restarted.observations.count() == 0


def test_rejected_evidence_persisted_as_evidence_row_only(tmp_path: Path) -> None:
    path = tmp_path / "facts.db"
    service = make_service(path)
    evidence = make_evidence(
        text="感觉你有点累。", source_id="assistant-1", source_type="assistant_message"
    )
    with pytest.raises(AuthorityError):
        service.admit(
            evidence,
            interaction_id="interaction-1",
            writing_runtime="runtime-1",
            writing_persona_id=None,
        )
    conn = sqlite3.connect(path)
    evidence_rows = conn.execute("SELECT id, interaction_id FROM evidence").fetchall()
    observation_rows = conn.execute("SELECT id FROM observations").fetchall()
    conn.close()
    assert [(row[0], row[1]) for row in evidence_rows] == [(evidence.id, "interaction-1")]
    assert observation_rows == []


def test_admission_persists_both_rows_in_database(tmp_path: Path) -> None:
    path = tmp_path / "facts.db"
    service = make_service(path)
    evidence = make_evidence(text="hello")
    service.admit(
        evidence,
        interaction_id="interaction-1",
        writing_runtime="runtime-1",
        writing_persona_id=None,
    )
    conn = sqlite3.connect(path)
    evidence_rows = conn.execute("SELECT id FROM evidence").fetchall()
    observation_rows = conn.execute("SELECT id FROM observations").fetchall()
    conn.close()
    assert [row[0] for row in evidence_rows] == [evidence.id]
    assert [row[0] for row in observation_rows] == [f"observation-{evidence.id}"]


def test_crash_window_observation_healed_by_idempotent_replay(tmp_path: Path) -> None:
    path = tmp_path / "facts.db"
    service = make_service(path)
    evidence = make_evidence(text="hello")
    service.admit(
        evidence,
        interaction_id="interaction-1",
        writing_runtime="runtime-1",
        writing_persona_id=None,
    )
    # Simulate a crash between the evidence insert and the observation insert.
    conn = sqlite3.connect(path)
    conn.execute("DELETE FROM observations")
    conn.commit()
    conn.close()
    restarted = make_service(path)
    assert restarted.evidence.count() == 1
    assert restarted.observations.count() == 0
    # Replay heals the derived observation without duplicating evidence; the
    # repaired Observation keeps the original admission identity (ADR-0009).
    healed = restarted.admit(
        evidence,
        interaction_id="interaction-1",
        writing_runtime="runtime-1",
        writing_persona_id=None,
    )
    assert healed.disposition is FactAdmissionDisposition.REPAIRED
    assert restarted.evidence.count() == 1
    assert restarted.observations.count() == 1


def test_orphan_observation_fails_closed(tmp_path: Path) -> None:
    """A DB with an observation row but no evidence row is an impossible
    partial pair: admission fails closed atomically (ADR-0009)."""
    path = tmp_path / "facts.db"
    backend = SqliteFactBackend(path)
    evidence = make_evidence(text="hello")
    service = FactIngestService(clock=FakeClock(NOW), backend=backend)
    service.admit(
        evidence,
        interaction_id="interaction-1",
        writing_runtime="runtime-1",
        writing_persona_id=None,
    )
    # Remove the evidence row only (corrupt state).
    conn = sqlite3.connect(path)
    conn.execute("DELETE FROM evidence")
    conn.commit()
    conn.close()
    restarted = make_service(path)
    assert restarted.evidence.count() == 0
    assert restarted.observations.count() == 1
    with pytest.raises(FactAdmissionConflictError, match="observation"):
        restarted.admit(
            evidence,
            interaction_id="interaction-1",
            writing_runtime="runtime-1",
            writing_persona_id=None,
        )
    # Atomic fail-closed: no evidence row was fabricated by the attempt.
    assert restarted.evidence.count() == 0
    assert restarted.observations.count() == 1


def test_two_services_share_one_backend_idempotently(tmp_path: Path) -> None:
    path = tmp_path / "facts.db"
    evidence = make_evidence(text="hello")
    first = make_service(path)
    first.admit(
        evidence,
        interaction_id="interaction-1",
        writing_runtime="runtime-1",
        writing_persona_id=None,
    )
    # A second service instance (e.g. another turn) replays the same evidence.
    second = make_service(path)
    second.admit(
        evidence,
        interaction_id="interaction-1",
        writing_runtime="runtime-1",
        writing_persona_id=None,
    )
    assert first.evidence.count() == 1
    assert second.evidence.count() == 1
    assert second.observations.count() == 1
    assert len(second.provenance.all()) == 1


def test_restart_without_backend_stays_in_memory(tmp_path: Path) -> None:
    service = FactIngestService(clock=FakeClock(NOW))
    evidence = make_evidence(text="hello")
    service.admit(
        evidence,
        interaction_id="interaction-1",
        writing_runtime="runtime-1",
        writing_persona_id=None,
    )
    fresh = FactIngestService(clock=FakeClock(NOW))
    assert fresh.evidence.count() == 0
    assert fresh.observations.count() == 0
    # The original instance keeps its in-memory state.
    assert service.evidence.count() == 1
