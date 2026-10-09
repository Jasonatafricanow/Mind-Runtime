"""Host receipts after a process restart must agree with the durable commit marker."""

import hashlib
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from tests.support.fake_clock import FakeClock

from mind_runtime.contracts import Scope, ScopeDomain
from mind_runtime.contracts.host import (
    HostAbortRequest,
    HostCommitRequest,
    HostStatus,
    HostTurnRequest,
    HostTurnStatus,
)
from mind_runtime.host import MindRuntimeHostAdapter
from mind_runtime.pipeline.orchestrator import TurnOrchestrator
from mind_runtime.pipeline.trace import TraceRecorder
from mind_runtime.state.persistence import SqliteCommitMarkerStore, SqliteStateBackend

NOW = datetime(2026, 8, 20, 14, 0, tzinfo=UTC)
SCOPE = Scope(domain=ScopeDomain.USER, user_id="u1")


def _boot(db: Path):
    backend = SqliteStateBackend(db)
    markers = SqliteCommitMarkerStore(db)
    trace = TraceRecorder()
    orch = TurnOrchestrator(
        clock=FakeClock(NOW), trace=trace, state_backend=backend, commit_markers=markers
    )
    return backend, markers, MindRuntimeHostAdapter(orchestrator=orch, trace=trace)


def _req(message: str, iid: str = "I-1") -> HostTurnRequest:
    return HostTurnRequest(
        interaction_id=iid, runtime_id="rt", scope=SCOPE, occurred_at=NOW,
        user_message=message, channel="t",
    )


def _db_digest(db: Path) -> str:
    con = sqlite3.connect(db)
    try:
        rows = []
        for (name,) in con.execute(
            "select name from sqlite_master where type='table' and name not like 'sqlite_%' "
            "order by name"
        ):
            rows.append((name, con.execute(f"select * from {name}").fetchall()))
        return hashlib.sha1(repr(rows).encode()).hexdigest()
    finally:
        con.close()


def _commit_then_restart(tmp_path: Path):
    db = tmp_path / "mr.db"
    backend, markers, adapter = _boot(db)
    begun = adapter.begin_turn(_req("original"))
    receipt = adapter.commit_turn(
        HostCommitRequest(turn_id=begun.turn_id, interaction_id=begun.interaction_id)
    )
    assert receipt.status is HostStatus.OK
    digest = _db_digest(db)
    backend.close()
    markers.close()
    return db, begun, digest


def test_replay_after_restart_is_already_processed_and_not_reentered(tmp_path):
    db, _, digest = _commit_then_restart(tmp_path)
    backend, markers, adapter = _boot(db)
    try:
        result = adapter.begin_turn(_req("original"))
        assert result.status is HostTurnStatus.ALREADY_PROCESSED
        assert result.outcome is HostStatus.ALREADY_PROCESSED
        assert "no_reentry" in result.reason_codes
        assert "payload_unverified" in result.reason_codes
        assert _db_digest(db) == digest
    finally:
        backend.close()
        markers.close()


def test_changed_payload_after_restart_never_starts_a_new_turn(tmp_path):
    db, _, digest = _commit_then_restart(tmp_path)
    backend, markers, adapter = _boot(db)
    try:
        result = adapter.begin_turn(_req("completely different"))
        assert result.outcome is HostStatus.ALREADY_PROCESSED
        assert _db_digest(db) == digest
    finally:
        backend.close()
        markers.close()


def test_abort_of_durably_committed_turn_is_refused_after_restart(tmp_path):
    db, begun, digest = _commit_then_restart(tmp_path)
    backend, markers, adapter = _boot(db)
    try:
        adapter.begin_turn(_req("original"))
        receipt = adapter.abort_turn(
            HostAbortRequest(turn_id=begun.turn_id, interaction_id=begun.interaction_id)
        )
        assert receipt.status is HostStatus.FAILED
        assert "cannot_abort_committed" in receipt.reason_codes
        assert "projection_discarded" not in receipt.reason_codes
        assert _db_digest(db) == digest
    finally:
        backend.close()
        markers.close()


def test_commit_retry_after_restart_reports_already_committed(tmp_path):
    db, begun, digest = _commit_then_restart(tmp_path)
    backend, markers, adapter = _boot(db)
    try:
        adapter.begin_turn(_req("original"))
        receipt = adapter.commit_turn(
            HostCommitRequest(turn_id=begun.turn_id, interaction_id=begun.interaction_id)
        )
        assert receipt.status is HostStatus.OK
        assert "already_committed" in receipt.reason_codes
        assert _db_digest(db) == digest
    finally:
        backend.close()
        markers.close()


def test_uncommitted_interaction_is_not_treated_as_processed_after_restart(tmp_path):
    db = tmp_path / "mr.db"
    backend, markers, adapter = _boot(db)
    adapter.begin_turn(_req("never committed"))  # process dies before commit
    backend.close()
    markers.close()
    backend, markers, adapter = _boot(db)
    try:
        result = adapter.begin_turn(_req("never committed"))
        assert result.outcome is HostStatus.OK
        assert result.status is not HostTurnStatus.ALREADY_PROCESSED
    finally:
        backend.close()
        markers.close()
