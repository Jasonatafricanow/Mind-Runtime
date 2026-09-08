"""C7B STEP 0.3 — disk-reopen proof tests (DB1-DB5).

Each test creates an isolated SQLite file in a temp directory,
destroys all Python objects, and reopens the backend from the
same on-disk file. The on-disk file is the only authority; the
in-memory backend is NOT involved here.
"""

from __future__ import annotations

import gc
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from mind_runtime.contracts import (
    DeliveryReceipt,
    DeliveryStatus,
    Scope,
    ScopeDomain,
    SyncFields,
)
from mind_runtime.delivery import (
    DeliveryLifecycleState,
    DeliveryRequest,
    SqliteDeliveryBackend,
    make_message_id,
    make_request_id,
)

NOW = datetime(2026, 1, 1, tzinfo=UTC)
SCOPE = Scope(domain=ScopeDomain.USER, user_id="u1")
RUNTIME_ID = "xiyue"


def _request(
    *, request_id: str, body: bytes = b"hello",
    idempotency_key: str = "k1", action_intent_id: str = "intent-1",
) -> DeliveryRequest:
    return DeliveryRequest(
        request_id=request_id,
        message_id=make_message_id(request_id),
        scope=SCOPE, origin_runtime_id=RUNTIME_ID,
        channel="weixin", target="user-1", action_type="proactive_message", payload_bytes=body,
        created_at=NOW,
        sync=SyncFields(SCOPE, RUNTIME_ID, request_id, 1, f"idem-{request_id}"),
    )


def _build_receipt(request: DeliveryRequest) -> DeliveryReceipt:
    return DeliveryReceipt(
        receipt_id=f"recpt-{request.request_id}",
        scope=request.scope,
        origin_runtime_id=request.origin_runtime_id,
        message_id=request.message_id,
        delivery_status=DeliveryStatus.SENT,
        delivered_at=NOW,
        sync=SyncFields(
            request.scope, request.origin_runtime_id,
            f"recpt-{request.request_id}", 1, f"idem-recpt-{request.request_id}",
        ),
    )


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "c7b.db"


# ----------------------------------------------------------- DB1


def test_db1_request_persists_across_reopen(db_path: Path) -> None:
    """Persist a DeliveryRequest + lifecycle state. Close backend.
    Open a new SqliteDeliveryBackend on the same path. The
    persisted request must be retrievable with identical
    bytes/state.
    """

    request = _request(request_id=make_request_id(SCOPE, "intent-1", "k1"))
    backend = SqliteDeliveryBackend(db_path)
    backend.record_request(
        request, lifecycle_state=DeliveryLifecycleState.PENDING,
    )
    backend.close()
    del backend
    gc.collect()

    fresh = SqliteDeliveryBackend(db_path)
    try:
        row = fresh.get_durable_request(request.request_id)
        assert row is not None
        assert row.request == request
        assert row.lifecycle_state is DeliveryLifecycleState.PENDING
        assert row.attempt_count == 0
        assert row.last_attempt_at is None
        assert row.last_reconcile_at is None
    finally:
        fresh.close()


# ----------------------------------------------------------- DB2


def test_db2_accepted_receipt_persists_with_provider_receipt_ref(
    db_path: Path,
) -> None:
    """Persist an ACCEPTED receipt with a provider_receipt_ref.
    Close. Reopen. The receipt and the provider_receipt_ref are
    preserved byte-for-byte.
    """

    request = _request(request_id=make_request_id(SCOPE, "intent-1", "k1"))
    receipt = _build_receipt(request)
    backend = SqliteDeliveryBackend(db_path)
    backend.record_request(
        request, lifecycle_state=DeliveryLifecycleState.IN_FLIGHT,
    )
    provider_ref = "wmp-abc-12345"
    provider_msg = "wm-msg-001"
    backend.record_receipt(
        receipt, request_id=request.request_id,
        provider_receipt_ref=provider_ref,
        provider_message_ref=provider_msg,
        attempt=1,
    )
    backend.set_lifecycle_state(
        request.request_id, DeliveryLifecycleState.ACCEPTED, at=NOW,
    )
    backend.close()
    del backend
    gc.collect()

    fresh = SqliteDeliveryBackend(db_path)
    try:
        stored = fresh.get_durable_receipt(receipt.receipt_id)
        assert stored is not None
        assert stored.receipt == receipt
        assert stored.provider_receipt_ref == provider_ref
        assert stored.provider_message_ref == provider_msg
        assert stored.attempt == 1
        assert stored.request_id == request.request_id
        row = fresh.get_durable_request(request.request_id)
        assert row is not None
        assert row.lifecycle_state is DeliveryLifecycleState.ACCEPTED
    finally:
        fresh.close()


# ----------------------------------------------------------- DB3


def test_db3_failed_retryable_and_unknown_remain_distinct_after_reopen(
    db_path: Path,
) -> None:
    """Persist one FAILED_RETRYABLE request and one UNKNOWN request.
    Reopen. The two distinct states remain distinct after reopen.
    """

    retryable = _request(
        request_id=make_request_id(SCOPE, "intent-1", "retry-1"),
    )
    unknown = _request(
        request_id=make_request_id(SCOPE, "intent-1", "unknown-1"),
    )
    backend = SqliteDeliveryBackend(db_path)
    backend.record_request(
        retryable, lifecycle_state=DeliveryLifecycleState.FAILED_RETRYABLE,
    )
    backend.record_request(
        unknown, lifecycle_state=DeliveryLifecycleState.UNKNOWN,
    )
    backend.close()
    del backend
    gc.collect()

    fresh = SqliteDeliveryBackend(db_path)
    try:
        retryable_row = fresh.get_durable_request(retryable.request_id)
        unknown_row = fresh.get_durable_request(unknown.request_id)
        assert retryable_row is not None
        assert unknown_row is not None
        assert retryable_row.lifecycle_state is (
            DeliveryLifecycleState.FAILED_RETRYABLE
        )
        assert unknown_row.lifecycle_state is DeliveryLifecycleState.UNKNOWN
        # And the two rows are still distinct (different rows, different ids).
        assert retryable_row is not unknown_row
    finally:
        fresh.close()


# ----------------------------------------------------------- DB4


def test_db4_idempotent_replay_then_collision_raises(db_path: Path) -> None:
    """Persist a request. Reopen. Insert the same request_id again
    with identical bytes — must be idempotent (no duplicate row,
    no error). Insert the same id with different bytes — must
    raise ValueError.
    """

    request = _request(
        request_id=make_request_id(SCOPE, "intent-1", "k1"),
        body=b"original",
    )
    backend = SqliteDeliveryBackend(db_path)
    backend.record_request(
        request, lifecycle_state=DeliveryLifecycleState.PENDING,
    )
    backend.close()
    del backend
    gc.collect()

    fresh = SqliteDeliveryBackend(db_path)
    try:
        # Idempotent: identical bytes -> False, no error, no new row.
        same = _request(
            request_id=request.request_id, body=b"original",
        )
        result = fresh.record_request(
            same, lifecycle_state=DeliveryLifecycleState.PENDING,
        )
        assert result is False
        row = fresh.get_durable_request(request.request_id)
        assert row is not None
        assert row.lifecycle_state is DeliveryLifecycleState.PENDING

        # Different bytes -> ValueError.
        tampered = _request(
            request_id=request.request_id, body=b"mutated",
        )
        with pytest.raises(ValueError, match="different immutable bytes"):
            fresh.record_request(
                tampered, lifecycle_state=DeliveryLifecycleState.PENDING,
            )
    finally:
        fresh.close()


# ----------------------------------------------------------- DB5


def test_db5_corrupt_state_json_fails_closed_with_row_id(
    db_path: Path,
) -> None:
    """Manually corrupt one row's state JSON or drop a required
    column in the SQLite file. Reopen — must fail closed with a
    clear ValueError naming the bad row id, not a generic SQLite
    traceback or silent ignore.
    """

    request = _request(request_id=make_request_id(SCOPE, "intent-1", "k1"))
    backend = SqliteDeliveryBackend(db_path)
    backend.record_request(
        request, lifecycle_state=DeliveryLifecycleState.PENDING,
    )
    backend.close()
    del backend
    gc.collect()

    # Manually corrupt the sync JSON for the row.
    conn = sqlite3.connect(db_path)
    conn.execute(
        "UPDATE delivery_requests SET sync = ? WHERE request_id = ?",
        ("{not-valid-json", request.request_id),
    )
    conn.commit()
    conn.close()

    with pytest.raises(ValueError, match=request.request_id):
        SqliteDeliveryBackend(db_path)


def test_db5_missing_column_fails_closed(db_path: Path) -> None:
    """Drop a required column from the SQLite file. Reopen —
    must fail closed with a clear ValueError naming the bad
    table / column, not a silent ignore.
    """

    request = _request(request_id=make_request_id(SCOPE, "intent-1", "k1"))
    backend = SqliteDeliveryBackend(db_path)
    backend.record_request(
        request, lifecycle_state=DeliveryLifecycleState.PENDING,
    )
    backend.close()
    del backend
    gc.collect()

    # Recreate the table without the required ``channel`` column.
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE delivery_requests_tmp AS SELECT request_id, message_id,"
        " scope_domain, scope_user_id, scope_agent_id, scope_persona_id,"
        " scope_relationship_id, scope_world_id, scope_interaction_id,"
        " origin_runtime_id, target, payload_bytes, created_at, sync,"
        " lifecycle_state, attempt_count, last_attempt_at,"
        " last_reconcile_at, last_provider_receipt_ref, sync_version"
        " FROM delivery_requests"
    )
    conn.execute("DROP TABLE delivery_requests")
    conn.execute("ALTER TABLE delivery_requests_tmp RENAME TO delivery_requests")
    conn.commit()
    conn.close()

    with pytest.raises(ValueError, match="channel"):
        SqliteDeliveryBackend(db_path)


def test_persistence_unknown_table_in_loader_refused() -> None:
    """Direct call to _load_all_required_columns with an unknown table
    name is refused (defense in depth; the only real callers pass
    known names)."""
    import sqlite3

    from mind_runtime.delivery.persistence import _load_all_required_columns

    conn = sqlite3.connect(":memory:")
    try:
        with pytest.raises(ValueError, match="unknown durable delivery table"):
            _load_all_required_columns(conn, "drop_this_table_now")
    finally:
        conn.close()
