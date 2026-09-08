"""Projection contracts: projected mind state and turn projection."""

from dataclasses import dataclass
from datetime import datetime

from mind_runtime.contracts.common import (
    SyncFields,
    require_aware_utc,
    require_non_empty,
    validate_sync_fields,
)
from mind_runtime.contracts.observation import Observation
from mind_runtime.contracts.scope import Scope, ScopeDomain
from mind_runtime.contracts.state import RuntimeState
from mind_runtime.contracts.transition import TransitionIntent


@dataclass(frozen=True, slots=True)
class ProjectedMindState:
    """A projected mind state snapshot that is not canonical until committed."""

    projection_id: str
    scope: Scope
    origin_runtime_id: str
    projected_states: tuple[RuntimeState, ...]
    sync: SyncFields
    committed: bool = False

    def __post_init__(self) -> None:
        require_non_empty(self.projection_id, "projection_id")
        require_non_empty(self.origin_runtime_id, "origin_runtime_id")
        if not isinstance(self.committed, bool):
            raise ValueError("committed must be a bool")
        if not self.projected_states:
            raise ValueError("projected_states must be non-empty")
        seen: set[str] = set()
        for state in self.projected_states:
            if state.scope != self.scope:
                raise ValueError("projected state scope must match projection scope")
            if state.dimension in seen:
                raise ValueError("projected state dimensions must be unique")
            seen.add(state.dimension)
        validate_sync_fields(
            self.sync,
            scope=self.scope,
            origin_runtime_id=self.origin_runtime_id,
            object_id=self.projection_id,
        )

    def sync_fields(self) -> SyncFields:
        """Return the projected state synchronization identity."""

        return self.sync


@dataclass(frozen=True, slots=True)
class TurnProjection:
    """An uncommitted turn-level projection; never canonical state."""

    projection_id: str
    interaction_id: str
    scope: Scope
    origin_runtime_id: str
    effective_state_before: RuntimeState
    observations: tuple[Observation, ...]
    situation: str | None
    assessment_trace_ref: str | None
    intent_refs: tuple[str, ...]
    policy_result_ref: str | None
    transition_intents: tuple[TransitionIntent, ...]
    projected_mind_state: ProjectedMindState
    created_at: datetime
    sync: SyncFields

    def __post_init__(self) -> None:
        for field_name in ("projection_id", "interaction_id", "origin_runtime_id"):
            require_non_empty(getattr(self, field_name), field_name)
        require_aware_utc(self.created_at, "created_at")
        if self.effective_state_before.scope != self.scope:
            raise ValueError("effective_state_before.scope must match scope")
        # ADR-0002 (D7.7): the projected mind state may carry the persona's
        # agent scope (agent affect belongs to the agent's persona scope,
        # never the user interaction scope). Any other domain mismatch stays
        # fail-closed.
        if (
            self.projected_mind_state.scope != self.scope
            and self.projected_mind_state.scope.domain is not ScopeDomain.AGENT
        ):
            raise ValueError(
                "projected_mind_state.scope must match scope or be an agent/persona scope"
            )
        for observation in self.observations:
            if observation.scope != self.scope:
                raise ValueError("observation scope must match scope")
        for intent in self.transition_intents:
            if intent.scope != self.scope and intent.scope != self.projected_mind_state.scope:
                raise ValueError(
                    "transition intent scope must match turn or projected mind state scope"
                )
        if self.assessment_trace_ref is not None:
            require_non_empty(self.assessment_trace_ref, "assessment_trace_ref")
        for ref in self.intent_refs:
            require_non_empty(ref, "intent_refs entries")
        if self.policy_result_ref is not None:
            require_non_empty(self.policy_result_ref, "policy_result_ref")
        validate_sync_fields(
            self.sync,
            scope=self.scope,
            origin_runtime_id=self.origin_runtime_id,
            object_id=self.projection_id,
        )

    def sync_fields(self) -> SyncFields:
        """Return the turn projection synchronization identity."""

        return self.sync
