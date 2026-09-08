"""Decision context contract: a bounded view, never a raw dump (chapter 17)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from mind_runtime.contracts.common import require_non_empty
from mind_runtime.contracts.scope import Scope

if TYPE_CHECKING:
    from mind_runtime.contracts import ExpressionContextItem


@dataclass(frozen=True, slots=True)
class DecisionContext:
    """The compiled, bounded context an Agent consumes for one turn."""

    context_id: str
    scope: Scope
    origin_runtime_id: str
    interaction_ref: str
    situation_ref: str
    effective_user_state_ref: str
    projected_agent_state_ref: str
    relationship_state_refs: tuple[str, ...]
    historical_context_ref: str | None
    assessment_trace_ref: str
    intent_ref: str
    policy_result_ref: str
    relevant_persona_ref: str | None
    goals_refs: tuple[str, ...]
    selected_intent_kind: str
    selected_action_type: str
    attempt: int
    expression_context: tuple[ExpressionContextItem, ...]
    # C10-C: tuple of authoritative agent.slow.* state_ids whose values
    # were projected into this context.  Empty tuple when no slow-state
    # projection was supplied (production default) or when the projection
    # was empty.  Carries observable provenance for the slow state
    # contribution items emitted alongside fast affect items.
    slow_state_projection_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        require_non_empty(self.context_id, "context_id")
        require_non_empty(self.origin_runtime_id, "origin_runtime_id")
        require_non_empty(self.interaction_ref, "interaction_ref")
        require_non_empty(self.situation_ref, "situation_ref")
        require_non_empty(self.effective_user_state_ref, "effective_user_state_ref")
        require_non_empty(self.projected_agent_state_ref, "projected_agent_state_ref")
        for ref in self.relationship_state_refs:
            require_non_empty(ref, "relationship_state_refs entries")
        if self.historical_context_ref is not None:
            require_non_empty(self.historical_context_ref, "historical_context_ref")
        require_non_empty(self.assessment_trace_ref, "assessment_trace_ref")
        require_non_empty(self.intent_ref, "intent_ref")
        require_non_empty(self.policy_result_ref, "policy_result_ref")
        if self.relevant_persona_ref is not None:
            require_non_empty(self.relevant_persona_ref, "relevant_persona_ref")
        for ref in self.goals_refs:
            require_non_empty(ref, "goals_refs entries")
        require_non_empty(self.selected_intent_kind, "selected_intent_kind")
        require_non_empty(self.selected_action_type, "selected_action_type")
        if isinstance(self.attempt, bool) or not isinstance(self.attempt, int) or self.attempt < 0:
            raise ValueError("attempt must be a non-negative integer")
        from mind_runtime.contracts import ExpressionContextItem

        identities: set[tuple[object, str, tuple[str, ...]]] = set()
        for item in self.expression_context:
            if not isinstance(item, ExpressionContextItem):
                raise ValueError("expression_context entries must be ExpressionContextItem")
            if item.identity in identities:
                raise ValueError("expression_context item identities must be unique")
            identities.add(item.identity)
        for ref in self.slow_state_projection_refs:
            require_non_empty(ref, "slow_state_projection_refs entries")
