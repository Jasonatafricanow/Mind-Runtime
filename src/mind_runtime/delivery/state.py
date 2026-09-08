"""Delivery lifecycle state machine (C7B).

The C7A delivery plane already defines ``DeliveryStatus`` for the
carrier-side receipt (SENT / UNSENT / UNKNOWN). C7B adds a separate
durable lifecycle state used by the orchestrator to track the
request from persist through carrier call through reconcile, and to
decide what to do after a crash.

The two enums are intentionally distinct:
  * ``DeliveryStatus`` answers "what did the carrier tell us about
    this message?". It is a property of one ``DeliveryReceipt``.
  * ``DeliveryLifecycleState`` answers "where is this request in the
    durable recovery pipeline?". It is a property of one persisted
    ``DeliveryRequest``.

Frozen by C7B STEP 1:

  PENDING             initial; request persisted, no carrier call yet
  IN_FLIGHT           carrier invocation begun
  ACCEPTED            provider returned success; monotonic truth
  REJECTED            provider returned a terminal reject
  FAILED_RETRYABLE    transient failure; eligible for retry
  UNKNOWN             outcome not yet known; requires reconcile

Definitions:
  * UNKNOWN != FAILED_RETRYABLE: UNKNOWN means "I don't know yet";
    FAILED_RETRYABLE means "I know, and you can try again".
  * REJECTED != FAILED_RETRYABLE: REJECTED is terminal-by-default.
  * ACCEPTED is monotonic: a row already in ACCEPTED cannot move
    out (kill switch OFF is NOT allowed to rewrite history).
  * provider_receipt_id is immutable once recorded; re-recording
    the same receipt_id with different bytes is fail-closed.
"""

from __future__ import annotations

from enum import StrEnum


class DeliveryLifecycleState(StrEnum):
    """Durable recovery state of one ``DeliveryRequest``.

    This is distinct from ``DeliveryStatus``: a single request can be
    in ``IN_FLIGHT`` while its most recent carrier receipt is
    ``UNKNOWN``. The lifecycle state is the orchestrator's source of
    truth for what to do next.
    """

    PENDING = "pending"
    IN_FLIGHT = "in_flight"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    FAILED_RETRYABLE = "failed_retryable"
    UNKNOWN = "unknown"


# Allowed transitions. Keep this table as a single source of truth
# for the state machine. The rules below are frozen by C7B STEP 1:
#
#   * PENDING -> IN_FLIGHT only (no skip to ACCEPTED); UNKNOWN is
#     allowed because the orchestrator can mark a fresh request
#     unknown before any carrier call (e.g. on early crash
#     detection or operator action).
#   * IN_FLIGHT -> ACCEPTED | REJECTED | FAILED_RETRYABLE | UNKNOWN.
#   * UNKNOWN -> ACCEPTED | REJECTED | FAILED_RETRYABLE | PENDING
#     (PENDING means "reconcile gave up, restart the attempt").
#   * FAILED_RETRYABLE -> PENDING (re-attempt) | REJECTED (give up).
#   * REJECTED is terminal-by-default: only the operator can reset.
#   * ACCEPTED is monotonic: a row in ACCEPTED cannot move out.
#
# Note: UNKNOWN -> PENDING is permitted so the daemon can re-arm the
# attempt after reconcile reports "not found, but recoverable"; the
# carrier call has not yet succeeded so the monotonicity rule is not
# violated.

_ALLOWED_TRANSITIONS: dict[DeliveryLifecycleState, frozenset[DeliveryLifecycleState]] = {
    DeliveryLifecycleState.PENDING: frozenset({
        DeliveryLifecycleState.IN_FLIGHT,
        DeliveryLifecycleState.FAILED_RETRYABLE,
        DeliveryLifecycleState.UNKNOWN,
    }),
    DeliveryLifecycleState.IN_FLIGHT: frozenset({
        DeliveryLifecycleState.ACCEPTED,
        DeliveryLifecycleState.REJECTED,
        DeliveryLifecycleState.FAILED_RETRYABLE,
        DeliveryLifecycleState.UNKNOWN,
    }),
    DeliveryLifecycleState.ACCEPTED: frozenset(),  # monotonic: terminal
    DeliveryLifecycleState.REJECTED: frozenset(),  # terminal-by-default
    DeliveryLifecycleState.FAILED_RETRYABLE: frozenset({
        DeliveryLifecycleState.PENDING,
        DeliveryLifecycleState.REJECTED,
    }),
    DeliveryLifecycleState.UNKNOWN: frozenset({
        DeliveryLifecycleState.ACCEPTED,
        DeliveryLifecycleState.REJECTED,
        DeliveryLifecycleState.FAILED_RETRYABLE,
        DeliveryLifecycleState.PENDING,
    }),
}


def validate_transition(
    from_state: DeliveryLifecycleState,
    to_state: DeliveryLifecycleState,
) -> None:
    """Refuse an illegal lifecycle transition.

    Raises ``ValueError`` with a clear message naming the source and
    target states when the transition is not allowed. Same-state
    transitions are always allowed (no-op writes are idempotent).
    """

    if not isinstance(from_state, DeliveryLifecycleState):
        raise ValueError(f"from_state must be a DeliveryLifecycleState: {from_state!r}")
    if not isinstance(to_state, DeliveryLifecycleState):
        raise ValueError(f"to_state must be a DeliveryLifecycleState: {to_state!r}")
    if from_state is to_state:
        return
    if to_state not in _ALLOWED_TRANSITIONS[from_state]:
        allowed = sorted(s.value for s in _ALLOWED_TRANSITIONS[from_state])
        raise ValueError(
            f"illegal delivery lifecycle transition: {from_state.value} -> "
            f"{to_state.value} (allowed from {from_state.value}: {allowed})"
        )


def is_terminal(state: DeliveryLifecycleState) -> bool:
    """A state from which the request cannot progress without operator action.

    ``ACCEPTED`` is monotonically terminal; ``REJECTED`` is
    terminal-by-default. ``UNKNOWN`` is NOT terminal: reconcile can
    still move it. ``FAILED_RETRYABLE`` is NOT terminal: the retry
    policy can move it to PENDING.
    """

    return state in (
        DeliveryLifecycleState.ACCEPTED,
        DeliveryLifecycleState.REJECTED,
    )
