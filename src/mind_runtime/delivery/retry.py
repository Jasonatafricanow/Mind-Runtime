"""Retry policy for durable delivery recovery (C7B STEP 4).

The retry policy is a pure function of three things:
  * the durable lifecycle state,
  * the attempt count already spent on this request,
  * the explicit retry budget configured for this turn / request.

The function NEVER infers intent from the carrier's transient shape.
The only escape hatch for "I don't know" (UNKNOWN) is the
reconciler, not blind retry.

C7B STEP 4 contracts (frozen):

  FAILED_RETRYABLE -> can_retry (until retry_budget exhausted)
  UNKNOWN         -> reconcile_first (never blind retry)
  REJECTED        -> do_not_retry (terminal by default)
  ACCEPTED        -> do_not_retry

The retry attempt count lives in the durable delivery_attempts
table; it is not part of the logical delivery_id. Two retries
share the same request_id and only differ in attempt.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from mind_runtime.delivery.state import DeliveryLifecycleState


class RetryDecisionKind(StrEnum):
    """The shape of the answer the retry policy returns."""

    CAN_RETRY = "can_retry"
    DO_NOT_RETRY = "do_not_retry"
    RECONCILE_FIRST = "reconcile_first"


@dataclass(frozen=True, slots=True)
class RetryDecision:
    """A pure-data answer to "what should we do next?".

    ``reason_code`` is a generic, non-secret string used in logs
    and trace events. It MUST NOT contain the payload or any
    private expression text.
    """

    kind: RetryDecisionKind
    reason_code: str

    @property
    def can_retry(self) -> bool:
        return self.kind is RetryDecisionKind.CAN_RETRY

    @property
    def do_not_retry(self) -> bool:
        return self.kind is RetryDecisionKind.DO_NOT_RETRY

    @property
    def reconcile_first(self) -> bool:
        return self.kind is RetryDecisionKind.RECONCILE_FIRST


def compute_retry_decision(
    state: DeliveryLifecycleState,
    attempt_count: int,
    retry_budget: int,
) -> RetryDecision:
    """Compute the next-step decision for a durable delivery request.

    ``attempt_count`` is the number of carrier calls already recorded
    in ``delivery_attempts`` for this request. ``retry_budget`` is the
    configured ceiling; when ``attempt_count >= retry_budget`` even a
    ``FAILED_RETRYABLE`` row must stop retrying.

    Returns a ``RetryDecision``. Raises ``ValueError`` for a state
    that the lifecycle does not define (defense in depth — callers
    should not be passing arbitrary strings).
    """

    if not isinstance(state, DeliveryLifecycleState):
        raise ValueError(f"state must be a DeliveryLifecycleState: {state!r}")
    if isinstance(attempt_count, bool) or attempt_count < 0:
        raise ValueError("attempt_count must be a non-negative integer")
    if isinstance(retry_budget, bool) or retry_budget < 0:
        raise ValueError("retry_budget must be a non-negative integer")

    if state is DeliveryLifecycleState.ACCEPTED:
        return RetryDecision(
            kind=RetryDecisionKind.DO_NOT_RETRY,
            reason_code="accepted_terminal",
        )
    if state is DeliveryLifecycleState.REJECTED:
        return RetryDecision(
            kind=RetryDecisionKind.DO_NOT_RETRY,
            reason_code="rejected_terminal",
        )
    if state is DeliveryLifecycleState.PENDING:
        # Fresh request that hasn't been started yet — eligible.
        if attempt_count >= retry_budget:
            return RetryDecision(
                kind=RetryDecisionKind.DO_NOT_RETRY,
                reason_code="budget_exhausted",
            )
        return RetryDecision(
            kind=RetryDecisionKind.CAN_RETRY,
            reason_code="fresh_request",
        )
    if state is DeliveryLifecycleState.FAILED_RETRYABLE:
        if attempt_count >= retry_budget:
            return RetryDecision(
                kind=RetryDecisionKind.DO_NOT_RETRY,
                reason_code="budget_exhausted",
            )
        return RetryDecision(
            kind=RetryDecisionKind.CAN_RETRY,
            reason_code="transient_failure",
        )
    if state is DeliveryLifecycleState.IN_FLIGHT:
        # IN_FLIGHT is owned by the live attempt; the daemon should
        # not be making a retry decision while the carrier call is
        # still outstanding. Return reconcile_first so callers fall
        # through to the reconciler.
        return RetryDecision(
            kind=RetryDecisionKind.RECONCILE_FIRST,
            reason_code="in_flight_owner_is_live",
        )
    # UNKNOWN
    return RetryDecision(
        kind=RetryDecisionKind.RECONCILE_FIRST,
        reason_code="outcome_unknown",
    )
