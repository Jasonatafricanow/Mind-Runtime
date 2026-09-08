"""Replication envelope and port contracts (DECISION-026)."""

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from mind_runtime.contracts.common import (
    SyncFields,
    require_non_empty,
    validate_sync_fields,
)
from mind_runtime.contracts.evidence import Evidence
from mind_runtime.contracts.observation import Observation
from mind_runtime.contracts.projection import ProjectedMindState, TurnProjection
from mind_runtime.contracts.scope import Scope
from mind_runtime.contracts.state import RuntimeState
from mind_runtime.contracts.transition import StateTransition

_SCOPED_PAYLOAD_TYPES = (Evidence, Observation, RuntimeState, StateTransition)


@dataclass(frozen=True, slots=True)
class ReplicationEnvelope:
    """One synchronizable unit; projected state is never allowed."""

    envelope_id: str
    scope: Scope
    origin_runtime_id: str
    payload: object
    payload_type: str
    sync: SyncFields

    def __post_init__(self) -> None:
        require_non_empty(self.envelope_id, "envelope_id")
        require_non_empty(self.origin_runtime_id, "origin_runtime_id")
        require_non_empty(self.payload_type, "payload_type")
        if isinstance(self.payload, (ProjectedMindState, TurnProjection)):
            raise TypeError("projected state cannot be replicated")
        for scoped_type in _SCOPED_PAYLOAD_TYPES:
            if isinstance(self.payload, scoped_type):
                payload_scope = self.payload.scope
                if payload_scope != self.scope:
                    raise ValueError("payload scope must match envelope scope")
        validate_sync_fields(
            self.sync,
            scope=self.scope,
            origin_runtime_id=self.origin_runtime_id,
            object_id=self.envelope_id,
        )

    def sync_fields(self) -> SyncFields:
        """Return the envelope synchronization identity."""

        return self.sync


@runtime_checkable
class ReplicationPort(Protocol):
    """A transport boundary for replication envelopes."""

    def send(self, envelope: ReplicationEnvelope) -> None:
        """Deliver one envelope to the remote side."""
        ...

    def receive(self) -> ReplicationEnvelope | None:
        """Return the next inbound envelope, or None when empty."""
        ...
