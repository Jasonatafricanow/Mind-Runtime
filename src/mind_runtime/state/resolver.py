"""EffectiveStateResolver: the single authoritative read gate for state.

The V0.1.4 baseline freezes: "当前状态"必须是统一计算结果，不允许各消费者
自行解释 raw state (DECISION-005). Every consumer (orchestrator, situation
builder, reconciler read paths) must go through ``EffectiveStateResolver``;
no business module may filter raw ``status`` itself.

The resolver is a pure read: it never writes records or transitions. It
evaluates validity (D4.2) at the read instant, merges the current-turn
overlay (D4.8), and returns one effective record per ``(scope, dimension)``:

- current-like records past their ``valid_until`` are NOT effective
  (excluded from the view);
- terminal records are always effective (lifecycle answers "what
  happened?");
- overlay records replace the canonical record for their dimension
  (read-your-writes within the turn);
- status strings outside the frozen vocabulary are rejected (fail closed).
"""

from dataclasses import dataclass
from datetime import datetime

from mind_runtime.contracts import RuntimeState, Scope
from mind_runtime.state.definitions import StateDefinitionRegistry
from mind_runtime.state.lifecycle import is_current_like, is_known_lifecycle, is_terminal


@dataclass(frozen=True)
class EffectiveStateView:
    """The resolved effective states: one record per (scope, dimension)."""

    states: tuple[RuntimeState, ...]
    resolved_at: datetime

    def for_dimension(self, dimension: str, scope: Scope) -> RuntimeState | None:
        for state in self.states:
            if state.dimension == dimension and state.scope == scope:
                return state
        return None

    def for_scope(self, scope: Scope) -> tuple[RuntimeState, ...]:
        return tuple(state for state in self.states if state.scope == scope)


class EffectiveStateResolver:
    """Resolves canonical state into the authoritative effective view."""

    def __init__(self, *, definitions: StateDefinitionRegistry) -> None:
        self._definitions = definitions

    def resolve(
        self,
        canonical: tuple[RuntimeState, ...],
        *,
        now: datetime,
        overlay: tuple[RuntimeState, ...] = (),
    ) -> EffectiveStateView:
        """Return the effective view at ``now`` (read-only, no writes)."""
        currents: dict[tuple[Scope, str], RuntimeState] = {}
        order: list[tuple[Scope, str]] = []
        for state in canonical:
            key = (state.scope, state.dimension)
            if key not in currents:
                order.append(key)
            currents[key] = state
        for state in overlay:
            # Read-your-writes: this turn's confirmed facts replace the
            # canonical record for their dimension.
            key = (state.scope, state.dimension)
            if key not in currents:
                order.append(key)
            currents[key] = state

        effective: list[RuntimeState] = []
        for key in order:
            state = currents[key]
            if not is_known_lifecycle(state.status):
                raise ValueError(f"opaque status {state.status!r} cannot be resolved")
            if is_terminal(state.status):
                effective.append(state)
                continue
            if not is_current_like(state.status):
                # EXPIRED records are not effective state.
                continue
            if state.valid_until is not None and now > state.valid_until:
                # TTL lapsed: not effective at this instant.
                continue
            effective.append(state)

        return EffectiveStateView(states=tuple(effective), resolved_at=now)
