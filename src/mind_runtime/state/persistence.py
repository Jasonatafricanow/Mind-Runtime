"""Durable SQLite backend for the D4 state plane.

The V0.1.4 D4 baseline requires the tables ``states`` /
``state_transitions`` / ``state_definitions``. Following the D3.C2 pattern:

- ``states`` holds every canonical state record (append-only, keyed by
  ``(scope, state_id)``); the current state of a dimension is the record
  with the highest ``version``.
- ``state_transitions`` is append-only, keyed by ``transition_id``.
- ``state_definitions`` is upserted by ``(domain, key)`` (the definitions
  authority).

Stdlib SQLite only: zero runtime dependencies.
"""

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Protocol, cast, runtime_checkable

from mind_runtime.contracts import (
    RuntimeState,
    Scope,
    ScopeDomain,
    StateDefinition,
    StateDomain,
    StateTransition,
    StateValueType,
    SyncFields,
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


def canonical_state_rows_equal(left: RuntimeState, right: RuntimeState) -> bool:
    """Compare durable canonical rows for persistence idempotency only.

    This is a storage-authority operation, not effective-state resolution and
    not a consumer-facing status read.  The orchestrator uses it only after a
    durable insert reports an existing ``state_id`` so an identical admitted
    row can be treated as an idempotent replay while a different row remains a
    stale-writer conflict.
    """

    return (
        left.state_id == right.state_id
        and left.scope == right.scope
        and left.dimension == right.dimension
        and left.version == right.version
        and left.status == right.status
        and left.value == right.value
        and left.origin_runtime_id == right.origin_runtime_id
    )

_SCHEMA = """
CREATE TABLE IF NOT EXISTS state_definitions (
    domain TEXT NOT NULL,
    key TEXT NOT NULL,
    value_type TEXT NOT NULL,
    dynamics_policy TEXT NOT NULL,
    default_validity_policy TEXT,
    bounds TEXT,
    PRIMARY KEY (domain, key)
);
CREATE TABLE IF NOT EXISTS states (
    scope_domain TEXT NOT NULL,
    scope_user_id TEXT NOT NULL DEFAULT '',
    scope_agent_id TEXT NOT NULL DEFAULT '',
    scope_persona_id TEXT NOT NULL DEFAULT '',
    scope_relationship_id TEXT NOT NULL DEFAULT '',
    scope_world_id TEXT NOT NULL DEFAULT '',
    scope_interaction_id TEXT NOT NULL DEFAULT '',
    state_id TEXT NOT NULL,
    dimension TEXT NOT NULL,
    status TEXT NOT NULL,
    value TEXT NOT NULL,
    valid_from TEXT NOT NULL,
    valid_until TEXT,
    relevant_until TEXT,
    last_observed_at TEXT NOT NULL,
    evidence_refs TEXT NOT NULL,
    transition_refs TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    origin_runtime_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    sync_version INTEGER NOT NULL,
    sync_idem_key TEXT NOT NULL,
    PRIMARY KEY (
        scope_domain, scope_user_id, scope_agent_id, scope_persona_id,
        scope_relationship_id, scope_world_id, scope_interaction_id, state_id
    )
);
CREATE TABLE IF NOT EXISTS state_transitions (
    transition_id TEXT PRIMARY KEY,
    scope_domain TEXT NOT NULL,
    scope_user_id TEXT NOT NULL DEFAULT '',
    scope_agent_id TEXT NOT NULL DEFAULT '',
    scope_persona_id TEXT NOT NULL DEFAULT '',
    scope_relationship_id TEXT NOT NULL DEFAULT '',
    scope_world_id TEXT NOT NULL DEFAULT '',
    scope_interaction_id TEXT NOT NULL DEFAULT '',
    origin_runtime_id TEXT NOT NULL,
    intent_id TEXT NOT NULL,
    from_state_id TEXT NOT NULL,
    to_state_id TEXT NOT NULL,
    committed_at TEXT NOT NULL,
    sync_version INTEGER NOT NULL,
    sync_idem_key TEXT NOT NULL
);
-- C10-B-W: rolling-window ledger of qualifying slow-plasticity contributions.
-- One row per qualifying HomeostasisDecision with SLOW_ACCEPT disposition.
-- Persisted in the shared state.db (same file as `states` and `state_transitions`);
-- written in the same SQLite transaction as the canonical RuntimeState update.
-- The window is the latest-N per (scope, dimension) ordered by accepted_at.
CREATE TABLE IF NOT EXISTS slow_contribution_window (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scope_domain TEXT NOT NULL,
    scope_user_id TEXT NOT NULL DEFAULT '',
    scope_agent_id TEXT NOT NULL DEFAULT '',
    scope_persona_id TEXT NOT NULL DEFAULT '',
    scope_relationship_id TEXT NOT NULL DEFAULT '',
    scope_world_id TEXT NOT NULL DEFAULT '',
    scope_interaction_id TEXT NOT NULL DEFAULT '',
    target_dimension TEXT NOT NULL,
    sequence INTEGER NOT NULL,
    accepted_at TEXT NOT NULL,
    proposed_value REAL NOT NULL,
    salience REAL NOT NULL,
    evidence_refs TEXT NOT NULL,
    source_event_ref TEXT,
    source_decision_id TEXT NOT NULL,
    UNIQUE (
        scope_domain, scope_user_id, scope_agent_id, scope_persona_id,
        scope_relationship_id, scope_world_id, scope_interaction_id,
        target_dimension, sequence
    )
);
CREATE INDEX IF NOT EXISTS idx_slow_window_ordering
    ON slow_contribution_window (
        scope_domain, scope_user_id, scope_agent_id, scope_persona_id,
        scope_relationship_id, scope_world_id, scope_interaction_id,
        target_dimension, accepted_at
    );
"""


def _to_json(value: object) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError) as error:
        raise ValueError(
            f"durable state store requires JSON-serializable values: {error}"
        ) from error


def _from_json(text: str) -> object:
    return json.loads(text)


def _format_dt(value: datetime) -> str:
    return value.isoformat()


def _parse_dt(text: str | None) -> datetime | None:
    return datetime.fromisoformat(text) if text else None


def _parse_required_dt(text: str) -> datetime:
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


def _scope_from_row(row: sqlite3.Row) -> Scope:
    kwargs: dict[str, str] = {}
    for column, field_name in zip(_SCOPE_COLUMNS[1:], _SCOPE_FIELD_NAMES, strict=True):
        value = row[column]
        if value:
            kwargs[field_name] = value
    return Scope(domain=ScopeDomain(row["scope_domain"]), **kwargs)


def _state_from_row(row: sqlite3.Row) -> RuntimeState:
    scope = _scope_from_row(row)
    state_id = row["state_id"]
    return RuntimeState(
        state_id=state_id,
        scope=scope,
        dimension=row["dimension"],
        value=_from_json(row["value"]),
        status=row["status"],
        valid_from=_parse_required_dt(row["valid_from"]),
        valid_until=_parse_dt(row["valid_until"]),
        relevant_until=_parse_dt(row["relevant_until"]),
        last_observed_at=_parse_required_dt(row["last_observed_at"]),
        evidence_refs=tuple(cast(list[str], _from_json(row["evidence_refs"]))),
        transition_refs=tuple(cast(list[str], _from_json(row["transition_refs"]))),
        updated_at=_parse_required_dt(row["updated_at"]),
        origin_runtime_id=row["origin_runtime_id"],
        version=row["version"],
        sync=SyncFields(
            scope,
            row["origin_runtime_id"],
            state_id,
            row["sync_version"],
            row["sync_idem_key"],
        ),
    )


def _definition_from_row(row: sqlite3.Row) -> StateDefinition:
    bounds = _from_json(row["bounds"]) if row["bounds"] is not None else None
    return StateDefinition(
        key=row["key"],
        domain=StateDomain(row["domain"]),
        value_type=StateValueType(row["value_type"]),
        dynamics_policy=row["dynamics_policy"],
        default_validity_policy=row["default_validity_policy"],
        bounds=bounds,
    )


def _transition_from_rows(
    row: sqlite3.Row, states_by_id: dict[str, RuntimeState]
) -> StateTransition:
    scope = _scope_from_row(row)
    from_state = states_by_id.get(row["from_state_id"])
    to_state = states_by_id.get(row["to_state_id"])
    if from_state is None or to_state is None:
        raise ValueError(f"transition {row['transition_id']} references a missing state")
    transition_id = row["transition_id"]
    return StateTransition(
        transition_id=transition_id,
        scope=scope,
        origin_runtime_id=row["origin_runtime_id"],
        intent_id=row["intent_id"],
        from_state=from_state,
        to_state=to_state,
        committed_at=_parse_required_dt(row["committed_at"]),
        sync=SyncFields(
            scope,
            row["origin_runtime_id"],
            transition_id,
            row["sync_version"],
            row["sync_idem_key"],
        ),
    )


@runtime_checkable
class StateBackend(Protocol):
    """Durable append-only storage for the D4 state plane."""

    def load_definitions(self) -> tuple[StateDefinition, ...]: ...

    def save_definition(self, definition: StateDefinition) -> None: ...

    def load_states(self) -> tuple[RuntimeState, ...]: ...

    def save_state(self, state: RuntimeState) -> bool: ...

    def load_transitions(self) -> tuple[StateTransition, ...]: ...

    def save_transition(self, transition: StateTransition) -> bool: ...


class SqliteStateBackend:
    """SQLite-backed ``StateBackend`` keeping the D4 baseline tables."""

    def __init__(
        self,
        path: str | Path,
        *,
        connection: sqlite3.Connection | None = None,
    ) -> None:
        self._path = str(path)
        if connection is not None:
            self._conn = connection
            self._owns_conn = False
        else:
            self._conn = sqlite3.connect(self._path)
            self._owns_conn = True
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._in_transaction = False

    @property
    def connection(self) -> sqlite3.Connection:
        return self._conn

    def close(self) -> None:
        if self._owns_conn:
            self._conn.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Manage an outer atomic cognitive transaction.

        Nested cognitive transactions fail closed immediately.
        """
        if self._in_transaction or self._conn.in_transaction:
            raise RuntimeError("nested cognitive transaction forbidden")
        self._in_transaction = True
        self._conn.execute("BEGIN")
        try:
            yield self._conn
        except BaseException:
            self._conn.rollback()
            raise
        else:
            self._conn.commit()
        finally:
            self._in_transaction = False

    def table_names(self) -> tuple[str, ...]:
        rows = self._conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"
        ).fetchall()
        return tuple(row["name"] for row in rows)

    # --- definitions ---

    def load_definitions(self) -> tuple[StateDefinition, ...]:
        rows = self._conn.execute("SELECT * FROM state_definitions ORDER BY domain, key").fetchall()
        return tuple(_definition_from_row(row) for row in rows)

    def save_definition(self, definition: StateDefinition) -> None:
        with self._conn:
            self._conn.execute(
                "INSERT OR REPLACE INTO state_definitions ("
                "domain, key, value_type, dynamics_policy, default_validity_policy, bounds"
                ") VALUES (?, ?, ?, ?, ?, ?)",
                (
                    definition.domain.value,
                    definition.key,
                    definition.value_type.value,
                    definition.dynamics_policy,
                    definition.default_validity_policy,
                    _to_json(definition.bounds) if definition.bounds is not None else None,
                ),
            )

    # --- states ---

    def load_states(self) -> tuple[RuntimeState, ...]:
        rows = self._conn.execute("SELECT * FROM states ORDER BY dimension, version").fetchall()
        return tuple(_state_from_row(row) for row in rows)

    def _insert_state(self, state: RuntimeState) -> None:
        self._conn.execute(
            "INSERT INTO states ("
            f"{', '.join(_SCOPE_COLUMNS)}, state_id, dimension, status, value,"
            " valid_from, valid_until, relevant_until, last_observed_at,"
            " evidence_refs, transition_refs, updated_at, origin_runtime_id,"
            " version, sync_version, sync_idem_key"
            ") VALUES ("
            f"{', '.join('?' * 7)}, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?"
            ")",
            (
                *_scope_values(state.scope),
                state.state_id,
                state.dimension,
                state.status,
                _to_json(state.value),
                _format_dt(state.valid_from),
                _format_dt(state.valid_until) if state.valid_until is not None else None,
                _format_dt(state.relevant_until)
                if state.relevant_until is not None
                else None,
                _format_dt(state.last_observed_at),
                _to_json(state.evidence_refs),
                _to_json(state.transition_refs),
                _format_dt(state.updated_at),
                state.origin_runtime_id,
                state.version,
                state.sync.version,
                state.sync.idempotency_key,
            ),
        )

    def save_state(self, state: RuntimeState) -> bool:
        try:
            if self._in_transaction:
                self._insert_state(state)
            else:
                with self._conn:
                    self._insert_state(state)
            return True
        except sqlite3.IntegrityError:
            return False

    # --- transitions ---

    def load_transitions(self) -> tuple[StateTransition, ...]:
        states_by_id = {
            row["state_id"]: _state_from_row(row)
            for row in self._conn.execute("SELECT * FROM states").fetchall()
        }
        rows = self._conn.execute(
            "SELECT * FROM state_transitions ORDER BY committed_at, transition_id"
        ).fetchall()
        return tuple(_transition_from_rows(row, states_by_id) for row in rows)

    def _insert_transition(self, transition: StateTransition) -> None:
        self._conn.execute(
            "INSERT INTO state_transitions ("
            f"{', '.join(_SCOPE_COLUMNS)}, transition_id, origin_runtime_id,"
            " intent_id, from_state_id, to_state_id, committed_at,"
            " sync_version, sync_idem_key"
            ") VALUES ("
            f"{', '.join('?' * 7)}, ?, ?, ?, ?, ?, ?, ?, ?"
            ")",
            (
                *_scope_values(transition.scope),
                transition.transition_id,
                transition.origin_runtime_id,
                transition.intent_id,
                transition.from_state.state_id,
                transition.to_state.state_id,
                _format_dt(transition.committed_at),
                transition.sync.version,
                transition.sync.idempotency_key,
            ),
        )

    def save_transition(self, transition: StateTransition) -> bool:
        try:
            if self._in_transaction:
                self._insert_transition(transition)
            else:
                with self._conn:
                    self._insert_transition(transition)
            return True
        except sqlite3.IntegrityError:
            return False

    # --- C10-B-W slow contribution window ---

    def load_slow_window(
        self,
        scope: Scope,
        target_dimension: str,
    ) -> tuple[dict, ...]:
        """Return the persisted slow-window rows for one (scope, dimension).

        Ordered by accepted_at ascending; capped by the caller's window_size
        after the call (this method returns the FULL persisted buffer so the
        writer can detect trim/append).
        """
        scope_vals = _scope_values(scope)
        rows = self._conn.execute(
            "SELECT * FROM slow_contribution_window WHERE "
            f"{' AND '.join(f'{col} = ?' for col in _SCOPE_COLUMNS)}"
            " AND target_dimension = ? ORDER BY accepted_at ASC, id ASC",
            (*scope_vals, target_dimension),
        ).fetchall()
        return tuple(
            {
                "id": row["id"],
                "sequence": row["sequence"],
                "accepted_at": _parse_required_dt(row["accepted_at"]),
                "proposed_value": row["proposed_value"],
                "salience": row["salience"],
                "evidence_refs": tuple(cast(list[str], _from_json(row["evidence_refs"]))),
                "source_event_ref": row["source_event_ref"],
                "source_decision_id": row["source_decision_id"],
            }
            for row in rows
        )

    def load_slow_states(
        self,
        scope: Scope,
        target_dimension: str,
    ) -> tuple[RuntimeState, ...]:
        """Return all persisted RuntimeState rows for one (scope, dimension).

        Convenience method for tests and audit. The general
        `load_states()` returns all canonical state across all dimensions.
        """
        scope_vals = _scope_values(scope)
        rows = self._conn.execute(
            "SELECT * FROM states WHERE "
            f"{' AND '.join(f'{col} = ?' for col in _SCOPE_COLUMNS)}"
            " AND dimension = ? ORDER BY version ASC",
            (*scope_vals, target_dimension),
        ).fetchall()
        return tuple(_state_from_row(row) for row in rows)

    def list_slow_window_dimensions(self, scope: Scope) -> tuple[tuple[Scope, str], ...]:
        """Enumerate (scope, target_dimension) pairs with persisted slow window rows."""
        scope_vals = _scope_values(scope)
        rows = self._conn.execute(
            "SELECT DISTINCT "
            f"{', '.join(_SCOPE_COLUMNS)}, target_dimension "
            "FROM slow_contribution_window WHERE "
            f"{' AND '.join(f'{col} = ?' for col in _SCOPE_COLUMNS)}",
            scope_vals,
        ).fetchall()
        return tuple(
            (_scope_from_row(row), row["target_dimension"]) for row in rows
        )

    def max_slow_window_sequence(self, scope: Scope, dimension: str) -> int:
        """Return the current max sequence for (scope, dimension), or 0 if none."""
        scope_vals = _scope_values(scope)
        row = self._conn.execute(
            "SELECT MAX(sequence) FROM slow_contribution_window WHERE "
            f"{' AND '.join(f'{col} = ?' for col in _SCOPE_COLUMNS)}"
            " AND target_dimension = ?",
            (*scope_vals, dimension),
        ).fetchone()
        return row[0] or 0

    def _execute_slow_window_update(
        self,
        *,
        state: RuntimeState,
        new_rows: tuple[dict, ...],
        trim_keys: tuple[Scope, str],
        window_size: int,
    ) -> None:
        scope_vals = _scope_values(state.scope)
        # 1. Insert new ledger rows.
        for row in new_rows:
            self._conn.execute(
                "INSERT INTO slow_contribution_window ("
                f"{', '.join(_SCOPE_COLUMNS)}, target_dimension, sequence,"
                " accepted_at, proposed_value, salience, evidence_refs,"
                " source_event_ref, source_decision_id"
                ") VALUES ("
                f"{', '.join('?' * 7)}, ?, ?, ?, ?, ?, ?, ?, ?"
                ")",
                (
                    *scope_vals,
                    state.dimension,
                    int(row["sequence"]),
                    _format_dt(row["accepted_at"]),
                    float(row["proposed_value"]),
                    float(row["salience"]),
                    _to_json(row["evidence_refs"]),
                    row.get("source_event_ref"),
                    row["source_decision_id"],
                ),
            )
        # 2. Trim oldest rows beyond window_size for (scope, dimension).
        if trim_keys:
            trim_scope, trim_dim = trim_keys
            self._trim_slow_window(
                trim_scope=trim_scope,
                trim_dim=trim_dim,
                window_size=window_size,
            )
        # 3. Persist the canonical RuntimeState (S_t = A_t).
        self._insert_state(state)

    def _trim_slow_window(
        self,
        *,
        trim_scope: Scope,
        trim_dim: str,
        window_size: int,
    ) -> None:
        trim_scope_vals = _scope_values(trim_scope)
        # Keep the latest N: drop the oldest (count - N).
        self._conn.execute(
            "DELETE FROM slow_contribution_window WHERE "
            f"{' AND '.join(f'{col} = ?' for col in _SCOPE_COLUMNS)}"
            " AND target_dimension = ? AND id NOT IN ("
            "  SELECT id FROM slow_contribution_window WHERE "
            f"  {' AND '.join(f'{col} = ?' for col in _SCOPE_COLUMNS)}"
            "  AND target_dimension = ?"
            "  ORDER BY accepted_at DESC, id DESC LIMIT ?"
            ")",
            (
                *trim_scope_vals,
                trim_dim,
                *trim_scope_vals,
                trim_dim,
                int(window_size),
            ),
        )

    def commit_slow_window_update(
        self,
        *,
        state: RuntimeState,
        new_rows: tuple[dict, ...],
        trim_keys: tuple[Scope, str],
        window_size: int,
    ) -> bool:
        """Atomically persist one slow-window update: insert new ledger rows,
        trim oldest rows if the window exceeds window_size, and write the
        canonical RuntimeState (S_t = A_t). All operations run in a single
        SQLite transaction. On any error the whole transaction is rolled back.

        Args:
            state: The RuntimeState to write. value must already equal A_t.
                   The writer must not pass a value derived from a prior state
                   (ADR-0017 Step B = S_t = A_t; no prior blend, no LR).
            new_rows: New ledger rows to insert. Each is a dict with the same
                      shape returned by load_slow_window (plus 'proposed_value',
                      'salience', 'accepted_at', 'evidence_refs',
                      'source_event_ref', 'source_decision_id'). The writer
                      assigns 'sequence' = 1 + current max(sequence) for
                      (scope, dimension), or 1 if no rows exist yet.
            trim_keys: (scope, target_dimension) the trim applies to.
                       The trim removes the oldest rows beyond window_size.
            window_size: Configuration-owned maximum window size.
        """
        if window_size < 1:
            raise ValueError("window_size must be >= 1")
        try:
            if self._in_transaction:
                self._execute_slow_window_update(
                    state=state,
                    new_rows=new_rows,
                    trim_keys=trim_keys,
                    window_size=window_size,
                )
            else:
                with self._conn:
                    self._execute_slow_window_update(
                        state=state,
                        new_rows=new_rows,
                        trim_keys=trim_keys,
                        window_size=window_size,
                    )
            return True
        except sqlite3.IntegrityError:
            return False

    def rollback_slow_window_update(self) -> None:
        """No-op explicit rollback hook.

        The atomicity is provided by `commit_slow_window_update` itself
        (one transaction). This hook exists so the writer can document
        a controlled path if it needs to abort before calling commit.
        """
        # Intentionally empty. The single-transaction guard in
        # commit_slow_window_update is the only atomicity mechanism.
        return None


class CommitMarkerStore(Protocol):
    """Durable, implementation-neutral record of committed cognitive turns.

    Written by the orchestrator at commit time (one row per turn whose
    projection was promoted) so downstream consumers can answer
    ``was_cognition_committed(interaction_id)`` from commit semantics
    alone — never by parsing projection-id naming conventions of a
    specific transition implementation.
    """

    def record_commit(
        self,
        *,
        interaction_id: str,
        scope: Scope,
        committed_at: datetime,
        projected_state_ids: tuple[str, ...],
        commit: bool = True,
    ) -> bool: ...

    def has_commit(self, *, interaction_id: str, scope: Scope) -> bool: ...


_MARKER_SCHEMA = """
CREATE TABLE IF NOT EXISTS commit_markers (
    scope_domain TEXT NOT NULL,
    scope_user_id TEXT NOT NULL DEFAULT '',
    interaction_id TEXT NOT NULL,
    committed_at TEXT NOT NULL,
    projected_state_ids TEXT NOT NULL,
    PRIMARY KEY (scope_domain, scope_user_id, interaction_id)
);
"""


class SqliteCommitMarkerStore:
    """SQLite ``CommitMarkerStore`` sharing the state-plane DB file."""

    def __init__(
        self,
        path: str | Path,
        *,
        connection: sqlite3.Connection | None = None,
    ) -> None:
        self._path = str(path)
        if connection is not None:
            self._conn = connection
            self._owns_conn = False
        else:
            self._conn = sqlite3.connect(self._path)
            self._owns_conn = True
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_MARKER_SCHEMA)

    def close(self) -> None:
        if self._owns_conn:
            self._conn.close()

    def record_commit(
        self,
        *,
        interaction_id: str,
        scope: Scope,
        committed_at: datetime,
        projected_state_ids: tuple[str, ...],
        commit: bool = True,
    ) -> bool:
        try:
            if commit and self._owns_conn and not self._conn.in_transaction:
                with self._conn:
                    self._conn.execute(
                        "INSERT INTO commit_markers "
                        "(scope_domain, scope_user_id, interaction_id, committed_at,"
                        " projected_state_ids) VALUES (?,?,?,?,?)",
                        (
                            scope.domain.value,
                            scope.user_id or "",
                            interaction_id,
                            _format_dt(committed_at),
                            json.dumps(list(projected_state_ids)),
                        ),
                    )
            else:
                self._conn.execute(
                    "INSERT INTO commit_markers "
                    "(scope_domain, scope_user_id, interaction_id, committed_at,"
                    " projected_state_ids) VALUES (?,?,?,?,?)",
                    (
                        scope.domain.value,
                        scope.user_id or "",
                        interaction_id,
                        _format_dt(committed_at),
                        json.dumps(list(projected_state_ids)),
                    ),
                )
            return True
        except sqlite3.IntegrityError:
            return False

    def has_commit(self, *, interaction_id: str, scope: Scope) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM commit_markers WHERE scope_domain=? AND scope_user_id=?"
            " AND interaction_id=?",
            (scope.domain.value, scope.user_id or "", interaction_id),
        ).fetchone()
        return row is not None
