"""Data governance contracts (DECISION-032)."""

from dataclasses import dataclass
from enum import StrEnum

from mind_runtime.contracts.common import require_non_empty
from mind_runtime.contracts.scope import Scope


class DataSensitivity(StrEnum):
    """Minimum data governance sensitivity levels."""

    PUBLIC = "public"
    PERSONAL = "personal"
    RELATIONSHIP_SENSITIVE = "relationship_sensitive"
    SECRET = "secret"


@dataclass(frozen=True, slots=True)
class RetentionClass:
    """Configurable trace retention for one sensitivity class."""

    retention_id: str
    scope: Scope
    origin_runtime_id: str
    sensitivity: DataSensitivity
    ttl_days: int | None
    keep_after_close: bool

    def __post_init__(self) -> None:
        require_non_empty(self.retention_id, "retention_id")
        require_non_empty(self.origin_runtime_id, "origin_runtime_id")
        if not isinstance(self.sensitivity, DataSensitivity):
            raise ValueError("sensitivity must be a DataSensitivity")
        if self.ttl_days is not None and (isinstance(self.ttl_days, bool) or self.ttl_days < 0):
            raise ValueError("ttl_days must be non-negative when present")
        if not isinstance(self.keep_after_close, bool):
            raise ValueError("keep_after_close must be a bool")


@dataclass(frozen=True, slots=True)
class RedactionPolicy:
    """Which fields to redact for one sensitivity class."""

    policy_id: str
    scope: Scope
    origin_runtime_id: str
    sensitivity: DataSensitivity
    redact_fields: frozenset[str]

    def __post_init__(self) -> None:
        require_non_empty(self.policy_id, "policy_id")
        require_non_empty(self.origin_runtime_id, "origin_runtime_id")
        if not isinstance(self.sensitivity, DataSensitivity):
            raise ValueError("sensitivity must be a DataSensitivity")
        if not isinstance(self.redact_fields, frozenset):
            raise ValueError("redact_fields must be a frozenset")
        for field_name in self.redact_fields:
            require_non_empty(field_name, "redact_fields entries")
