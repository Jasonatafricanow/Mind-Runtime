"""Pipeline-facing ports backed by the D4 state plane."""

from datetime import datetime

from mind_runtime.contracts import RuntimeState, Scope, SyncFields
from mind_runtime.state.resolver import EffectiveStateResolver


class ResolverEffectiveStatePort:
    """``EffectiveStatePort`` implementation backed by the authoritative resolver.

    This is the only production effective-state entry for the pipeline: it
    resolves the canonical snapshot through ``EffectiveStateResolver`` and
    returns the turn's effective state (the record whose evidence refs match
    the turn, else the first state of the turn's scope, else a synthesized
    passthrough so an empty factual plane still produces a valid turn).
    """

    def __init__(self, *, resolver: EffectiveStateResolver) -> None:
        self._resolver = resolver

    def effective(
        self,
        *,
        interaction_id: str,
        evidence_refs: tuple[str, ...],
        canonical_snapshot: tuple[RuntimeState, ...],
        scope: Scope,
        clock: datetime,
    ) -> RuntimeState:
        view = self._resolver.resolve(canonical_snapshot, now=clock)
        turn_refs = set(evidence_refs)
        for state in view.states:
            if state.scope == scope and turn_refs & set(state.evidence_refs):
                return state
        for state in view.states:
            if state.scope == scope:
                return state
        # No effective state for this scope yet: synthesize the passthrough
        # carrying the turn's evidence refs (same shape as the D2S stub).
        dimension = f"{scope.domain.value}.effective"
        now = clock
        state_id = f"effective-{interaction_id}"
        return RuntimeState(
            state_id=state_id,
            scope=scope,
            origin_runtime_id="runtime-1",
            dimension=dimension,
            value={"evidence_refs": list(evidence_refs)},
            status="active",
            valid_from=now,
            valid_until=None,
            relevant_until=None,
            last_observed_at=now,
            evidence_refs=evidence_refs,
            transition_refs=(),
            updated_at=now,
            version=1,
            sync=SyncFields(scope, "runtime-1", state_id, 1, "idem-eff"),
        )
