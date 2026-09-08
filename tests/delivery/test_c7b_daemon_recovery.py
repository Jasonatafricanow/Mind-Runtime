"""C7B STEP 6 — daemon / restart recovery tests (DR1-DR2).

A daemon pass discovers durable unfinished delivery work
(PENDING, IN_FLIGHT, UNKNOWN, FAILED_RETRYABLE) and re-drives it
WITHOUT fabricating a new would-send artifact or re-creating
the Intent. The discovery path reads from the
``SqliteDeliveryBackend`` only.
"""

from __future__ import annotations

import gc
import logging
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
    ResolvedAccept,
    SqliteDeliveryBackend,
    make_message_id,
    make_request_id,
)
from mind_runtime.delivery.daemon import DaemonPass

NOW = datetime(2026, 1, 1, tzinfo=UTC)
SCOPE = Scope(domain=ScopeDomain.USER, user_id="u1")
RUNTIME_ID = "xiyue"


def _request(
    *, request_id: str, body: bytes = b"hello",
) -> DeliveryRequest:
    return DeliveryRequest(
        request_id=request_id,
        message_id=make_message_id(request_id),
        scope=SCOPE, origin_runtime_id=RUNTIME_ID,
        channel="weixin", target="user-1", action_type="proactive_message", payload_bytes=body,
        created_at=NOW,
        sync=SyncFields(SCOPE, RUNTIME_ID, request_id, 1, f"idem-{request_id}"),
    )


class _CountingPort:
    """Records every deliver() call so tests can assert on count."""

    def __init__(self, *, fail_after: int | None = None) -> None:
        self.calls: list[DeliveryRequest] = []
        self._sent = 0
        self._fail_after = fail_after

    def deliver(self, request: DeliveryRequest) -> DeliveryReceipt:
        self.calls.append(request)
        if self._fail_after is not None and self._sent >= self._fail_after:
            return DeliveryReceipt(
                receipt_id=f"recpt-{request.request_id}",
                scope=request.scope,
                origin_runtime_id=request.origin_runtime_id,
                message_id=request.message_id,
                delivery_status=DeliveryStatus.UNKNOWN,
                delivered_at=None,
                sync=SyncFields(
                    request.scope, request.origin_runtime_id,
                    f"recpt-{request.request_id}", 1,
                    f"idem-recpt-{request.request_id}",
                ),
            )
        self._sent += 1
        return DeliveryReceipt(
            receipt_id=f"recpt-{request.request_id}",
            scope=request.scope,
            origin_runtime_id=request.origin_runtime_id,
            message_id=request.message_id,
            delivery_status=DeliveryStatus.SENT,
            delivered_at=datetime.now(tz=UTC),
            sync=SyncFields(
                request.scope, request.origin_runtime_id,
                f"recpt-{request.request_id}", 1,
                f"idem-recpt-{request.request_id}",
            ),
        )


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "c7b_daemon.db"


# ----------------------------------------------------------- DR1


def test_dr1_repeated_daemon_pass_does_not_duplicate_logical_delivery(
    db_path: Path,
) -> None:
    """A repeated daemon pass after crash does not duplicate
    logical delivery (same delivery_id, no double-receipt).
    """

    request = _request(request_id=make_request_id(SCOPE, "intent-1", "k1"))
    backend = SqliteDeliveryBackend(db_path)
    backend.record_request(
        request, lifecycle_state=DeliveryLifecycleState.PENDING,
    )
    port = _CountingPort()
    daemon = DaemonPass(backend=backend, port=port, retry_budget=3)
    first = daemon.run()
    # First pass: the request is now ACCEPTED, terminal.
    assert len(first) == 1
    assert first[0].final_state is DeliveryLifecycleState.ACCEPTED
    assert len(port.calls) == 1
    backend.close()
    del backend
    gc.collect()

    # Restart, second pass: the request is already terminal, so
    # the daemon must NOT re-invoke the carrier.
    fresh = SqliteDeliveryBackend(db_path)
    try:
        port2 = _CountingPort()
        daemon2 = DaemonPass(backend=fresh, port=port2, retry_budget=3)
        second = daemon2.run()
        # The daemon sees the row as terminal-by-default and skips it.
        assert len(port2.calls) == 0
        assert len(second) == 0
    finally:
        fresh.close()


# ----------------------------------------------------------- DR2


def test_dr2_restart_reuses_same_logical_delivery_id(
    db_path: Path,
) -> None:
    """Restart reuses the same logical delivery_id (no new request)."""

    request = _request(request_id=make_request_id(SCOPE, "intent-1", "k1"))
    backend = SqliteDeliveryBackend(db_path)
    backend.record_request(
        request, lifecycle_state=DeliveryLifecycleState.FAILED_RETRYABLE,
    )
    backend.close()
    del backend
    gc.collect()

    # Restart, run daemon: the durable request_id is reused verbatim.
    fresh = SqliteDeliveryBackend(db_path)
    try:
        port = _CountingPort()
        daemon = DaemonPass(backend=fresh, port=port, retry_budget=3)
        outcomes = daemon.run()
        assert len(outcomes) == 1
        assert outcomes[0].request_id == request.request_id
        # The daemon did NOT create a new request: only one carrier
        # call (re-attempt) and the same request_id.
        assert len(port.calls) == 1
        assert port.calls[0].request_id == request.request_id
        row = fresh.get_durable_request(request.request_id)
        assert row is not None
        assert row.lifecycle_state is DeliveryLifecycleState.ACCEPTED
    finally:
        fresh.close()


# ----------------------------------------------------------- deterministic order


def test_daemon_iterates_in_request_id_ascending_order(
    db_path: Path,
) -> None:
    """The daemon walks the unfinished rows in deterministic
    request_id ascending order.
    """

    r1 = _request(request_id="deliv-aaa")
    r2 = _request(request_id="deliv-zzz")
    r3 = _request(request_id="deliv-mmm")
    backend = SqliteDeliveryBackend(db_path)
    backend.record_request(
        r1, lifecycle_state=DeliveryLifecycleState.PENDING,
    )
    backend.record_request(
        r2, lifecycle_state=DeliveryLifecycleState.FAILED_RETRYABLE,
    )
    backend.record_request(
        r3, lifecycle_state=DeliveryLifecycleState.PENDING,
    )
    port = _CountingPort()
    daemon = DaemonPass(backend=backend, port=port, retry_budget=3)
    outcomes = daemon.run()
    request_ids = [o.request_id for o in outcomes]
    assert request_ids == sorted(request_ids)
    assert len(port.calls) == 3
    backend.close()


# ----------------------------------------------------------- reconcile


def test_daemon_with_level1_reconciler_resolves_unknown(
    db_path: Path,
) -> None:
    """A LEVEL 1 reconciler can resolve UNKNOWN -> ACCEPTED on a
    daemon pass; no duplicate send is observed.
    """

    request = _request(request_id=make_request_id(SCOPE, "intent-1", "k1"))
    backend = SqliteDeliveryBackend(db_path)
    backend.record_request(
        request, lifecycle_state=DeliveryLifecycleState.PENDING,
    )
    backend.set_lifecycle_state(
        request.request_id, DeliveryLifecycleState.UNKNOWN,
        at=datetime.now(tz=UTC),
    )

    class _AcceptingReconciler:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def reconcile(self, request: DeliveryRequest) -> ResolvedAccept:
            self.calls.append(request.request_id)
            return ResolvedAccept(
                provider_receipt_ref="wmp-x",
                provider_message_ref="wm-x",
            )

    reconciler = _AcceptingReconciler()
    port = _CountingPort()
    daemon = DaemonPass(
        backend=backend, port=port, reconciler=reconciler, retry_budget=3,
    )
    outcomes = daemon.run()
    # The reconciler decided ACCEPTED; the carrier was NOT invoked.
    assert len(port.calls) == 0
    assert reconciler.calls == [request.request_id]
    assert len(outcomes) == 1
    assert outcomes[0].final_state is DeliveryLifecycleState.ACCEPTED
    row = backend.get_durable_request(request.request_id)
    assert row is not None
    assert row.lifecycle_state is DeliveryLifecycleState.ACCEPTED
    assert row.last_provider_receipt_ref == "wmp-x"
    backend.close()


# ----------------------------------------------------------- log generic


def test_daemon_log_does_not_carry_payload(
    db_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    """The daemon's log entries are generic; the payload is not
    carried into any log message.
    """

    request = _request(
        request_id=make_request_id(SCOPE, "intent-1", "k1"),
        body="今天下午想和你分享一首诗".encode(),
    )
    backend = SqliteDeliveryBackend(db_path)
    backend.record_request(
        request, lifecycle_state=DeliveryLifecycleState.PENDING,
    )
    port = _CountingPort()
    with caplog.at_level(logging.INFO, logger="mind_runtime.delivery.daemon"):
        daemon = DaemonPass(backend=backend, port=port, retry_budget=3)
        daemon.run()
    for record in caplog.records:
        assert "今天下午想和你分享一首诗" not in record.getMessage()
    backend.close()
