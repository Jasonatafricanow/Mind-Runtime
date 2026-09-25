"""Durable backend for the D3 factual plane (V0.1.4 first-batch tables).

The frozen V0.1.4 D3 baseline requires append-only persistence for the first
batch of tables: ``interactions``, ``evidence``, ``observations``. The D3
implementation draft deviated to in-memory stores; this module restores the
baseline using stdlib SQLite (zero runtime dependencies).

Semantics:

- Append-only: rows are inserted, never updated or deleted. The only
  exception is ``interactions``, whose lifecycle transitions (OPEN ->
  COMMITTED/ABORTED) legitimately rewrite the row for the same
  ``interaction_id``.
- Idempotency: ``(scope, id)`` is the primary key; duplicate inserts are
  rejected and reported as ``False``.
- Transaction boundary: every logical write is one SQLite transaction. An
  admitted Evidence + Observation pair is written atomically by
  ``save_admission``; rejected Evidence is persisted alone so the audit
  trail survives. A crash between the two inserts is recovered by idempotent
  replay (see D3.C3).
"""

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Protocol, cast, runtime_checkable

from mind_runtime.contracts import (
    Authority,
    AuthorityLevel,
    EffectiveWindow,
    EffectiveWindowKind,
    Evidence,
    Interaction,
    InteractionStatus,
    Observation,
    ObservationModality,
    Scope,
    ScopeDomain,
    SemanticDaypart,
    SemanticPrecision,
    SemanticRelation,
    SemanticTime,
    SyncFields,
)
from mind_runtime.contracts.common import FrozenMapping

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
CREATE TABLE IF NOT EXISTS interactions (
    interaction_id TEXT PRIMARY KEY,
    scope_domain TEXT NOT NULL,
    scope_user_id TEXT NOT NULL DEFAULT '',
    scope_agent_id TEXT NOT NULL DEFAULT '',
    scope_persona_id TEXT NOT NULL DEFAULT '',
    scope_relationship_id TEXT NOT NULL DEFAULT '',
    scope_world_id TEXT NOT NULL DEFAULT '',
    scope_interaction_id TEXT NOT NULL DEFAULT '',
    channel TEXT NOT NULL,
    session_id TEXT NOT NULL,
    turn_id TEXT NOT NULL,
    started_at TEXT NOT NULL,
    committed_at TEXT,
    status TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS evidence (
    scope_domain TEXT NOT NULL,
    scope_user_id TEXT NOT NULL DEFAULT '',
    scope_agent_id TEXT NOT NULL DEFAULT '',
    scope_persona_id TEXT NOT NULL DEFAULT '',
    scope_relationship_id TEXT NOT NULL DEFAULT '',
    scope_world_id TEXT NOT NULL DEFAULT '',
    scope_interaction_id TEXT NOT NULL DEFAULT '',
    id TEXT NOT NULL,
    origin_runtime_id TEXT NOT NULL,
    source_type TEXT NOT NULL,
    source_id TEXT NOT NULL,
    authority_level TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    received_at TEXT NOT NULL,
    payload TEXT NOT NULL,
    interaction_id TEXT NOT NULL,
    sync_version INTEGER NOT NULL,
    sync_idem_key TEXT NOT NULL,
    PRIMARY KEY (
        scope_domain, scope_user_id, scope_agent_id, scope_persona_id,
        scope_relationship_id, scope_world_id, scope_interaction_id, id
    )
);
CREATE TABLE IF NOT EXISTS observations (
    scope_domain TEXT NOT NULL,
    scope_user_id TEXT NOT NULL DEFAULT '',
    scope_agent_id TEXT NOT NULL DEFAULT '',
    scope_persona_id TEXT NOT NULL DEFAULT '',
    scope_relationship_id TEXT NOT NULL DEFAULT '',
    scope_world_id TEXT NOT NULL DEFAULT '',
    scope_interaction_id TEXT NOT NULL DEFAULT '',
    id TEXT NOT NULL,
    interaction_id TEXT NOT NULL,
    origin_runtime_id TEXT NOT NULL,
    type TEXT NOT NULL,
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    confidence REAL NOT NULL,
    observed_at TEXT NOT NULL,
    evidence_refs TEXT NOT NULL,
    sync_version INTEGER NOT NULL,
    sync_idem_key TEXT NOT NULL,
    modality TEXT NOT NULL DEFAULT 'asserted',
    semantic_relation TEXT NOT NULL DEFAULT 'unresolved',
    semantic_precision TEXT NOT NULL DEFAULT 'unresolved',
    semantic_daypart TEXT NOT NULL DEFAULT '',
    effective_window_kind TEXT NOT NULL DEFAULT 'unresolved',
    effective_start_at TEXT NULL,
    effective_end_at TEXT NULL,
    PRIMARY KEY (
        scope_domain, scope_user_id, scope_agent_id, scope_persona_id,
        scope_relationship_id, scope_world_id, scope_interaction_id, id
    )
);
"""


def _jsonable(value: object) -> object:
    """Convert frozen immutable values to JSON-faithful structures.

    FrozenMapping and tuple round-trip losslessly through JSON (tuples come
    back as tuples via the contract freeze). bytes and frozenset cannot
    round-trip faithfully, so they are rejected loudly instead of being
    silently corrupted.
    """
    if isinstance(value, FrozenMapping):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, (bytes, frozenset)):
        raise ValueError(f"durable store cannot round-trip {type(value).__name__} values")
    return value


def _to_json(value: object) -> str:
    """Serialize an immutable value deterministically for durable storage."""
    try:
        return json.dumps(_jsonable(value), ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError) as error:
        raise ValueError(f"durable store requires JSON-serializable values: {error}") from error


def _from_json(text: str) -> object:
    return json.loads(text)


def _format_dt(value: datetime) -> str:
    return value.isoformat()


def _parse_dt(text: str) -> datetime:
    return datetime.fromisoformat(text)


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


def _scope_where(alias: str = "") -> str:
    """SQL WHERE fragment matching the full scope columns ('' matches NULL-ish)."""
    prefix = f"{alias}." if alias else ""
    return " AND ".join(f"{prefix}{column} = ?" for column in _SCOPE_COLUMNS)


def _scope_from_row(row: sqlite3.Row) -> Scope:
    kwargs: dict[str, str] = {}
    for column, field_name in zip(_SCOPE_COLUMNS[1:], _SCOPE_FIELD_NAMES, strict=True):
        value = row[column]
        if value:
            kwargs[field_name] = value
    return Scope(domain=ScopeDomain(row["scope_domain"]), **kwargs)


def _sync_from_row(row: sqlite3.Row, scope: Scope, object_id: str) -> SyncFields:
    return SyncFields(
        scope,
        row["origin_runtime_id"],
        object_id,
        row["sync_version"],
        row["sync_idem_key"],
    )


def _evidence_from_row(row: sqlite3.Row) -> tuple[Evidence, str]:
    scope = _scope_from_row(row)
    level = AuthorityLevel(row["authority_level"])
    authority_source = None if level is AuthorityLevel.NONE else row["source_id"]
    evidence = Evidence(
        id=row["id"],
        scope=scope,
        origin_runtime_id=row["origin_runtime_id"],
        source_type=row["source_type"],
        source_id=row["source_id"],
        authority_level=level,
        authority=Authority(scope, level, authority_source),
        occurred_at=_parse_dt(row["occurred_at"]),
        received_at=_parse_dt(row["received_at"]),
        payload=_from_json(row["payload"]),
        sync=_sync_from_row(row, scope, row["id"]),
    )
    return evidence, row["interaction_id"]


def _observation_columns() -> tuple[str, ...]:
    return (
        *_SCOPE_COLUMNS,
        "id",
        "interaction_id",
        "origin_runtime_id",
        "type",
        "key",
        "value",
        "confidence",
        "observed_at",
        "evidence_refs",
        "sync_version",
        "sync_idem_key",
        "modality",
        "semantic_relation",
        "semantic_precision",
        "semantic_daypart",
        "effective_window_kind",
        "effective_start_at",
        "effective_end_at",
    )


def _observation_values(observation: Observation) -> tuple[object, ...]:
    modality_val = observation.modality.value
    rel_val = observation.semantic_time.relation.value
    prec_val = observation.semantic_time.precision.value
    daypart_val = (
        observation.semantic_time.daypart.value
        if observation.semantic_time.daypart is not None
        else ""
    )
    if observation.effective_window is None:
        window_kind_val = "unresolved"
        start_at_val = None
        end_at_val = None
    else:
        window_kind_val = observation.effective_window.kind.value
        start_at_val = _format_dt(observation.effective_window.start_at)
        end_at_val = (
            _format_dt(observation.effective_window.end_at)
            if observation.effective_window.end_at is not None
            else None
        )

    return (
        *_scope_values(observation.scope),
        observation.id,
        observation.interaction_id,
        observation.origin_runtime_id,
        observation.type,
        observation.key,
        _to_json(observation.value),
        observation.confidence,
        _format_dt(observation.observed_at),
        _to_json(observation.evidence_refs),
        observation.sync.version,
        observation.sync.idempotency_key,
        modality_val,
        rel_val,
        prec_val,
        daypart_val,
        window_kind_val,
        start_at_val,
        end_at_val,
    )


def _observation_from_row(row: sqlite3.Row) -> Observation:
    scope = _scope_from_row(row)
    keys = row.keys() if hasattr(row, "keys") else ()
    modality_val = row["modality"] if "modality" in keys else "asserted"
    rel_val = row["semantic_relation"] if "semantic_relation" in keys else "unresolved"
    prec_val = row["semantic_precision"] if "semantic_precision" in keys else "unresolved"
    daypart_val = row["semantic_daypart"] if "semantic_daypart" in keys else ""
    window_kind_val = (
        row["effective_window_kind"] if "effective_window_kind" in keys else "unresolved"
    )
    start_at_val = row["effective_start_at"] if "effective_start_at" in keys else None
    end_at_val = row["effective_end_at"] if "effective_end_at" in keys else None

    modality = ObservationModality(modality_val)
    daypart = SemanticDaypart(daypart_val) if daypart_val else None
    semantic_time = SemanticTime(
        relation=SemanticRelation(rel_val),
        precision=SemanticPrecision(prec_val),
        daypart=daypart,
    )
    if window_kind_val == "unresolved" or not window_kind_val:
        effective_window = None
    else:
        effective_window = EffectiveWindow(
            kind=EffectiveWindowKind(window_kind_val),
            start_at=_parse_dt(start_at_val) if start_at_val else _parse_dt(row["observed_at"]),
            end_at=_parse_dt(end_at_val) if end_at_val else None,
        )

    return Observation(
        id=row["id"],
        interaction_id=row["interaction_id"],
        scope=scope,
        origin_runtime_id=row["origin_runtime_id"],
        type=row["type"],
        key=row["key"],
        value=_from_json(row["value"]),
        confidence=row["confidence"],
        observed_at=_parse_dt(row["observed_at"]),
        evidence_refs=tuple(cast(list[str], _from_json(row["evidence_refs"]))),
        sync=_sync_from_row(row, scope, row["id"]),
        modality=modality,
        semantic_time=semantic_time,
        effective_window=effective_window,
    )


def _interaction_from_row(row: sqlite3.Row) -> Interaction:
    committed_at = _parse_dt(row["committed_at"]) if row["committed_at"] else None
    return Interaction(
        interaction_id=row["interaction_id"],
        scope=_scope_from_row(row),
        channel=row["channel"],
        session_id=row["session_id"],
        turn_id=row["turn_id"],
        started_at=_parse_dt(row["started_at"]),
        committed_at=committed_at,
        status=InteractionStatus(row["status"]),
    )


@runtime_checkable
class FactBackend(Protocol):
    """Durable append-only storage for the D3 factual plane."""

    def load_interactions(self) -> tuple[Interaction, ...]:
        """Return every stored interaction, oldest first."""
        ...

    def save_interaction(self, interaction: Interaction) -> None:
        """Insert or lifecycle-update one interaction (idempotent)."""
        ...

    def load_evidence(self) -> tuple[tuple[Evidence, str], ...]:
        """Return (evidence, interaction_id) pairs, oldest first."""
        ...

    def save_evidence(self, evidence: Evidence, *, interaction_id: str) -> bool:
        """Insert one Evidence row; False when (scope, id) already exists."""
        ...

    def load_observations(self) -> tuple[Observation, ...]:
        """Return every stored observation, oldest first."""
        ...

    def save_observation(self, observation: Observation) -> bool:
        """Insert one Observation row; False when (scope, id) already exists."""
        ...

    def find_evidence(self, scope: Scope, evidence_id: str) -> tuple[Evidence, str] | None:
        """Return the exact stored (Evidence, interaction_id) or None.

        Read-only arbitration lookup (ADR-0009 §5): the backend stays
        append-only, never a mutable repository.
        """
        ...

    def find_observation(self, scope: Scope, observation_id: str) -> Observation | None:
        """Return the exact stored Observation or None (read-only lookup)."""
        ...

    def save_admission(
        self,
        evidence: Evidence,
        *,
        interaction_id: str,
        observation: Observation,
    ) -> bool:
        """Atomically insert the admitted Evidence + Observation pair.

        One transaction: a duplicate Evidence rolls the whole pair back.
        """
        ...


class SqliteFactBackend:
    """SQLite-backed ``FactBackend`` keeping the exact first-batch tables."""

    def __init__(self, path: str | Path) -> None:
        self._path = str(path)
        self._conn = sqlite3.connect(self._path)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._migrate_observations()

    def _migrate_observations(self) -> None:
        """Additive non-destructive migration for observations columns."""
        rows = self._conn.execute("PRAGMA table_info(observations)").fetchall()
        existing_cols = {row["name"] for row in rows}
        new_cols = [
            ("modality", "TEXT NOT NULL DEFAULT 'asserted'"),
            ("semantic_relation", "TEXT NOT NULL DEFAULT 'unresolved'"),
            ("semantic_precision", "TEXT NOT NULL DEFAULT 'unresolved'"),
            ("semantic_daypart", "TEXT NOT NULL DEFAULT ''"),
            ("effective_window_kind", "TEXT NOT NULL DEFAULT 'unresolved'"),
            ("effective_start_at", "TEXT NULL"),
            ("effective_end_at", "TEXT NULL"),
        ]
        with self._conn:
            for col_name, col_def in new_cols:
                if col_name not in existing_cols:
                    self._conn.execute(f"ALTER TABLE observations ADD COLUMN {col_name} {col_def}")

    def close(self) -> None:
        """Close the underlying connection."""
        self._conn.close()

    def table_names(self) -> tuple[str, ...]:
        """Return the physical table names (must stay the first-batch three)."""
        rows = self._conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"
        ).fetchall()
        return tuple(row["name"] for row in rows)

    # --- interactions ---

    def load_interactions(self) -> tuple[Interaction, ...]:
        rows = self._conn.execute(
            "SELECT * FROM interactions ORDER BY started_at, interaction_id"
        ).fetchall()
        return tuple(_interaction_from_row(row) for row in rows)

    def save_interaction(self, interaction: Interaction) -> None:
        with self._conn:
            self._conn.execute(
                "INSERT OR REPLACE INTO interactions ("
                f"{', '.join(_SCOPE_COLUMNS)}, interaction_id, channel, session_id,"
                " turn_id, started_at, committed_at, status"
                ") VALUES ("
                f"{', '.join('?' * 7)}, ?, ?, ?, ?, ?, ?, ?"
                ")",
                (
                    *_scope_values(interaction.scope),
                    interaction.interaction_id,
                    interaction.channel,
                    interaction.session_id,
                    interaction.turn_id,
                    _format_dt(interaction.started_at),
                    _format_dt(interaction.committed_at)
                    if interaction.committed_at is not None
                    else None,
                    interaction.status.value,
                ),
            )

    # --- evidence ---

    def load_evidence(self) -> tuple[tuple[Evidence, str], ...]:
        rows = self._conn.execute("SELECT * FROM evidence ORDER BY received_at, id").fetchall()
        return tuple(_evidence_from_row(row) for row in rows)

    def save_evidence(self, evidence: Evidence, *, interaction_id: str) -> bool:
        try:
            with self._conn:
                self._conn.execute(
                    "INSERT INTO evidence ("
                    f"{', '.join(_SCOPE_COLUMNS)}, id, origin_runtime_id, source_type,"
                    " source_id, authority_level, occurred_at, received_at, payload,"
                    " interaction_id, sync_version, sync_idem_key"
                    ") VALUES ("
                    f"{', '.join('?' * 7)}, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?"
                    ")",
                    (
                        *_scope_values(evidence.scope),
                        evidence.id,
                        evidence.origin_runtime_id,
                        evidence.source_type,
                        evidence.source_id,
                        evidence.authority_level.value,
                        _format_dt(evidence.occurred_at),
                        _format_dt(evidence.received_at),
                        _to_json(evidence.payload),
                        interaction_id,
                        evidence.sync.version,
                        evidence.sync.idempotency_key,
                    ),
                )
            return True
        except sqlite3.IntegrityError:
            return False

    # --- observations ---

    def load_observations(self) -> tuple[Observation, ...]:
        rows = self._conn.execute("SELECT * FROM observations ORDER BY observed_at, id").fetchall()
        return tuple(_observation_from_row(row) for row in rows)

    def save_observation(self, observation: Observation) -> bool:
        cols = _observation_columns()
        placeholders = ", ".join("?" * len(cols))
        try:
            with self._conn:
                self._conn.execute(
                    f"INSERT INTO observations ({', '.join(cols)}) VALUES ({placeholders})",
                    _observation_values(observation),
                )
            return True
        except sqlite3.IntegrityError:
            return False

    # --- exact read-only lookups (ADR-0009 arbitration) ---

    def find_evidence(self, scope: Scope, evidence_id: str) -> tuple[Evidence, str] | None:
        row = self._conn.execute(
            f"SELECT * FROM evidence WHERE {_scope_where()} AND id = ?",
            (*_scope_values(scope), evidence_id),
        ).fetchone()
        return _evidence_from_row(row) if row is not None else None

    def find_observation(self, scope: Scope, observation_id: str) -> Observation | None:
        row = self._conn.execute(
            f"SELECT * FROM observations WHERE {_scope_where()} AND id = ?",
            (*_scope_values(scope), observation_id),
        ).fetchone()
        return _observation_from_row(row) if row is not None else None

    # --- atomic admission pair ---

    def save_admission(
        self,
        evidence: Evidence,
        *,
        interaction_id: str,
        observation: Observation,
    ) -> bool:
        cols = _observation_columns()
        placeholders = ", ".join("?" * len(cols))
        try:
            with self._conn:
                self._conn.execute(
                    "INSERT INTO evidence ("
                    f"{', '.join(_SCOPE_COLUMNS)}, id, origin_runtime_id, source_type,"
                    " source_id, authority_level, occurred_at, received_at, payload,"
                    " interaction_id, sync_version, sync_idem_key"
                    ") VALUES ("
                    f"{', '.join('?' * 7)}, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?"
                    ")",
                    (
                        *_scope_values(evidence.scope),
                        evidence.id,
                        evidence.origin_runtime_id,
                        evidence.source_type,
                        evidence.source_id,
                        evidence.authority_level.value,
                        _format_dt(evidence.occurred_at),
                        _format_dt(evidence.received_at),
                        _to_json(evidence.payload),
                        interaction_id,
                        evidence.sync.version,
                        evidence.sync.idempotency_key,
                    ),
                )
                self._conn.execute(
                    f"INSERT INTO observations ({', '.join(cols)}) VALUES ({placeholders})",
                    _observation_values(observation),
                )
            return True
        except sqlite3.IntegrityError:
            return False
