"""Reconciliation port for resolving UNKNOWN deliveries (C7B STEP 3).

A separate, pluggable port for "ask the provider what really
happened" so the orchestrator can resolve UNKNOWN rows without
blindly resending. The reconciler is the only authority allowed to
move a request from UNKNOWN to ACCEPTED / REJECTED / FAILED_RETRYABLE.

LEVEL 0 (NoopDeliveryReconciler): always returns
``ResolvedUnknown``. Even after reconcile, the request stays
UNKNOWN. The orchestrator MUST NOT blind-resend. This is the
default pin for the Sqlite delivery backend.

LEVEL 1+ (scripted stubs, provider-backed reconcilers): can
resolve UNKNOWN to ACCEPTED, FAILED_RETRYABLE, REJECTED, or
NOT_FOUND. These are only used in tests and in production with a
provider that exposes an authoritative lookup API.

LEVEL 3 (idempotency-key providers): reserved for providers with
explicit idempotency keys. None today; not required for C7B.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from mind_runtime.delivery import DeliveryRequest


@dataclass(frozen=True, slots=True)
class ResolvedAccept:
    """The provider has confirmed: this message was delivered."""

    provider_receipt_ref: str
    provider_message_ref: str | None


@dataclass(frozen=True, slots=True)
class ResolvedRetryable:
    """The provider has confirmed: this attempt failed transiently."""

    reason: str


@dataclass(frozen=True, slots=True)
class ResolvedReject:
    """The provider has confirmed: this attempt is terminal-rejected."""

    reason: str


@dataclass(frozen=True, slots=True)
class ResolvedNotFound:
    """The provider has confirmed: it never saw this request."""

    reason: str


@dataclass(frozen=True, slots=True)
class ResolvedUnknown:
    """Even reconcile cannot tell. UNKNOWN stays UNKNOWN."""

    reason: str


ReconciliationResult = (
    ResolvedAccept
    | ResolvedRetryable
    | ResolvedReject
    | ResolvedNotFound
    | ResolvedUnknown
)


@runtime_checkable
class DeliveryReconciler(Protocol):
    """Pluggable port for resolving UNKNOWN delivery rows."""

    def reconcile(self, request: DeliveryRequest) -> ReconciliationResult:
        """Ask the provider-side authority what really happened.

        Implementations MUST NOT raise; transport failures convert
        to ``ResolvedUnknown``. Calling ``reconcile`` for a request
        the provider never saw MUST return ``ResolvedNotFound``,
        not ``ResolvedAccept`` (the daemon must not fabricate a
        receipt for an absent message).
        """
        ...


class NoopDeliveryReconciler:
    """LEVEL 0 reconciler: always returns ``ResolvedUnknown``.

    Pinned as the default for the Sqlite delivery backend. The
    orchestrator MUST NOT resend on a ``ResolvedUnknown`` result;
    UNKNOWN stays UNKNOWN until an operator action or a higher-level
    reconciler is plugged in.
    """

    reason: str = "noop_reconciler_level_0"

    def reconcile(self, request: DeliveryRequest) -> ResolvedUnknown:
        return ResolvedUnknown(reason=self.reason)
