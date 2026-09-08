"""Action intent, permission, and policy result contracts (D9 baseline)."""

from dataclasses import dataclass
from enum import StrEnum

from mind_runtime.contracts.common import (
    SyncFields,
    require_non_empty,
    validate_sync_fields,
)
from mind_runtime.contracts.scope import Scope


@dataclass(frozen=True, slots=True)
class ActionIntent:
    """A concrete action proposal produced after ActionPolicy."""

    intent_id: str
    scope: Scope
    origin_runtime_id: str
    cognitive_intent_id: str
    action: str
    target: str | None
    sync: SyncFields

    def __post_init__(self) -> None:
        require_non_empty(self.intent_id, "intent_id")
        require_non_empty(self.origin_runtime_id, "origin_runtime_id")
        require_non_empty(self.cognitive_intent_id, "cognitive_intent_id")
        require_non_empty(self.action, "action")
        if self.target is not None:
            require_non_empty(self.target, "target")
        validate_sync_fields(
            self.sync,
            scope=self.scope,
            origin_runtime_id=self.origin_runtime_id,
            object_id=self.intent_id,
        )

    def sync_fields(self) -> SyncFields:
        """Return the action intent synchronization identity."""

        return self.sync


@dataclass(frozen=True, slots=True)
class ActionPermission:
    """Whether an action type is currently permitted (baseline 15.1)."""

    permission_id: str
    scope: Scope
    origin_runtime_id: str
    action_type: str
    allowed: bool
    reasons: tuple[str, ...]
    constraints: tuple[str, ...]

    def __post_init__(self) -> None:
        require_non_empty(self.permission_id, "permission_id")
        require_non_empty(self.origin_runtime_id, "origin_runtime_id")
        require_non_empty(self.action_type, "action_type")
        if not isinstance(self.allowed, bool):
            raise ValueError("allowed must be a bool")
        for reason in self.reasons:
            require_non_empty(reason, "reasons entries")
        for constraint in self.constraints:
            require_non_empty(constraint, "constraints entries")


class ActionDecision(StrEnum):
    """The policy verdict on one action intent."""

    ALLOW = "allow"
    DENY = "deny"
    DEFER = "defer"


@dataclass(frozen=True, slots=True)
class ActionPolicyResult:
    """The traceable result of running ActionPolicy on one intent."""

    policy_id: str
    scope: Scope
    origin_runtime_id: str
    intent_id: str
    decision: ActionDecision
    permission: ActionPermission | None
    reason_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        require_non_empty(self.policy_id, "policy_id")
        require_non_empty(self.origin_runtime_id, "origin_runtime_id")
        require_non_empty(self.intent_id, "intent_id")
        if not isinstance(self.decision, ActionDecision):
            raise ValueError("decision must be an ActionDecision")
        for code in self.reason_codes:
            require_non_empty(code, "reason_codes entries")
        if self.permission is not None:
            if self.permission.scope != self.scope:
                raise ValueError("permission scope must match policy scope")
            if self.permission.origin_runtime_id != self.origin_runtime_id:
                raise ValueError("permission origin must match policy origin")
        if self.decision is ActionDecision.ALLOW and (
            self.permission is None or not self.permission.allowed
        ):
            raise ValueError("ALLOW requires an allowed permission")
        if self.decision in {ActionDecision.DENY, ActionDecision.DEFER} and (
            self.permission is None or self.permission.allowed
        ):
            raise ValueError(f"{self.decision.name} requires a denied permission")
