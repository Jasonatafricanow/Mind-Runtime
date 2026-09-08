"""Interaction lifecycle contract."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from mind_runtime.contracts.scope import Scope


class InteractionStatus(StrEnum):
    """Lifecycle status for an interaction."""

    OPEN = "open"
    COMMITTED = "committed"
    ABORTED = "aborted"


def _require_aware_utc(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError(f"{field_name} must be aware UTC")


def _is_non_empty(value: str) -> bool:
    return isinstance(value, str) and bool(value.strip())


@dataclass(frozen=True, slots=True)
class Interaction:
    """Local causal index for a single interaction lifecycle."""

    interaction_id: str
    scope: Scope
    channel: str
    session_id: str
    turn_id: str
    started_at: datetime
    committed_at: datetime | None
    status: InteractionStatus

    def __post_init__(self) -> None:
        if not isinstance(self.status, InteractionStatus):
            raise ValueError("status must be an InteractionStatus")

        for field_name in ("interaction_id", "channel", "session_id", "turn_id"):
            if not _is_non_empty(getattr(self, field_name)):
                raise ValueError(f"{field_name} must be non-empty")

        _require_aware_utc(self.started_at, "started_at")

        if self.status is InteractionStatus.COMMITTED:
            if self.committed_at is None:
                raise ValueError("committed status requires committed_at")
            _require_aware_utc(self.committed_at, "committed_at")
            if self.committed_at < self.started_at:
                raise ValueError("committed_at cannot precede started_at")
        elif self.committed_at is not None:
            raise ValueError(f"{self.status.value} forbids committed_at")
