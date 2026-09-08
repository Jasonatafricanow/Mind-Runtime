"""C7B STEP 8 — privacy tests.

Recovery / retry / log / trace must NOT carry raw private
expression text. Allowed generic trace fields:

  delivery_id, intent_id, provider, status, attempt, reason_codes,
  provider_receipt_ref (only if non-secret), timestamps.

The tests pin a private payload and assert it does not appear in
any recovery-side log message, reconciliation metadata, retry
decision, or kill-switch log entry.
"""

from __future__ import annotations

import io
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
    ResolvedRetryable,
    SqliteDeliveryBackend,
    make_message_id,
    make_request_id,
)
from mind_runtime.delivery.daemon import DaemonPass, _apply_reconcile
from mind_runtime.delivery.retry import compute_retry_decision

PRIVATE_PAYLOAD = "今天下午想和你分享一首诗".encode()
NOW = datetime(2026, 1, 1, tzinfo=UTC)
SCOPE = Scope(domain=ScopeDomain.USER, user_id="u1")
RUNTIME_ID = "xiyue"


def _request(
    *, request_id: str, body: bytes = PRIVATE_PAYLOAD,
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


# ----------------------------------------------------------- daemon log


def test_daemon_log_does_not_carry_payload_text(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    """The daemon's log entries are generic; the payload is not
    carried into any log message.
    """

    db_path = tmp_path / "c7b_privacy.db"
    request = _request(request_id=make_request_id(SCOPE, "intent-1", "k1"))
    backend = SqliteDeliveryBackend(db_path)
    backend.record_request(
        request, lifecycle_state=DeliveryLifecycleState.PENDING,
    )
    port = _CountingPort()
    with caplog.at_level(logging.INFO, logger="mind_runtime.delivery.daemon"):
        daemon = DaemonPass(backend=backend, port=port, retry_budget=3)
        daemon.run()
    joined = "\n".join(record.getMessage() for record in caplog.records)
    # The private payload text must not appear.
    assert "今天下午想和你分享一首诗" not in joined
    backend.close()


# ----------------------------------------------------------- reconcile log


def test_reconcile_metadata_does_not_carry_payload(tmp_path: Path) -> None:
    """Reconciliation metadata (the result dataclass + the
    backend-stored row) does not carry payload text.
    """

    db_path = tmp_path / "c7b_privacy.db"
    request = _request(request_id=make_request_id(SCOPE, "intent-1", "k1"))
    backend = SqliteDeliveryBackend(db_path)
    backend.record_request(
        request, lifecycle_state=DeliveryLifecycleState.UNKNOWN,
    )
    state, reason, ref = _apply_reconcile(
        request=request,
        result=ResolvedRetryable(reason="rate_limited"),
        backend=backend,
        now=datetime.now(tz=UTC),
    )
    # The reason is generic; the request row's payload is not
    # echoed in the reason or the new state.
    assert reason == "reconcile_retryable"
    assert ref is None
    assert state is DeliveryLifecycleState.FAILED_RETRYABLE
    row = backend.get_durable_request(request.request_id)
    assert row is not None
    # The stored payload is still bytes (not exposed through the
    # log path). The row has no private text in its scalar fields.
    assert row.last_provider_receipt_ref is None
    backend.close()


# ----------------------------------------------------------- retry decision


def test_retry_decision_does_not_carry_payload() -> None:
    """The retry decision's reason_code is generic; the payload
    is never read by the policy.
    """

    for state in (
        DeliveryLifecycleState.PENDING,
        DeliveryLifecycleState.IN_FLIGHT,
        DeliveryLifecycleState.ACCEPTED,
        DeliveryLifecycleState.REJECTED,
        DeliveryLifecycleState.FAILED_RETRYABLE,
        DeliveryLifecycleState.UNKNOWN,
    ):
        decision = compute_retry_decision(state, 0, 3)
        joined = f"{decision.kind.value} {decision.reason_code}"
        assert "今天下午想和你分享一首诗" not in joined
        assert PRIVATE_PAYLOAD.decode("utf-8") not in joined


# ----------------------------------------------------------- kill switch log


def test_kill_switch_log_entries_are_generic(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    """The kill-switch decide() reason codes are generic; no
    payload text appears in any code.
    """

    db_path = tmp_path / "c7b_privacy.db"
    backend = SqliteDeliveryBackend(db_path)
    try:
        ks = backend.kill_switch()
        ks.set_global(on=False, updated_at=datetime.now(tz=UTC))
        decision = ks.decide(channel="weixin", target="user-1")
        # The reason_code is generic.
        assert decision.allowed is False
        assert "今天下午想和你分享一首诗" not in decision.reason_code
    finally:
        backend.close()


# ----------------------------------------------------------- durable row


def test_durable_row_does_not_expose_payload_to_log(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    """A persisted row's payload is not echoed in any log line,
    even when the row is reloaded after restart.
    """

    db_path = tmp_path / "c7b_privacy.db"
    request = _request(request_id=make_request_id(SCOPE, "intent-1", "k1"))
    backend = SqliteDeliveryBackend(db_path)
    backend.record_request(
        request, lifecycle_state=DeliveryLifecycleState.PENDING,
    )
    backend.close()
    del backend
    import gc
    gc.collect()

    # Reopen: no log line carries the payload.
    logger = logging.getLogger("mind_runtime.delivery")
    handler = logging.StreamHandler(io.StringIO())
    handler.setLevel(logging.DEBUG)
    logger.addHandler(handler)
    try:
        with caplog.at_level(logging.DEBUG, logger="mind_runtime.delivery"):
            fresh = SqliteDeliveryBackend(db_path)
            row = fresh.get_durable_request(request.request_id)
            assert row is not None
            fresh.close()
        joined = "\n".join(record.getMessage() for record in caplog.records)
        assert "今天下午想和你分享一首诗" not in joined
    finally:
        logger.removeHandler(handler)


# ----------------------------------------------------------- reason codes


def test_reason_codes_dao_round_trip_is_generic(tmp_path: Path) -> None:
    """Reason codes written into delivery_attempts must be
    generic strings; the round-trip preserves them as-is.
    """

    db_path = tmp_path / "c7b_privacy.db"
    request = _request(request_id=make_request_id(SCOPE, "intent-1", "k1"))
    backend = SqliteDeliveryBackend(db_path)
    backend.record_request(
        request, lifecycle_state=DeliveryLifecycleState.PENDING,
    )
    backend.record_attempt(
        attempt_id=f"att-{request.request_id}-1",
        request_id=request.request_id,
        attempt=1,
        started_at=datetime.now(tz=UTC),
        ended_at=datetime.now(tz=UTC),
        outcome=DeliveryLifecycleState.FAILED_RETRYABLE,
        provider_receipt_ref=None,
        reason_codes=("transient_failure", "no_private_text"),
    )
    attempts = backend.attempts_for_request(request.request_id)
    assert len(attempts) == 1
    assert "transient_failure" in attempts[0].reason_codes
    assert "no_private_text" in attempts[0].reason_codes
    # And the payload never made it into the reason_codes list.
    joined = " ".join(attempts[0].reason_codes)
    assert "今天下午想和你分享一首诗" not in joined
    backend.close()
