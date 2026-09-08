"""C7B STEP 1 — delivery state machine tests.

The state machine is a pure function: ``validate_transition(from, to)``.
These tests pin every legal / illegal transition, including the
frozen rules:

  * PENDING -> IN_FLIGHT only.
  * IN_FLIGHT -> ACCEPTED | REJECTED | FAILED_RETRYABLE | UNKNOWN.
  * UNKNOWN -> ACCEPTED | REJECTED | FAILED_RETRYABLE | PENDING.
  * FAILED_RETRYABLE -> PENDING | REJECTED.
  * ACCEPTED is monotonic (no transitions out).
  * REJECTED is terminal-by-default.
"""

from __future__ import annotations

import pytest

from mind_runtime.delivery import (
    DeliveryLifecycleState,
    is_terminal,
    validate_transition,
)


def test_same_state_is_idempotent_noop() -> None:
    """A self-transition is allowed (no-op write)."""
    for state in DeliveryLifecycleState:
        validate_transition(state, state)


def test_pending_only_goes_to_in_flight_or_failed_retryable() -> None:
    """PENDING -> IN_FLIGHT or PENDING -> FAILED_RETRYABLE or
    PENDING -> UNKNOWN are the only three legal forward moves
    (a self-transition is a no-op).
    """

    for to_state in DeliveryLifecycleState:
        if to_state is DeliveryLifecycleState.PENDING:
            continue  # self-transition is a no-op
        if to_state in (
            DeliveryLifecycleState.IN_FLIGHT,
            DeliveryLifecycleState.FAILED_RETRYABLE,
            DeliveryLifecycleState.UNKNOWN,
        ):
            validate_transition(
                DeliveryLifecycleState.PENDING, to_state,
            )
        else:
            with pytest.raises(ValueError, match="pending"):
                validate_transition(
                    DeliveryLifecycleState.PENDING, to_state,
                )


def test_in_flight_can_resolve_to_any_outcome() -> None:
    """IN_FLIGHT can move to ACCEPTED, REJECTED, FAILED_RETRYABLE,
    or UNKNOWN. Not back to PENDING.
    """

    for to_state in (
        DeliveryLifecycleState.ACCEPTED,
        DeliveryLifecycleState.REJECTED,
        DeliveryLifecycleState.FAILED_RETRYABLE,
        DeliveryLifecycleState.UNKNOWN,
    ):
        validate_transition(DeliveryLifecycleState.IN_FLIGHT, to_state)
    with pytest.raises(ValueError, match="in_flight"):
        validate_transition(
            DeliveryLifecycleState.IN_FLIGHT, DeliveryLifecycleState.PENDING,
        )


def test_accepted_is_monotonic_terminal() -> None:
    """ACCEPTED cannot move out under any rule. This is the
    monotonic-truth invariant the kill switch must respect.
    """

    for to_state in DeliveryLifecycleState:
        if to_state is DeliveryLifecycleState.ACCEPTED:
            continue
        with pytest.raises(ValueError, match="accepted"):
            validate_transition(DeliveryLifecycleState.ACCEPTED, to_state)


def test_rejected_is_terminal_by_default() -> None:
    """REJECTED is terminal-by-default: no automatic transitions."""

    for to_state in DeliveryLifecycleState:
        if to_state is DeliveryLifecycleState.REJECTED:
            continue
        with pytest.raises(ValueError, match="rejected"):
            validate_transition(DeliveryLifecycleState.REJECTED, to_state)


def test_failed_retryable_can_re_attempt() -> None:
    """FAILED_RETRYABLE -> PENDING (re-attempt) or REJECTED (give up)."""

    for to_state in (
        DeliveryLifecycleState.PENDING,
        DeliveryLifecycleState.REJECTED,
    ):
        validate_transition(
            DeliveryLifecycleState.FAILED_RETRYABLE, to_state,
        )
    with pytest.raises(ValueError, match="failed_retryable"):
        validate_transition(
            DeliveryLifecycleState.FAILED_RETRYABLE,
            DeliveryLifecycleState.ACCEPTED,
        )
    with pytest.raises(ValueError, match="failed_retryable"):
        validate_transition(
            DeliveryLifecycleState.FAILED_RETRYABLE,
            DeliveryLifecycleState.IN_FLIGHT,
        )


def test_unknown_can_be_resolved_or_rearmed() -> None:
    """UNKNOWN is the catch-all: can resolve to ACCEPTED / REJECTED
    / FAILED_RETRYABLE, or re-arm to PENDING. Cannot go back to
    IN_FLIGHT directly (must go through PENDING).
    """

    for to_state in (
        DeliveryLifecycleState.ACCEPTED,
        DeliveryLifecycleState.REJECTED,
        DeliveryLifecycleState.FAILED_RETRYABLE,
        DeliveryLifecycleState.PENDING,
    ):
        validate_transition(DeliveryLifecycleState.UNKNOWN, to_state)
    with pytest.raises(ValueError, match="unknown"):
        validate_transition(
            DeliveryLifecycleState.UNKNOWN, DeliveryLifecycleState.IN_FLIGHT,
        )


def test_is_terminal_classification() -> None:
    """is_terminal matches the monotonic / terminal-by-default rules."""

    assert is_terminal(DeliveryLifecycleState.ACCEPTED) is True
    assert is_terminal(DeliveryLifecycleState.REJECTED) is True
    assert is_terminal(DeliveryLifecycleState.UNKNOWN) is False
    assert is_terminal(DeliveryLifecycleState.FAILED_RETRYABLE) is False
    assert is_terminal(DeliveryLifecycleState.PENDING) is False
    assert is_terminal(DeliveryLifecycleState.IN_FLIGHT) is False


def test_validate_transition_rejects_bad_inputs() -> None:
    """The validator refuses non-enum inputs (defense in depth)."""

    with pytest.raises(ValueError, match="from_state"):
        validate_transition("pending", DeliveryLifecycleState.IN_FLIGHT)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="to_state"):
        validate_transition(DeliveryLifecycleState.PENDING, "in_flight")  # type: ignore[arg-type]
