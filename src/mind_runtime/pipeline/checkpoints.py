"""TurnCheckpoint stores and restart recovery decisions (D5.4).

A checkpoint records the recoverable stage of one interaction
(processing / dispatching / awaiting_commit). Recovery rules frozen by the
baseline:

- an AWAITING_COMMIT checkpoint means the projection was never committed —
  it must NOT be treated as committed after restart;
- a DISPATCHING checkpoint with a SENT receipt must be reconciled to
  completion, never silently aborted;
- a DISPATCHING checkpoint with UNKNOWN delivery must not be silently
  aborted either — the delivery state stays explicit;
- a DISPATCHING checkpoint with UNSENT delivery may be safely aborted.
"""

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol, runtime_checkable

from mind_runtime.contracts import (
    DeliveryStatus,
    Scope,
    ScopeDomain,
    SyncFields,
    TurnCheckpoint,
    TurnStage,
)

_SCOPE_COLUMNS = (
    "scope_domain",
    "scope_user_id",
    "scope_agent_id",
    "scope_persona_id",
    "scope_relationship_id",
    "scope_world_id",
    "scope_interaction_id",
)

_SCOPE_FIELD_NAMES = (
    "user_id",
    "agent_id",
    "persona_id",
    "relationship_id",
    "world_id",
    "interaction_id",
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS checkpoints (
    checkpoint_id TEXT PRIMARY KEY,
    interaction_id TEXT NOT NULL,
    scope_domain TEXT NOT NULL,
    scope_user_id TEXT NOT NULL DEFAULT '',
    scope_agent_id TEXT NOT NULL DEFAULT '',
    scope_persona_id TEXT NOT NULL DEFAULT '',
    scope_relationship_id TEXT NOT NULL DEFAULT '',
    scope_world_id TEXT NOT NULL DEFAULT '',
    scope_interaction_id TEXT NOT NULL DEFAULT '',
    origin_runtime_id TEXT NOT NULL,
    stage TEXT NOT NULL,
    base_state_version INTEGER NOT NULL,
    projection_ref TEXT NOT NULL,
    action_id TEXT,
    delivery_status TEXT NOT NULL,
    checkpointed_at TEXT NOT NULL,
    sync_version INTEGER NOT NULL,
    sync_idem_key TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS checkpoints_interaction_idx
    ON checkpoints (interaction_id);
"""


def _scope_values(scope: Scope) -> tuple[str, ...]:
    return (
        scope.domain.value,
        scope.user_id or "",
        scope.agent_id or "",
        scope.persona_id or "",
        scope.relationship_id or "",
        scope.world_id or "",
        scope.interaction_id or "",
    )


def _scope_from_row(row: sqlite3.Row) -> Scope:
    kwargs: dict[str, str] = {}
    for column, field_name in zip(_SCOPE_COLUMNS[1:], _SCOPE_FIELD_NAMES, strict=True):
        value = row[column]
        if value:
            kwargs[field_name] = value
    return Scope(domain=ScopeDomain(row["scope_domain"]), **kwargs)


def _checkpoint_from_row(row: sqlite3.Row) -> TurnCheckpoint:
    scope = _scope_from_row(row)
    return TurnCheckpoint(
        checkpoint_id=row["checkpoint_id"],
        interaction_id=row["interaction_id"],
        scope=scope,
        origin_runtime_id=row["origin_runtime_id"],
        stage=TurnStage(row["stage"]),
        base_state_version=row["base_state_version"],
        projection_ref=row["projection_ref"],
        action_id=row["action_id"],
        delivery_status=DeliveryStatus(row["delivery_status"]),
        checkpointed_at=datetime.fromisoformat(row["checkpointed_at"]),
        sync=SyncFields(
            scope,
            row["origin_runtime_id"],
            row["checkpoint_id"],
            row["sync_version"],
            row["sync_idem_key"],
        ),
    )


@runtime_checkable
class CheckpointStore(Protocol):
    """Durable storage for one checkpoint per interaction."""

    def save(self, checkpoint: TurnCheckpoint) -> None:
        """Insert or replace the checkpoint for its interaction."""
        ...

    def load(self, interaction_id: str) -> TurnCheckpoint | None:
        """Return the interaction's checkpoint or None."""
        ...

    def remove(self, interaction_id: str) -> None:
        """Drop the interaction's checkpoint (turn finished)."""
        ...


class InMemoryCheckpointStore:
    """Non-durable checkpoint store for tests and ephemeral runs."""

    def __init__(self) -> None:
        self._checkpoints: dict[str, TurnCheckpoint] = {}

    def save(self, checkpoint: TurnCheckpoint) -> None:
        self._checkpoints[checkpoint.interaction_id] = checkpoint

    def load(self, interaction_id: str) -> TurnCheckpoint | None:
        return self._checkpoints.get(interaction_id)

    def remove(self, interaction_id: str) -> None:
        self._checkpoints.pop(interaction_id, None)

    def all(self) -> tuple[TurnCheckpoint, ...]:
        return tuple(self._checkpoints.values())


class SqliteCheckpointStore:
    """SQLite-backed checkpoint store (one row per interaction)."""

    def __init__(self, path: str | Path) -> None:
        self._conn = sqlite3.connect(str(path))
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)

    def close(self) -> None:
        self._conn.close()

    def table_names(self) -> tuple[str, ...]:
        rows = self._conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"
        ).fetchall()
        return tuple(row["name"] for row in rows)

    def save(self, checkpoint: TurnCheckpoint) -> None:
        with self._conn:
            self._conn.execute(
                "INSERT OR REPLACE INTO checkpoints ("
                f"{', '.join(_SCOPE_COLUMNS)}, checkpoint_id, interaction_id,"
                " origin_runtime_id, stage, base_state_version, projection_ref,"
                " action_id, delivery_status, checkpointed_at, sync_version,"
                " sync_idem_key"
                ") VALUES ("
                f"{', '.join('?' * 7)}, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?"
                ")",
                (
                    *_scope_values(checkpoint.scope),
                    checkpoint.checkpoint_id,
                    checkpoint.interaction_id,
                    checkpoint.origin_runtime_id,
                    checkpoint.stage.value,
                    checkpoint.base_state_version,
                    checkpoint.projection_ref,
                    checkpoint.action_id,
                    checkpoint.delivery_status.value,
                    checkpoint.checkpointed_at.isoformat(),
                    checkpoint.sync.version,
                    checkpoint.sync.idempotency_key,
                ),
            )

    def load(self, interaction_id: str) -> TurnCheckpoint | None:
        row = self._conn.execute(
            "SELECT * FROM checkpoints WHERE interaction_id = ?", (interaction_id,)
        ).fetchone()
        return _checkpoint_from_row(row) if row is not None else None

    def remove(self, interaction_id: str) -> None:
        with self._conn:
            self._conn.execute(
                "DELETE FROM checkpoints WHERE interaction_id = ?", (interaction_id,)
            )


@dataclass(frozen=True)
class RecoveryDecision:
    """What a restart may do with a checkpointed turn (D5.4)."""

    interaction_id: str
    stage: TurnStage | None
    delivery_status: DeliveryStatus | None
    action: str


def recovery_decision(checkpoint: TurnCheckpoint | None) -> RecoveryDecision:
    """Decide the restart action for one checkpoint (fail closed)."""
    if checkpoint is None:
        return RecoveryDecision(
            interaction_id="",
            stage=None,
            delivery_status=None,
            action="no_checkpoint",
        )
    if checkpoint.stage is TurnStage.AWAITING_COMMIT:
        return RecoveryDecision(
            interaction_id=checkpoint.interaction_id,
            stage=checkpoint.stage,
            delivery_status=checkpoint.delivery_status,
            action="not_committed",
        )
    if checkpoint.stage is TurnStage.DISPATCHING:
        if checkpoint.delivery_status is DeliveryStatus.SENT:
            return RecoveryDecision(
                interaction_id=checkpoint.interaction_id,
                stage=checkpoint.stage,
                delivery_status=checkpoint.delivery_status,
                action="reconcile_complete",
            )
        if checkpoint.delivery_status is DeliveryStatus.UNKNOWN:
            return RecoveryDecision(
                interaction_id=checkpoint.interaction_id,
                stage=checkpoint.stage,
                delivery_status=checkpoint.delivery_status,
                action="delivery_unknown",
            )
        return RecoveryDecision(
            interaction_id=checkpoint.interaction_id,
            stage=checkpoint.stage,
            delivery_status=checkpoint.delivery_status,
            action="safe_abort",
        )
    return RecoveryDecision(
        interaction_id=checkpoint.interaction_id,
        stage=checkpoint.stage,
        delivery_status=checkpoint.delivery_status,
        action="processing_incomplete",
    )
