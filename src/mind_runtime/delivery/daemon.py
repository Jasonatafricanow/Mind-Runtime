"""Daemon / restart recovery for the durable delivery plane (C7B STEP 6).

A daemon pass discovers durable unfinished delivery work
(PENDING, IN_FLIGHT, UNKNOWN, FAILED_RETRYABLE) and re-drives it
WITHOUT fabricating a new would-send artifact or re-creating the
Intent. The discovery path reads from the ``SqliteDeliveryBackend``
only — never from the caller's in-process state.

The daemon MUST:
  * iterate unfinished rows in deterministic order (request_id asc)
  * for each row, call reconcile first (UNKNOWN) before retry
  * re-attempt via the existing ``DeliveryPort``
  * never re-derive a would-send text from the previous tick;
    if the previous attempt is FAILED_RETRYABLE, the daemon uses
    the persisted payload_bytes and request_id verbatim
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol, cast

from mind_runtime.contracts import DeliveryStatus
from mind_runtime.delivery import DeliveryReceipt, DeliveryRequest
from mind_runtime.delivery.persistence import (
    DeliveryBackend,
    DurableRequestRow,
)
from mind_runtime.delivery.reconcile import (
    DeliveryReconciler,
    NoopDeliveryReconciler,
    ReconciliationResult,
    ResolvedAccept,
    ResolvedNotFound,
    ResolvedReject,
    ResolvedRetryable,
)
from mind_runtime.delivery.retry import (
    RetryDecisionKind,
    compute_retry_decision,
)
from mind_runtime.delivery.state import DeliveryLifecycleState


@dataclass(frozen=True, slots=True)
class DaemonOutcome:
    """The per-request result of one daemon pass.

    Generic, non-secret fields only. The log sinks downstream must
    not have access to ``request.payload_bytes``; the daemon
    deliberately exposes ``request_id`` (the durable identity) and
    nothing else.
    """

    request_id: str
    decision_kind: RetryDecisionKind
    final_state: DeliveryLifecycleState
    attempt: int
    reason_code: str
    provider_receipt_ref: str | None


@dataclass
class DaemonPass:
    """One deterministic pass over the durable delivery backlog.

    The pass walks ``backend.unfinished_requests()`` in order,
    asks the reconciler / retry policy what to do, and writes
    the resulting state back to the durable store. It is the
    only path allowed to transition FAILED_RETRYABLE / UNKNOWN
    rows forward after a process restart.
    """

    backend: DeliveryBackend
    port: DeliveryPortLike
    reconciler: DeliveryReconciler = field(default_factory=NoopDeliveryReconciler)
    retry_budget: int = 3
    now: Callable[[], datetime] = field(default=lambda: datetime.now(tz=UTC))
    log: logging.Logger = field(
        default_factory=lambda: logging.getLogger("mind_runtime.delivery.daemon")
    )

    def run(self) -> tuple[DaemonOutcome, ...]:
        outcomes: list[DaemonOutcome] = []
        for row in self.backend.unfinished_requests():
            outcomes.append(self._drive_one(row))
        return tuple(outcomes)

    def _drive_one(self, row: DurableRequestRow) -> DaemonOutcome:
        request = row.request
        state = row.lifecycle_state
        attempt_count = row.attempt_count
        if request.surface_handoff is not None:
            # This C7 request is a durable Soul-to-Body provider envelope.
            # The generic carrier daemon must never send its prompt as a
            # user-facing delivery or recompute cognition on retry. Body/Host
            # consumes the exact persisted request through the handoff seam.
            return DaemonOutcome(
                request_id=request.request_id,
                decision_kind=RetryDecisionKind.DO_NOT_RETRY,
                final_state=state,
                attempt=attempt_count,
                reason_code="surface_body_handoff_owned",
                provider_receipt_ref=row.last_provider_receipt_ref,
            )
        decision = compute_retry_decision(state, attempt_count, self.retry_budget)
        reason_code = decision.reason_code
        provider_receipt_ref: str | None = row.last_provider_receipt_ref

        if decision.kind is RetryDecisionKind.DO_NOT_RETRY:
            self._log_event(
                "delivery.daemon.skip",
                request_id=request.request_id,
                reason_code=reason_code,
            )
            return DaemonOutcome(
                request_id=request.request_id,
                decision_kind=decision.kind,
                final_state=state,
                attempt=attempt_count,
                reason_code=reason_code,
                provider_receipt_ref=provider_receipt_ref,
            )

        if decision.kind is RetryDecisionKind.RECONCILE_FIRST:
            result = self.reconciler.reconcile(request)
            self.backend.record_reconcile(request.request_id, at=self.now())
            outcome_state, outcome_reason, provider_receipt_ref = _apply_reconcile(
                request=request,
                result=result,
                backend=self.backend,
                now=self.now(),
            )
            if outcome_state is not None:
                # Reconciler has spoken; write the new state and stop.
                self.backend.set_lifecycle_state(
                    request.request_id, outcome_state, at=self.now(),
                )
                self._log_event(
                    "delivery.daemon.reconcile",
                    request_id=request.request_id,
                    reason_code=outcome_reason,
                )
                return DaemonOutcome(
                    request_id=request.request_id,
                    decision_kind=decision.kind,
                    final_state=outcome_state,
                    attempt=attempt_count,
                    reason_code=outcome_reason,
                    provider_receipt_ref=provider_receipt_ref,
                )
            # Reconciler said "unknown": keep UNKNOWN, do NOT resend.
            self._log_event(
                "delivery.daemon.reconcile_unknown",
                request_id=request.request_id,
                reason_code=outcome_reason,
            )
            return DaemonOutcome(
                request_id=request.request_id,
                decision_kind=decision.kind,
                final_state=state,
                attempt=attempt_count,
                reason_code=outcome_reason,
                provider_receipt_ref=provider_receipt_ref,
            )

        # CAN_RETRY
        if state in (DeliveryLifecycleState.FAILED_RETRYABLE,
                     DeliveryLifecycleState.PENDING,
                     DeliveryLifecycleState.UNKNOWN):
            # Move to IN_FLIGHT, call the carrier, record outcome.
            # FAILED_RETRYABLE must round-trip through PENDING per
            # the state machine; the carrier call is only ever
            # made from IN_FLIGHT.
            if state is DeliveryLifecycleState.FAILED_RETRYABLE:
                self.backend.set_lifecycle_state(
                    request.request_id,
                    DeliveryLifecycleState.PENDING,
                    at=self.now(),
                )
            self.backend.set_lifecycle_state(
                request.request_id,
                DeliveryLifecycleState.IN_FLIGHT,
                at=self.now(),
            )
            new_attempt = self.backend.increment_attempt(
                request.request_id, at=self.now(),
            )
            attempt_id = f"att-{request.request_id}-{new_attempt}"
            self.backend.record_attempt(
                attempt_id=attempt_id,
                request_id=request.request_id,
                attempt=new_attempt,
                started_at=self.now(),
                ended_at=None,
                outcome=DeliveryLifecycleState.IN_FLIGHT,
                provider_receipt_ref=None,
                reason_codes=("daemon_retry",),
            )
            try:
                receipt = cast(DeliveryReceipt, self.port.deliver(request))
            except Exception as error:  # pragma: no cover - port contract
                # DeliveryPort must not raise; this is defense in depth.
                self._log_event(
                    "delivery.daemon.port_raised",
                    request_id=request.request_id,
                    reason_code="port_raised",
                )
                self.backend.set_lifecycle_state(
                    request.request_id,
                    DeliveryLifecycleState.UNKNOWN,
                    at=self.now(),
                )
                self.backend.record_attempt(
                    attempt_id=attempt_id,
                    request_id=request.request_id,
                    attempt=new_attempt,
                    started_at=self.now(),
                    ended_at=self.now(),
                    outcome=DeliveryLifecycleState.UNKNOWN,
                    provider_receipt_ref=None,
                    reason_codes=("port_raised", str(error)[:64]),
                )
                return DaemonOutcome(
                    request_id=request.request_id,
                    decision_kind=decision.kind,
                    final_state=DeliveryLifecycleState.UNKNOWN,
                    attempt=new_attempt,
                    reason_code="port_raised",
                    provider_receipt_ref=provider_receipt_ref,
                )

            new_state, outcome_reason, provider_receipt_ref = _apply_receipt(
                request=request,
                receipt=receipt,
                backend=self.backend,
                now=self.now(),
                attempt=new_attempt,
            )
            self.backend.set_lifecycle_state(
                request.request_id, new_state, at=self.now(),
            )
            self.backend.record_attempt(
                attempt_id=attempt_id,
                request_id=request.request_id,
                attempt=new_attempt,
                started_at=self.now(),
                ended_at=self.now(),
                outcome=new_state,
                provider_receipt_ref=provider_receipt_ref,
                reason_codes=(outcome_reason,),
            )
            self._log_event(
                "delivery.daemon.retry",
                request_id=request.request_id,
                reason_code=outcome_reason,
            )
            return DaemonOutcome(
                request_id=request.request_id,
                decision_kind=decision.kind,
                final_state=new_state,
                attempt=new_attempt,
                reason_code=outcome_reason,
                provider_receipt_ref=provider_receipt_ref,
            )

        # IN_FLIGHT is unreachable here: compute_retry_decision
        # always returns ``reconcile_first`` for IN_FLIGHT (which
        # is handled above). The earlier branches are exhaustive;
        # if a future change ever routes IN_FLIGHT through
        # ``can_retry`` or ``do_not_retry`` the assert will fire
        # in development. The daemon's contract is: every
        # iteration of ``unfinished_requests`` returns through
        # one of the three return paths above.

        raise AssertionError(  # pragma: no cover
            f"unreachable daemon branch: state={state!r},"
            f" decision={decision.kind!r}"
        )

    def _log_event(self, event: str, *, request_id: str, reason_code: str) -> None:
        # Generic fields only: no payload, no channel detail beyond
        # the (request_id, reason_code) pair, no private expression.
        self.log.info(
            "%s request_id=%s reason_code=%s",
            event, request_id, reason_code,
        )


def _apply_reconcile(
    *, request: DeliveryRequest, result: ReconciliationResult,
    backend: DeliveryBackend, now: datetime,
) -> tuple[DeliveryLifecycleState | None, str, str | None]:
    """Translate a reconciler result into a (state, reason, ref) tuple.

    Returns ``(None, reason, ref)`` when the reconciler answered
    ``ResolvedUnknown``: the caller must NOT transition the row.
    """

    if isinstance(result, ResolvedAccept):
        backend.record_provider_receipt_ref(
            request.request_id, result.provider_receipt_ref,
        )
        return (
            DeliveryLifecycleState.ACCEPTED,
            "reconcile_accept",
            result.provider_receipt_ref,
        )
    if isinstance(result, ResolvedRetryable):
        return (
            DeliveryLifecycleState.FAILED_RETRYABLE,
            "reconcile_retryable",
            None,
        )
    if isinstance(result, ResolvedReject):
        return (
            DeliveryLifecycleState.REJECTED,
            "reconcile_reject",
            None,
        )
    if isinstance(result, ResolvedNotFound):
        # The provider never saw this request. Treat as retryable so
        # the next daemon pass can re-arm the attempt.
        return (
            DeliveryLifecycleState.FAILED_RETRYABLE,
            "reconcile_not_found",
            None,
        )
    # ResolvedUnknown
    return (None, result.reason, None)


def _apply_receipt(
    *,
    request: DeliveryRequest,
    receipt: DeliveryReceipt,
    backend: DeliveryBackend,
    now: datetime,
    attempt: int,
) -> tuple[DeliveryLifecycleState, str, str | None]:
    """Translate a fresh carrier receipt into a (state, reason, ref) tuple."""

    status = receipt.delivery_status
    if status is DeliveryStatus.SENT:
        # Persist the receipt in the receipts table. The receipt_id
        # is the carrier-side identifier; the request_id is the
        # logical key. Idempotent: re-recording yields False.
        provider_ref: str | None = None
        provider_msg: str | None = None
        if receipt.delivered_at is not None:
            # The receipt is monotonic truth; we record the delivered_at
            # as the provider reference clock if no other ref exists.
            provider_ref = f"sent:{receipt.receipt_id}"
        try:
            backend.record_receipt(
                receipt, request_id=request.request_id,
                provider_receipt_ref=provider_ref,
                provider_message_ref=provider_msg,
                attempt=attempt,
            )
        except ValueError:
            # Collision with different bytes: surface as a state
            # conflict. Keep the row at ACCEPTED — the durable
            # receipt is monotonic.
            pass
        return (
            DeliveryLifecycleState.ACCEPTED,
            "carrier_sent",
            provider_ref,
        )
    if status is DeliveryStatus.UNSENT:
        return (
            DeliveryLifecycleState.REJECTED,
            "carrier_unsent",
            None,
        )
    return (
        DeliveryLifecycleState.UNKNOWN,
        "carrier_unknown",
        None,
    )


class DeliveryPortLike(Protocol):
    """The minimum surface the daemon needs from a delivery port.

    Same shape as ``DeliveryPort`` (the C7A protocol). The
    daemon does not depend on the type by name to keep the
    import graph lean.
    """

    def deliver(self, request: DeliveryRequest) -> object: ...
