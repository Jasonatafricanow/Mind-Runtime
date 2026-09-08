"""Delivery plane: durable outbound requests, receipts, and recovery.

This package is split across two slices:

  * **C7A** — typed ``DeliveryRequest`` / ``DeliveryPort`` contract,
    a deterministic in-memory backend, and the durable request /
    receipt stores. The in-memory backend is the test / reference
    carrier; it is NOT production restart authority.
  * **C7B** — real disk-level durability (``SqliteDeliveryBackend``),
    crash / recovery semantics, the lifecycle state machine,
    a pluggable reconciler port, an explicit retry policy, a
    fail-closed durable kill switch, the daemon / restart recovery
    pass, and the four idempotency levels (0-3) defined below.

Idempotency levels (frozen by C7B STEP 7)
----------------------------------------

The C7B code claims: "local orchestration is idempotent and
provider-aware". It does NOT claim: "exactly-once external
delivery" unless a specific provider contract proves it.

  LEVEL 0 — no provider-side authority
    * NoopDeliveryReconciler is pinned by default.
    * UNKNOWN stays UNKNOWN after reconcile.
    * The orchestrator MUST NOT blind-resend.
    * The Sqlite delivery backend is pinned to LEVEL 0 by default.

  LEVEL 1 — provider lookup
    * The reconciler can ask the provider what really happened
      and resolve UNKNOWN to ACCEPTED / REJECTED / FAILED_RETRYABLE
      / NOT_FOUND.
    * No duplicate send is observed: the durable receipt is the
      same logical one.

  LEVEL 2 — provider callback / push delivery
    * Same as LEVEL 1 but the provider can also push the
      ACCEPTED state into our durable store directly.
    * The daemon's reconcile pass is a backstop, not the primary
      path.

  LEVEL 3 — provider explicit idempotency keys
    * Reserved for providers that expose explicit idempotency-key
      APIs (none today; not required for C7B).

Privacy (C7B STEP 8)
--------------------

Recovery / retry / log / trace must NOT carry raw private
expression text. Allowed generic trace fields:

  delivery_id, intent_id, provider, status, attempt,
  reason_codes, provider_receipt_ref (only if non-secret),
  timestamps.

The log sinks the daemon writes to are generic; the payload_bytes
are never logged, never serialised into the reason_codes list, and
never appear in any trace event.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol, runtime_checkable

from mind_runtime.contracts import (
    DeliveryReceipt,
    DeliveryStatus,
    Scope,
    SyncFields,
)
from mind_runtime.contracts.common import (
    require_aware_utc,
    require_non_empty,
    validate_sync_fields,
)


@dataclass(frozen=True, slots=True)
class DeliveryRequest:
    """One durable outbound request handed to the carrier.

    request_id is the idempotency key: re-issuing the same request_id
    is a no-op on the carrier side. message_id is the stable identifier
    the carrier uses to talk about this message (and the same id will
    flow into the eventual DeliveryReceipt.message_id).

    action_type (C7C) is the producer-known intent action (e.g.
    "proactive_message", "send_photo"). The C7C settled-action
    projector is the ONLY consumer that translates this into
    counter writes; the carrier and the rest of the delivery plane
    treat it as opaque metadata.
    """

    request_id: str
    message_id: str
    scope: Scope
    origin_runtime_id: str
    channel: str
    target: str
    action_type: str
    payload_bytes: bytes
    created_at: datetime
    sync: SyncFields

    def __post_init__(self) -> None:
        for field_name in (
            "request_id", "message_id", "origin_runtime_id", "channel",
            "target",
        ):
            require_non_empty(getattr(self, field_name), field_name)
        # C7C-R: action_type is OPTIONAL at construction time. An
        # empty value is the documented sentinel for a legacy
        # unknown action_type (pre-C7C on-disk rows). The settled-
        # action projector (and only it) is the one that fail-closes
        # on this sentinel — no silent default to proactive_message
        # anywhere in the system.
        if not isinstance(self.action_type, str):
            raise ValueError("action_type must be a string")
        if not isinstance(self.payload_bytes, bytes):
            raise ValueError("payload_bytes must be bytes (immutable wire form)")
        if not self.payload_bytes:
            raise ValueError("payload_bytes must not be empty")
        require_aware_utc(self.created_at, "created_at")
        if not isinstance(self.scope, Scope):
            raise ValueError("scope must be a Scope")
        validate_sync_fields(
            self.sync,
            scope=self.scope,
            origin_runtime_id=self.origin_runtime_id,
            object_id=self.request_id,
        )

    def sync_fields(self) -> SyncFields:
        return self.sync


class DeliveryPort(Protocol):
    """One outbound delivery attempt."""

    def deliver(self, request: DeliveryRequest) -> DeliveryReceipt:
        """Hand ``request`` to the carrier and return a typed receipt.

        The port MUST NOT raise; transport failures convert to
        ``DeliveryStatus.UNKNOWN`` receipts. Re-issuing the same
        ``request.request_id`` is a no-op (the carrier must dedup by id).
        """
        ...


@runtime_checkable
class DeliveryRequestStore(Protocol):
    """Append-only durable record of every delivery request issued.

    The same store is what feeds the durable boundary checked by the
    validate suite. A later slice may swap this for sqlite; today the
    only safe consumer is the in-memory implementation below.
    """

    def record(self, request: DeliveryRequest) -> None:
        ...

    def has(self, request_id: str) -> bool:
        ...

    def get(self, request_id: str) -> DeliveryRequest | None:
        ...

    def all(self) -> tuple[DeliveryRequest, ...]:
        ...


@runtime_checkable
class DeliveryReceiptStore(Protocol):
    """Append-only durable record of every delivery receipt observed."""

    def record(self, receipt: DeliveryReceipt) -> None:
        ...

    def get(self, receipt_id: str) -> DeliveryReceipt | None:
        ...

    def by_message_id(self, message_id: str) -> tuple[DeliveryReceipt, ...]:
        ...

    def all(self) -> tuple[DeliveryReceipt, ...]:
        ...


@dataclass
class InMemoryDeliveryRequestStore:
    """Process-local durable store; the C7A reference / test backend.

    The contract is explicit: a new C7A slice may swap to sqlite by
    implementing ``DeliveryRequestStore``; nothing else needs to change.
    This in-memory store is NOT production restart authority; the
    C7B ``SqliteDeliveryBackend`` is the durable plane.
    """

    _records: dict[str, DeliveryRequest] = field(default_factory=dict)

    def record(self, request: DeliveryRequest) -> None:
        existing = self._records.get(request.request_id)
        if existing is not None and existing != request:
            # byte-identical bodies: refuse to enqueue a second form
            # (this is the immutable-bytes guarantee the G5 test pins).
            raise ValueError(
                f"durable request id collision: {request.request_id!r} "
                "exists with different immutable bytes")
        self._records[request.request_id] = request

    def has(self, request_id: str) -> bool:
        return request_id in self._records

    def get(self, request_id: str) -> DeliveryRequest | None:
        return self._records.get(request_id)

    def all(self) -> tuple[DeliveryRequest, ...]:
        return tuple(self._records.values())


@dataclass
class InMemoryDeliveryReceiptStore:
    """Process-local durable store for observed receipts.

    Not production restart authority; the C7B ``SqliteDeliveryBackend``
    is the durable plane.
    """

    _records: dict[str, DeliveryReceipt] = field(default_factory=dict)
    _by_message: dict[str, list[DeliveryReceipt]] = field(default_factory=dict)

    def record(self, receipt: DeliveryReceipt) -> None:
        existing = self._records.get(receipt.receipt_id)
        if existing is not None and existing != receipt:
            raise ValueError(
                f"durable receipt id collision: {receipt.receipt_id!r} "
                "exists with different immutable bytes")
        self._records[receipt.receipt_id] = receipt
        self._by_message.setdefault(receipt.message_id, []).append(receipt)

    def get(self, receipt_id: str) -> DeliveryReceipt | None:
        return self._records.get(receipt_id)

    def by_message_id(self, message_id: str) -> tuple[DeliveryReceipt, ...]:
        return tuple(self._by_message.get(message_id, ()))

    def all(self) -> tuple[DeliveryReceipt, ...]:
        return tuple(self._records.values())


class InMemoryDeliveryBackend:
    """Deterministic fake carrier used by validate / tests.

    Behaviour table (encoded by the flags passed to __init__):
      * default: every deliver() yields SENT, request_id dedup is a no-op;
      * fail_after=N: the first N deliveries yield SENT, the next yield
        UNKNOWN (kill-switch test);
      * duplicate_via_message_id: re-issuing the same message_id with a
        different body is treated as a duplicate and yields SENT with
        the original request's payload (carrier enforces immutability).

    This is NOT production restart authority; the C7B
    ``SqliteDeliveryBackend`` is the durable plane.
    """

    def __init__(
        self,
        *,
        fail_after: int | None = None,
        duplicate_via_message_id: bool = False,
    ) -> None:
        self._seen_request_ids: set[str] = set()
        self._seen_message_ids: dict[str, str] = {}
        self._sent: int = 0
        self._fail_after = fail_after
        self._duplicate_via_message_id = duplicate_via_message_id

    def deliver(self, request: DeliveryRequest) -> DeliveryReceipt:
        # First-seen: keep the request; later calls with the same id are
        # a dedup hit and must NOT generate a new receipt.
        if request.request_id in self._seen_request_ids:
            return _build_receipt(request, DeliveryStatus.SENT)
        self._seen_request_ids.add(request.request_id)
        self._seen_message_ids.setdefault(request.message_id, request.request_id)

        if (self._fail_after is not None
                and self._sent >= self._fail_after):
            return _build_receipt(request, DeliveryStatus.UNKNOWN)

        self._sent += 1
        return _build_receipt(request, DeliveryStatus.SENT)

    @property
    def sent_count(self) -> int:
        return self._sent

    @property
    def seen_request_ids(self) -> frozenset[str]:
        return frozenset(self._seen_request_ids)


def _build_receipt(
    request: DeliveryRequest, status: DeliveryStatus
) -> DeliveryReceipt:
    return DeliveryReceipt(
        receipt_id=f"recpt-{request.request_id}",
        scope=request.scope,
        origin_runtime_id=request.origin_runtime_id,
        message_id=request.message_id,
        delivery_status=status,
        delivered_at=request.created_at if status is DeliveryStatus.SENT else None,
        sync=SyncFields(
            request.scope,
            request.origin_runtime_id,
            f"recpt-{request.request_id}",
            1,
            f"idem-recpt-{request.request_id}",
        ),
    )


def make_request_id(scope: Scope, action_intent_id: str,
                    idempotency_key: str) -> str:
    """Build the durable request_id from the turn's idempotency contract.

    The key contract: same (scope, action_intent_id, idempotency_key) →
    same request_id → carrier-side no-op. Different idempotency_keys →
    independent deliveries. The same key across retries / reconcile
    runs must converge to one durable record.
    """
    if not idempotency_key:
        raise ValueError("idempotency_key must be non-empty")
    return f"deliv-{scope.domain.value}-{action_intent_id}-{idempotency_key}"


def make_message_id(request_id: str) -> str:
    """Stable message id; the carrier uses it across all downstream
    events (sent confirmation, retry, kill switch)."""
    return f"msg-{request_id}"


# --- C7B re-exports ----------------------------------------------------

from mind_runtime.delivery.daemon import (  # noqa: E402
    DaemonOutcome,
    DaemonPass,
)
from mind_runtime.delivery.kill_switch import (  # noqa: E402
    DeliveryKillSwitch,
    KillSwitchDecision,
    KillSwitchLevel,
    open_kill_switch,
)
from mind_runtime.delivery.persistence import (  # noqa: E402
    DeliveryBackend,
    DurableAttemptRow,
    DurableReceiptRow,
    DurableRequestRow,
    SqliteDeliveryBackend,
)
from mind_runtime.delivery.reconcile import (  # noqa: E402
    DeliveryReconciler,
    NoopDeliveryReconciler,
    ReconciliationResult,
    ResolvedAccept,
    ResolvedNotFound,
    ResolvedReject,
    ResolvedRetryable,
    ResolvedUnknown,
)
from mind_runtime.delivery.retry import (  # noqa: E402
    RetryDecision,
    RetryDecisionKind,
    compute_retry_decision,
)
from mind_runtime.delivery.state import (  # noqa: E402
    DeliveryLifecycleState,
    is_terminal,
    validate_transition,
)

__all__ = [
    # C7A surface
    "DeliveryPort",
    "DeliveryReceipt",
    "DeliveryReceiptStore",
    "DeliveryRequest",
    "DeliveryRequestStore",
    "DeliveryStatus",
    "InMemoryDeliveryBackend",
    "InMemoryDeliveryReceiptStore",
    "InMemoryDeliveryRequestStore",
    "make_message_id",
    "make_request_id",
    # C7B additions
    "DeliveryBackend",
    "DeliveryKillSwitch",
    "DeliveryLifecycleState",
    "DeliveryReconciler",
    "DaemonOutcome",
    "DaemonPass",
    "DurableAttemptRow",
    "DurableReceiptRow",
    "DurableRequestRow",
    "KillSwitchDecision",
    "KillSwitchLevel",
    "NoopDeliveryReconciler",
    "ReconciliationResult",
    "ResolvedAccept",
    "ResolvedNotFound",
    "ResolvedReject",
    "ResolvedRetryable",
    "ResolvedUnknown",
    "RetryDecision",
    "RetryDecisionKind",
    "SqliteDeliveryBackend",
    "compute_retry_decision",
    "is_terminal",
    "open_kill_switch",
    "validate_transition",
]
