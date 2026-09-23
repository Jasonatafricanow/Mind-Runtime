"""Intent lifecycle persistence ports and atomic in-memory implementation."""

import json
import sqlite3
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Protocol, runtime_checkable

from mind_runtime.contracts import (
    Intent,
    IntentStatus,
    IntentTransition,
    ReconsiderationPolicy,
    Scope,
    ScopeDomain,
    SyncFields,
)
from mind_runtime.contracts.intent import IntentScoreContribution, IntentScoreTrace

type _IntentKey = tuple[Scope, str]

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

_SCOPE_SQL = ", ".join(_SCOPE_COLUMNS)
_SCOPE_PLACEHOLDERS = ", ".join("?" for _column in _SCOPE_COLUMNS)
_SCOPE_WHERE = " AND ".join(f"{column} = ?" for column in _SCOPE_COLUMNS)
_PRIMARY_IDENTITY = f"{_SCOPE_SQL}, intent_id, version"

_SCHEMA = f"""
CREATE TABLE IF NOT EXISTS intents (
    scope_domain TEXT NOT NULL,
    scope_user_id TEXT NOT NULL DEFAULT '',
    scope_agent_id TEXT NOT NULL DEFAULT '',
    scope_persona_id TEXT NOT NULL DEFAULT '',
    scope_relationship_id TEXT NOT NULL DEFAULT '',
    scope_world_id TEXT NOT NULL DEFAULT '',
    scope_interaction_id TEXT NOT NULL DEFAULT '',
    intent_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    origin_runtime_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    strength REAL NOT NULL,
    earliest_at TEXT,
    due_at TEXT,
    expires_at TEXT,
    reconsideration_policy TEXT NOT NULL,
    cause_refs TEXT NOT NULL,
    state_refs TEXT NOT NULL,
    status TEXT NOT NULL,
    sync_idem_key TEXT NOT NULL,
    surface_use TEXT,
    PRIMARY KEY ({_PRIMARY_IDENTITY}),
    UNIQUE ({_SCOPE_SQL}, intent_id, sync_idem_key)
);
CREATE TABLE IF NOT EXISTS intent_transitions (
    scope_domain TEXT NOT NULL,
    scope_user_id TEXT NOT NULL DEFAULT '',
    scope_agent_id TEXT NOT NULL DEFAULT '',
    scope_persona_id TEXT NOT NULL DEFAULT '',
    scope_relationship_id TEXT NOT NULL DEFAULT '',
    scope_world_id TEXT NOT NULL DEFAULT '',
    scope_interaction_id TEXT NOT NULL DEFAULT '',
    transition_id TEXT NOT NULL,
    origin_runtime_id TEXT NOT NULL,
    intent_id TEXT NOT NULL,
    from_status TEXT NOT NULL,
    to_status TEXT NOT NULL,
    reason_codes TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    version INTEGER NOT NULL,
    sync_idem_key TEXT NOT NULL,
    PRIMARY KEY ({_SCOPE_SQL}, transition_id),
    UNIQUE ({_SCOPE_SQL}, intent_id, version),
    FOREIGN KEY ({_PRIMARY_IDENTITY})
        REFERENCES intents ({_PRIMARY_IDENTITY})
);
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


def _to_json(values: tuple[str, ...]) -> str:
    return json.dumps(values, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _from_json(value: str) -> tuple[str, ...]:
    loaded = json.loads(value)
    if not isinstance(loaded, list) or not all(isinstance(item, str) for item in loaded):
        raise ValueError("stored reference list is invalid")
    return tuple(loaded)


def _format_dt(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _parse_dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value is not None else None


def _intent_from_row(row: sqlite3.Row) -> Intent:
    scope = _scope_from_row(row)
    intent_id = row["intent_id"]
    version = row["version"]
    origin_runtime_id = row["origin_runtime_id"]
    return Intent(
        intent_id=intent_id,
        scope=scope,
        origin_runtime_id=origin_runtime_id,
        kind=row["kind"],
        strength=row["strength"],
        earliest_at=_parse_dt(row["earliest_at"]),
        due_at=_parse_dt(row["due_at"]),
        expires_at=_parse_dt(row["expires_at"]),
        reconsideration_policy=ReconsiderationPolicy(row["reconsideration_policy"]),
        cause_refs=_from_json(row["cause_refs"]),
        state_refs=_from_json(row["state_refs"]),
        status=IntentStatus(row["status"]),
        sync=SyncFields(
            scope,
            origin_runtime_id,
            intent_id,
            version,
            row["sync_idem_key"],
        ),
        surface_use=_surface_use_from_json(row["surface_use"], scope)
        if "surface_use" in row.keys() else None,
    )


def _surface_use_to_json(trace: IntentScoreTrace | None) -> str | None:
    if trace is None:
        return None
    return json.dumps({
        "trace_id": trace.trace_id, "rule_id": trace.rule_id,
        "intent_id": trace.intent_id,
        "contributions": [
            [part.source_kind, part.source_ref, part.amount] for part in trace.contributions
        ],
        "unclamped_score": trace.unclamped_score,
        "final_strength": trace.final_strength,
        "admitted": trace.admitted, "reason_codes": list(trace.reason_codes),
        "created_at": trace.created_at.isoformat(),
        "surface_controls_ref": trace.surface_controls_ref,
        "surface_dependency_digest": trace.surface_dependency_digest,
        "overlap_validation_ref": trace.overlap_validation_ref,
        "surface_weights": [list(pair) for pair in trace.surface_weights],
        "surface_recipe_ref": trace.surface_recipe_ref,
        "ruleset_ref": trace.ruleset_ref,
    }, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _surface_use_from_json(raw: str | None, scope: Scope) -> IntentScoreTrace | None:
    if raw is None:
        return None
    try:
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("evidence must be an object")
        return IntentScoreTrace(
            trace_id=data["trace_id"], scope=scope,
            rule_id=data["rule_id"], intent_id=data["intent_id"],
            contributions=tuple(IntentScoreContribution(*part) for part in data["contributions"]),
            unclamped_score=data["unclamped_score"], final_strength=data["final_strength"],
            admitted=data["admitted"], reason_codes=tuple(data["reason_codes"]),
            created_at=datetime.fromisoformat(data["created_at"]),
            surface_controls_ref=data["surface_controls_ref"],
            surface_dependency_digest=data["surface_dependency_digest"],
            overlap_validation_ref=data["overlap_validation_ref"],
            surface_weights=tuple(tuple(pair) for pair in data["surface_weights"]),
            surface_recipe_ref=data["surface_recipe_ref"], ruleset_ref=data["ruleset_ref"],
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("invalid durable Intent Surface-use evidence") from exc


def _transition_from_row(row: sqlite3.Row) -> IntentTransition:
    scope = _scope_from_row(row)
    transition_id = row["transition_id"]
    origin_runtime_id = row["origin_runtime_id"]
    version = row["version"]
    occurred_at = _parse_dt(row["occurred_at"])
    if occurred_at is None:
        raise ValueError("stored transition occurred_at is missing")
    return IntentTransition(
        transition_id=transition_id,
        scope=scope,
        origin_runtime_id=origin_runtime_id,
        intent_id=row["intent_id"],
        from_status=IntentStatus(row["from_status"]),
        to_status=IntentStatus(row["to_status"]),
        reason_codes=_from_json(row["reason_codes"]),
        occurred_at=occurred_at,
        version=version,
        sync=SyncFields(
            scope,
            origin_runtime_id,
            transition_id,
            version,
            row["sync_idem_key"],
        ),
    )


@runtime_checkable
class IntentBackend(Protocol):
    """Append-only persistence required by IntentLifecycleService."""

    def append_initial(self, intent: Intent) -> Intent:
        """Admit version one, or return an exact idempotent replay."""
        ...

    def apply_transition(
        self, before: Intent, after: Intent, transition: IntentTransition
    ) -> Intent:
        """Atomically append a new Intent version and its transition."""
        ...

    def current(self, scope: Scope) -> tuple[Intent, ...]:
        """Return latest Intent versions in stable id order."""
        ...

    def history(self, scope: Scope, intent_id: str) -> tuple[Intent, ...]:
        """Return all Intent versions in ascending version order."""
        ...

    def transitions(self, scope: Scope, intent_id: str) -> tuple[IntentTransition, ...]:
        """Return append-only transitions in ascending version order."""
        ...


@dataclass(frozen=True, slots=True)
class _MemorySnapshot:
    current: dict[_IntentKey, Intent]
    history: dict[_IntentKey, tuple[Intent, ...]]
    transitions: dict[_IntentKey, tuple[IntentTransition, ...]]


class InMemoryIntentBackend:
    """Copy-on-write backend whose visible state changes in one assignment."""

    def __init__(self) -> None:
        self._snapshot = _MemorySnapshot(current={}, history={}, transitions={})

    def append_initial(self, intent: Intent) -> Intent:
        if intent.status is not IntentStatus.CANDIDATE or intent.sync.version != 1:
            raise ValueError("initial Intent must be a version-one candidate")
        key = (intent.scope, intent.intent_id)
        existing_history = self._snapshot.history.get(key)
        if existing_history is not None:
            existing = existing_history[0]
            if existing.sync.idempotency_key == intent.sync.idempotency_key:
                if existing == intent:
                    return existing
                raise ValueError("conflicting admission idempotency replay")
            raise ValueError("Intent already admitted with conflicting identity")

        next_current = dict(self._snapshot.current)
        next_history = dict(self._snapshot.history)
        next_transitions = dict(self._snapshot.transitions)
        next_current[key] = intent
        next_history[key] = (intent,)
        next_transitions[key] = ()
        self._commit(_MemorySnapshot(next_current, next_history, next_transitions))
        return intent

    def apply_transition(
        self, before: Intent, after: Intent, transition: IntentTransition
    ) -> Intent:
        key = (before.scope, before.intent_id)
        history = self._snapshot.history.get(key)
        if history is None:
            raise KeyError(f"missing Intent {before.intent_id}")
        existing_transitions = self._snapshot.transitions[key]
        replay = next(
            (item for item in history if item.sync.idempotency_key == after.sync.idempotency_key),
            None,
        )
        if replay is not None:
            replay_transition = next(
                (item for item in existing_transitions if item.version == replay.sync.version),
                None,
            )
            if replay == after and replay_transition == transition:
                return replay
            raise ValueError("conflicting transition idempotency replay")

        current = self._snapshot.current.get(key)
        _validate_transition_shape(before, after, transition, current)
        next_current = dict(self._snapshot.current)
        next_history = dict(self._snapshot.history)
        next_transitions = dict(self._snapshot.transitions)
        next_current[key] = after
        next_history[key] = (*history, after)
        next_transitions[key] = (*existing_transitions, transition)
        self._commit(_MemorySnapshot(next_current, next_history, next_transitions))
        return after

    def current(self, scope: Scope) -> tuple[Intent, ...]:
        return tuple(
            intent
            for (intent_scope, _intent_id), intent in sorted(
                self._snapshot.current.items(), key=lambda item: item[0][1]
            )
            if intent_scope == scope
        )

    def history(self, scope: Scope, intent_id: str) -> tuple[Intent, ...]:
        try:
            return self._snapshot.history[(scope, intent_id)]
        except KeyError as error:
            raise KeyError(f"missing Intent {intent_id}") from error

    def transitions(self, scope: Scope, intent_id: str) -> tuple[IntentTransition, ...]:
        try:
            return self._snapshot.transitions[(scope, intent_id)]
        except KeyError as error:
            raise KeyError(f"missing Intent {intent_id}") from error

    def _commit(self, snapshot: _MemorySnapshot) -> None:
        self._snapshot = snapshot


class SqliteIntentBackend:
    """Append-only stdlib SQLite backend with atomic version/transition writes."""

    def __init__(self, path: str | Path) -> None:
        self._path = str(path)
        self._conn = sqlite3.connect(self._path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.executescript(_SCHEMA)
        if "surface_use" not in {row["name"] for row in self._conn.execute("PRAGMA table_info('intents')")}:
            self._conn.execute("ALTER TABLE intents ADD COLUMN surface_use TEXT")

    def close(self) -> None:
        self._conn.close()

    def table_names(self) -> tuple[str, ...]:
        rows = self._conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"
        ).fetchall()
        return tuple(row["name"] for row in rows)

    def append_initial(self, intent: Intent) -> Intent:
        if intent.status is not IntentStatus.CANDIDATE or intent.sync.version != 1:
            raise ValueError("initial Intent must be a version-one candidate")
        existing = self._history_or_empty(intent.scope, intent.intent_id)
        if existing:
            admitted = existing[0]
            if admitted.sync.idempotency_key == intent.sync.idempotency_key:
                if admitted == intent:
                    return admitted
                raise ValueError("conflicting admission idempotency replay")
            raise ValueError("Intent already admitted with conflicting identity")
        with self._conn:
            self._insert_intent(intent)
        return intent

    def apply_transition(
        self, before: Intent, after: Intent, transition: IntentTransition
    ) -> Intent:
        replay = self._intent_by_idempotency(
            after.scope, after.intent_id, after.sync.idempotency_key
        )
        if replay is not None:
            replay_transition = self._transition_by_version(
                replay.scope, replay.intent_id, replay.sync.version
            )
            if replay == after and replay_transition == transition:
                return replay
            raise ValueError("conflicting transition idempotency replay")
        current = self._current_one(before.scope, before.intent_id)
        _validate_transition_shape(before, after, transition, current)
        with self._conn:
            self._insert_intent(after)
            self._insert_transition(transition)
        return after

    def current(self, scope: Scope) -> tuple[Intent, ...]:
        rows = self._conn.execute(
            f"SELECT * FROM intents WHERE {_SCOPE_WHERE} ORDER BY intent_id, version",
            _scope_values(scope),
        ).fetchall()
        latest: dict[str, Intent] = {}
        for row in rows:
            intent = _intent_from_row(row)
            latest[intent.intent_id] = intent
        return tuple(latest[intent_id] for intent_id in sorted(latest))

    def history(self, scope: Scope, intent_id: str) -> tuple[Intent, ...]:
        history = self._history_or_empty(scope, intent_id)
        if not history:
            raise KeyError(f"missing Intent {intent_id}")
        return history

    def transitions(self, scope: Scope, intent_id: str) -> tuple[IntentTransition, ...]:
        rows = self._conn.execute(
            f"SELECT * FROM intent_transitions WHERE {_SCOPE_WHERE} "
            "AND intent_id = ? ORDER BY version",
            (*_scope_values(scope), intent_id),
        ).fetchall()
        if not rows and not self._history_or_empty(scope, intent_id):
            raise KeyError(f"missing Intent {intent_id}")
        return tuple(_transition_from_row(row) for row in rows)

    def _history_or_empty(self, scope: Scope, intent_id: str) -> tuple[Intent, ...]:
        rows = self._conn.execute(
            f"SELECT * FROM intents WHERE {_SCOPE_WHERE} AND intent_id = ? ORDER BY version",
            (*_scope_values(scope), intent_id),
        ).fetchall()
        return tuple(_intent_from_row(row) for row in rows)

    def _current_one(self, scope: Scope, intent_id: str) -> Intent | None:
        history = self._history_or_empty(scope, intent_id)
        return history[-1] if history else None

    def _intent_by_idempotency(
        self, scope: Scope, intent_id: str, idempotency_key: str
    ) -> Intent | None:
        row = self._conn.execute(
            f"SELECT * FROM intents WHERE {_SCOPE_WHERE} AND intent_id = ? AND sync_idem_key = ?",
            (*_scope_values(scope), intent_id, idempotency_key),
        ).fetchone()
        return _intent_from_row(row) if row is not None else None

    def _transition_by_version(
        self, scope: Scope, intent_id: str, version: int
    ) -> IntentTransition | None:
        row = self._conn.execute(
            f"SELECT * FROM intent_transitions WHERE {_SCOPE_WHERE} "
            "AND intent_id = ? AND version = ?",
            (*_scope_values(scope), intent_id, version),
        ).fetchone()
        return _transition_from_row(row) if row is not None else None

    def _insert_intent(self, intent: Intent) -> None:
        self._conn.execute(
            "INSERT INTO intents ("
            f"{_SCOPE_SQL}, intent_id, version, origin_runtime_id, kind, strength, "
            "earliest_at, due_at, expires_at, reconsideration_policy, cause_refs, "
            "state_refs, status, sync_idem_key, surface_use"
            f") VALUES ({_SCOPE_PLACEHOLDERS}, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                *_scope_values(intent.scope),
                intent.intent_id,
                intent.sync.version,
                intent.origin_runtime_id,
                intent.kind,
                intent.strength,
                _format_dt(intent.earliest_at),
                _format_dt(intent.due_at),
                _format_dt(intent.expires_at),
                intent.reconsideration_policy.value,
                _to_json(intent.cause_refs),
                _to_json(intent.state_refs),
                intent.status.value,
                intent.sync.idempotency_key,
                _surface_use_to_json(intent.surface_use),
            ),
        )

    def _insert_transition(self, transition: IntentTransition) -> None:
        self._conn.execute(
            "INSERT INTO intent_transitions ("
            f"{_SCOPE_SQL}, transition_id, origin_runtime_id, intent_id, from_status, "
            "to_status, reason_codes, occurred_at, version, sync_idem_key"
            f") VALUES ({_SCOPE_PLACEHOLDERS}, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                *_scope_values(transition.scope),
                transition.transition_id,
                transition.origin_runtime_id,
                transition.intent_id,
                transition.from_status.value,
                transition.to_status.value,
                _to_json(transition.reason_codes),
                _format_dt(transition.occurred_at),
                transition.version,
                transition.sync.idempotency_key,
            ),
        )


def _validate_transition_shape(
    before: Intent,
    after: Intent,
    transition: IntentTransition,
    current: Intent | None,
) -> None:
    if current != before:
        raise ValueError("transition before version is not current")
    if after.scope != before.scope or after.intent_id != before.intent_id:
        raise ValueError("transition cannot change Intent identity")
    if after.origin_runtime_id != before.origin_runtime_id:
        raise ValueError("transition cannot change Intent origin")
    if after.sync.version != before.sync.version + 1:
        raise ValueError("transition must increment Intent version by one")
    if after != replace(before, status=after.status, sync=after.sync):
        raise ValueError("transition cannot change immutable Intent facts")
    if (
        transition.scope != before.scope
        or transition.origin_runtime_id != before.origin_runtime_id
        or transition.intent_id != before.intent_id
        or transition.from_status is not before.status
        or transition.to_status is not after.status
        or transition.version != after.sync.version
    ):
        raise ValueError("IntentTransition must describe before and after versions")
    if transition.sync.idempotency_key != after.sync.idempotency_key:
        raise ValueError("Intent and transition idempotency keys must match")
