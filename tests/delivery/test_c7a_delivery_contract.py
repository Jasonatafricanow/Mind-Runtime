"""C7A Delivery contract tests (6 invariants).

These tests exercise the typed surface, the durable in-memory
backend, and the deterministic fake carrier. No real network / no
Hermes / no chat — the G-cases are about determinism, idempotency,
and durability, all of which can be tested without a carrier.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from mind_runtime.contracts import (
    DeliveryStatus,
    Scope,
    ScopeDomain,
    SyncFields,
)
from mind_runtime.delivery import (
    DeliveryRequest,
    InMemoryDeliveryBackend,
    InMemoryDeliveryReceiptStore,
    InMemoryDeliveryRequestStore,
    make_message_id,
    make_request_id,
)

NOW = datetime(2026, 1, 1, tzinfo=UTC)
SCOPE = Scope(domain=ScopeDomain.USER, user_id="u1")
RUNTIME_ID = "xiyue"


def _request(
    *, request_id: str, message_id: str | None = None, body: bytes = b"hello",
    idempotency_key: str = "k1", action_intent_id: str = "intent-1",
    channel: str = "weixin", target: str = "user-1",
    created_at: datetime = NOW,
) -> DeliveryRequest:
    return DeliveryRequest(
        request_id=request_id,
        message_id=message_id or make_message_id(request_id),
        scope=SCOPE, origin_runtime_id=RUNTIME_ID,
        channel=channel, target=target, action_type="proactive_message", payload_bytes=body,
        created_at=created_at,
        sync=SyncFields(SCOPE, RUNTIME_ID, request_id, 1, f"idem-{request_id}"),
    )


def test_g1_idempotent_dedup_yields_no_double_send() -> None:
    """Same idempotency_key + same target → ONE durable record, ONE send."""
    backend = InMemoryDeliveryBackend()
    store = InMemoryDeliveryRequestStore()
    receipt_store = InMemoryDeliveryReceiptStore()
    request = _request(request_id=make_request_id(SCOPE, "intent-1", "k1"))
    store.record(request)
    first = backend.deliver(request)
    receipt_store.record(first)
    second = backend.deliver(request)
    receipt_store.record(second)
    assert first.delivery_status is DeliveryStatus.SENT
    assert second.delivery_status is DeliveryStatus.SENT
    assert first.receipt_id == second.receipt_id
    assert backend.sent_count == 1
    assert len(store.all()) == 1
    assert len(receipt_store.all()) == 1


def test_g2_different_idempotency_keys_yield_independent_deliveries() -> None:
    """Different idempotency_keys must produce independent durable records."""
    backend = InMemoryDeliveryBackend()
    store = InMemoryDeliveryRequestStore()
    request_a = _request(
        request_id=make_request_id(SCOPE, "intent-1", "action-A"),
    )
    request_b = _request(
        request_id=make_request_id(SCOPE, "intent-1", "action-B"),
    )
    store.record(request_a)
    store.record(request_b)
    receipt_a = backend.deliver(request_a)
    receipt_b = backend.deliver(request_b)
    assert receipt_a.receipt_id != receipt_b.receipt_id
    assert receipt_a.message_id != receipt_b.message_id
    assert backend.sent_count == 2
    assert len(store.all()) == 2


def test_g3_transport_failure_yields_unknown_receipt_and_keeps_request_durable() -> None:
    """When the carrier itself cannot decide, the receipt is UNKNOWN
    and the request stays in the durable log so reconcile can replay."""
    backend = InMemoryDeliveryBackend(fail_after=0)
    store = InMemoryDeliveryRequestStore()
    request = _request(request_id=make_request_id(SCOPE, "intent-1", "k1"))
    store.record(request)
    receipt = backend.deliver(request)
    assert receipt.delivery_status is DeliveryStatus.UNKNOWN
    assert receipt.delivered_at is None
    assert store.has(request.request_id), (
        "failed request must remain durable for replay")
    replay = backend.deliver(request)
    assert replay.receipt_id == receipt.receipt_id
    assert backend.sent_count == 0


def test_g4_request_log_durable_across_registry_instances() -> None:
    """The durable plane is the same identity regardless of which
    in-process object holds the records; a fresh store re-loads."""
    src_store = InMemoryDeliveryRequestStore()
    request = _request(request_id=make_request_id(SCOPE, "intent-1", "k1"))
    src_store.record(request)
    snapshot = src_store.all()

    fresh_store = InMemoryDeliveryRequestStore()
    for r in snapshot:
        fresh_store.record(r)
    assert fresh_store.has(request.request_id)
    assert fresh_store.get(request.request_id) == request


def test_g5_same_id_different_bytes_fails_closed() -> None:
    """The durable plane refuses a second request with the same id and
    different immutable bytes. A corrupted retry must not be silently
    accepted with mutated payload."""
    store = InMemoryDeliveryRequestStore()
    request = _request(
        request_id=make_request_id(SCOPE, "intent-1", "k1"),
        body=b"original",
    )
    store.record(request)
    tampered = _request(
        request_id=request.request_id,
        body=b"mutated",
    )
    with pytest.raises(ValueError, match="different immutable bytes"):
        store.record(tampered)


def test_g6_kill_switch_cancels_outstanding_durable_requests() -> None:
    """The fail_after backend serves as the canonical kill switch:
    once the budget is exhausted every subsequent deliver yields
    UNKNOWN while the durable plane keeps the request record."""
    backend = InMemoryDeliveryBackend(fail_after=2)
    store = InMemoryDeliveryRequestStore()
    receipt_store = InMemoryDeliveryReceiptStore()
    ids = [f"deliv-{i}" for i in range(5)]
    statuses = []
    for rid in ids:
        request = _request(request_id=rid)
        store.record(request)
        receipt = backend.deliver(request)
        receipt_store.record(receipt)
        statuses.append(receipt.delivery_status)
    assert statuses[:2] == [DeliveryStatus.SENT, DeliveryStatus.SENT]
    assert statuses[2:] == [DeliveryStatus.UNKNOWN] * 3
    assert len(store.all()) == 5
    assert len(receipt_store.all()) == 5


# -------------------------------------------------- contract-level guard tests


def test_contract_rejects_empty_payload() -> None:
    """DeliveryRequest refuses an empty body: the carrier can never
    deliver nothing."""
    with pytest.raises(ValueError, match="payload_bytes"):
        DeliveryRequest(
            request_id="deliv-empty",
            message_id="msg-empty",
            scope=SCOPE, origin_runtime_id=RUNTIME_ID,
            channel="weixin", target="user-1",action_type="proactive_message", payload_bytes=b"",
            created_at=NOW,
            sync=SyncFields(SCOPE, RUNTIME_ID, "deliv-empty", 1, "idem-deliv-empty"),
        )


def test_contract_rejects_empty_idempotency_key() -> None:
    with pytest.raises(ValueError, match="idempotency_key"):
        make_request_id(SCOPE, "intent-1", "")


def test_contract_rejects_empty_request_id() -> None:
    with pytest.raises(ValueError, match="request_id"):
        DeliveryRequest(
            request_id="",
            message_id="msg-1",
            scope=SCOPE, origin_runtime_id=RUNTIME_ID,
            channel="weixin", target="user-1",action_type="proactive_message", payload_bytes=b"x",
            created_at=NOW,
            sync=SyncFields(SCOPE, RUNTIME_ID, "", 1, "idem-empty"),
        )


def test_contract_rejects_empty_message_id() -> None:
    with pytest.raises(ValueError, match="message_id"):
        DeliveryRequest(
            request_id="deliv-1",
            message_id="",
            scope=SCOPE, origin_runtime_id=RUNTIME_ID,
            channel="weixin", target="user-1",action_type="proactive_message", payload_bytes=b"x",
            created_at=NOW,
            sync=SyncFields(SCOPE, RUNTIME_ID, "deliv-1", 1, "idem-1"),
        )


def test_contract_rejects_empty_channel() -> None:
    with pytest.raises(ValueError, match="channel"):
        DeliveryRequest(
            request_id="deliv-1",
            message_id="msg-1",
            scope=SCOPE, origin_runtime_id=RUNTIME_ID,
            channel="", target="user-1",action_type="proactive_message", payload_bytes=b"x",
            created_at=NOW,
            sync=SyncFields(SCOPE, RUNTIME_ID, "deliv-1", 1, "idem-1"),
        )


def test_contract_rejects_empty_target() -> None:
    with pytest.raises(ValueError, match="target"):
        DeliveryRequest(
            request_id="deliv-1",
            message_id="msg-1",
            scope=SCOPE, origin_runtime_id=RUNTIME_ID,
            channel="weixin", target="",action_type="proactive_message", payload_bytes=b"x",
            created_at=NOW,
            sync=SyncFields(SCOPE, RUNTIME_ID, "deliv-1", 1, "idem-1"),
        )


def test_contract_rejects_non_bytes_payload() -> None:
    with pytest.raises(ValueError, match="payload_bytes must be bytes"):
        DeliveryRequest(
            request_id="deliv-1",
            message_id="msg-1",
            scope=SCOPE, origin_runtime_id=RUNTIME_ID,
            channel="weixin", target="user-1",
            action_type="proactive_message", payload_bytes="not-bytes",  # type: ignore[arg-type]
            created_at=NOW,
            sync=SyncFields(SCOPE, RUNTIME_ID, "deliv-1", 1, "idem-1"),
        )


def test_contract_rejects_non_scope() -> None:
    with pytest.raises(ValueError, match="scope must be a Scope"):
        DeliveryRequest(
            request_id="deliv-1",
            message_id="msg-1",
            scope="not-scope",  # type: ignore[arg-type]
            origin_runtime_id=RUNTIME_ID,
            channel="weixin", target="user-1",action_type="proactive_message", payload_bytes=b"x",
            created_at=NOW,
            sync=SyncFields(SCOPE, RUNTIME_ID, "deliv-1", 1, "idem-1"),
        )


def test_contract_rejects_scope_origin_mismatch() -> None:
    """SyncFields must match the request scope and origin (defense in depth)."""
    other_scope = Scope(
        domain=ScopeDomain.USER, user_id="other-user",
    )
    with pytest.raises(ValueError, match="scope must match"):
        DeliveryRequest(
            request_id="deliv-1",
            message_id="msg-1",
            scope=SCOPE, origin_runtime_id=RUNTIME_ID,
            channel="weixin", target="user-1",action_type="proactive_message", payload_bytes=b"x",
            created_at=NOW,
            sync=SyncFields(other_scope, RUNTIME_ID, "deliv-1", 1, "idem-1"),
        )


def test_receipt_store_rejects_id_collision_with_different_bytes() -> None:
    """A receipt with the same id but different immutable bytes is refused."""
    from mind_runtime.delivery import InMemoryDeliveryBackend, InMemoryDeliveryReceiptStore

    backend = InMemoryDeliveryBackend()
    store = InMemoryDeliveryReceiptStore()
    request = _request(request_id=make_request_id(SCOPE, "intent-1", "k1"))
    receipt = backend.deliver(request)
    store.record(receipt)
    # A second receipt with the same id but a different delivered_at must
    # collide (immutable bytes invariant).
    tampered = replace(receipt, delivered_at=NOW + timedelta(seconds=1))
    with pytest.raises(ValueError, match="collision"):
        store.record(tampered)


def test_in_memory_backend_records_seen_request_ids() -> None:
    """The deterministic carrier exposes its seen_request_ids for assertions."""
    from mind_runtime.delivery import InMemoryDeliveryBackend

    backend = InMemoryDeliveryBackend()
    request = _request(request_id=make_request_id(SCOPE, "intent-1", "k1"))
    receipt = backend.deliver(request)
    assert request.request_id in backend.seen_request_ids
    assert backend.sent_count == 1
    assert receipt.delivery_status is DeliveryStatus.SENT


def test_in_memory_backend_fail_after_kill_switch() -> None:
    """After fail_after=N the next deliver() yields UNKNOWN, not SENT."""
    from mind_runtime.delivery import InMemoryDeliveryBackend

    backend = InMemoryDeliveryBackend(fail_after=1)
    request1 = _request(request_id=make_request_id(SCOPE, "intent-1", "k1"))
    request2 = _request(request_id=make_request_id(SCOPE, "intent-1", "k2"))
    receipt1 = backend.deliver(request1)
    receipt2 = backend.deliver(request2)
    assert receipt1.delivery_status is DeliveryStatus.SENT
    assert receipt2.delivery_status is DeliveryStatus.UNKNOWN
    assert backend.sent_count == 1


def test_in_memory_backend_idempotent_dedup() -> None:
    """Re-delivering the same request_id yields a SENT receipt, no double-send."""
    from mind_runtime.delivery import InMemoryDeliveryBackend

    backend = InMemoryDeliveryBackend()
    request = _request(request_id=make_request_id(SCOPE, "intent-1", "k1"))
    receipt1 = backend.deliver(request)
    receipt2 = backend.deliver(request)
    # Same id, both SENT, but no double-increment.
    assert receipt1.delivery_status is DeliveryStatus.SENT
    assert receipt2.delivery_status is DeliveryStatus.SENT
    assert backend.sent_count == 1


def test_receipt_store_get_returns_none_when_missing() -> None:
    """get() on an unknown receipt_id returns None (not raises)."""
    from mind_runtime.delivery import InMemoryDeliveryReceiptStore

    store = InMemoryDeliveryReceiptStore()
    assert store.get("absent-id") is None
    assert store.by_message_id("absent-msg") == ()


def test_request_store_duplicate_record_is_idempotent() -> None:
    """Recording the same DeliveryRequest twice is a no-op (no error)."""
    from mind_runtime.delivery import InMemoryDeliveryRequestStore

    store = InMemoryDeliveryRequestStore()
    request = _request(request_id=make_request_id(SCOPE, "intent-1", "k1"))
    store.record(request)
    # The same record is a no-op (immutable bytes: same id + same fields).
    store.record(request)
    assert store.get(request.request_id) is not None


def test_request_sync_fields_returns_typed_identity() -> None:
    """DeliveryRequest.sync_fields exposes the durable sync identity."""
    request = _request(request_id=make_request_id(SCOPE, "intent-1", "k1"))
    sync = request.sync_fields()
    assert sync.object_id == request.request_id
    assert sync.origin_runtime_id == request.origin_runtime_id
    assert sync.scope == request.scope
