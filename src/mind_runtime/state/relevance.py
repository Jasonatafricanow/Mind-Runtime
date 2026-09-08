"""D4.6 lifecycle vs relevance separation.

The V0.1.4 baseline freezes three independent dimensions:

- lifecycle status answers "what happened?" (e.g. cancelled);
- validity answers "is it still current?" (expired via TTL, terminal
  protected);
- context relevance answers "is it still worth mentioning?" governed by
  ``relevant_until``.

A CANCELLED state never decays into EXPIRED, but its context relevance can
lapse once ``relevant_until`` passes. This module evaluates the D4-owned
relevance derivations; deeper derived facts land in D6.
"""

from dataclasses import dataclass
from datetime import datetime

from mind_runtime.contracts import RuntimeState, Scope
from mind_runtime.state.lifecycle import StateLifecycle, is_terminal


@dataclass(frozen=True)
class RelevanceOutcome:
    """The relevance verdict for one state at one instant."""

    dimension: str
    scope: Scope
    recently_cancelled: bool
    reason: str


def evaluate_relevance(state: RuntimeState, *, now: datetime) -> RelevanceOutcome:
    """Evaluate context relevance independently of lifecycle validity.

    ``now`` must be aware UTC (the contract enforces it on construction).
    """
    if is_terminal(state.status) and state.status == StateLifecycle.CANCELLED.value:
        lapsed = state.relevant_until is not None and now > state.relevant_until
        if lapsed:
            return RelevanceOutcome(
                dimension=state.dimension,
                scope=state.scope,
                recently_cancelled=False,
                reason="cancelled_window_lapsed",
            )
        return RelevanceOutcome(
            dimension=state.dimension,
            scope=state.scope,
            recently_cancelled=True,
            reason="cancelled_within_window",
        )
    return RelevanceOutcome(
        dimension=state.dimension,
        scope=state.scope,
        recently_cancelled=False,
        reason="not_cancelled",
    )
