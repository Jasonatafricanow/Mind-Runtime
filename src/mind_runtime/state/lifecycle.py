"""D4.1 frozen lifecycle vocabulary for canonical state.

The V0.1.4 baseline freezes the state lifecycle dimensions:

- current-like lifecycles (ACTIVE, IMPROVING) are the only statuses that
  can be the "current" state of a dimension, and the only ones time can
  turn into EXPIRED (D4.2 TTL).
- terminal lifecycles (RESOLVED, COMPLETED, CANCELLED, SUPERSEDED) answer
  "what happened?" and can never be rewritten to EXPIRED by time.
- EXPIRED is a validity outcome, not a lifecycle terminal.

This vocabulary is deliberately separate from the D1 `RuntimeState.status`
string field (which stays a raw string for D1 compatibility): lifecycle
legality is enforced by the state domain layer, not by the frozen contract.
"""

from enum import StrEnum
from typing import Final


class StateLifecycle(StrEnum):
    """The frozen canonical-state lifecycle statuses (D4.1)."""

    ACTIVE = "active"
    IMPROVING = "improving"
    EXPIRED = "expired"
    RESOLVED = "resolved"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    SUPERSEDED = "superseded"


CURRENT_LIKE_LIFECYCLES: Final[frozenset[StateLifecycle]] = frozenset(
    {StateLifecycle.ACTIVE, StateLifecycle.IMPROVING}
)

TERMINAL_LIFECYCLES: Final[frozenset[StateLifecycle]] = frozenset(
    {
        StateLifecycle.RESOLVED,
        StateLifecycle.COMPLETED,
        StateLifecycle.CANCELLED,
        StateLifecycle.SUPERSEDED,
    }
)

# EXPIRED is a validity outcome, not a lifecycle terminal: terminal states
# are never rewritten to expired by time (baseline: "terminal 状态永不被
# 时间改写成 expired").


def _coerce(status: str | StateLifecycle) -> StateLifecycle | None:
    if isinstance(status, StateLifecycle):
        return status
    try:
        return StateLifecycle(status)
    except ValueError:
        return None


def is_known_lifecycle(status: str | StateLifecycle) -> bool:
    """True when the status names one of the seven frozen lifecycles."""
    return _coerce(status) is not None


def is_current_like(status: str | StateLifecycle) -> bool:
    """True for ACTIVE/IMPROVING; False for everything else, fail-safe."""
    coerced = _coerce(status)
    return coerced is not None and coerced in CURRENT_LIKE_LIFECYCLES


def is_terminal(status: str | StateLifecycle) -> bool:
    """True for RESOLVED/COMPLETED/CANCELLED/SUPERSEDED, fail-safe."""
    coerced = _coerce(status)
    return coerced is not None and coerced in TERMINAL_LIFECYCLES
