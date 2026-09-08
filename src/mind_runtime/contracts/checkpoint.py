"""Checkpoint and receipt contracts for turn recovery and reconciliation."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from mind_runtime.contracts.common import (
    SyncFields,
    require_aware_utc,
    require_non_empty,
    validate_sync_fields,
)
from mind_runtime.contracts.scope import Scope


class TurnStage(StrEnum):
    """Recoverable intermediate turn stages (baseline 4.9 / D5)."""

    PROCESSING = "processing"
    DISPATCHING = "dispatching"
    AWAITING_COMMIT = "awaiting_commit"


class DeliveryStatus(StrEnum):
    """Distinguishes not-sent, sent, and unknown send state (D5)."""

    UNSENT = "unsent"
    SENT = "sent"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class TurnCheckpoint:
    """A recoverable checkpoint of one interaction's turn stage."""

    checkpoint_id: str
    interaction_id: str
    scope: Scope
    origin_runtime_id: str
    stage: TurnStage
    base_state_version: int
    projection_ref: str
    action_id: str | None
    delivery_status: DeliveryStatus
    checkpointed_at: datetime
    sync: SyncFields

    def __post_init__(self) -> None:
        for field_name in (
            "checkpoint_id",
            "interaction_id",
            "origin_runtime_id",
            "projection_ref",
        ):
            require_non_empty(getattr(self, field_name), field_name)
        if not isinstance(self.stage, TurnStage):
            raise ValueError("stage must be a TurnStage")
        if not isinstance(self.delivery_status, DeliveryStatus):
            raise ValueError("delivery_status must be a DeliveryStatus")
        if isinstance(self.base_state_version, bool) or self.base_state_version < 1:
            raise ValueError("base_state_version must be at least 1")
        require_aware_utc(self.checkpointed_at, "checkpointed_at")
        validate_sync_fields(
            self.sync,
            scope=self.scope,
            origin_runtime_id=self.origin_runtime_id,
            object_id=self.checkpoint_id,
        )

    def sync_fields(self) -> SyncFields:
        """Return the checkpoint synchronization identity."""

        return self.sync


@dataclass(frozen=True, slots=True)
class ActionReceipt:
    """Records whether a dispatched external action actually happened."""

    receipt_id: str
    scope: Scope
    origin_runtime_id: str
    action_intent_id: str
    delivery_status: DeliveryStatus
    outcome: str | None
    received_at: datetime
    sync: SyncFields

    def __post_init__(self) -> None:
        for field_name in ("receipt_id", "origin_runtime_id", "action_intent_id"):
            require_non_empty(getattr(self, field_name), field_name)
        if not isinstance(self.delivery_status, DeliveryStatus):
            raise ValueError("delivery_status must be a DeliveryStatus")
        if self.outcome is not None:
            require_non_empty(self.outcome, "outcome")
        require_aware_utc(self.received_at, "received_at")
        validate_sync_fields(
            self.sync,
            scope=self.scope,
            origin_runtime_id=self.origin_runtime_id,
            object_id=self.receipt_id,
        )

    def sync_fields(self) -> SyncFields:
        """Return the action receipt synchronization identity."""

        return self.sync


@dataclass(frozen=True, slots=True)
class DeliveryReceipt:
    """Records the delivery state of one outbound message."""

    receipt_id: str
    scope: Scope
    origin_runtime_id: str
    message_id: str
    delivery_status: DeliveryStatus
    delivered_at: datetime | None
    sync: SyncFields

    def __post_init__(self) -> None:
        for field_name in ("receipt_id", "origin_runtime_id", "message_id"):
            require_non_empty(getattr(self, field_name), field_name)
        if not isinstance(self.delivery_status, DeliveryStatus):
            raise ValueError("delivery_status must be a DeliveryStatus")
        if self.delivered_at is not None:
            require_aware_utc(self.delivered_at, "delivered_at")
        validate_sync_fields(
            self.sync,
            scope=self.scope,
            origin_runtime_id=self.origin_runtime_id,
            object_id=self.receipt_id,
        )

    def sync_fields(self) -> SyncFields:
        """Return the delivery receipt synchronization identity."""

        return self.sync
