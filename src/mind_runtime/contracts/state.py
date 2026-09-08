"""State definition and immutable runtime state contracts."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from mind_runtime.contracts.common import (
    SyncFields,
    freeze_refs,
    freeze_value,
    require_aware_utc,
    require_non_empty,
    validate_sync_fields,
)
from mind_runtime.contracts.scope import Scope, ScopeDomain


class StateValueType(StrEnum):
    """The four V0.1.4 declarative state value categories."""

    CATEGORICAL = "categorical"
    BOOLEAN = "boolean"
    SCALAR = "scalar"
    STRUCTURED = "structured"


class StateDomain(StrEnum):
    """The V0.1.4 domains permitted to define or carry runtime state."""

    USER = "user"
    AGENT = "agent"
    RELATIONSHIP = "relationship"
    INTERACTION = "interaction"


_STATE_DOMAIN_BY_SCOPE = {
    ScopeDomain.USER: StateDomain.USER,
    ScopeDomain.AGENT: StateDomain.AGENT,
    ScopeDomain.RELATIONSHIP: StateDomain.RELATIONSHIP,
    ScopeDomain.INTERACTION: StateDomain.INTERACTION,
}


def state_domain_for_scope(scope: Scope) -> StateDomain:
    """Return a StateDomain or reject scopes without a V0.1.4 state domain."""

    try:
        return _STATE_DOMAIN_BY_SCOPE[scope.domain]
    except KeyError as error:
        raise ValueError("scope.domain must be a StateDomain") from error


def require_domain_key(value: str, domain: StateDomain, field_name: str) -> None:
    """Require a non-empty `<domain>.<name>` identifier for a state concept."""

    require_non_empty(value, field_name)
    prefix, separator, name = value.partition(".")
    if prefix != domain.value or not separator or not name.strip():
        raise ValueError(f"{field_name} must use approved <domain>.<name> form")


@dataclass(frozen=True, slots=True)
class StateDefinition:
    """The scoped schema of one state dimension."""

    key: str
    domain: StateDomain
    value_type: StateValueType
    dynamics_policy: str
    default_validity_policy: str | None
    bounds: object | None

    def __post_init__(self) -> None:
        if not isinstance(self.domain, StateDomain):
            raise ValueError("domain must be a StateDomain")
        if not isinstance(self.value_type, StateValueType):
            raise ValueError("value_type must be a StateValueType")
        require_domain_key(self.key, self.domain, "key")
        require_non_empty(self.dynamics_policy, "dynamics_policy")
        if self.default_validity_policy is not None:
            require_non_empty(self.default_validity_policy, "default_validity_policy")
        if self.bounds is not None:
            object.__setattr__(self, "bounds", freeze_value(self.bounds, "bounds"))


@dataclass(frozen=True, slots=True)
class RuntimeState:
    """A synchronizable canonical state snapshot with frozen V0.1.4 fields."""

    state_id: str
    scope: Scope
    dimension: str
    value: object
    status: str
    valid_from: datetime
    valid_until: datetime | None
    relevant_until: datetime | None
    last_observed_at: datetime
    evidence_refs: tuple[str, ...]
    transition_refs: tuple[str, ...]
    updated_at: datetime
    origin_runtime_id: str
    version: int
    sync: SyncFields

    def __post_init__(self) -> None:
        for field_name in ("state_id", "origin_runtime_id", "status"):
            require_non_empty(getattr(self, field_name), field_name)
        require_domain_key(self.dimension, state_domain_for_scope(self.scope), "dimension")
        if isinstance(self.version, bool) or self.version < 1:
            raise ValueError("version must be at least 1")
        for field_name in ("valid_from", "last_observed_at", "updated_at"):
            require_aware_utc(getattr(self, field_name), field_name)
        for field_name in ("valid_until", "relevant_until"):
            value = getattr(self, field_name)
            if value is not None:
                require_aware_utc(value, field_name)
        object.__setattr__(self, "value", freeze_value(self.value, "value"))
        object.__setattr__(self, "evidence_refs", freeze_refs(self.evidence_refs, "evidence_refs"))
        object.__setattr__(
            self, "transition_refs", freeze_refs(self.transition_refs, "transition_refs")
        )
        validate_sync_fields(
            self.sync,
            scope=self.scope,
            origin_runtime_id=self.origin_runtime_id,
            object_id=self.state_id,
            expected_version=self.version,
        )

    def sync_fields(self) -> SyncFields:
        """Return the runtime state's synchronization identity."""

        return self.sync
