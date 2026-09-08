"""Immutable factual evidence contract."""

from dataclasses import dataclass
from datetime import datetime

from mind_runtime.contracts.common import (
    SyncFields,
    freeze_value,
    require_aware_utc,
    require_non_empty,
    validate_sync_fields,
)
from mind_runtime.contracts.scope import Authority, AuthorityLevel, Scope


@dataclass(frozen=True, slots=True)
class Evidence:
    """A durable, authoritative factual input that can be synchronized."""

    id: str
    source_type: str
    source_id: str
    authority_level: AuthorityLevel
    occurred_at: datetime
    received_at: datetime
    payload: object
    scope: Scope
    origin_runtime_id: str
    authority: Authority
    sync: SyncFields

    def __post_init__(self) -> None:
        for field_name in (
            "id",
            "origin_runtime_id",
            "source_type",
            "source_id",
        ):
            require_non_empty(getattr(self, field_name), field_name)
        if not isinstance(self.authority_level, AuthorityLevel):
            raise ValueError("authority_level must be an AuthorityLevel")
        if not isinstance(self.authority, Authority):
            raise ValueError("authority must be an Authority")
        if self.authority.scope != self.scope:
            raise ValueError("authority.scope must match scope")
        if self.authority.level != self.authority_level:
            raise ValueError("authority.level must match authority_level")
        if self.authority_level is AuthorityLevel.NONE:
            if self.authority.source_id is not None:
                raise ValueError("NONE authority forbids authority.source_id")
        elif self.authority.source_id != self.source_id:
            raise ValueError("authority.source_id must match source_id")
        require_aware_utc(self.occurred_at, "occurred_at")
        require_aware_utc(self.received_at, "received_at")
        object.__setattr__(self, "payload", freeze_value(self.payload, "payload"))
        validate_sync_fields(
            self.sync,
            scope=self.scope,
            origin_runtime_id=self.origin_runtime_id,
            object_id=self.id,
        )

    def sync_fields(self) -> SyncFields:
        """Return the factual evidence synchronization identity."""

        return self.sync
