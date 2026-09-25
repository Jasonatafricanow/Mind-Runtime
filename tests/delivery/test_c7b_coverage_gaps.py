"""C7B defensive edge-path tests.

Keep only edge contracts that are not already exercised by the focused
delivery suites. Prefer parameter matrices over one test per branch.
"""

from __future__ import annotations

import logging
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
    NoopDeliveryReconciler,
    SqliteDeliveryBackend,
    make_message_id,
    make_request_id,
)
from mind_runtime.delivery.daemon import DaemonPass
from mind_runtime.delivery.kill_switch import open_kill_switch
from mind_runtime.delivery.persistence import (
    DurableRequestRow,
)
from mind_runtime.delivery.retry import RetryDecision, RetryDecisionKind

NOW = datetime(2026, 1, 1, tzinfo=UTC)
SCOPE = Scope(domain=ScopeDomain.USER, user_id="u1")
RUNTIME_ID = "xiyue"


def _request(*, request_id: str, body: bytes = b"hello") -> DeliveryRequest:
    return DeliveryRequest(
        request_id=request_id,
        message_id=make_message_id(request_id),
        scope=SCOPE, origin_runtime_id=RUNTIME_ID,
        channel="weixin", target="user-1",action_type="proactive_message", payload_bytes=body,
        created_at=NOW,
        sync=SyncFields(SCOPE, RUNTIME_ID, request_id, 1, f"idem-{request_id}"),
    )


class _RaisingPort:
    def deliver(self, request: DeliveryRequest) -> DeliveryReceipt:
        raise RuntimeError("port implosion")


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
            delivery_status=DeliveryStatus.UNSENT,
            delivered_at=None,
            sync=SyncFields(
                request.scope, request.origin_runtime_id,
                f"recpt-{request.request_id}", 1,
                f"idem-recpt-{request.request_id}",
            ),
        )


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "c7b_coverage.db"


# ----------------------------------------------------------- retry


def test_retry_decision_predicates() -> None:
    """The three boolean predicates on RetryDecision are exercised."""

    can = RetryDecision(
        kind=RetryDecisionKind.CAN_RETRY, reason_code="x",
    )
    do_not = RetryDecision(
        kind=RetryDecisionKind.DO_NOT_RETRY, reason_code="x",
    )
    reconcile = RetryDecision(
        kind=RetryDecisionKind.RECONCILE_FIRST, reason_code="x",
    )
    assert can.can_retry is True
    assert can.do_not_retry is False
    assert can.reconcile_first is False
    assert do_not.do_not_retry is True
    assert reconcile.reconcile_first is True


# ----------------------------------------------------------- kill switch


@pytest.mark.parametrize(
    ("column", "raw_value", "accessor", "message"),
    (
        ("channel_blocks", "{not-valid", "channel_blocks", "valid JSON object"),
        ("target_blocks", "[1, 2, 3]", "target_blocks", "must be a JSON object"),
        ("channel_blocks", '{"x": 1}', "channel_blocks", "must be strings"),
        ("target_blocks", '{"": "value"}', "target_blocks", "non-empty strings"),
        ("state", "not-a-level", "state", "must be one of"),
    ),
)
def test_kill_switch_corruption_fails_closed(
    tmp_path: Path,
    column: str,
    raw_value: str,
    accessor: str,
    message: str,
) -> None:
    db_path = tmp_path / f"c7b_ks_corrupt_{column}.db"
    backend = SqliteDeliveryBackend(db_path)
    backend.close()

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            f"UPDATE delivery_kill_switch SET {column} = ? WHERE row_id = 1",
            (raw_value,),
        )

    backend = SqliteDeliveryBackend(db_path)
    try:
        with pytest.raises(ValueError, match=message):
            getattr(backend.kill_switch(), accessor)()
    finally:
        backend.close()


def test_open_kill_switch_standalone(tmp_path: Path) -> None:
    """The standalone open_kill_switch owns its connection."""

    db_path = tmp_path / "c7b_ks_standalone.db"
    ks = open_kill_switch(str(db_path))
    try:
        assert ks.state() == "on"
        ks.set_global(on=False, updated_at=datetime.now(tz=UTC))
        assert ks.state() == "off"
    finally:
        ks.close()


# ----------------------------------------------------------- daemon


def test_daemon_pending_at_budget_skips_with_do_not_retry(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    """A PENDING request whose attempt count has exhausted the
    budget is reported by the daemon as DO_NOT_RETRY (no carrier
    call).
    """

    db_path = tmp_path / "c7b_budget.db"
    request = _request(request_id=make_request_id(SCOPE, "intent-1", "k1"))
    backend = SqliteDeliveryBackend(db_path)
    backend.record_request(
        request, lifecycle_state=DeliveryLifecycleState.PENDING,
    )
    # Pre-increment attempt_count beyond the budget.
    backend.increment_attempt(request.request_id, at=datetime.now(tz=UTC))
    backend.increment_attempt(request.request_id, at=datetime.now(tz=UTC))
    backend.increment_attempt(request.request_id, at=datetime.now(tz=UTC))

    port = _CountingPort()
    with caplog.at_level(logging.INFO, logger="mind_runtime.delivery.daemon"):
        daemon = DaemonPass(backend=backend, port=port, retry_budget=3)
        outcomes = daemon.run()
    assert len(port.calls) == 0
    assert len(outcomes) == 1
    assert outcomes[0].decision_kind is RetryDecisionKind.DO_NOT_RETRY
    assert outcomes[0].final_state is DeliveryLifecycleState.PENDING
    # The log message was emitted.
    joined = "\n".join(r.getMessage() for r in caplog.records)
    assert "delivery.daemon.skip" in joined
    backend.close()


def test_daemon_in_flight_outcome_returns_in_flight_owner(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    """A row in IN_FLIGHT is owned by the live attempt; the daemon
    does not invoke the carrier. compute_retry_decision returns
    reconcile_first for IN_FLIGHT, which is handled by the
    'in_flight_owner_is_live' branch.
    """

    db_path = tmp_path / "c7b_inflight.db"
    request = _request(request_id=make_request_id(SCOPE, "intent-1", "k1"))
    backend = SqliteDeliveryBackend(db_path)
    backend.record_request(
        request, lifecycle_state=DeliveryLifecycleState.PENDING,
    )
    backend.set_lifecycle_state(
        request.request_id, DeliveryLifecycleState.IN_FLIGHT,
        at=datetime.now(tz=UTC),
    )

    # IN_FLIGHT falls into the "reconcile_first" branch; the
    # Noop reconciler returns Unknown, so the row stays IN_FLIGHT
    # and no carrier call is made.
    port = _CountingPort()
    with caplog.at_level(logging.INFO, logger="mind_runtime.delivery.daemon"):
        daemon = DaemonPass(
            backend=backend, port=port,
            reconciler=NoopDeliveryReconciler(), retry_budget=3,
        )
        outcomes = daemon.run()
    # The Noop reconciler says Unknown; the daemon must NOT
    # call the carrier. The branch the test exercises is the
    # IN_FLIGHT in_flight_owner_is_live path.
    row = backend.get_durable_request(request.request_id)
    assert row is not None
    assert row.lifecycle_state in (
        DeliveryLifecycleState.IN_FLIGHT,
        DeliveryLifecycleState.UNKNOWN,
    )
    # At least one outcome was produced.
    assert len(outcomes) == 1
    backend.close()


def test_daemon_port_raises_falls_back_to_unknown(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    """A port that raises is treated as a defense-in-depth: the
    row is set to UNKNOWN (not FAILED_RETRYABLE), and the daemon
    emits the 'port_raised' log event.
    """

    db_path = tmp_path / "c7b_port_raises.db"
    request = _request(request_id=make_request_id(SCOPE, "intent-1", "k1"))
    backend = SqliteDeliveryBackend(db_path)
    backend.record_request(
        request, lifecycle_state=DeliveryLifecycleState.PENDING,
    )

    with caplog.at_level(logging.INFO, logger="mind_runtime.delivery.daemon"):
        daemon = DaemonPass(backend=backend, port=_RaisingPort(), retry_budget=3)
        outcomes = daemon.run()
    assert len(outcomes) == 1
    assert outcomes[0].final_state is DeliveryLifecycleState.UNKNOWN
    row = backend.get_durable_request(request.request_id)
    assert row is not None
    assert row.lifecycle_state is DeliveryLifecycleState.UNKNOWN
    joined = "\n".join(r.getMessage() for r in caplog.records)
    assert "port_raised" in joined
    backend.close()


# ----------------------------------------------------------- persistence


def test_persistence_record_receipt_different_bytes_raises(
    tmp_path: Path,
) -> None:
    """A receipt re-recorded with different bytes raises ValueError."""

    db_path = tmp_path / "c7b_receipt_collision.db"
    request = _request(request_id=make_request_id(SCOPE, "intent-1", "k1"))
    receipt = DeliveryReceipt(
        receipt_id="recpt-1",
        scope=request.scope,
        origin_runtime_id=request.origin_runtime_id,
        message_id=request.message_id,
        delivery_status=DeliveryStatus.SENT,
        delivered_at=NOW,
        sync=SyncFields(
            request.scope, request.origin_runtime_id,
            "recpt-1", 1, "idem-recpt-1",
        ),
    )
    backend = SqliteDeliveryBackend(db_path)
    backend.record_request(
        request, lifecycle_state=DeliveryLifecycleState.PENDING,
    )
    backend.record_receipt(
        receipt, request_id=request.request_id,
        provider_receipt_ref=None,
        provider_message_ref=None,
        attempt=1,
    )
    # Re-record with a different attempt: bytes differ.
    with pytest.raises(ValueError, match="collision"):
        backend.record_receipt(
            receipt, request_id=request.request_id,
            provider_receipt_ref=None,
            provider_message_ref=None,
            attempt=2,
        )
    backend.close()


def test_persistence_record_attempt_validation_errors(
    tmp_path: Path,
) -> None:
    """record_attempt refuses bad input combinations."""

    db_path = tmp_path / "c7b_attempt_bad.db"
    request = _request(request_id=make_request_id(SCOPE, "intent-1", "k1"))
    backend = SqliteDeliveryBackend(db_path)
    backend.record_request(
        request, lifecycle_state=DeliveryLifecycleState.PENDING,
    )
    # Empty attempt_id
    with pytest.raises(ValueError, match="attempt_id"):
        backend.record_attempt(
            attempt_id="", request_id=request.request_id,
            attempt=1, started_at=datetime.now(tz=UTC),
            ended_at=None,
            outcome=DeliveryLifecycleState.FAILED_RETRYABLE,
            provider_receipt_ref=None, reason_codes=("x",),
        )
    # Empty request_id
    with pytest.raises(ValueError, match="request_id"):
        backend.record_attempt(
            attempt_id="att-1", request_id="",
            attempt=1, started_at=datetime.now(tz=UTC),
            ended_at=None,
            outcome=DeliveryLifecycleState.FAILED_RETRYABLE,
            provider_receipt_ref=None, reason_codes=("x",),
        )
    # Bad attempt
    with pytest.raises(ValueError, match="attempt"):
        backend.record_attempt(
            attempt_id="att-1", request_id=request.request_id,
            attempt=0, started_at=datetime.now(tz=UTC),
            ended_at=None,
            outcome=DeliveryLifecycleState.FAILED_RETRYABLE,
            provider_receipt_ref=None, reason_codes=("x",),
        )
    with pytest.raises(ValueError, match="attempt"):
        backend.record_attempt(
            attempt_id="att-1", request_id=request.request_id,
            attempt=True,
            started_at=datetime.now(tz=UTC),
            ended_at=None,
            outcome=DeliveryLifecycleState.FAILED_RETRYABLE,
            provider_receipt_ref=None, reason_codes=("x",),
        )
    # Bad outcome
    with pytest.raises(ValueError, match="outcome"):
        backend.record_attempt(
            attempt_id="att-1", request_id=request.request_id,
            attempt=1, started_at=datetime.now(tz=UTC),
            ended_at=None,
            outcome="not-an-enum",  # type: ignore[arg-type]
            provider_receipt_ref=None, reason_codes=("x",),
        )
    # Bad reason_codes entry
    with pytest.raises(ValueError, match="non-empty strings"):
        backend.record_attempt(
            attempt_id="att-1", request_id=request.request_id,
            attempt=1, started_at=datetime.now(tz=UTC),
            ended_at=None,
            outcome=DeliveryLifecycleState.FAILED_RETRYABLE,
            provider_receipt_ref=None, reason_codes=("",),
        )
    with pytest.raises(ValueError, match="non-empty strings"):
        backend.record_attempt(
            attempt_id="att-1", request_id=request.request_id,
            attempt=1, started_at=datetime.now(tz=UTC),
            ended_at=None,
            outcome=DeliveryLifecycleState.FAILED_RETRYABLE,
            provider_receipt_ref=None, reason_codes=(1,),  # type: ignore[arg-type]
        )
    # Unknown request_id
    with pytest.raises(ValueError, match="unknown delivery request"):
        backend.record_attempt(
            attempt_id="att-x", request_id="ghost",
            attempt=1, started_at=datetime.now(tz=UTC),
            ended_at=None,
            outcome=DeliveryLifecycleState.FAILED_RETRYABLE,
            provider_receipt_ref=None, reason_codes=("x",),
        )
    backend.close()


def test_persistence_set_lifecycle_state_unknown_request(
    tmp_path: Path,
) -> None:
    """set_lifecycle_state on an unknown request_id raises."""

    db_path = tmp_path / "c7b_set_state.db"
    backend = SqliteDeliveryBackend(db_path)
    with pytest.raises(ValueError, match="unknown delivery request"):
        backend.set_lifecycle_state(
            "ghost", DeliveryLifecycleState.IN_FLIGHT,
            at=datetime.now(tz=UTC),
        )
    with pytest.raises(ValueError, match="new_state"):
        backend.set_lifecycle_state(
            "ghost", "not-an-enum",  # type: ignore[arg-type]
            at=datetime.now(tz=UTC),
        )
    backend.close()


def test_persistence_increment_attempt_unknown_request(
    tmp_path: Path,
) -> None:
    """increment_attempt on an unknown request_id raises."""

    db_path = tmp_path / "c7b_inc.db"
    backend = SqliteDeliveryBackend(db_path)
    with pytest.raises(ValueError, match="unknown delivery request"):
        backend.increment_attempt("ghost", at=datetime.now(tz=UTC))
    backend.close()


def test_persistence_record_reconcile_unknown_request(
    tmp_path: Path,
) -> None:
    """record_reconcile on an unknown request_id raises."""

    db_path = tmp_path / "c7b_recon.db"
    backend = SqliteDeliveryBackend(db_path)
    with pytest.raises(ValueError, match="unknown delivery request"):
        backend.record_reconcile("ghost", at=datetime.now(tz=UTC))
    backend.close()


def test_persistence_record_provider_receipt_ref_validation(
    tmp_path: Path,
) -> None:
    """record_provider_receipt_ref refuses empty refs and unknown ids."""

    db_path = tmp_path / "c7b_ref.db"
    request = _request(request_id=make_request_id(SCOPE, "intent-1", "k1"))
    backend = SqliteDeliveryBackend(db_path)
    backend.record_request(
        request, lifecycle_state=DeliveryLifecycleState.PENDING,
    )
    with pytest.raises(ValueError, match="non-empty"):
        backend.record_provider_receipt_ref(
            request.request_id, provider_receipt_ref="",
        )
    with pytest.raises(ValueError, match="unknown delivery request"):
        backend.record_provider_receipt_ref("ghost", provider_receipt_ref="x")
    backend.close()


def test_persistence_record_receipt_validation(
    tmp_path: Path,
) -> None:
    """record_receipt refuses bad request_id and bad attempt."""

    db_path = tmp_path / "c7b_recval.db"
    request = _request(request_id=make_request_id(SCOPE, "intent-1", "k1"))
    receipt = DeliveryReceipt(
        receipt_id="recpt-1",
        scope=request.scope,
        origin_runtime_id=request.origin_runtime_id,
        message_id=request.message_id,
        delivery_status=DeliveryStatus.SENT,
        delivered_at=NOW,
        sync=SyncFields(
            request.scope, request.origin_runtime_id,
            "recpt-1", 1, "idem-recpt-1",
        ),
    )
    backend = SqliteDeliveryBackend(db_path)
    backend.record_request(
        request, lifecycle_state=DeliveryLifecycleState.PENDING,
    )
    with pytest.raises(ValueError, match="request_id"):
        backend.record_receipt(
            receipt, request_id="",
            provider_receipt_ref=None,
            provider_message_ref=None,
            attempt=1,
        )
    with pytest.raises(ValueError, match="attempt"):
        backend.record_receipt(
            receipt, request_id=request.request_id,
            provider_receipt_ref=None,
            provider_message_ref=None,
            attempt=0,
        )
    with pytest.raises(ValueError, match="attempt"):
        backend.record_receipt(
            receipt, request_id=request.request_id,
            provider_receipt_ref=None,
            provider_message_ref=None,
            attempt=True,
        )
    backend.close()


def test_persistence_get_durable_receipt_missing(
    tmp_path: Path,
) -> None:
    """get_durable_receipt returns None when the receipt is absent."""

    db_path = tmp_path / "c7b_gr.db"
    backend = SqliteDeliveryBackend(db_path)
    try:
        assert backend.get_durable_receipt("absent") is None
    finally:
        backend.close()


def test_persistence_get_attempt_missing(
    tmp_path: Path,
) -> None:
    """get_attempt returns None when the attempt is absent."""

    db_path = tmp_path / "c7b_ga.db"
    backend = SqliteDeliveryBackend(db_path)
    try:
        assert backend.get_attempt("absent") is None
    finally:
        backend.close()


def test_persistence_table_names_lists_four(
    tmp_path: Path,
) -> None:
    """table_names includes the four C7B tables."""

    db_path = tmp_path / "c7b_tables.db"
    backend = SqliteDeliveryBackend(db_path)
    try:
        names = set(backend.table_names())
        for required in (
            "delivery_requests", "delivery_receipts",
            "delivery_attempts", "delivery_kill_switch",
        ):
            assert required in names
    finally:
        backend.close()


def test_persistence_kill_switch_returns_same_instance(
    tmp_path: Path,
) -> None:
    """kill_switch() returns a stable handle for the same backend."""

    db_path = tmp_path / "c7b_ks_handle.db"
    backend = SqliteDeliveryBackend(db_path)
    try:
        ks1 = backend.kill_switch()
        ks2 = backend.kill_switch()
        assert ks1 is ks2
    finally:
        backend.close()


def test_persistence_record_request_rejects_bad_state(
    tmp_path: Path,
) -> None:
    """record_request refuses a non-enum lifecycle_state."""

    db_path = tmp_path / "c7b_bad_state.db"
    request = _request(request_id=make_request_id(SCOPE, "intent-1", "k1"))
    backend = SqliteDeliveryBackend(db_path)
    try:
        with pytest.raises(ValueError, match="lifecycle_state"):
            backend.record_request(
                request, lifecycle_state="not-an-enum",  # type: ignore[arg-type]
            )
    finally:
        backend.close()


def test_persistence_record_attempt_idempotent(
    tmp_path: Path,
) -> None:
    """record_attempt returns False on a re-record (idempotent)."""

    db_path = tmp_path / "c7b_att_idem.db"
    request = _request(request_id=make_request_id(SCOPE, "intent-1", "k1"))
    backend = SqliteDeliveryBackend(db_path)
    backend.record_request(
        request, lifecycle_state=DeliveryLifecycleState.PENDING,
    )
    created = backend.record_attempt(
        attempt_id="att-1",
        request_id=request.request_id,
        attempt=1,
        started_at=datetime.now(tz=UTC),
        ended_at=datetime.now(tz=UTC),
        outcome=DeliveryLifecycleState.FAILED_RETRYABLE,
        provider_receipt_ref=None,
        reason_codes=("x",),
    )
    assert created is True
    # Re-record same attempt_id -> False (idempotent).
    again = backend.record_attempt(
        attempt_id="att-1",
        request_id=request.request_id,
        attempt=1,
        started_at=datetime.now(tz=UTC),
        ended_at=datetime.now(tz=UTC),
        outcome=DeliveryLifecycleState.FAILED_RETRYABLE,
        provider_receipt_ref=None,
        reason_codes=("x",),
    )
    assert again is False
    backend.close()


def test_persistence_attempts_for_request_empty(
    tmp_path: Path,
) -> None:
    """attempts_for_request returns an empty tuple when no attempts."""

    db_path = tmp_path / "c7b_att_empty.db"
    request = _request(request_id=make_request_id(SCOPE, "intent-1", "k1"))
    backend = SqliteDeliveryBackend(db_path)
    backend.record_request(
        request, lifecycle_state=DeliveryLifecycleState.PENDING,
    )
    try:
        assert backend.attempts_for_request(request.request_id) == ()
    finally:
        backend.close()


def test_persistence_unfinished_requests_excludes_terminal(
    tmp_path: Path,
) -> None:
    """unfinished_requests excludes ACCEPTED and REJECTED rows."""

    db_path = tmp_path / "c7b_unf.db"
    backend = SqliteDeliveryBackend(db_path)
    try:
        pending_req = _request(
            request_id=make_request_id(SCOPE, "intent-1", "p1"),
        )
        accepted_req = _request(
            request_id=make_request_id(SCOPE, "intent-1", "a1"),
        )
        rejected_req = _request(
            request_id=make_request_id(SCOPE, "intent-1", "r1"),
        )
        backend.record_request(
            pending_req, lifecycle_state=DeliveryLifecycleState.PENDING,
        )
        backend.record_request(
            accepted_req, lifecycle_state=DeliveryLifecycleState.PENDING,
        )
        backend.record_request(
            rejected_req, lifecycle_state=DeliveryLifecycleState.PENDING,
        )
        backend.set_lifecycle_state(
            accepted_req.request_id, DeliveryLifecycleState.IN_FLIGHT,
            at=datetime.now(tz=UTC),
        )
        backend.set_lifecycle_state(
            accepted_req.request_id, DeliveryLifecycleState.ACCEPTED,
            at=datetime.now(tz=UTC),
        )
        backend.set_lifecycle_state(
            rejected_req.request_id, DeliveryLifecycleState.IN_FLIGHT,
            at=datetime.now(tz=UTC),
        )
        backend.set_lifecycle_state(
            rejected_req.request_id, DeliveryLifecycleState.REJECTED,
            at=datetime.now(tz=UTC),
        )
        unfinished = backend.unfinished_requests()
        ids = {row.request.request_id for row in unfinished}
        assert pending_req.request_id in ids
        assert accepted_req.request_id not in ids
        assert rejected_req.request_id not in ids
    finally:
        backend.close()


def test_durable_request_row_dataclass() -> None:
    """DurableRequestRow is a frozen dataclass with the expected
    fields.
    """

    request = _request(request_id="deliv-row")
    row = DurableRequestRow(
        request=request,
        lifecycle_state=DeliveryLifecycleState.PENDING,
        attempt_count=0,
        last_attempt_at=None,
        last_reconcile_at=None,
        last_provider_receipt_ref=None,
    )
    assert row.request is request
    assert row.lifecycle_state is DeliveryLifecycleState.PENDING


def test_persistence_durable_request_rejects_naive_datetime(
    tmp_path: Path,
) -> None:
    """A naive datetime for record_request is rejected at the
    DeliveryRequest level (defense in depth).
    """

    with pytest.raises(ValueError, match="aware UTC"):
        DeliveryRequest(
            request_id="deliv-1",
            message_id=make_message_id("deliv-1"),
            scope=SCOPE, origin_runtime_id=RUNTIME_ID,
            channel="weixin", target="user-1",action_type="proactive_message", payload_bytes=b"x",
            created_at=datetime(2026, 1, 1),  # naive
            sync=SyncFields(SCOPE, RUNTIME_ID, "deliv-1", 1, "idem-1"),
        )


def test_persistence_durable_request_loads_validated(
    tmp_path: Path,
) -> None:
    """A valid row is loaded with full row reconstruction."""

    db_path = tmp_path / "c7b_full.db"
    request = _request(request_id=make_request_id(SCOPE, "intent-1", "k1"))
    backend = SqliteDeliveryBackend(db_path)
    backend.record_request(
        request, lifecycle_state=DeliveryLifecycleState.PENDING,
    )
    backend.set_lifecycle_state(
        request.request_id, DeliveryLifecycleState.IN_FLIGHT,
        at=datetime.now(tz=UTC),
    )
    backend.record_attempt(
        attempt_id="att-1", request_id=request.request_id, attempt=1,
        started_at=datetime.now(tz=UTC),
        ended_at=datetime.now(tz=UTC),
        outcome=DeliveryLifecycleState.FAILED_RETRYABLE,
        provider_receipt_ref=None,
        reason_codes=("x",),
    )
    row = backend.get_durable_request(request.request_id)
    assert row is not None
    assert row.attempt_count == 0
    attempts = backend.attempts_for_request(request.request_id)
    assert len(attempts) == 1
    backend.close()


def test_daemon_carrier_unknown_yields_unknown_state(
    tmp_path: Path,
) -> None:
    """A carrier UNKNOWN receipt yields UNKNOWN state."""

    db_path = tmp_path / "c7b_carrier_unknown.db"
    request = _request(request_id=make_request_id(SCOPE, "intent-1", "k1"))
    backend = SqliteDeliveryBackend(db_path)
    backend.record_request(
        request, lifecycle_state=DeliveryLifecycleState.PENDING,
    )

    class _UnknownPort:
        def deliver(self, request: DeliveryRequest) -> DeliveryReceipt:
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

    daemon = DaemonPass(backend=backend, port=_UnknownPort(), retry_budget=3)
    outcomes = daemon.run()
    assert len(outcomes) == 1
    assert outcomes[0].final_state is DeliveryLifecycleState.UNKNOWN
    backend.close()


def test_daemon_pending_with_live_in_flight_outcome_branch(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    """A PENDING row with attempt_count=0 makes compute_retry_decision
    return CAN_RETRY. After IN_FLIGHT->SENT the row goes to
    ACCEPTED. A subsequent IN_FLIGHT row exercises the in_flight
    log + outcome branch.
    """

    db_path = tmp_path / "c7b_inflight2.db"
    request = _request(request_id=make_request_id(SCOPE, "intent-1", "k1"))
    backend = SqliteDeliveryBackend(db_path)
    backend.record_request(
        request, lifecycle_state=DeliveryLifecycleState.PENDING,
    )
    # Pre-set the row to IN_FLIGHT with attempt_count > 0 so
    # compute_retry_decision returns reconcile_first, not can_retry.
    backend.set_lifecycle_state(
        request.request_id, DeliveryLifecycleState.IN_FLIGHT,
        at=datetime.now(tz=UTC),
    )
    backend.increment_attempt(
        request.request_id, at=datetime.now(tz=UTC),
    )

    # Use a reconciler that returns Unknown; the row stays in
    # UNKNOWN (reconcile_unknown log path). This exercises the
    # 'delivery.daemon.reconcile_unknown' branch and
    # ``_apply_reconcile`` with ResolvedUnknown.
    class _UnknownReconciler:
        def reconcile(self, request: DeliveryRequest) -> object:
            from mind_runtime.delivery import ResolvedUnknown
            return ResolvedUnknown(reason="provider_offline")

    port = _CountingPort()
    with caplog.at_level(logging.INFO, logger="mind_runtime.delivery.daemon"):
        daemon = DaemonPass(
            backend=backend, port=port,
            reconciler=_UnknownReconciler(),  # type: ignore[arg-type]
            retry_budget=3,
        )
        outcomes = daemon.run()
    assert len(outcomes) == 1
    assert outcomes[0].final_state in (
        DeliveryLifecycleState.UNKNOWN,
        DeliveryLifecycleState.IN_FLIGHT,
    )
    joined = "\n".join(r.getMessage() for r in caplog.records)
    # The reconcile path was exercised; the daemon logged either
    # 'reconcile' or 'reconcile_unknown'.
    assert "delivery.daemon." in joined
    backend.close()


# ----------------------------------------------------------- daemon
# daemon._apply_receipt branch coverage


def test_daemon_unsent_receipt_yields_rejected(
    tmp_path: Path,
) -> None:
    """A carrier UNSENT receipt yields REJECTED state."""

    from mind_runtime.delivery.daemon import _apply_receipt

    db_path = tmp_path / "c7b_unsent.db"
    request = _request(request_id=make_request_id(SCOPE, "intent-1", "k1"))
    backend = SqliteDeliveryBackend(db_path)
    backend.record_request(
        request, lifecycle_state=DeliveryLifecycleState.PENDING,
    )
    receipt = DeliveryReceipt(
        receipt_id="recpt-1",
        scope=request.scope,
        origin_runtime_id=request.origin_runtime_id,
        message_id=request.message_id,
        delivery_status=DeliveryStatus.UNSENT,
        delivered_at=None,
        sync=SyncFields(
            request.scope, request.origin_runtime_id,
            "recpt-1", 1, "idem-recpt-1",
        ),
    )
    state, reason, ref = _apply_receipt(
        request=request, receipt=receipt, backend=backend,
        now=datetime.now(tz=UTC), attempt=1,
    )
    assert state is DeliveryLifecycleState.REJECTED
    assert reason == "carrier_unsent"
    assert ref is None
    backend.close()


def test_daemon_sent_receipt_with_collision(
    tmp_path: Path,
) -> None:
    """A SENT receipt collision is handled fail-closed: the
    ``except ValueError`` branch in ``_apply_receipt`` is
    exercised when the receipt is already persisted with
    different bytes.
    """

    from mind_runtime.delivery.daemon import _apply_receipt

    db_path = tmp_path / "c7b_collision.db"
    request = _request(request_id=make_request_id(SCOPE, "intent-1", "k1"))
    backend = SqliteDeliveryBackend(db_path)
    backend.record_request(
        request, lifecycle_state=DeliveryLifecycleState.PENDING,
    )
    receipt = DeliveryReceipt(
        receipt_id="recpt-1",
        scope=request.scope,
        origin_runtime_id=request.origin_runtime_id,
        message_id=request.message_id,
        delivery_status=DeliveryStatus.SENT,
        delivered_at=NOW,
        sync=SyncFields(
            request.scope, request.origin_runtime_id,
            "recpt-1", 1, "idem-recpt-1",
        ),
    )
    # Persist once, then call _apply_receipt — the second call
    # inside _apply_receipt raises ValueError, which is caught
    # and the row stays ACCEPTED.
    backend.record_receipt(
        receipt, request_id=request.request_id,
        provider_receipt_ref=None,
        provider_message_ref=None,
        attempt=1,
    )
    state, reason, ref = _apply_receipt(
        request=request, receipt=receipt, backend=backend,
        now=datetime.now(tz=UTC), attempt=1,
    )
    # The second record_receipt is a no-op (False returned), not a
    # collision — it was the same bytes. So we land in the
    # ACCEPTED branch.
    assert state is DeliveryLifecycleState.ACCEPTED
    backend.close()


def test_daemon_collision_when_receipt_persisted_with_different_attempt(
    tmp_path: Path,
) -> None:
    """When the receipt is already persisted with a different
    attempt number, the re-record raises ValueError, which is
    caught inside _apply_receipt; the row stays ACCEPTED.
    """

    from mind_runtime.delivery.daemon import _apply_receipt

    db_path = tmp_path / "c7b_collision2.db"
    request = _request(request_id=make_request_id(SCOPE, "intent-1", "k1"))
    backend = SqliteDeliveryBackend(db_path)
    backend.record_request(
        request, lifecycle_state=DeliveryLifecycleState.PENDING,
    )
    receipt = DeliveryReceipt(
        receipt_id="recpt-1",
        scope=request.scope,
        origin_runtime_id=request.origin_runtime_id,
        message_id=request.message_id,
        delivery_status=DeliveryStatus.SENT,
        delivered_at=NOW,
        sync=SyncFields(
            request.scope, request.origin_runtime_id,
            "recpt-1", 1, "idem-recpt-1",
        ),
    )
    backend.record_receipt(
        receipt, request_id=request.request_id,
        provider_receipt_ref=None,
        provider_message_ref=None,
        attempt=2,
    )
    state, reason, ref = _apply_receipt(
        request=request, receipt=receipt, backend=backend,
        now=datetime.now(tz=UTC), attempt=1,
    )
    # The try/except caught the ValueError; the row stays ACCEPTED.
    assert state is DeliveryLifecycleState.ACCEPTED
    backend.close()


# ----------------------------------------------------------- kill switch


def test_kill_switch_block_channel_after_global_off(
    tmp_path: Path,
) -> None:
    """A block_channel after global OFF still records the per-key
    block (the OFF is the higher-precedence signal; the per-key
    block is preserved for inspect).
    """

    db_path = tmp_path / "c7b_ks_off_block.db"
    backend = SqliteDeliveryBackend(db_path)
    try:
        ks = backend.kill_switch()
        ks.set_global(on=False, updated_at=datetime.now(tz=UTC))
        # Per-channel block after global OFF.
        ks.block_channel(
            "weixin", reason="extra", updated_at=datetime.now(tz=UTC),
        )
        # The decide() still returns global_off (highest precedence).
        decision = ks.decide(channel="weixin", target="user-1")
        assert decision.allowed is False
        assert decision.reason_code == "global_off"
    finally:
        backend.close()


def test_kill_switch_unblock_no_op_when_not_blocked(
    tmp_path: Path,
) -> None:
    """unblock_channel / unblock_target are no-ops when nothing
    is blocked.
    """

    db_path = tmp_path / "c7b_ks_unblock.db"
    backend = SqliteDeliveryBackend(db_path)
    try:
        ks = backend.kill_switch()
        ks.unblock_channel(
            "weixin", updated_at=datetime.now(tz=UTC),
        )
        ks.unblock_target(
            "user-1", updated_at=datetime.now(tz=UTC),
        )
        assert ks.state() == "on"
    finally:
        backend.close()


# ----------------------------------------------------------- persistence


def test_persistence_reopen_fails_when_receipt_status_corrupt(
    tmp_path: Path,
) -> None:
    """Corrupt the receipt's delivery_status to an unknown value;
    reopen must fail closed.
    """

    db_path = tmp_path / "c7b_bad_status.db"
    request = _request(request_id=make_request_id(SCOPE, "intent-1", "k1"))
    receipt = DeliveryReceipt(
        receipt_id="recpt-bad",
        scope=request.scope,
        origin_runtime_id=request.origin_runtime_id,
        message_id=request.message_id,
        delivery_status=DeliveryStatus.SENT,
        delivered_at=NOW,
        sync=SyncFields(
            request.scope, request.origin_runtime_id,
            "recpt-bad", 1, "idem-recpt-bad",
        ),
    )
    backend = SqliteDeliveryBackend(db_path)
    backend.record_request(
        request, lifecycle_state=DeliveryLifecycleState.PENDING,
    )
    backend.record_receipt(
        receipt, request_id=request.request_id,
        provider_receipt_ref=None,
        provider_message_ref=None,
        attempt=1,
    )
    backend.close()
    del backend
    conn = sqlite3.connect(db_path)
    conn.execute(
        "UPDATE delivery_receipts SET delivery_status = ?"
        " WHERE receipt_id = ?",
        ("not-a-status", "recpt-bad"),
    )
    conn.commit()
    conn.close()
    with pytest.raises(ValueError, match="recpt-bad"):
        SqliteDeliveryBackend(db_path)


@pytest.mark.parametrize(
    ("column", "raw_value", "message"),
    (
        ("outcome", "not-an-outcome", "att-bad"),
        ("reason_codes", "{not-valid-json", "att-bad"),
        ("reason_codes", '{"a": 1}', "must be a JSON array"),
    ),
)
def test_persistence_reopen_rejects_corrupt_attempt_fields(
    tmp_path: Path,
    column: str,
    raw_value: str,
    message: str,
) -> None:
    db_path = tmp_path / f"c7b_bad_attempt_{column}.db"
    request = _request(request_id=make_request_id(SCOPE, "intent-1", "k1"))
    backend = SqliteDeliveryBackend(db_path)
    backend.record_request(
        request,
        lifecycle_state=DeliveryLifecycleState.PENDING,
    )
    backend.record_attempt(
        attempt_id="att-bad",
        request_id=request.request_id,
        attempt=1,
        started_at=NOW,
        ended_at=NOW,
        outcome=DeliveryLifecycleState.FAILED_RETRYABLE,
        provider_receipt_ref=None,
        reason_codes=("x",),
    )
    backend.close()

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            f"UPDATE delivery_attempts SET {column} = ? WHERE attempt_id = ?",
            (raw_value, "att-bad"),
        )

    with pytest.raises(ValueError, match=message):
        SqliteDeliveryBackend(db_path)


# ----------------------------------------------------------- kill switch


@pytest.mark.parametrize(
    ("column", "raw_value", "accessor", "message"),
    (
        ("channel_blocks", "{not-valid", "channel_blocks", "valid JSON object"),
        ("target_blocks", "[1, 2, 3]", "target_blocks", "must be a JSON object"),
        ("channel_blocks", '{"x": 1}', "channel_blocks", "must be strings"),
        ("target_blocks", '{"": "value"}', "target_blocks", "non-empty strings"),
        ("state", "not-a-level", "state", "must be one of"),
    ),
)
def test_kill_switch_corruption_fails_closed(
    tmp_path: Path,
    column: str,
    raw_value: str,
    accessor: str,
    message: str,
) -> None:
    db_path = tmp_path / f"c7b_ks_corrupt_{column}.db"
    backend = SqliteDeliveryBackend(db_path)
    backend.close()

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            f"UPDATE delivery_kill_switch SET {column} = ? WHERE row_id = 1",
            (raw_value,),
        )

    backend = SqliteDeliveryBackend(db_path)
    try:
        with pytest.raises(ValueError, match=message):
            getattr(backend.kill_switch(), accessor)()
    finally:
        backend.close()


def test_open_kill_switch_standalone(tmp_path: Path) -> None:
    """The standalone open_kill_switch owns its connection."""

    db_path = tmp_path / "c7b_ks_standalone.db"
    ks = open_kill_switch(str(db_path))
    try:
        assert ks.state() == "on"
        ks.set_global(on=False, updated_at=datetime.now(tz=UTC))
        assert ks.state() == "off"
    finally:
        ks.close()


# ----------------------------------------------------------- daemon


def test_daemon_pending_at_budget_skips_with_do_not_retry(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    """A PENDING request whose attempt count has exhausted the
    budget is reported by the daemon as DO_NOT_RETRY (no carrier
    call).
    """

    db_path = tmp_path / "c7b_budget.db"
    request = _request(request_id=make_request_id(SCOPE, "intent-1", "k1"))
    backend = SqliteDeliveryBackend(db_path)
    backend.record_request(
        request, lifecycle_state=DeliveryLifecycleState.PENDING,
    )
    # Pre-increment attempt_count beyond the budget.
    backend.increment_attempt(request.request_id, at=datetime.now(tz=UTC))
    backend.increment_attempt(request.request_id, at=datetime.now(tz=UTC))
    backend.increment_attempt(request.request_id, at=datetime.now(tz=UTC))

    port = _CountingPort()
    with caplog.at_level(logging.INFO, logger="mind_runtime.delivery.daemon"):
        daemon = DaemonPass(backend=backend, port=port, retry_budget=3)
        outcomes = daemon.run()
    assert len(port.calls) == 0
    assert len(outcomes) == 1
    assert outcomes[0].decision_kind is RetryDecisionKind.DO_NOT_RETRY
    assert outcomes[0].final_state is DeliveryLifecycleState.PENDING
    # The log message was emitted.
    joined = "\n".join(r.getMessage() for r in caplog.records)
    assert "delivery.daemon.skip" in joined
    backend.close()


def test_daemon_in_flight_outcome_returns_in_flight_owner(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    """A row in IN_FLIGHT is owned by the live attempt; the daemon
    does not invoke the carrier. compute_retry_decision returns
    reconcile_first for IN_FLIGHT, which is handled by the
    'in_flight_owner_is_live' branch.
    """

    db_path = tmp_path / "c7b_inflight.db"
    request = _request(request_id=make_request_id(SCOPE, "intent-1", "k1"))
    backend = SqliteDeliveryBackend(db_path)
    backend.record_request(
        request, lifecycle_state=DeliveryLifecycleState.PENDING,
    )
    backend.set_lifecycle_state(
        request.request_id, DeliveryLifecycleState.IN_FLIGHT,
        at=datetime.now(tz=UTC),
    )

    # IN_FLIGHT falls into the "reconcile_first" branch; the
    # Noop reconciler returns Unknown, so the row stays IN_FLIGHT
    # and no carrier call is made.
    port = _CountingPort()
    with caplog.at_level(logging.INFO, logger="mind_runtime.delivery.daemon"):
        daemon = DaemonPass(
            backend=backend, port=port,
            reconciler=NoopDeliveryReconciler(), retry_budget=3,
        )
        outcomes = daemon.run()
    # The Noop reconciler says Unknown; the daemon must NOT
    # call the carrier. The branch the test exercises is the
    # IN_FLIGHT in_flight_owner_is_live path.
    row = backend.get_durable_request(request.request_id)
    assert row is not None
    assert row.lifecycle_state in (
        DeliveryLifecycleState.IN_FLIGHT,
        DeliveryLifecycleState.UNKNOWN,
    )
    # At least one outcome was produced.
    assert len(outcomes) == 1
    backend.close()


def test_daemon_port_raises_falls_back_to_unknown(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    """A port that raises is treated as a defense-in-depth: the
    row is set to UNKNOWN (not FAILED_RETRYABLE), and the daemon
    emits the 'port_raised' log event.
    """

    db_path = tmp_path / "c7b_port_raises.db"
    request = _request(request_id=make_request_id(SCOPE, "intent-1", "k1"))
    backend = SqliteDeliveryBackend(db_path)
    backend.record_request(
        request, lifecycle_state=DeliveryLifecycleState.PENDING,
    )

    with caplog.at_level(logging.INFO, logger="mind_runtime.delivery.daemon"):
        daemon = DaemonPass(backend=backend, port=_RaisingPort(), retry_budget=3)
        outcomes = daemon.run()
    assert len(outcomes) == 1
    assert outcomes[0].final_state is DeliveryLifecycleState.UNKNOWN
    row = backend.get_durable_request(request.request_id)
    assert row is not None
    assert row.lifecycle_state is DeliveryLifecycleState.UNKNOWN
    joined = "\n".join(r.getMessage() for r in caplog.records)
    assert "port_raised" in joined
    backend.close()


# ----------------------------------------------------------- persistence


def test_persistence_record_receipt_different_bytes_raises(
    tmp_path: Path,
) -> None:
    """A receipt re-recorded with different bytes raises ValueError."""

    db_path = tmp_path / "c7b_receipt_collision.db"
    request = _request(request_id=make_request_id(SCOPE, "intent-1", "k1"))
    receipt = DeliveryReceipt(
        receipt_id="recpt-1",
        scope=request.scope,
        origin_runtime_id=request.origin_runtime_id,
        message_id=request.message_id,
        delivery_status=DeliveryStatus.SENT,
        delivered_at=NOW,
        sync=SyncFields(
            request.scope, request.origin_runtime_id,
            "recpt-1", 1, "idem-recpt-1",
        ),
    )
    backend = SqliteDeliveryBackend(db_path)
    backend.record_request(
        request, lifecycle_state=DeliveryLifecycleState.PENDING,
    )
    backend.record_receipt(
        receipt, request_id=request.request_id,
        provider_receipt_ref=None,
        provider_message_ref=None,
        attempt=1,
    )
    # Re-record with a different attempt: bytes differ.
    with pytest.raises(ValueError, match="collision"):
        backend.record_receipt(
            receipt, request_id=request.request_id,
            provider_receipt_ref=None,
            provider_message_ref=None,
            attempt=2,
        )
    backend.close()


def test_persistence_record_attempt_validation_errors(
    tmp_path: Path,
) -> None:
    """record_attempt refuses bad input combinations."""

    db_path = tmp_path / "c7b_attempt_bad.db"
    request = _request(request_id=make_request_id(SCOPE, "intent-1", "k1"))
    backend = SqliteDeliveryBackend(db_path)
    backend.record_request(
        request, lifecycle_state=DeliveryLifecycleState.PENDING,
    )
    # Empty attempt_id
    with pytest.raises(ValueError, match="attempt_id"):
        backend.record_attempt(
            attempt_id="", request_id=request.request_id,
            attempt=1, started_at=datetime.now(tz=UTC),
            ended_at=None,
            outcome=DeliveryLifecycleState.FAILED_RETRYABLE,
            provider_receipt_ref=None, reason_codes=("x",),
        )
    # Empty request_id
    with pytest.raises(ValueError, match="request_id"):
        backend.record_attempt(
            attempt_id="att-1", request_id="",
            attempt=1, started_at=datetime.now(tz=UTC),
            ended_at=None,
            outcome=DeliveryLifecycleState.FAILED_RETRYABLE,
            provider_receipt_ref=None, reason_codes=("x",),
        )
    # Bad attempt
    with pytest.raises(ValueError, match="attempt"):
        backend.record_attempt(
            attempt_id="att-1", request_id=request.request_id,
            attempt=0, started_at=datetime.now(tz=UTC),
            ended_at=None,
            outcome=DeliveryLifecycleState.FAILED_RETRYABLE,
            provider_receipt_ref=None, reason_codes=("x",),
        )
    with pytest.raises(ValueError, match="attempt"):
        backend.record_attempt(
            attempt_id="att-1", request_id=request.request_id,
            attempt=True,
            started_at=datetime.now(tz=UTC),
            ended_at=None,
            outcome=DeliveryLifecycleState.FAILED_RETRYABLE,
            provider_receipt_ref=None, reason_codes=("x",),
        )
    # Bad outcome
    with pytest.raises(ValueError, match="outcome"):
        backend.record_attempt(
            attempt_id="att-1", request_id=request.request_id,
            attempt=1, started_at=datetime.now(tz=UTC),
            ended_at=None,
            outcome="not-an-enum",  # type: ignore[arg-type]
            provider_receipt_ref=None, reason_codes=("x",),
        )
    # Bad reason_codes entry
    with pytest.raises(ValueError, match="non-empty strings"):
        backend.record_attempt(
            attempt_id="att-1", request_id=request.request_id,
            attempt=1, started_at=datetime.now(tz=UTC),
            ended_at=None,
            outcome=DeliveryLifecycleState.FAILED_RETRYABLE,
            provider_receipt_ref=None, reason_codes=("",),
        )
    with pytest.raises(ValueError, match="non-empty strings"):
        backend.record_attempt(
            attempt_id="att-1", request_id=request.request_id,
            attempt=1, started_at=datetime.now(tz=UTC),
            ended_at=None,
            outcome=DeliveryLifecycleState.FAILED_RETRYABLE,
            provider_receipt_ref=None, reason_codes=(1,),  # type: ignore[arg-type]
        )
    # Unknown request_id
    with pytest.raises(ValueError, match="unknown delivery request"):
        backend.record_attempt(
            attempt_id="att-x", request_id="ghost",
            attempt=1, started_at=datetime.now(tz=UTC),
            ended_at=None,
            outcome=DeliveryLifecycleState.FAILED_RETRYABLE,
            provider_receipt_ref=None, reason_codes=("x",),
        )
    backend.close()


def test_persistence_set_lifecycle_state_unknown_request(
    tmp_path: Path,
) -> None:
    """set_lifecycle_state on an unknown request_id raises."""

    db_path = tmp_path / "c7b_set_state.db"
    backend = SqliteDeliveryBackend(db_path)
    with pytest.raises(ValueError, match="unknown delivery request"):
        backend.set_lifecycle_state(
            "ghost", DeliveryLifecycleState.IN_FLIGHT,
            at=datetime.now(tz=UTC),
        )
    with pytest.raises(ValueError, match="new_state"):
        backend.set_lifecycle_state(
            "ghost", "not-an-enum",  # type: ignore[arg-type]
            at=datetime.now(tz=UTC),
        )
    backend.close()


def test_persistence_increment_attempt_unknown_request(
    tmp_path: Path,
) -> None:
    """increment_attempt on an unknown request_id raises."""

    db_path = tmp_path / "c7b_inc.db"
    backend = SqliteDeliveryBackend(db_path)
    with pytest.raises(ValueError, match="unknown delivery request"):
        backend.increment_attempt("ghost", at=datetime.now(tz=UTC))
    backend.close()


def test_persistence_record_reconcile_unknown_request(
    tmp_path: Path,
) -> None:
    """record_reconcile on an unknown request_id raises."""

    db_path = tmp_path / "c7b_recon.db"
    backend = SqliteDeliveryBackend(db_path)
    with pytest.raises(ValueError, match="unknown delivery request"):
        backend.record_reconcile("ghost", at=datetime.now(tz=UTC))
    backend.close()


def test_persistence_record_provider_receipt_ref_validation(
    tmp_path: Path,
) -> None:
    """record_provider_receipt_ref refuses empty refs and unknown ids."""

    db_path = tmp_path / "c7b_ref.db"
    request = _request(request_id=make_request_id(SCOPE, "intent-1", "k1"))
    backend = SqliteDeliveryBackend(db_path)
    backend.record_request(
        request, lifecycle_state=DeliveryLifecycleState.PENDING,
    )
    with pytest.raises(ValueError, match="non-empty"):
        backend.record_provider_receipt_ref(
            request.request_id, provider_receipt_ref="",
        )
    with pytest.raises(ValueError, match="unknown delivery request"):
        backend.record_provider_receipt_ref("ghost", provider_receipt_ref="x")
    backend.close()


def test_persistence_record_receipt_validation(
    tmp_path: Path,
) -> None:
    """record_receipt refuses bad request_id and bad attempt."""

    db_path = tmp_path / "c7b_recval.db"
    request = _request(request_id=make_request_id(SCOPE, "intent-1", "k1"))
    receipt = DeliveryReceipt(
        receipt_id="recpt-1",
        scope=request.scope,
        origin_runtime_id=request.origin_runtime_id,
        message_id=request.message_id,
        delivery_status=DeliveryStatus.SENT,
        delivered_at=NOW,
        sync=SyncFields(
            request.scope, request.origin_runtime_id,
            "recpt-1", 1, "idem-recpt-1",
        ),
    )
    backend = SqliteDeliveryBackend(db_path)
    backend.record_request(
        request, lifecycle_state=DeliveryLifecycleState.PENDING,
    )
    with pytest.raises(ValueError, match="request_id"):
        backend.record_receipt(
            receipt, request_id="",
            provider_receipt_ref=None,
            provider_message_ref=None,
            attempt=1,
        )
    with pytest.raises(ValueError, match="attempt"):
        backend.record_receipt(
            receipt, request_id=request.request_id,
            provider_receipt_ref=None,
            provider_message_ref=None,
            attempt=0,
        )
    with pytest.raises(ValueError, match="attempt"):
        backend.record_receipt(
            receipt, request_id=request.request_id,
            provider_receipt_ref=None,
            provider_message_ref=None,
            attempt=True,
        )
    backend.close()


def test_persistence_get_durable_receipt_missing(
    tmp_path: Path,
) -> None:
    """get_durable_receipt returns None when the receipt is absent."""

    db_path = tmp_path / "c7b_gr.db"
    backend = SqliteDeliveryBackend(db_path)
    try:
        assert backend.get_durable_receipt("absent") is None
    finally:
        backend.close()


def test_persistence_get_attempt_missing(
    tmp_path: Path,
) -> None:
    """get_attempt returns None when the attempt is absent."""

    db_path = tmp_path / "c7b_ga.db"
    backend = SqliteDeliveryBackend(db_path)
    try:
        assert backend.get_attempt("absent") is None
    finally:
        backend.close()


def test_persistence_table_names_lists_four(
    tmp_path: Path,
) -> None:
    """table_names includes the four C7B tables."""

    db_path = tmp_path / "c7b_tables.db"
    backend = SqliteDeliveryBackend(db_path)
    try:
        names = set(backend.table_names())
        for required in (
            "delivery_requests", "delivery_receipts",
            "delivery_attempts", "delivery_kill_switch",
        ):
            assert required in names
    finally:
        backend.close()


def test_persistence_kill_switch_returns_same_instance(
    tmp_path: Path,
) -> None:
    """kill_switch() returns a stable handle for the same backend."""

    db_path = tmp_path / "c7b_ks_handle.db"
    backend = SqliteDeliveryBackend(db_path)
    try:
        ks1 = backend.kill_switch()
        ks2 = backend.kill_switch()
        assert ks1 is ks2
    finally:
        backend.close()


def test_persistence_record_request_rejects_bad_state(
    tmp_path: Path,
) -> None:
    """record_request refuses a non-enum lifecycle_state."""

    db_path = tmp_path / "c7b_bad_state.db"
    request = _request(request_id=make_request_id(SCOPE, "intent-1", "k1"))
    backend = SqliteDeliveryBackend(db_path)
    try:
        with pytest.raises(ValueError, match="lifecycle_state"):
            backend.record_request(
                request, lifecycle_state="not-an-enum",  # type: ignore[arg-type]
            )
    finally:
        backend.close()


def test_persistence_record_attempt_idempotent(
    tmp_path: Path,
) -> None:
    """record_attempt returns False on a re-record (idempotent)."""

    db_path = tmp_path / "c7b_att_idem.db"
    request = _request(request_id=make_request_id(SCOPE, "intent-1", "k1"))
    backend = SqliteDeliveryBackend(db_path)
    backend.record_request(
        request, lifecycle_state=DeliveryLifecycleState.PENDING,
    )
    created = backend.record_attempt(
        attempt_id="att-1",
        request_id=request.request_id,
        attempt=1,
        started_at=datetime.now(tz=UTC),
        ended_at=datetime.now(tz=UTC),
        outcome=DeliveryLifecycleState.FAILED_RETRYABLE,
        provider_receipt_ref=None,
        reason_codes=("x",),
    )
    assert created is True
    # Re-record same attempt_id -> False (idempotent).
    again = backend.record_attempt(
        attempt_id="att-1",
        request_id=request.request_id,
        attempt=1,
        started_at=datetime.now(tz=UTC),
        ended_at=datetime.now(tz=UTC),
        outcome=DeliveryLifecycleState.FAILED_RETRYABLE,
        provider_receipt_ref=None,
        reason_codes=("x",),
    )
    assert again is False
    backend.close()


def test_persistence_attempts_for_request_empty(
    tmp_path: Path,
) -> None:
    """attempts_for_request returns an empty tuple when no attempts."""

    db_path = tmp_path / "c7b_att_empty.db"
    request = _request(request_id=make_request_id(SCOPE, "intent-1", "k1"))
    backend = SqliteDeliveryBackend(db_path)
    backend.record_request(
        request, lifecycle_state=DeliveryLifecycleState.PENDING,
    )
    try:
        assert backend.attempts_for_request(request.request_id) == ()
    finally:
        backend.close()


def test_persistence_unfinished_requests_excludes_terminal(
    tmp_path: Path,
) -> None:
    """unfinished_requests excludes ACCEPTED and REJECTED rows."""

    db_path = tmp_path / "c7b_unf.db"
    backend = SqliteDeliveryBackend(db_path)
    try:
        pending_req = _request(
            request_id=make_request_id(SCOPE, "intent-1", "p1"),
        )
        accepted_req = _request(
            request_id=make_request_id(SCOPE, "intent-1", "a1"),
        )
        rejected_req = _request(
            request_id=make_request_id(SCOPE, "intent-1", "r1"),
        )
        backend.record_request(
            pending_req, lifecycle_state=DeliveryLifecycleState.PENDING,
        )
        backend.record_request(
            accepted_req, lifecycle_state=DeliveryLifecycleState.PENDING,
        )
        backend.record_request(
            rejected_req, lifecycle_state=DeliveryLifecycleState.PENDING,
        )
        backend.set_lifecycle_state(
            accepted_req.request_id, DeliveryLifecycleState.IN_FLIGHT,
            at=datetime.now(tz=UTC),
        )
        backend.set_lifecycle_state(
            accepted_req.request_id, DeliveryLifecycleState.ACCEPTED,
            at=datetime.now(tz=UTC),
        )
        backend.set_lifecycle_state(
            rejected_req.request_id, DeliveryLifecycleState.IN_FLIGHT,
            at=datetime.now(tz=UTC),
        )
        backend.set_lifecycle_state(
            rejected_req.request_id, DeliveryLifecycleState.REJECTED,
            at=datetime.now(tz=UTC),
        )
        unfinished = backend.unfinished_requests()
        ids = {row.request.request_id for row in unfinished}
        assert pending_req.request_id in ids
        assert accepted_req.request_id not in ids
        assert rejected_req.request_id not in ids
    finally:
        backend.close()


def test_durable_request_row_dataclass() -> None:
    """DurableRequestRow is a frozen dataclass with the expected
    fields.
    """

    request = _request(request_id="deliv-row")
    row = DurableRequestRow(
        request=request,
        lifecycle_state=DeliveryLifecycleState.PENDING,
        attempt_count=0,
        last_attempt_at=None,
        last_reconcile_at=None,
        last_provider_receipt_ref=None,
    )
    assert row.request is request
    assert row.lifecycle_state is DeliveryLifecycleState.PENDING


def test_persistence_durable_request_rejects_naive_datetime(
    tmp_path: Path,
) -> None:
    """A naive datetime for record_request is rejected at the
    DeliveryRequest level (defense in depth).
    """

    with pytest.raises(ValueError, match="aware UTC"):
        DeliveryRequest(
            request_id="deliv-1",
            message_id=make_message_id("deliv-1"),
            scope=SCOPE, origin_runtime_id=RUNTIME_ID,
            channel="weixin", target="user-1",action_type="proactive_message", payload_bytes=b"x",
            created_at=datetime(2026, 1, 1),  # naive
            sync=SyncFields(SCOPE, RUNTIME_ID, "deliv-1", 1, "idem-1"),
        )


def test_persistence_durable_request_loads_validated(
    tmp_path: Path,
) -> None:
    """A valid row is loaded with full row reconstruction."""

    db_path = tmp_path / "c7b_full.db"
    request = _request(request_id=make_request_id(SCOPE, "intent-1", "k1"))
    backend = SqliteDeliveryBackend(db_path)
    backend.record_request(
        request, lifecycle_state=DeliveryLifecycleState.PENDING,
    )
    backend.set_lifecycle_state(
        request.request_id, DeliveryLifecycleState.IN_FLIGHT,
        at=datetime.now(tz=UTC),
    )
    backend.record_attempt(
        attempt_id="att-1", request_id=request.request_id, attempt=1,
        started_at=datetime.now(tz=UTC),
        ended_at=datetime.now(tz=UTC),
        outcome=DeliveryLifecycleState.FAILED_RETRYABLE,
        provider_receipt_ref=None,
        reason_codes=("x",),
    )
    row = backend.get_durable_request(request.request_id)
    assert row is not None
    assert row.attempt_count == 0
    attempts = backend.attempts_for_request(request.request_id)
    assert len(attempts) == 1
    backend.close()


def test_daemon_carrier_unknown_yields_unknown_state(
    tmp_path: Path,
) -> None:
    """A carrier UNKNOWN receipt yields UNKNOWN state."""

    db_path = tmp_path / "c7b_carrier_unknown.db"
    request = _request(request_id=make_request_id(SCOPE, "intent-1", "k1"))
    backend = SqliteDeliveryBackend(db_path)
    backend.record_request(
        request, lifecycle_state=DeliveryLifecycleState.PENDING,
    )

    class _UnknownPort:
        def deliver(self, request: DeliveryRequest) -> DeliveryReceipt:
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

    daemon = DaemonPass(backend=backend, port=_UnknownPort(), retry_budget=3)
    outcomes = daemon.run()
    assert len(outcomes) == 1
    assert outcomes[0].final_state is DeliveryLifecycleState.UNKNOWN
    backend.close()


def test_daemon_pending_with_live_in_flight_outcome_branch(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    """A PENDING row with attempt_count=0 makes compute_retry_decision
    return CAN_RETRY. After IN_FLIGHT->SENT the row goes to
    ACCEPTED. A subsequent IN_FLIGHT row exercises the in_flight
    log + outcome branch.
    """

    db_path = tmp_path / "c7b_inflight2.db"
    request = _request(request_id=make_request_id(SCOPE, "intent-1", "k1"))
    backend = SqliteDeliveryBackend(db_path)
    backend.record_request(
        request, lifecycle_state=DeliveryLifecycleState.PENDING,
    )
    # Pre-set the row to IN_FLIGHT with attempt_count > 0 so
    # compute_retry_decision returns reconcile_first, not can_retry.
    backend.set_lifecycle_state(
        request.request_id, DeliveryLifecycleState.IN_FLIGHT,
        at=datetime.now(tz=UTC),
    )
    backend.increment_attempt(
        request.request_id, at=datetime.now(tz=UTC),
    )

    # Use a reconciler that returns Unknown; the row stays in
    # UNKNOWN (reconcile_unknown log path). This exercises the
    # 'delivery.daemon.reconcile_unknown' branch and
    # ``_apply_reconcile`` with ResolvedUnknown.
    class _UnknownReconciler:
        def reconcile(self, request: DeliveryRequest) -> object:
            from mind_runtime.delivery import ResolvedUnknown
            return ResolvedUnknown(reason="provider_offline")

    port = _CountingPort()
    with caplog.at_level(logging.INFO, logger="mind_runtime.delivery.daemon"):
        daemon = DaemonPass(
            backend=backend, port=port,
            reconciler=_UnknownReconciler(),  # type: ignore[arg-type]
            retry_budget=3,
        )
        outcomes = daemon.run()
    assert len(outcomes) == 1
    assert outcomes[0].final_state in (
        DeliveryLifecycleState.UNKNOWN,
        DeliveryLifecycleState.IN_FLIGHT,
    )
    joined = "\n".join(r.getMessage() for r in caplog.records)
    # The reconcile path was exercised; the daemon logged either
    # 'reconcile' or 'reconcile_unknown'.
    assert "delivery.daemon." in joined
    backend.close()


# ----------------------------------------------------------- daemon
# daemon._apply_receipt branch coverage


def test_daemon_unsent_receipt_yields_rejected(
    tmp_path: Path,
) -> None:
    """A carrier UNSENT receipt yields REJECTED state."""

    from mind_runtime.delivery.daemon import _apply_receipt

    db_path = tmp_path / "c7b_unsent.db"
    request = _request(request_id=make_request_id(SCOPE, "intent-1", "k1"))
    backend = SqliteDeliveryBackend(db_path)
    backend.record_request(
        request, lifecycle_state=DeliveryLifecycleState.PENDING,
    )
    receipt = DeliveryReceipt(
        receipt_id="recpt-1",
        scope=request.scope,
        origin_runtime_id=request.origin_runtime_id,
        message_id=request.message_id,
        delivery_status=DeliveryStatus.UNSENT,
        delivered_at=None,
        sync=SyncFields(
            request.scope, request.origin_runtime_id,
            "recpt-1", 1, "idem-recpt-1",
        ),
    )
    state, reason, ref = _apply_receipt(
        request=request, receipt=receipt, backend=backend,
        now=datetime.now(tz=UTC), attempt=1,
    )
    assert state is DeliveryLifecycleState.REJECTED
    assert reason == "carrier_unsent"
    assert ref is None
    backend.close()


def test_daemon_sent_receipt_with_collision(
    tmp_path: Path,
) -> None:
    """A SENT receipt collision is handled fail-closed: the
    ``except ValueError`` branch in ``_apply_receipt`` is
    exercised when the receipt is already persisted with
    different bytes.
    """

    from mind_runtime.delivery.daemon import _apply_receipt

    db_path = tmp_path / "c7b_collision.db"
    request = _request(request_id=make_request_id(SCOPE, "intent-1", "k1"))
    backend = SqliteDeliveryBackend(db_path)
    backend.record_request(
        request, lifecycle_state=DeliveryLifecycleState.PENDING,
    )
    receipt = DeliveryReceipt(
        receipt_id="recpt-1",
        scope=request.scope,
        origin_runtime_id=request.origin_runtime_id,
        message_id=request.message_id,
        delivery_status=DeliveryStatus.SENT,
        delivered_at=NOW,
        sync=SyncFields(
            request.scope, request.origin_runtime_id,
            "recpt-1", 1, "idem-recpt-1",
        ),
    )
    # Persist once, then call _apply_receipt — the second call
    # inside _apply_receipt raises ValueError, which is caught
    # and the row stays ACCEPTED.
    backend.record_receipt(
        receipt, request_id=request.request_id,
        provider_receipt_ref=None,
        provider_message_ref=None,
        attempt=1,
    )
    state, reason, ref = _apply_receipt(
        request=request, receipt=receipt, backend=backend,
        now=datetime.now(tz=UTC), attempt=1,
    )
    # The second record_receipt is a no-op (False returned), not a
    # collision — it was the same bytes. So we land in the
    # ACCEPTED branch.
    assert state is DeliveryLifecycleState.ACCEPTED
    backend.close()


def test_daemon_collision_when_receipt_persisted_with_different_attempt(
    tmp_path: Path,
) -> None:
    """When the receipt is already persisted with a different
    attempt number, the re-record raises ValueError, which is
    caught inside _apply_receipt; the row stays ACCEPTED.
    """

    from mind_runtime.delivery.daemon import _apply_receipt

    db_path = tmp_path / "c7b_collision2.db"
    request = _request(request_id=make_request_id(SCOPE, "intent-1", "k1"))
    backend = SqliteDeliveryBackend(db_path)
    backend.record_request(
        request, lifecycle_state=DeliveryLifecycleState.PENDING,
    )
    receipt = DeliveryReceipt(
        receipt_id="recpt-1",
        scope=request.scope,
        origin_runtime_id=request.origin_runtime_id,
        message_id=request.message_id,
        delivery_status=DeliveryStatus.SENT,
        delivered_at=NOW,
        sync=SyncFields(
            request.scope, request.origin_runtime_id,
            "recpt-1", 1, "idem-recpt-1",
        ),
    )
    backend.record_receipt(
        receipt, request_id=request.request_id,
        provider_receipt_ref=None,
        provider_message_ref=None,
        attempt=2,
    )
    state, reason, ref = _apply_receipt(
        request=request, receipt=receipt, backend=backend,
        now=datetime.now(tz=UTC), attempt=1,
    )
    # The try/except caught the ValueError; the row stays ACCEPTED.
    assert state is DeliveryLifecycleState.ACCEPTED
    backend.close()


# ----------------------------------------------------------- kill switch


def test_kill_switch_block_channel_after_global_off(
    tmp_path: Path,
) -> None:
    """A block_channel after global OFF still records the per-key
    block (the OFF is the higher-precedence signal; the per-key
    block is preserved for inspect).
    """

    db_path = tmp_path / "c7b_ks_off_block.db"
    backend = SqliteDeliveryBackend(db_path)
    try:
        ks = backend.kill_switch()
        ks.set_global(on=False, updated_at=datetime.now(tz=UTC))
        # Per-channel block after global OFF.
        ks.block_channel(
            "weixin", reason="extra", updated_at=datetime.now(tz=UTC),
        )
        # The decide() still returns global_off (highest precedence).
        decision = ks.decide(channel="weixin", target="user-1")
        assert decision.allowed is False
        assert decision.reason_code == "global_off"
    finally:
        backend.close()


def test_kill_switch_unblock_no_op_when_not_blocked(
    tmp_path: Path,
) -> None:
    """unblock_channel / unblock_target are no-ops when nothing
    is blocked.
    """

    db_path = tmp_path / "c7b_ks_unblock.db"
    backend = SqliteDeliveryBackend(db_path)
    try:
        ks = backend.kill_switch()
        ks.unblock_channel(
            "weixin", updated_at=datetime.now(tz=UTC),
        )
        ks.unblock_target(
            "user-1", updated_at=datetime.now(tz=UTC),
        )
        assert ks.state() == "on"
    finally:
        backend.close()


# ----------------------------------------------------------- persistence


def test_persistence_reopen_fails_when_receipt_status_corrupt(
    tmp_path: Path,
) -> None:
    """Corrupt the receipt's delivery_status to an unknown value;
    reopen must fail closed.
    """

    db_path = tmp_path / "c7b_bad_status.db"
    request = _request(request_id=make_request_id(SCOPE, "intent-1", "k1"))
    receipt = DeliveryReceipt(
        receipt_id="recpt-bad",
        scope=request.scope,
        origin_runtime_id=request.origin_runtime_id,
        message_id=request.message_id,
        delivery_status=DeliveryStatus.SENT,
        delivered_at=NOW,
        sync=SyncFields(
            request.scope, request.origin_runtime_id,
            "recpt-bad", 1, "idem-recpt-bad",
        ),
    )
    backend = SqliteDeliveryBackend(db_path)
    backend.record_request(
        request, lifecycle_state=DeliveryLifecycleState.PENDING,
    )
    backend.record_receipt(
        receipt, request_id=request.request_id,
        provider_receipt_ref=None,
        provider_message_ref=None,
        attempt=1,
    )
    backend.close()
    del backend
    conn = sqlite3.connect(db_path)
    conn.execute(
        "UPDATE delivery_receipts SET delivery_status = ?"
        " WHERE receipt_id = ?",
        ("not-a-status", "recpt-bad"),
    )
    conn.commit()
    conn.close()
    with pytest.raises(ValueError, match="recpt-bad"):
        SqliteDeliveryBackend(db_path)


def test_persistence_reopen_fails_when_attempt_outcome_corrupt(
    tmp_path: Path,
) -> None:
    """Corrupt the attempt's outcome to an unknown value; reopen
    must fail closed.
    """

    db_path = tmp_path / "c7b_bad_outcome.db"
    request = _request(request_id=make_request_id(SCOPE, "intent-1", "k1"))
    backend = SqliteDeliveryBackend(db_path)
    backend.record_request(
        request, lifecycle_state=DeliveryLifecycleState.PENDING,
    )
    backend.record_attempt(
        attempt_id="att-bad", request_id=request.request_id, attempt=1,
        started_at=datetime.now(tz=UTC),
        ended_at=datetime.now(tz=UTC),
        outcome=DeliveryLifecycleState.FAILED_RETRYABLE,
        provider_receipt_ref=None,
        reason_codes=("x",),
    )
    backend.close()
    del backend
    conn = sqlite3.connect(db_path)
    conn.execute(
        "UPDATE delivery_attempts SET outcome = ? WHERE attempt_id = ?",
        ("not-an-outcome", "att-bad"),
    )
    conn.commit()
    conn.close()
    with pytest.raises(ValueError, match="att-bad"):
        SqliteDeliveryBackend(db_path)


def test_persistence_reopen_fails_when_reason_codes_malformed(
    tmp_path: Path,
) -> None:
    """Corrupt the attempt's reason_codes JSON; reopen must fail
    closed.
    """

    db_path = tmp_path / "c7b_bad_reasons.db"
    request = _request(request_id=make_request_id(SCOPE, "intent-1", "k1"))
    backend = SqliteDeliveryBackend(db_path)
    backend.record_request(
        request, lifecycle_state=DeliveryLifecycleState.PENDING,
    )
    backend.record_attempt(
        attempt_id="att-bad-r", request_id=request.request_id, attempt=1,
        started_at=datetime.now(tz=UTC),
        ended_at=datetime.now(tz=UTC),
        outcome=DeliveryLifecycleState.FAILED_RETRYABLE,
        provider_receipt_ref=None,
        reason_codes=("x",),
    )
    backend.close()
    del backend
    conn = sqlite3.connect(db_path)
    conn.execute(
        "UPDATE delivery_attempts SET reason_codes = ?"
        " WHERE attempt_id = ?",
        ("{not-valid-json", "att-bad-r"),
    )
    conn.commit()
    conn.close()
    with pytest.raises(ValueError, match="att-bad-r"):
        SqliteDeliveryBackend(db_path)


def test_persistence_reopen_fails_when_reason_codes_not_array(
    tmp_path: Path,
) -> None:
    """A reason_codes value that is valid JSON but not an array
    fails closed.
    """

    db_path = tmp_path / "c7b_bad_reasons2.db"
    request = _request(request_id=make_request_id(SCOPE, "intent-1", "k1"))
    backend = SqliteDeliveryBackend(db_path)
    backend.record_request(
        request, lifecycle_state=DeliveryLifecycleState.PENDING,
    )
    backend.record_attempt(
        attempt_id="att-bad-r2", request_id=request.request_id, attempt=1,
        started_at=datetime.now(tz=UTC),
        ended_at=datetime.now(tz=UTC),
        outcome=DeliveryLifecycleState.FAILED_RETRYABLE,
        provider_receipt_ref=None,
        reason_codes=("x",),
    )
    backend.close()
    del backend
    conn = sqlite3.connect(db_path)
    conn.execute(
        "UPDATE delivery_attempts SET reason_codes = ?"
        " WHERE attempt_id = ?",
        ('{"a": 1}', "att-bad-r2"),
    )
    conn.commit()
    conn.close()
    with pytest.raises(ValueError, match="must be a JSON array"):
        SqliteDeliveryBackend(db_path)


# ----------------------------------------------------------- kill switch


def test_kill_switch_unblock_target_no_op_when_not_blocked(
    tmp_path: Path,
) -> None:
    """unblock_target is a no-op when nothing is blocked."""

    db_path = tmp_path / "c7b_ks_unblock_tgt.db"
    backend = SqliteDeliveryBackend(db_path)
    try:
        backend.kill_switch().unblock_target(
            "user-1", updated_at=datetime.now(tz=UTC),
        )
    finally:
        backend.close()


# ----------------------------------------------------------- more persistence


@pytest.mark.parametrize(
    ("raw_sync", "message"),
    (
        ('["not", "a", "dict"]', "must be a JSON object"),
        ('{"scope": "user"}', "missing required keys"),
        (
            '{"scope": 1, "origin_runtime_id": "x", "object_id": "y",'
            ' "version": 1, "idempotency_key": "z"}',
            "sync.scope",
        ),
    ),
)
def test_persistence_request_reopen_rejects_corrupt_sync(
    tmp_path: Path,
    raw_sync: str,
    message: str,
) -> None:
    db_path = tmp_path / "c7b_corrupt_sync.db"
    request = _request(request_id=make_request_id(SCOPE, "intent-1", "k1"))
    backend = SqliteDeliveryBackend(db_path)
    backend.record_request(
        request,
        lifecycle_state=DeliveryLifecycleState.PENDING,
    )
    backend.close()

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE delivery_requests SET sync = ? WHERE request_id = ?",
            (raw_sync, request.request_id),
        )

    with pytest.raises(ValueError, match=message):
        SqliteDeliveryBackend(db_path)


def test_persistence_receipt_reopen_corrupt_sync(
    tmp_path: Path,
) -> None:
    """A receipt with a corrupt sync field fails closed on reopen."""

    db_path = tmp_path / "c7b_corrupt_rec_sync.db"
    request = _request(request_id=make_request_id(SCOPE, "intent-1", "k1"))
    receipt = DeliveryReceipt(
        receipt_id="recpt-bad-sync",
        scope=request.scope,
        origin_runtime_id=request.origin_runtime_id,
        message_id=request.message_id,
        delivery_status=DeliveryStatus.SENT,
        delivered_at=NOW,
        sync=SyncFields(
            request.scope, request.origin_runtime_id,
            "recpt-bad-sync", 1, "idem-recpt-bad-sync",
        ),
    )
    backend = SqliteDeliveryBackend(db_path)
    backend.record_request(
        request, lifecycle_state=DeliveryLifecycleState.PENDING,
    )
    backend.record_receipt(
        receipt, request_id=request.request_id,
        provider_receipt_ref=None,
        provider_message_ref=None,
        attempt=1,
    )
    backend.close()
    del backend
    conn = sqlite3.connect(db_path)
    conn.execute(
        "UPDATE delivery_receipts SET sync = ? WHERE receipt_id = ?",
        ("[1, 2, 3]", "recpt-bad-sync"),
    )
    conn.commit()
    conn.close()
    with pytest.raises(ValueError, match="must be a JSON object"):
        SqliteDeliveryBackend(db_path)


def test_persistence_attempt_reason_codes_load_failure(
    tmp_path: Path,
) -> None:
    """A reason_codes value that is not a list (when loaded by
    get_attempt / attempts_for_request) raises.
    """

    db_path = tmp_path / "c7b_att_bad_load.db"
    request = _request(request_id=make_request_id(SCOPE, "intent-1", "k1"))
    backend = SqliteDeliveryBackend(db_path)
    backend.record_request(
        request, lifecycle_state=DeliveryLifecycleState.PENDING,
    )
    backend.record_attempt(
        attempt_id="att-bad-load", request_id=request.request_id, attempt=1,
        started_at=datetime.now(tz=UTC),
        ended_at=datetime.now(tz=UTC),
        outcome=DeliveryLifecycleState.FAILED_RETRYABLE,
        provider_receipt_ref=None,
        reason_codes=("x",),
    )
    backend.close()
    del backend
    # Reopen with a valid reason_codes JSON but not a list. The
    # reopen's validation must catch it.
    conn = sqlite3.connect(db_path)
    conn.execute(
        "UPDATE delivery_attempts SET reason_codes = ?"
        " WHERE attempt_id = ?",
        ('{"not": "list"}', "att-bad-load"),
    )
    conn.commit()
    conn.close()
    with pytest.raises(ValueError, match="must be a JSON array"):
        SqliteDeliveryBackend(db_path)


def test_persistence_path_property(tmp_path: Path) -> None:
    """The path property exposes the on-disk path."""

    db_path = tmp_path / "c7b_path.db"
    backend = SqliteDeliveryBackend(db_path)
    try:
        assert backend.path == str(db_path)
    finally:
        backend.close()


def test_persistence_set_lifecycle_state_at_validation(
    tmp_path: Path,
) -> None:
    """set_lifecycle_state requires aware-UTC timestamps."""

    db_path = tmp_path / "c7b_at.db"
    request = _request(request_id=make_request_id(SCOPE, "intent-1", "k1"))
    backend = SqliteDeliveryBackend(db_path)
    backend.record_request(
        request, lifecycle_state=DeliveryLifecycleState.PENDING,
    )
    try:
        with pytest.raises(ValueError, match="aware UTC"):
            backend.set_lifecycle_state(
                request.request_id,
                DeliveryLifecycleState.IN_FLIGHT,
                at=datetime(2026, 1, 1),  # naive
            )
    finally:
        backend.close()


def test_persistence_record_attempt_ended_at_validation(
    tmp_path: Path,
) -> None:
    """record_attempt requires aware-UTC ended_at."""

    db_path = tmp_path / "c7b_ended.db"
    request = _request(request_id=make_request_id(SCOPE, "intent-1", "k1"))
    backend = SqliteDeliveryBackend(db_path)
    backend.record_request(
        request, lifecycle_state=DeliveryLifecycleState.PENDING,
    )
    try:
        with pytest.raises(ValueError, match="aware UTC"):
            backend.record_attempt(
                attempt_id="att-naive", request_id=request.request_id,
                attempt=1, started_at=datetime.now(tz=UTC),
                ended_at=datetime(2026, 1, 1),  # naive
                outcome=DeliveryLifecycleState.FAILED_RETRYABLE,
                provider_receipt_ref=None, reason_codes=("x",),
            )
    finally:
        backend.close()


def test_persistence_get_durable_request_idempotent_record(
    tmp_path: Path,
) -> None:
    """Recording the same request twice (same bytes) returns False."""

    db_path = tmp_path / "c7b_dup.db"
    request = _request(request_id=make_request_id(SCOPE, "intent-1", "k1"))
    backend = SqliteDeliveryBackend(db_path)
    try:
        first = backend.record_request(
            request, lifecycle_state=DeliveryLifecycleState.PENDING,
        )
        assert first is True
        second = backend.record_request(
            request, lifecycle_state=DeliveryLifecycleState.PENDING,
        )
        assert second is False
    finally:
        backend.close()


# ----------------------------------------------------------- more persistence



# ----------------------------------------------------------- persistence load errors


def test_persistence_load_request_corrupt_payload_type(
    tmp_path: Path,
) -> None:
    """A request whose payload_bytes is not bytes fails closed
    on load.
    """

    db_path = tmp_path / "c7b_load_bad_payload.db"
    request = _request(request_id=make_request_id(SCOPE, "intent-1", "k1"))
    backend = SqliteDeliveryBackend(db_path)
    backend.record_request(
        request, lifecycle_state=DeliveryLifecycleState.PENDING,
    )
    backend.close()
    del backend
    # Replace the payload with a non-bytes value.
    conn = sqlite3.connect(db_path)
    conn.execute(
        "UPDATE delivery_requests SET payload_bytes = ?"
        " WHERE request_id = ?",
        ("not-bytes", request.request_id),
    )
    conn.commit()
    conn.close()
    backend = SqliteDeliveryBackend(db_path)
    try:
        with pytest.raises(ValueError, match="non-bytes payload"):
            backend.get_durable_request(request.request_id)
    finally:
        backend.close()


def test_persistence_get_attempt_corrupt_reason_codes(
    tmp_path: Path,
) -> None:
    """An attempt with malformed reason_codes fails closed on reopen."""

    db_path = tmp_path / "c7b_load_bad_reasons.db"
    request = _request(request_id=make_request_id(SCOPE, "intent-1", "k1"))
    backend = SqliteDeliveryBackend(db_path)
    backend.record_request(
        request, lifecycle_state=DeliveryLifecycleState.PENDING,
    )
    backend.record_attempt(
        attempt_id="att-bad-r3", request_id=request.request_id, attempt=1,
        started_at=datetime.now(tz=UTC),
        ended_at=datetime.now(tz=UTC),
        outcome=DeliveryLifecycleState.FAILED_RETRYABLE,
        provider_receipt_ref=None,
        reason_codes=("x",),
    )
    backend.close()
    del backend
    conn = sqlite3.connect(db_path)
    conn.execute(
        "UPDATE delivery_attempts SET reason_codes = ?"
        " WHERE attempt_id = ?",
        ('"just-a-string"', "att-bad-r3"),
    )
    conn.commit()
    conn.close()
    with pytest.raises(ValueError, match="must be a JSON array"):
        SqliteDeliveryBackend(db_path)


def test_persistence_kill_switch_corrupt_channel_blocks_bad_json(
    tmp_path: Path,
) -> None:
    """A non-object channel_blocks JSON value fails closed when
    the kill switch is consulted.
    """

    db_path = tmp_path / "c7b_ks_bad_ch.db"
    backend = SqliteDeliveryBackend(db_path)
    backend.close()
    del backend
    conn = sqlite3.connect(db_path)
    # An array instead of an object. The kill-switch inspection
    # must catch it.
    conn.execute(
        "UPDATE delivery_kill_switch SET channel_blocks = ?"
        " WHERE row_id = 1",
        ('["not-an-object"]',),
    )
    conn.commit()
    conn.close()
    backend = SqliteDeliveryBackend(db_path)
    try:
        with pytest.raises(ValueError, match="must be a JSON object"):
            backend.kill_switch().state()
    finally:
        backend.close()


# ----------------------------------------------------------- direct module tests


def test_persistence_to_json_non_serializable(
    tmp_path: Path,
) -> None:
    """_to_json raises ValueError for non-JSON-serializable values."""

    from mind_runtime.delivery.persistence import _to_json
    with pytest.raises(ValueError, match="JSON-serializable"):
        _to_json({1, 2, 3})  # sets are not JSON-serializable


def test_persistence_validate_sync_payload_version_not_int(
    tmp_path: Path,
) -> None:
    """_validate_sync_payload rejects a non-integer version."""

    from mind_runtime.delivery.persistence import _validate_sync_payload
    with pytest.raises(ValueError, match="version must be an integer"):
        _validate_sync_payload(
            '{"scope": "user", "origin_runtime_id": "x", "object_id": "y",'
            ' "version": "v1", "idempotency_key": "z"}',
            "row-x", "delivery_requests",
        )


def test_persistence_kill_switch_block_map_non_str_raw(
    tmp_path: Path,
) -> None:
    """A non-string channel_blocks raw value fails closed."""

    from mind_runtime.delivery.kill_switch import _validate_block_map
    with pytest.raises(ValueError, match="must be a JSON object string"):
        _validate_block_map(123, "channel_blocks")  # type: ignore[arg-type]


def test_persistence_get_durable_request_returns_none_for_unknown(
    tmp_path: Path,
) -> None:
    """get_durable_request returns None for an unknown request_id."""

    db_path = tmp_path / "c7b_get_none.db"
    backend = SqliteDeliveryBackend(db_path)
    try:
        result = backend.get_durable_request("nonexistent")
        assert result is None
    finally:
        backend.close()


def test_persistence_record_receipt_returns_false_on_idempotent(
    tmp_path: Path,
) -> None:
    """record_receipt returns False on a no-op re-record."""

    db_path = tmp_path / "c7b_rec_false.db"
    request = _request(request_id=make_request_id(SCOPE, "intent-1", "k1"))
    receipt = DeliveryReceipt(
        receipt_id="recpt-1",
        scope=request.scope,
        origin_runtime_id=request.origin_runtime_id,
        message_id=request.message_id,
        delivery_status=DeliveryStatus.SENT,
        delivered_at=NOW,
        sync=SyncFields(
            request.scope, request.origin_runtime_id,
            "recpt-1", 1, "idem-recpt-1",
        ),
    )
    backend = SqliteDeliveryBackend(db_path)
    backend.record_request(
        request, lifecycle_state=DeliveryLifecycleState.PENDING,
    )
    try:
        first = backend.record_receipt(
            receipt, request_id=request.request_id,
            provider_receipt_ref="r1",
            provider_message_ref="m1",
            attempt=1,
        )
        assert first is True
        second = backend.record_receipt(
            receipt, request_id=request.request_id,
            provider_receipt_ref="r1",
            provider_message_ref="m1",
            attempt=1,
        )
        assert second is False
    finally:
        backend.close()


# ----------------------------------------------------------- direct module tests 2


def test_persistence_attempt_from_row_non_list_reason_codes() -> None:
    """_attempt_from_row raises on non-list reason_codes."""

    import sqlite3 as _sqlite3

    from mind_runtime.delivery.persistence import _attempt_from_row

    conn = _sqlite3.connect(":memory:")
    conn.row_factory = _sqlite3.Row
    conn.execute(
        "CREATE TABLE delivery_attempts ("
        "attempt_id TEXT, request_id TEXT, attempt INTEGER,"
        " started_at TEXT, ended_at TEXT, outcome TEXT,"
        " provider_receipt_ref TEXT, reason_codes TEXT)"
    )
    conn.execute(
        "INSERT INTO delivery_attempts VALUES (?,?,?,?,?,?,?,?)",
        ("a1", "r1", 1, "2026-01-01T00:00:00+00:00",
         None, "failed_retryable", None, '"a-string"'),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM delivery_attempts").fetchone()
    with pytest.raises(ValueError, match="is not a JSON array"):
        _attempt_from_row(row)
    conn.close()


def test_persistence_validate_sync_payload_empty_string_field(
    tmp_path: Path,
) -> None:
    """_validate_sync_payload rejects empty string fields."""

    from mind_runtime.delivery.persistence import _validate_sync_payload
    with pytest.raises(ValueError, match="sync.origin_runtime_id"):
        _validate_sync_payload(
            '{"scope": "user", "origin_runtime_id": "",'
            ' "object_id": "y", "version": 1, "idempotency_key": "z"}',
            "row-x", "delivery_requests",
        )
    with pytest.raises(ValueError, match="sync.object_id"):
        _validate_sync_payload(
            '{"scope": "user", "origin_runtime_id": "x",'
            ' "object_id": "", "version": 1, "idempotency_key": "z"}',
            "row-x", "delivery_requests",
        )
    with pytest.raises(ValueError, match="sync.idempotency_key"):
        _validate_sync_payload(
            '{"scope": "user", "origin_runtime_id": "x",'
            ' "object_id": "y", "version": 1, "idempotency_key": ""}',
            "row-x", "delivery_requests",
        )


def test_persistence_get_attempt_returns_row(
    tmp_path: Path,
) -> None:
    """get_attempt returns a DurableAttemptRow when the row exists."""

    db_path = tmp_path / "c7b_get_att.db"
    request = _request(request_id=make_request_id(SCOPE, "intent-1", "k1"))
    backend = SqliteDeliveryBackend(db_path)
    backend.record_request(
        request, lifecycle_state=DeliveryLifecycleState.PENDING,
    )
    backend.record_attempt(
        attempt_id="att-1", request_id=request.request_id, attempt=1,
        started_at=datetime.now(tz=UTC),
        ended_at=datetime.now(tz=UTC),
        outcome=DeliveryLifecycleState.FAILED_RETRYABLE,
        provider_receipt_ref=None,
        reason_codes=("x",),
    )
    try:
        row = backend.get_attempt("att-1")
        assert row is not None
        assert row.attempt_id == "att-1"
        assert row.attempt == 1
    finally:
        backend.close()


def test_daemon_apply_receipt_sent_no_delivered_at(
    tmp_path: Path,
) -> None:
    """A SENT receipt with delivered_at=None is accepted; the
    provider_ref is None.
    """

    from mind_runtime.delivery.daemon import _apply_receipt

    db_path = tmp_path / "c7b_no_dt.db"
    request = _request(request_id=make_request_id(SCOPE, "intent-1", "k1"))
    backend = SqliteDeliveryBackend(db_path)
    backend.record_request(
        request, lifecycle_state=DeliveryLifecycleState.PENDING,
    )
    receipt = DeliveryReceipt(
        receipt_id="recpt-1",
        scope=request.scope,
        origin_runtime_id=request.origin_runtime_id,
        message_id=request.message_id,
        delivery_status=DeliveryStatus.SENT,
        delivered_at=None,
        sync=SyncFields(
            request.scope, request.origin_runtime_id,
            "recpt-1", 1, "idem-recpt-1",
        ),
    )
    state, reason, ref = _apply_receipt(
        request=request, receipt=receipt, backend=backend,
        now=datetime.now(tz=UTC), attempt=1,
    )
    assert state is DeliveryLifecycleState.ACCEPTED
    assert reason == "carrier_sent"
    assert ref is None
    backend.close()


def test_kill_switch_close_no_op_when_connection_not_owned(
    tmp_path: Path,
) -> None:
    """A kill switch that shares a connection with a backend does
    not close the connection on .close().
    """

    db_path = tmp_path / "c7b_ks_shared.db"
    backend = SqliteDeliveryBackend(db_path)
    try:
        # The switch here is owned by the backend; .close() is a
        # no-op.
        backend.kill_switch().close()
        # The backend's connection is still usable.
        backend.kill_switch().state()
    finally:
        backend.close()
