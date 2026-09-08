"""C7B STEP 4 — retry policy tests.

The retry policy is a pure function. The tests pin the four
frozen rules (FAILED_RETRYABLE / UNKNOWN / REJECTED / ACCEPTED)
and the budget ceiling.
"""

from __future__ import annotations

import pytest

from mind_runtime.delivery import (
    DeliveryLifecycleState,
    RetryDecisionKind,
    compute_retry_decision,
)


def test_failed_retryable_under_budget_can_retry() -> None:
    """FAILED_RETRYABLE + attempt < budget -> can_retry."""

    decision = compute_retry_decision(
        DeliveryLifecycleState.FAILED_RETRYABLE, 1, 3,
    )
    assert decision.kind is RetryDecisionKind.CAN_RETRY
    assert decision.reason_code == "transient_failure"


def test_failed_retryable_at_budget_does_not_retry() -> None:
    """FAILED_RETRYABLE + attempt >= budget -> do_not_retry."""

    decision = compute_retry_decision(
        DeliveryLifecycleState.FAILED_RETRYABLE, 3, 3,
    )
    assert decision.kind is RetryDecisionKind.DO_NOT_RETRY
    assert decision.reason_code == "budget_exhausted"


def test_unknown_always_reconciles_first() -> None:
    """UNKNOWN -> reconcile_first, even with budget remaining.
    Never blind retry.
    """

    decision = compute_retry_decision(
        DeliveryLifecycleState.UNKNOWN, 0, 3,
    )
    assert decision.kind is RetryDecisionKind.RECONCILE_FIRST
    assert decision.reason_code == "outcome_unknown"

    # And even with attempts.
    decision = compute_retry_decision(
        DeliveryLifecycleState.UNKNOWN, 2, 3,
    )
    assert decision.kind is RetryDecisionKind.RECONCILE_FIRST


def test_rejected_never_retries() -> None:
    """REJECTED is terminal-by-default."""

    decision = compute_retry_decision(
        DeliveryLifecycleState.REJECTED, 0, 3,
    )
    assert decision.kind is RetryDecisionKind.DO_NOT_RETRY
    assert decision.reason_code == "rejected_terminal"


def test_accepted_never_retries() -> None:
    """ACCEPTED is monotonic truth; no automatic retry."""

    decision = compute_retry_decision(
        DeliveryLifecycleState.ACCEPTED, 0, 3,
    )
    assert decision.kind is RetryDecisionKind.DO_NOT_RETRY
    assert decision.reason_code == "accepted_terminal"


def test_in_flight_owner_is_live() -> None:
    """IN_FLIGHT is owned by the live attempt; the daemon must
    not make a retry decision. The policy returns reconcile_first
    so callers fall through to the reconciler.
    """

    decision = compute_retry_decision(
        DeliveryLifecycleState.IN_FLIGHT, 0, 3,
    )
    assert decision.kind is RetryDecisionKind.RECONCILE_FIRST
    assert decision.reason_code == "in_flight_owner_is_live"


def test_pending_fresh_request_can_retry() -> None:
    """A fresh PENDING request can_retry with reason 'fresh_request'."""

    decision = compute_retry_decision(
        DeliveryLifecycleState.PENDING, 0, 3,
    )
    assert decision.kind is RetryDecisionKind.CAN_RETRY
    assert decision.reason_code == "fresh_request"


def test_pending_at_budget_does_not_retry() -> None:
    """A PENDING request with attempts >= budget cannot retry."""

    decision = compute_retry_decision(
        DeliveryLifecycleState.PENDING, 5, 3,
    )
    assert decision.kind is RetryDecisionKind.DO_NOT_RETRY
    assert decision.reason_code == "budget_exhausted"


def test_compute_retry_decision_rejects_bad_state() -> None:
    """Defense in depth: bad state inputs raise ValueError."""

    with pytest.raises(ValueError, match="state must be a DeliveryLifecycleState"):
        compute_retry_decision("pending", 0, 3)  # type: ignore[arg-type]


def test_compute_retry_decision_rejects_negative_attempt() -> None:
    """Negative or bool attempt counts are invalid."""

    with pytest.raises(ValueError, match="attempt_count"):
        compute_retry_decision(
            DeliveryLifecycleState.FAILED_RETRYABLE, -1, 3,
        )
    with pytest.raises(ValueError, match="attempt_count"):
        compute_retry_decision(
            DeliveryLifecycleState.FAILED_RETRYABLE, True, 3,
        )


def test_compute_retry_decision_rejects_negative_budget() -> None:
    """Negative or bool budgets are invalid."""

    with pytest.raises(ValueError, match="retry_budget"):
        compute_retry_decision(
            DeliveryLifecycleState.FAILED_RETRYABLE, 0, -1,
        )
    with pytest.raises(ValueError, match="retry_budget"):
        compute_retry_decision(
            DeliveryLifecycleState.FAILED_RETRYABLE, 0, True,
        )
