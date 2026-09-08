"""Projected intent and committed state transition contracts."""

from dataclasses import dataclass
from datetime import datetime

from mind_runtime.contracts.common import (
    SyncFields,
    freeze_refs,
    require_aware_utc,
    require_non_empty,
    validate_sync_fields,
)
from mind_runtime.contracts.scope import Scope
from mind_runtime.contracts.state import RuntimeState, require_domain_key, state_domain_for_scope

_COMMIT_PHASES = frozenset({"ingest", "turn_commit"})


def _require_matching_state_scopes(scope: Scope, *states: RuntimeState) -> None:
    if any(state.scope != scope for state in states):
        raise ValueError("state scope must match transition scope")


@dataclass(frozen=True, slots=True)
class TransitionIntent:
    """An uncommitted state proposal that must not be synchronized."""

    intent_id: str
    interaction_id: str
    scope: Scope
    origin_runtime_id: str
    target_dimension: str
    before: RuntimeState
    proposed_after: RuntimeState
    cause_refs: tuple[str, ...]
    policy: str
    confidence: float
    commit_phase: str

    def __post_init__(self) -> None:
        for field_name in (
            "intent_id",
            "interaction_id",
            "origin_runtime_id",
            "target_dimension",
            "policy",
        ):
            require_non_empty(getattr(self, field_name), field_name)
        require_domain_key(
            self.target_dimension,
            state_domain_for_scope(self.scope),
            "target_dimension",
        )
        _require_matching_state_scopes(self.scope, self.before, self.proposed_after)
        if self.before.dimension != self.target_dimension:
            raise ValueError("before.dimension must match target_dimension")
        if self.proposed_after.dimension != self.target_dimension:
            raise ValueError("proposed_after.dimension must match target_dimension")
        if (
            isinstance(self.confidence, bool)
            or not isinstance(self.confidence, (int, float))
            or not 0 <= self.confidence <= 1
        ):
            raise ValueError("confidence must be in [0, 1]")
        if self.commit_phase not in _COMMIT_PHASES:
            raise ValueError("commit_phase must be ingest or turn_commit")
        object.__setattr__(self, "cause_refs", freeze_refs(self.cause_refs, "cause_refs"))


@dataclass(frozen=True, slots=True)
class StateTransition:
    """A committed factual transition that can be synchronized."""

    transition_id: str
    scope: Scope
    origin_runtime_id: str
    intent_id: str
    from_state: RuntimeState
    to_state: RuntimeState
    committed_at: datetime
    sync: SyncFields

    def __post_init__(self) -> None:
        for field_name in ("transition_id", "origin_runtime_id", "intent_id"):
            require_non_empty(getattr(self, field_name), field_name)
        _require_matching_state_scopes(self.scope, self.from_state, self.to_state)
        if self.from_state.dimension != self.to_state.dimension:
            raise ValueError("state dimensions must match")
        require_aware_utc(self.committed_at, "committed_at")
        validate_sync_fields(
            self.sync,
            scope=self.scope,
            origin_runtime_id=self.origin_runtime_id,
            object_id=self.transition_id,
        )

    def sync_fields(self) -> SyncFields:
        """Return the committed transition synchronization identity."""

        return self.sync
