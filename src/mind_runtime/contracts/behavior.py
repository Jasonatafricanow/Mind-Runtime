"""Cross-layer D9 behavior-composition input contracts."""

from dataclasses import dataclass
from datetime import datetime

from mind_runtime.contracts.appraisal import SemanticEventCandidate
from mind_runtime.contracts.common import require_aware_utc, require_non_empty
from mind_runtime.contracts.intent import Intent
from mind_runtime.contracts.projection import ProjectedMindState
from mind_runtime.contracts.scope import Scope
from mind_runtime.contracts.situation import Situation


@dataclass(frozen=True, slots=True)
class IntentEngineInput:
    """Explicit deterministic inputs to one Intent scoring pass."""

    interaction_id: str
    scope: Scope
    origin_runtime_id: str
    context: Situation
    projected: ProjectedMindState
    accepted_events: tuple[SemanticEventCandidate, ...]
    clock: datetime

    def __post_init__(self) -> None:
        require_non_empty(self.interaction_id, "interaction_id")
        require_non_empty(self.origin_runtime_id, "origin_runtime_id")
        if self.context.scope != self.scope:
            raise ValueError("context scope must match intent engine scope")
        seen: set[str] = set()
        for event in self.accepted_events:
            if event.scope != self.scope:
                raise ValueError("accepted event scope must match intent engine scope")
            if event.candidate_id in seen:
                raise ValueError("accepted event ids must be unique")
            seen.add(event.candidate_id)
        require_aware_utc(self.clock, "clock")


@dataclass(frozen=True, slots=True)
class PolicyResources:
    """Current external action capabilities, never permission verdicts."""

    available_actions: tuple[str, ...]

    def __post_init__(self) -> None:
        seen: set[str] = set()
        for action in self.available_actions:
            require_non_empty(action, "available_actions entries")
            if action in seen:
                raise ValueError("available_actions must be unique")
            seen.add(action)


@dataclass(frozen=True, slots=True)
class ActionPolicyInput:
    """All factual inputs to one deterministic permission decision."""

    intent: Intent
    context: Situation
    scope: Scope
    clock: datetime
    resources: PolicyResources

    def __post_init__(self) -> None:
        if self.intent.scope != self.scope:
            raise ValueError("intent scope must match policy scope")
        if self.context.scope != self.scope:
            raise ValueError("context scope must match policy scope")
        require_aware_utc(self.clock, "clock")
