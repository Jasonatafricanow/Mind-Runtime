"""C7B STEP 3 — reconciliation port tests.

Tests cover the four reconciler outcomes (Accept / Retryable /
Reject / NotFound / Unknown) and the rule that the orchestrator
MUST NOT blind-resend on Unknown.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from mind_runtime.contracts import (
    DeliveryReceipt,
    DeliveryStatus,
    Scope,
    ScopeDomain,
    SyncFields,
)
from mind_runtime.delivery import (
    DeliveryRequest,
    NoopDeliveryReconciler,
    ResolvedAccept,
    ResolvedNotFound,
    ResolvedReject,
    ResolvedRetryable,
    ResolvedUnknown,
    make_message_id,
    make_request_id,
)
from mind_runtime.delivery.daemon import DaemonPass, _apply_reconcile
from mind_runtime.delivery.persistence import (
    SqliteDeliveryBackend,
)
from mind_runtime.delivery.state import DeliveryLifecycleState

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
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        sync=SyncFields(SCOPE, RUNTIME_ID, request_id, 1, f"idem-{request_id}"),
    )


class _ScriptedReconciler:
    """Test reconciler that returns a scripted answer per request_id."""

    def __init__(self, script: dict[str, object]) -> None:
        self._script = script
        self.calls: list[str] = []

    def reconcile(self, request: DeliveryRequest) -> object:
        self.calls.append(request.request_id)
        return self._script[request.request_id]


def test_noop_reconciler_always_returns_unknown() -> None:
    """NoopDeliveryReconciler returns ResolvedUnknown for every request."""

    request = _request(request_id=make_request_id(SCOPE, "intent-1", "k1"))
    reconciler = NoopDeliveryReconciler()
    result = reconciler.reconcile(request)
    assert isinstance(result, ResolvedUnknown)
    assert result.reason == "noop_reconciler_level_0"


def test_reconcile_resolves_unknown_to_accepted() -> None:
    """A scripted LEVEL 1+ reconciler can resolve UNKNOWN -> ACCEPTED."""

    request = _request(request_id=make_request_id(SCOPE, "intent-1", "k1"))
    reconciler = _ScriptedReconciler({
        request.request_id: ResolvedAccept(
            provider_receipt_ref="wmp-receipt-7",
            provider_message_ref="wm-msg-7",
        ),
    })
    result = reconciler.reconcile(request)
    assert isinstance(result, ResolvedAccept)
    assert result.provider_receipt_ref == "wmp-receipt-7"


def test_reconcile_resolves_unknown_to_retryable() -> None:
    """A reconciler can resolve UNKNOWN -> retryable with a reason."""

    request = _request(request_id=make_request_id(SCOPE, "intent-1", "k1"))
    reconciler = _ScriptedReconciler({
        request.request_id: ResolvedRetryable(reason="rate_limited"),
    })
    result = reconciler.reconcile(request)
    assert isinstance(result, ResolvedRetryable)
    assert result.reason == "rate_limited"


def test_reconcile_resolves_unknown_to_not_found() -> None:
    """A reconciler can resolve UNKNOWN -> not_found (provider never saw it)."""

    request = _request(request_id=make_request_id(SCOPE, "intent-1", "k1"))
    reconciler = _ScriptedReconciler({
        request.request_id: ResolvedNotFound(reason="provider_never_saw"),
    })
    result = reconciler.reconcile(request)
    assert isinstance(result, ResolvedNotFound)
    assert result.reason == "provider_never_saw"


def test_reconcile_unknown_does_not_blind_resend(
    tmp_path: Path,
) -> None:
    """When the reconciler returns Unknown, the orchestrator MUST NOT
    blindly resend. UNKNOWN stays UNKNOWN or requires explicit
    operator action.
    """

    db_path = tmp_path / "c7b.db"
    request = _request(request_id=make_request_id(SCOPE, "intent-1", "k1"))
    backend = SqliteDeliveryBackend(db_path)
    backend.record_request(
        request, lifecycle_state=DeliveryLifecycleState.PENDING,
    )
    backend.set_lifecycle_state(
        request.request_id, DeliveryLifecycleState.UNKNOWN, at=datetime.now(tz=UTC),
    )

    # Use a port counter so we can prove no carrier call happened.
    class _CountingPort:
        def __init__(self) -> None:
            self.calls: list[DeliveryRequest] = []

        def deliver(self, request: DeliveryRequest) -> DeliveryReceipt:
            self.calls.append(request)
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

    port = _CountingPort()
    daemon = DaemonPass(
        backend=backend, port=port,
        reconciler=NoopDeliveryReconciler(), retry_budget=3,
    )
    outcomes = daemon.run()
    # Outcome is reconcile_first; the Noop reconciler said "unknown";
    # the row is still UNKNOWN; the carrier was NOT invoked.
    assert len(port.calls) == 0
    assert len(outcomes) == 1
    assert outcomes[0].final_state is DeliveryLifecycleState.UNKNOWN
    row = backend.get_durable_request(request.request_id)
    assert row is not None
    assert row.lifecycle_state is DeliveryLifecycleState.UNKNOWN
    backend.close()


def test_apply_reconcile_accept_persists_provider_receipt_ref(
    tmp_path: Path,
) -> None:
    """_apply_reconcile with ResolvedAccept persists the
    provider_receipt_ref and returns ACCEPTED.
    """

    db_path = tmp_path / "c7b.db"
    request = _request(request_id=make_request_id(SCOPE, "intent-1", "k1"))
    backend = SqliteDeliveryBackend(db_path)
    backend.record_request(
        request, lifecycle_state=DeliveryLifecycleState.UNKNOWN,
    )

    state, reason, ref = _apply_reconcile(
        request=request,
        result=ResolvedAccept(
            provider_receipt_ref="wmp-x",
            provider_message_ref="wm-x",
        ),
        backend=backend,
        now=datetime.now(tz=UTC),
    )
    assert state is DeliveryLifecycleState.ACCEPTED
    assert reason == "reconcile_accept"
    assert ref == "wmp-x"
    row = backend.get_durable_request(request.request_id)
    assert row is not None
    assert row.last_provider_receipt_ref == "wmp-x"
    backend.close()


def test_apply_reconcile_unknown_returns_none_to_signal_no_transition(
    tmp_path: Path,
) -> None:
    """_apply_reconcile with ResolvedUnknown returns (None, reason, None):
    the caller must NOT transition the row.
    """

    db_path = tmp_path / "c7b.db"
    request = _request(request_id=make_request_id(SCOPE, "intent-1", "k1"))
    backend = SqliteDeliveryBackend(db_path)
    backend.record_request(
        request, lifecycle_state=DeliveryLifecycleState.UNKNOWN,
    )

    state, reason, ref = _apply_reconcile(
        request=request,
        result=ResolvedUnknown(reason="provider_offline"),
        backend=backend,
        now=datetime.now(tz=UTC),
    )
    assert state is None
    assert reason == "provider_offline"
    assert ref is None
    backend.close()


def test_apply_reconcile_not_found_treated_as_retryable(tmp_path: Path) -> None:
    """_apply_reconcile with ResolvedNotFound -> FAILED_RETRYABLE so
    the daemon pass can re-arm the attempt.
    """

    db_path = tmp_path / "c7b_apply_reconcile_nf.db"
    request = _request(request_id=make_request_id(SCOPE, "intent-1", "k1"))
    backend = SqliteDeliveryBackend(db_path)
    backend.record_request(
        request, lifecycle_state=DeliveryLifecycleState.UNKNOWN,
    )
    state, reason, ref = _apply_reconcile(
        request=request,
        result=ResolvedNotFound(reason="never_saw_it"),
        backend=backend,
        now=datetime.now(tz=UTC),
    )
    assert state is DeliveryLifecycleState.FAILED_RETRYABLE
    assert reason == "reconcile_not_found"
    assert ref is None
    backend.close()


def test_apply_reconcile_reject_terminates(tmp_path: Path) -> None:
    """_apply_reconcile with ResolvedReject -> REJECTED."""

    db_path = tmp_path / "c7b.db"
    request = _request(request_id=make_request_id(SCOPE, "intent-1", "k1"))
    backend = SqliteDeliveryBackend(db_path)
    backend.record_request(
        request, lifecycle_state=DeliveryLifecycleState.UNKNOWN,
    )
    state, reason, ref = _apply_reconcile(
        request=request,
        result=ResolvedReject(reason="policy_violation"),
        backend=backend,
        now=datetime.now(tz=UTC),
    )
    assert state is DeliveryLifecycleState.REJECTED
    assert reason == "reconcile_reject"
    assert ref is None
    backend.close()
