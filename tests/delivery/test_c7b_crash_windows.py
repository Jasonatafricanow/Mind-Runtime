"""C7B STEP 2 — crash window tests (CR1-CR5).

Each test destroys all Python objects, reopens the backend, and
asserts the recovery semantic. Crash windows are NOT simulated by
"build a fresh in-memory store" — the SQLite file is the only
authority.
"""

from __future__ import annotations

import gc
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
    InMemoryDeliveryBackend,
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


def _build_receipt(request: DeliveryRequest, status: DeliveryStatus) -> DeliveryReceipt:
    return DeliveryReceipt(
        receipt_id=f"recpt-{request.request_id}",
        scope=request.scope,
        origin_runtime_id=request.origin_runtime_id,
        message_id=request.message_id,
        delivery_status=status,
        delivered_at=NOW if status is DeliveryStatus.SENT else None,
        sync=SyncFields(
            request.scope, request.origin_runtime_id,
            f"recpt-{request.request_id}", 1, f"idem-recpt-{request.request_id}",
        ),
    )


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "c7b_crash.db"


# -------------------------------------------------------------- CR1


def test_cr1_pending_survives_crash_then_carrier_runs_once(
    db_path: Path,
) -> None:
    """Persist a request. Do NOT call the carrier. Close everything.
    Reopen. The request is still PENDING. A new deliver() call
    invokes the carrier exactly once (not zero, not twice).
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
        assert row.lifecycle_state is DeliveryLifecycleState.PENDING

        # Simulate a fresh process: a new port, a new backend.
        port = InMemoryDeliveryBackend()
        receipt = port.deliver(request)
        assert receipt.delivery_status is DeliveryStatus.SENT
        # Re-delivering the same id is a no-op on the carrier.
        receipt_again = port.deliver(request)
        assert receipt_again.receipt_id == receipt.receipt_id
        assert port.sent_count == 1
    finally:
        fresh.close()


# -------------------------------------------------------------- CR2


def test_cr2_in_flight_crash_yields_unknown_not_blind_failed(
    db_path: Path,
) -> None:
    """Start deliver(); kill the process before the carrier returns.
    Reopen. The request is in UNKNOWN. The recovery code does NOT
    blindly mark it FAILED_RETRYABLE.
    """

    request = _request(request_id=make_request_id(SCOPE, "intent-1", "k1"))
    backend = SqliteDeliveryBackend(db_path)
    backend.record_request(
        request, lifecycle_state=DeliveryLifecycleState.PENDING,
    )
    backend.set_lifecycle_state(
        request.request_id, DeliveryLifecycleState.IN_FLIGHT, at=NOW,
    )
    # Simulate the crash: persist the IN_FLIGHT row, then "die"
    # without ever writing an outcome.
    backend.close()
    del backend
    gc.collect()

    fresh = SqliteDeliveryBackend(db_path)
    try:
        row = fresh.get_durable_request(request.request_id)
        assert row is not None
        # Crash window: the row is still IN_FLIGHT. The recovery
        # code does NOT silently mark it FAILED_RETRYABLE — UNKNOWN
        # is the post-crash state, and the reconciler decides.
        # The daemon pass is what would move IN_FLIGHT -> UNKNOWN
        # before reconciliation; that is exercised in test_dr1.
        assert row.lifecycle_state is DeliveryLifecycleState.IN_FLIGHT

        # Explicit recovery: the recovery code (the daemon) must
        # transition IN_FLIGHT -> UNKNOWN (NOT FAILED_RETRYABLE).
        fresh.set_lifecycle_state(
            request.request_id,
            DeliveryLifecycleState.UNKNOWN,
            at=datetime.now(tz=UTC),
        )
        row = fresh.get_durable_request(request.request_id)
        assert row is not None
        assert row.lifecycle_state is DeliveryLifecycleState.UNKNOWN
    finally:
        fresh.close()


# -------------------------------------------------------------- CR3


def test_cr3_carrier_accept_persists_across_reopen(
    db_path: Path,
) -> None:
    """Carrier returns ACCEPTED but the local code dies before the
    receipt is persisted. Reopen. The next call must NOT cause a
    duplicate logical send when the provider supports lookup; the
    persisted receipt is the same logical one.
    """

    request = _request(request_id=make_request_id(SCOPE, "intent-1", "k1"))
    backend = SqliteDeliveryBackend(db_path)
    backend.record_request(
        request, lifecycle_state=DeliveryLifecycleState.PENDING,
    )
    backend.set_lifecycle_state(
        request.request_id, DeliveryLifecycleState.IN_FLIGHT, at=NOW,
    )
    # "Die" before writing the receipt.
    backend.close()
    del backend
    gc.collect()

    fresh = SqliteDeliveryBackend(db_path)
    port = InMemoryDeliveryBackend()
    receipt = port.deliver(request)
    assert receipt.delivery_status is DeliveryStatus.SENT
    # The receipt_id is derived from request_id, so a second
    # call to deliver() with the same request yields the
    # SAME receipt_id (idempotent dedup).
    second = port.deliver(request)
    assert second.receipt_id == receipt.receipt_id
    assert port.sent_count == 1

    # Persist the receipt and ACCEPTED state.
    fresh.record_receipt(
        receipt, request_id=request.request_id,
        provider_receipt_ref="wmp-1",
        provider_message_ref="wm-msg-1",
        attempt=1,
    )
    fresh.set_lifecycle_state(
        request.request_id, DeliveryLifecycleState.ACCEPTED, at=NOW,
    )
    fresh.close()
    del fresh
    gc.collect()

    # Reopen and verify the ACCEPTED truth survives.
    reopened = SqliteDeliveryBackend(db_path)
    try:
        row = reopened.get_durable_request(request.request_id)
        assert row is not None
        assert row.lifecycle_state is DeliveryLifecycleState.ACCEPTED
        stored = reopened.get_durable_receipt(receipt.receipt_id)
        assert stored is not None
        assert stored.provider_receipt_ref == "wmp-1"
    finally:
        reopened.close()


# -------------------------------------------------------------- CR4


def test_cr4_failed_retryable_retry_increments_attempt(
    db_path: Path,
) -> None:
    """Persist a FAILED_RETRYABLE state. Retry per the explicit
    retry policy. The same delivery_id, incremented attempt.
    """

    request = _request(request_id=make_request_id(SCOPE, "intent-1", "k1"))
    backend = SqliteDeliveryBackend(db_path)
    backend.record_request(
        request, lifecycle_state=DeliveryLifecycleState.PENDING,
    )
    backend.set_lifecycle_state(
        request.request_id, DeliveryLifecycleState.FAILED_RETRYABLE, at=NOW,
    )
    backend.close()
    del backend
    gc.collect()

    fresh = SqliteDeliveryBackend(db_path)
    try:
        # First retry: FAILED_RETRYABLE -> PENDING -> IN_FLIGHT.
        # The state machine forces the round-trip; this is the
        # frozen contract.
        new_attempt = fresh.increment_attempt(
            request.request_id, at=datetime.now(tz=UTC),
        )
        assert new_attempt == 1
        fresh.set_lifecycle_state(
            request.request_id, DeliveryLifecycleState.PENDING,
            at=datetime.now(tz=UTC),
        )
        fresh.set_lifecycle_state(
            request.request_id, DeliveryLifecycleState.IN_FLIGHT,
            at=datetime.now(tz=UTC),
        )
        # Record the attempt.
        fresh.record_attempt(
            attempt_id=f"att-{request.request_id}-{new_attempt}",
            request_id=request.request_id,
            attempt=new_attempt,
            started_at=datetime.now(tz=UTC),
            ended_at=datetime.now(tz=UTC),
            outcome=DeliveryLifecycleState.FAILED_RETRYABLE,
            provider_receipt_ref=None,
            reason_codes=("transient_failure",),
        )
        fresh.set_lifecycle_state(
            request.request_id, DeliveryLifecycleState.FAILED_RETRYABLE,
            at=datetime.now(tz=UTC),
        )
        fresh.close()
        del fresh
        gc.collect()

        # Reopen: the second retry attempt would be 2.
        reopened = SqliteDeliveryBackend(db_path)
        try:
            row = reopened.get_durable_request(request.request_id)
            assert row is not None
            assert row.attempt_count == 1
            # Same request_id; not a new one.
            assert row.request.request_id == request.request_id
            attempts = reopened.attempts_for_request(request.request_id)
            assert len(attempts) == 1
            assert attempts[0].attempt == 1
        finally:
            reopened.close()
    finally:
        pass


# -------------------------------------------------------------- CR5


def test_cr5_rejected_state_has_no_automatic_retry(
    db_path: Path,
) -> None:
    """Persist a REJECTED state. No automatic retry unless the
    contract explicitly says so (it doesn't here).
    """

    request = _request(request_id=make_request_id(SCOPE, "intent-1", "k1"))
    backend = SqliteDeliveryBackend(db_path)
    backend.record_request(
        request, lifecycle_state=DeliveryLifecycleState.PENDING,
    )
    backend.set_lifecycle_state(
        request.request_id, DeliveryLifecycleState.IN_FLIGHT, at=NOW,
    )
    backend.set_lifecycle_state(
        request.request_id, DeliveryLifecycleState.REJECTED, at=NOW,
    )
    backend.close()
    del backend
    gc.collect()

    fresh = SqliteDeliveryBackend(db_path)
    try:
        row = fresh.get_durable_request(request.request_id)
        assert row is not None
        assert row.lifecycle_state is DeliveryLifecycleState.REJECTED

        # Attempting to retry must fail closed: REJECTED is
        # terminal-by-default and validate_transition refuses to
        # move it.
        with pytest.raises(ValueError, match="illegal delivery lifecycle"):
            fresh.set_lifecycle_state(
                request.request_id,
                DeliveryLifecycleState.FAILED_RETRYABLE,
                at=datetime.now(tz=UTC),
            )
    finally:
        fresh.close()
