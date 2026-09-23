"""Durable SQLite backend for the C7B delivery plane.

The C7A in-memory backend is the deterministic test / reference
backend. This module is the production restart-durable backend:
the SQLite file is the only authority for crash / reconcile / retry.

Conventions (matching ``state/persistence.py`` and
``facts/persistence.py``):

  * stdlib-only sqlite3, zero runtime dependencies.
  * ``_SCOPE_COLUMNS`` tuple used uniformly for all scope columns.
  * ``save_*`` returns bool; primary-key collisions return False
    (the row was already there with the same bytes).
  * ``save_*`` raises ``ValueError`` only when the same natural id
    is written with different bytes (immutable-bytes guarantee).
  * A malformed / incompatible persisted row fails closed on
    reopen with a clear ``ValueError`` naming the bad row.

Tables (frozen by C7B STEP 0):

  delivery_requests      one row per request, durable lifecycle state
  delivery_receipts      one row per receipt observed from the carrier
  delivery_attempts      one row per attempt (start / end / outcome)
  delivery_kill_switch   single-row table consulted before every call

Idempotency keys:
  delivery_requests.request_id  — natural key
  delivery_receipts.receipt_id  — natural key
  delivery_attempts.attempt_id  — natural key
  delivery_kill_switch.row_id   — constant 1
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol, runtime_checkable

from mind_runtime.contracts import (
    DeliveryReceipt,
    DeliveryStatus,
    Scope,
    ScopeDomain,
    SyncFields,
)
from mind_runtime.contracts.common import (
    require_aware_utc,
)
from mind_runtime.delivery import DeliveryRequest, SurfaceHandoffProvenance
from mind_runtime.delivery.kill_switch import (
    DeliveryKillSwitch,
    _ensure_kill_switch_schema,
)
from mind_runtime.delivery.state import (
    DeliveryLifecycleState,
    validate_transition,
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
CREATE TABLE IF NOT EXISTS delivery_requests (
    request_id TEXT PRIMARY KEY,
    message_id TEXT NOT NULL,
    scope_domain TEXT NOT NULL,
    scope_user_id TEXT NOT NULL DEFAULT '',
    scope_agent_id TEXT NOT NULL DEFAULT '',
    scope_persona_id TEXT NOT NULL DEFAULT '',
    scope_relationship_id TEXT NOT NULL DEFAULT '',
    scope_world_id TEXT NOT NULL DEFAULT '',
    scope_interaction_id TEXT NOT NULL DEFAULT '',
    origin_runtime_id TEXT NOT NULL,
    channel TEXT NOT NULL,
    target TEXT NOT NULL,
    action_type TEXT NOT NULL DEFAULT '',
    payload_bytes BLOB NOT NULL,
    surface_handoff TEXT,
    created_at TEXT NOT NULL,
    sync TEXT NOT NULL,
    lifecycle_state TEXT NOT NULL,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    last_attempt_at TEXT,
    last_reconcile_at TEXT,
    last_provider_receipt_ref TEXT,
    sync_version INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS delivery_receipts (
    receipt_id TEXT PRIMARY KEY,
    request_id TEXT NOT NULL,
    message_id TEXT NOT NULL,
    scope_domain TEXT NOT NULL,
    scope_user_id TEXT NOT NULL DEFAULT '',
    scope_agent_id TEXT NOT NULL DEFAULT '',
    scope_persona_id TEXT NOT NULL DEFAULT '',
    scope_relationship_id TEXT NOT NULL DEFAULT '',
    scope_world_id TEXT NOT NULL DEFAULT '',
    scope_interaction_id TEXT NOT NULL DEFAULT '',
    origin_runtime_id TEXT NOT NULL,
    delivery_status TEXT NOT NULL,
    delivered_at TEXT,
    provider_receipt_ref TEXT,
    provider_message_ref TEXT,
    sync TEXT NOT NULL,
    attempt INTEGER NOT NULL DEFAULT 1,
    sync_version INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS delivery_attempts (
    attempt_id TEXT PRIMARY KEY,
    request_id TEXT NOT NULL,
    attempt INTEGER NOT NULL,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    outcome TEXT NOT NULL,
    provider_receipt_ref TEXT,
    reason_codes TEXT NOT NULL DEFAULT '[]'
);
"""


def _to_json(value: object) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError) as error:
        raise ValueError(
            f"durable delivery store requires JSON-serializable values: {error}"
        ) from error


def _from_json(text: str) -> object:
    return json.loads(text)


def _format_dt(value: datetime) -> str:
    return value.isoformat()


def _parse_dt(text: str | None) -> datetime | None:
    return datetime.fromisoformat(text) if text else None


def _parse_required_dt(text: str) -> datetime:
    value = datetime.fromisoformat(text)
    require_aware_utc(value, "stored timestamp")
    return value


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


def _request_from_row(row: sqlite3.Row) -> DeliveryRequest:
    scope = _scope_from_row(row)
    sync_obj = _from_json(row["sync"])
    if not isinstance(sync_obj, dict):
        raise ValueError(  # pragma: no cover
            f"delivery_requests sync row {row['request_id']!r}"
            " is not a JSON object"
        )
    expected_keys = {"scope", "origin_runtime_id", "object_id", "version", "idempotency_key"}
    missing = expected_keys - set(sync_obj.keys())
    if missing:
        raise ValueError(  # pragma: no cover
            f"delivery_requests sync row {row['request_id']!r}"
            f" missing required keys: {sorted(missing)}"
        )
    try:
        sync = SyncFields(
            scope=scope,
            origin_runtime_id=str(sync_obj["origin_runtime_id"]),
            object_id=str(sync_obj["object_id"]),
            version=int(sync_obj["version"]),
            idempotency_key=str(sync_obj["idempotency_key"]),
        )
    except (TypeError, ValueError) as error:  # pragma: no cover
        raise ValueError(  # pragma: no cover
            f"delivery_requests sync row {row['request_id']!r}"
            f" is malformed: {error}"
        ) from error
    payload = row["payload_bytes"]
    if not isinstance(payload, bytes):
        raise ValueError(  # pragma: no cover
            f"delivery_requests row {row['request_id']!r} has non-bytes payload"
        )
    return DeliveryRequest(
        request_id=row["request_id"],
        message_id=row["message_id"],
        scope=scope,
        origin_runtime_id=row["origin_runtime_id"],
        channel=row["channel"],
        target=row["target"],
        action_type=row["action_type"] if "action_type" in row.keys() else "",
        payload_bytes=payload,
        created_at=_parse_required_dt(row["created_at"]),
        sync=sync,
        surface_handoff=_surface_handoff_from_json(row["surface_handoff"])
        if "surface_handoff" in row.keys() else None,
    )


def _surface_handoff_to_json(value: SurfaceHandoffProvenance | None) -> str | None:
    if value is None:
        return None
    return _to_json({
        "context_id": value.context_id,
        "intent_id": value.intent_id,
        "action_type": value.action_type,
        "policy_id": value.policy_id,
        "policy_constraints": list(value.policy_constraints),
        "controls_id": value.controls_id,
        "recipe_ref": value.recipe_ref,
        "expression_map_ref": value.expression_map_ref,
        "qualitative_guidance": [list(pair) for pair in value.qualitative_guidance],
        "intent_surface_use_ref": value.intent_surface_use_ref,
        "render_id": value.render_id,
        "logical_attempt_id": value.logical_attempt_id,
        "envelope_digest": value.envelope_digest,
    })


def _surface_handoff_from_json(raw: str | None) -> SurfaceHandoffProvenance | None:
    if raw is None:
        return None
    try:
        data = _from_json(raw)
        if not isinstance(data, dict):
            raise ValueError("Surface handoff must be an object")
        return SurfaceHandoffProvenance(
            context_id=data["context_id"], intent_id=data["intent_id"],
            action_type=data["action_type"], policy_id=data["policy_id"],
            policy_constraints=tuple(data["policy_constraints"]),
            controls_id=data["controls_id"], recipe_ref=data["recipe_ref"],
            expression_map_ref=data["expression_map_ref"],
            qualitative_guidance=tuple(tuple(pair) for pair in data["qualitative_guidance"]),
            intent_surface_use_ref=data["intent_surface_use_ref"],
            render_id=data["render_id"], logical_attempt_id=data["logical_attempt_id"],
            envelope_digest=data["envelope_digest"],
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("invalid durable Surface handoff provenance") from exc


def _validate_sync_payload(raw: str, row_id: str, row_label: str) -> None:
    """Validate the persisted SyncFields JSON without a full row context.

    Used on reopen to fail-closed: a malformed ``sync`` JSON
    payload yields a ValueError naming the offending row id.
    """

    try:
        sync_obj = _from_json(raw)
    except json.JSONDecodeError as error:
        raise ValueError(
            f"{row_label} row {row_id!r} has malformed sync JSON: {error}"
        ) from error
    if not isinstance(sync_obj, dict):
        raise ValueError(
            f"{row_label} row {row_id!r} sync must be a JSON object"
        )
    expected_keys = {"scope", "origin_runtime_id", "object_id", "version", "idempotency_key"}
    missing = expected_keys - set(sync_obj.keys())
    if missing:
        raise ValueError(
            f"{row_label} row {row_id!r} sync missing required keys:"
            f" {sorted(missing)}"
        )
    # The Scope value is the scope's domain name (a string); refuse
    # a non-string value. The other fields are coerced to str /
    # int in the load path; here we only check that scope is a
    # string, which is what _scope_from_row assumes.
    scope_value = sync_obj.get("scope")
    if not isinstance(scope_value, str) or not scope_value:
        raise ValueError(
            f"{row_label} row {row_id!r} sync.scope must be a non-empty"
            f" string: {scope_value!r}"
        )
    # version must be an integer.
    if not isinstance(sync_obj.get("version"), int) or isinstance(
        sync_obj.get("version"), bool
    ):
        raise ValueError(
            f"{row_label} row {row_id!r} sync.version must be an integer"
        )
    # origin_runtime_id, object_id, idempotency_key must coerce to
    # non-empty strings. None / non-string types fail closed.
    for key in ("origin_runtime_id", "object_id", "idempotency_key"):
        value = sync_obj.get(key)
        if not isinstance(value, str) or not value:
            raise ValueError(
                f"{row_label} row {row_id!r} sync.{key} must be a"
                f" non-empty string: {value!r}"
            )


def _receipt_sync_or_raise(row_id: str, raw: str) -> None:
    _validate_sync_payload(raw, row_id, "delivery_receipts")


def _request_sync_or_raise(row_id: str, raw: str) -> None:
    _validate_sync_payload(raw, row_id, "delivery_requests")


def _receipt_from_row(row: sqlite3.Row) -> DeliveryReceipt:
    scope = _scope_from_row(row)
    sync_obj = _from_json(row["sync"])
    if not isinstance(sync_obj, dict):
        raise ValueError(  # pragma: no cover
            f"delivery_receipts sync row {row['receipt_id']!r}"
            " is not a JSON object"
        )
    expected_keys = {"scope", "origin_runtime_id", "object_id", "version", "idempotency_key"}
    missing = expected_keys - set(sync_obj.keys())
    if missing:
        raise ValueError(  # pragma: no cover
            f"delivery_receipts sync row {row['receipt_id']!r}"
            f" missing required keys: {sorted(missing)}"
        )
    try:
        sync = SyncFields(
            scope=scope,
            origin_runtime_id=str(sync_obj["origin_runtime_id"]),
            object_id=str(sync_obj["object_id"]),
            version=int(sync_obj["version"]),
            idempotency_key=str(sync_obj["idempotency_key"]),
        )
    except (TypeError, ValueError) as error:  # pragma: no cover
        raise ValueError(  # pragma: no cover
            f"delivery_receipts sync row {row['receipt_id']!r}"
            f" is malformed: {error}"
        ) from error
    return DeliveryReceipt(
        receipt_id=row["receipt_id"],
        scope=scope,
        origin_runtime_id=row["origin_runtime_id"],
        message_id=row["message_id"],
        delivery_status=DeliveryStatus(row["delivery_status"]),
        delivered_at=_parse_dt(row["delivered_at"]),
        sync=sync,
    )


def _load_all_required_columns(conn: sqlite3.Connection, table: str) -> None:
    """Fail-closed reopen check: every required column must exist.

    SQLite ``PRAGMA table_info`` returns one row per column. We use
    this on reopen to detect a manually-corrupted schema (column
    dropped) and refuse to load the backend with a clear error.
    """

    # PRAGMA does not accept parameter placeholders for identifiers
    # (SQLite grammar is fixed), and string-composing an identifier
    # into a query is the only known SQL-injection surface for this
    # function. The single known-safe option is to dispatch on the
    # three known backend table names and use a per-table
    # pre-validated PRAGMA statement — the ``table`` parameter is
    # checked against the hard-coded allow-list and the actual
    # statement that runs is a constant built from that check.
    if table == "delivery_requests":
        rows = conn.execute("PRAGMA table_info('delivery_requests')").fetchall()
    elif table == "delivery_receipts":
        rows = conn.execute("PRAGMA table_info('delivery_receipts')").fetchall()
    elif table == "delivery_attempts":
        rows = conn.execute("PRAGMA table_info('delivery_attempts')").fetchall()
    else:
        raise ValueError(f"unknown durable delivery table: {table!r}")
    present = {row["name"] for row in rows}

    required: dict[str, tuple[str, ...]] = {
        "delivery_requests": (
            "request_id", "message_id", "scope_domain", "scope_user_id",
            "scope_agent_id", "scope_persona_id", "scope_relationship_id",
            "scope_world_id", "scope_interaction_id", "origin_runtime_id",
            "channel", "target", "action_type", "payload_bytes", "created_at",
            "sync", "lifecycle_state", "attempt_count", "last_attempt_at",
            "last_reconcile_at", "last_provider_receipt_ref", "sync_version",
        ),
        "delivery_receipts": (
            "receipt_id", "request_id", "message_id", "scope_domain",
            "scope_user_id", "scope_agent_id", "scope_persona_id",
            "scope_relationship_id", "scope_world_id", "scope_interaction_id",
            "origin_runtime_id", "delivery_status", "delivered_at",
            "provider_receipt_ref", "provider_message_ref", "sync", "attempt",
            "sync_version",
        ),
        "delivery_attempts": (
            "attempt_id", "request_id", "attempt", "started_at", "ended_at",
            "outcome", "provider_receipt_ref", "reason_codes",
        ),
    }
    if table not in required:
        return  # pragma: no cover
    missing = [c for c in required[table] if c not in present]
    if missing:
        raise ValueError(
            f"durable delivery backend table {table!r} is missing required"
            f" column(s): {missing}"
        )


def _validate_required_row_columns(conn: sqlite3.Connection) -> None:
    for table in ("delivery_requests", "delivery_receipts", "delivery_attempts"):
        _load_all_required_columns(conn, table)


@dataclass(frozen=True, slots=True)
class DurableRequestRow:
    """A request row with its durable recovery metadata.

    This is the C7B-specific read shape: the C7A ``DeliveryRequest``
    plus the lifecycle state, attempt count, and reconcile metadata
    that the recovery / daemon / kill-switch code needs.
    """

    request: DeliveryRequest
    lifecycle_state: DeliveryLifecycleState
    attempt_count: int
    last_attempt_at: datetime | None
    last_reconcile_at: datetime | None
    last_provider_receipt_ref: str | None


@dataclass(frozen=True, slots=True)
class DurableReceiptRow:
    """A receipt row with its provider-receipt references."""

    receipt: DeliveryReceipt
    request_id: str
    provider_receipt_ref: str | None
    provider_message_ref: str | None
    attempt: int


@dataclass(frozen=True, slots=True)
class DurableAttemptRow:
    """One carrier-attempt record."""

    attempt_id: str
    request_id: str
    attempt: int
    started_at: datetime
    ended_at: datetime | None
    outcome: DeliveryLifecycleState
    provider_receipt_ref: str | None
    reason_codes: tuple[str, ...]


@runtime_checkable
class DeliveryBackend(Protocol):
    """The C7B durable delivery backend contract.

    The methods below are additive over the C7A stores; the C7A
    ``DeliveryRequestStore`` / ``DeliveryReceiptStore`` protocols
    are still satisfied by the in-memory impl. ``record_request``
    returns False for an idempotent no-op and raises ValueError
    for a same-id different-bytes write.
    """

    def record_request(
        self, request: DeliveryRequest, *, lifecycle_state: DeliveryLifecycleState,
    ) -> bool: ...

    def get_durable_request(self, request_id: str) -> DurableRequestRow | None: ...

    def set_lifecycle_state(
        self, request_id: str, new_state: DeliveryLifecycleState, *,
        at: datetime,
    ) -> None: ...

    def increment_attempt(
        self, request_id: str, *, at: datetime,
    ) -> int: ...

    def record_reconcile(
        self, request_id: str, *, at: datetime,
    ) -> None: ...

    def record_provider_receipt_ref(
        self, request_id: str, provider_receipt_ref: str,
    ) -> None: ...

    def record_receipt(
        self, receipt: DeliveryReceipt, *, request_id: str,
        provider_receipt_ref: str | None,
        provider_message_ref: str | None,
        attempt: int,
    ) -> bool: ...

    def get_durable_receipt(self, receipt_id: str) -> DurableReceiptRow | None: ...

    def record_attempt(
        self, *, attempt_id: str, request_id: str, attempt: int,
        started_at: datetime, ended_at: datetime | None,
        outcome: DeliveryLifecycleState, provider_receipt_ref: str | None,
        reason_codes: tuple[str, ...],
    ) -> bool: ...

    def get_attempt(self, attempt_id: str) -> DurableAttemptRow | None: ...

    def attempts_for_request(self, request_id: str) -> tuple[DurableAttemptRow, ...]: ...

    def unfinished_requests(self) -> tuple[DurableRequestRow, ...]: ...

    def kill_switch(self) -> DeliveryKillSwitch: ...

    def close(self) -> None: ...


class SqliteDeliveryBackend:
    """SQLite-backed ``DeliveryBackend``.

    The on-disk file is the only source of truth across restarts.
    InMemoryDeliveryBackend is the in-process / test reference; the
    two are NOT interchangeable. The C7B tests explicitly distinguish
    "in-process contract" (uses InMemory) from "process-restart
    durability" (uses this class).
    """

    def __init__(self, path: str | Path) -> None:
        self._path = str(path)
        self._conn = sqlite3.connect(self._path)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        if "surface_handoff" not in {
            row["name"] for row in self._conn.execute("PRAGMA table_info('delivery_requests')")
        }:
            self._conn.execute("ALTER TABLE delivery_requests ADD COLUMN surface_handoff TEXT")
        # Validate the schema on reopen: a manually-corrupted file
        # with missing columns / wrong types fails closed.
        _validate_required_row_columns(self._conn)
        _ensure_kill_switch_schema(self._conn)
        # Fail-closed reopen check: every persisted state value must
        # round-trip through the lifecycle state enum. A bad row
        # raises ValueError naming the request_id. We select only
        # the validation-relevant columns; the load_* methods
        # perform the full row reconstruction.
        for row in self._conn.execute(
            "SELECT request_id, lifecycle_state, sync FROM delivery_requests"
        ).fetchall():
            try:
                DeliveryLifecycleState(row["lifecycle_state"])
            except ValueError as error:  # pragma: no cover
                raise ValueError(  # pragma: no cover
                    f"durable delivery_requests row {row['request_id']!r}"
                    f" has unknown lifecycle_state: {row['lifecycle_state']!r}"
                ) from error
            _request_sync_or_raise(row["request_id"], row["sync"])
        for row in self._conn.execute(
            "SELECT receipt_id, delivery_status, sync FROM delivery_receipts"
        ).fetchall():
            try:
                DeliveryStatus(row["delivery_status"])
            except ValueError as error:
                raise ValueError(
                    f"durable delivery_receipts row {row['receipt_id']!r}"
                    f" has unknown delivery_status: {row['delivery_status']!r}"
                ) from error
            # Round-trip the sync JSON; raises ValueError on malformed rows.
            _receipt_sync_or_raise(row["receipt_id"], row["sync"])
        for row in self._conn.execute(
            "SELECT attempt_id, outcome, reason_codes FROM delivery_attempts"
        ).fetchall():
            try:
                DeliveryLifecycleState(row["outcome"])
            except ValueError as error:
                raise ValueError(
                    f"durable delivery_attempts row {row['attempt_id']!r}"
                    f" has unknown outcome: {row['outcome']!r}"
                ) from error
            try:
                parsed = _from_json(row["reason_codes"])
            except json.JSONDecodeError as error:
                raise ValueError(
                    f"durable delivery_attempts row {row['attempt_id']!r}"
                    f" has malformed reason_codes JSON: {error}"
                ) from error
            if not isinstance(parsed, list):
                raise ValueError(
                    f"durable delivery_attempts row {row['attempt_id']!r}"
                    f" reason_codes must be a JSON array"
                )
        self._kill_switch = DeliveryKillSwitch(self._conn)

    @property
    def path(self) -> str:
        return self._path

    def table_names(self) -> tuple[str, ...]:
        rows = self._conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"
        ).fetchall()
        return tuple(row["name"] for row in rows)

    def close(self) -> None:
        self._conn.close()

    def kill_switch(self) -> DeliveryKillSwitch:
        return self._kill_switch

    # --- requests ---

    def record_request(
        self, request: DeliveryRequest, *, lifecycle_state: DeliveryLifecycleState,
    ) -> bool:
        if not isinstance(lifecycle_state, DeliveryLifecycleState):
            raise ValueError(
                f"lifecycle_state must be a DeliveryLifecycleState: {lifecycle_state!r}"
            )
        existing = self._conn.execute(
            "SELECT * FROM delivery_requests WHERE request_id = ?",
            (request.request_id,),
        ).fetchone()
        if existing is not None:
            current = _request_from_row(existing)
            if current == request:
                return False
            raise ValueError(
                f"durable delivery request id collision: {request.request_id!r}"
                " exists with different immutable bytes"
            )
        with self._conn:
            self._conn.execute(
                "INSERT INTO delivery_requests ("
                "request_id, message_id,"
                f"{', '.join(_SCOPE_COLUMNS)},"
                " origin_runtime_id, channel, target, action_type, payload_bytes, surface_handoff,"
                " created_at, sync, lifecycle_state, attempt_count,"
                " last_attempt_at, last_reconcile_at, last_provider_receipt_ref,"
                " sync_version"
                ") VALUES ("
                f"?, ?, {', '.join('?' * 7)}, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?"
                ")",
                (
                    request.request_id,
                    request.message_id,
                    *_scope_values(request.scope),
                    request.origin_runtime_id,
                    request.channel,
                    request.target,
                    request.action_type,
                    request.payload_bytes,
                    _surface_handoff_to_json(request.surface_handoff),
                    _format_dt(request.created_at),
                    _to_json({
                        "scope": request.scope.domain.value,
                        "origin_runtime_id": request.origin_runtime_id,
                        "object_id": request.request_id,
                        "version": request.sync.version,
                        "idempotency_key": request.sync.idempotency_key,
                    }),
                    lifecycle_state.value,
                    0,
                    None,
                    None,
                    None,
                    request.sync.version,
                ),
            )
        return True

    def get_durable_request(self, request_id: str) -> DurableRequestRow | None:
        row = self._conn.execute(
            "SELECT * FROM delivery_requests WHERE request_id = ?",
            (request_id,),
        ).fetchone()
        if row is None:
            return None
        return DurableRequestRow(
            request=_request_from_row(row),
            lifecycle_state=DeliveryLifecycleState(row["lifecycle_state"]),
            attempt_count=row["attempt_count"],
            last_attempt_at=_parse_dt(row["last_attempt_at"]),
            last_reconcile_at=_parse_dt(row["last_reconcile_at"]),
            last_provider_receipt_ref=row["last_provider_receipt_ref"],
        )

    def set_lifecycle_state(
        self, request_id: str, new_state: DeliveryLifecycleState, *,
        at: datetime,
    ) -> None:
        if not isinstance(new_state, DeliveryLifecycleState):
            raise ValueError(
                f"new_state must be a DeliveryLifecycleState: {new_state!r}"
            )
        require_aware_utc(at, "at")
        row = self._conn.execute(
            "SELECT lifecycle_state FROM delivery_requests WHERE request_id = ?",
            (request_id,),
        ).fetchone()
        if row is None:
            raise ValueError(f"unknown delivery request: {request_id!r}")
        current = DeliveryLifecycleState(row["lifecycle_state"])
        validate_transition(current, new_state)
        with self._conn:
            self._conn.execute(
                "UPDATE delivery_requests SET lifecycle_state = ?"
                " WHERE request_id = ?",
                (new_state.value, request_id),
            )

    def increment_attempt(
        self, request_id: str, *, at: datetime,
    ) -> int:
        require_aware_utc(at, "at")
        row = self._conn.execute(
            "SELECT attempt_count, last_attempt_at FROM delivery_requests"
            " WHERE request_id = ?",
            (request_id,),
        ).fetchone()
        if row is None:
            raise ValueError(f"unknown delivery request: {request_id!r}")
        new_count = int(row["attempt_count"]) + 1
        with self._conn:
            self._conn.execute(
                "UPDATE delivery_requests SET attempt_count = ?,"
                " last_attempt_at = ? WHERE request_id = ?",
                (new_count, _format_dt(at), request_id),
            )
        return new_count

    def record_reconcile(self, request_id: str, *, at: datetime) -> None:
        require_aware_utc(at, "at")
        row = self._conn.execute(
            "SELECT request_id FROM delivery_requests WHERE request_id = ?",
            (request_id,),
        ).fetchone()
        if row is None:
            raise ValueError(f"unknown delivery request: {request_id!r}")
        with self._conn:
            self._conn.execute(
                "UPDATE delivery_requests SET last_reconcile_at = ?"
                " WHERE request_id = ?",
                (_format_dt(at), request_id),
            )

    def record_provider_receipt_ref(
        self, request_id: str, provider_receipt_ref: str,
    ) -> None:
        if not provider_receipt_ref:
            raise ValueError("provider_receipt_ref must be non-empty")
        row = self._conn.execute(
            "SELECT request_id FROM delivery_requests WHERE request_id = ?",
            (request_id,),
        ).fetchone()
        if row is None:
            raise ValueError(f"unknown delivery request: {request_id!r}")
        with self._conn:
            self._conn.execute(
                "UPDATE delivery_requests SET last_provider_receipt_ref = ?"
                " WHERE request_id = ?",
                (provider_receipt_ref, request_id),
            )

    # --- receipts ---

    def record_receipt(
        self, receipt: DeliveryReceipt, *, request_id: str,
        provider_receipt_ref: str | None,
        provider_message_ref: str | None,
        attempt: int,
    ) -> bool:
        if not request_id:
            raise ValueError("request_id must be non-empty")
        if isinstance(attempt, bool) or attempt < 1:
            raise ValueError("attempt must be a positive integer")
        existing = self._conn.execute(
            "SELECT * FROM delivery_receipts WHERE receipt_id = ?",
            (receipt.receipt_id,),
        ).fetchone()
        if existing is not None:
            current = _receipt_from_row(existing)
            if (
                current == receipt
                and existing["request_id"] == request_id
                and existing["provider_receipt_ref"] == provider_receipt_ref
                and existing["provider_message_ref"] == provider_message_ref
                and int(existing["attempt"]) == attempt
            ):
                return False
            raise ValueError(
                f"durable delivery receipt id collision: {receipt.receipt_id!r}"
                " exists with different immutable bytes"
            )
        with self._conn:
            self._conn.execute(
                "INSERT INTO delivery_receipts ("
                "receipt_id, request_id, message_id,"
                f"{', '.join(_SCOPE_COLUMNS)},"
                " origin_runtime_id, delivery_status, delivered_at,"
                " provider_receipt_ref, provider_message_ref, sync, attempt,"
                " sync_version"
                ") VALUES ("
                # 18 placeholders: receipt_id, request_id, message_id,
                # 7 scope columns, origin_runtime_id, delivery_status,
                # delivered_at, provider_receipt_ref, provider_message_ref,
                # sync, attempt, sync_version.
                "?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?"
                ")",
                (
                    receipt.receipt_id,
                    request_id,
                    receipt.message_id,
                    *_scope_values(receipt.scope),
                    receipt.origin_runtime_id,
                    receipt.delivery_status.value,
                    _format_dt(receipt.delivered_at) if receipt.delivered_at is not None else None,
                    provider_receipt_ref,
                    provider_message_ref,
                    _to_json({
                        "scope": receipt.scope.domain.value,
                        "origin_runtime_id": receipt.origin_runtime_id,
                        "object_id": receipt.receipt_id,
                        "version": receipt.sync.version,
                        "idempotency_key": receipt.sync.idempotency_key,
                    }),
                    attempt,
                    receipt.sync.version,
                ),
            )
        return True

    def get_durable_receipt(self, receipt_id: str) -> DurableReceiptRow | None:
        row = self._conn.execute(
            "SELECT * FROM delivery_receipts WHERE receipt_id = ?",
            (receipt_id,),
        ).fetchone()
        if row is None:
            return None
        return DurableReceiptRow(
            receipt=_receipt_from_row(row),
            request_id=row["request_id"],
            provider_receipt_ref=row["provider_receipt_ref"],
            provider_message_ref=row["provider_message_ref"],
            attempt=int(row["attempt"]),
        )

    # --- attempts ---

    def record_attempt(
        self, *, attempt_id: str, request_id: str, attempt: int,
        started_at: datetime, ended_at: datetime | None,
        outcome: DeliveryLifecycleState, provider_receipt_ref: str | None,
        reason_codes: tuple[str, ...],
    ) -> bool:
        if not attempt_id:
            raise ValueError("attempt_id must be non-empty")
        if not request_id:
            raise ValueError("request_id must be non-empty")
        if isinstance(attempt, bool) or attempt < 1:
            raise ValueError("attempt must be a positive integer")
        if not isinstance(outcome, DeliveryLifecycleState):
            raise ValueError(f"outcome must be a DeliveryLifecycleState: {outcome!r}")
        require_aware_utc(started_at, "started_at")
        if ended_at is not None:
            require_aware_utc(ended_at, "ended_at")
        for code in reason_codes:
            if not isinstance(code, str) or not code:
                raise ValueError("reason_codes entries must be non-empty strings")
        # C7 legacy callers record an IN_FLIGHT event and subsequently report
        # a terminal event under the same attempt id. Preserve that historical
        # contract. A SURFACE_V1 handoff instead makes each physical attempt
        # immutable, because its admitted provider evidence must not drift.
        parent = self._conn.execute(
            "SELECT request_id, surface_handoff FROM delivery_requests WHERE request_id = ?",
            (request_id,),
        ).fetchone()
        if parent is None:
            raise ValueError(f"unknown delivery request: {request_id!r}")
        existing = self._conn.execute(
            "SELECT * FROM delivery_attempts WHERE attempt_id = ?",
            (attempt_id,),
        ).fetchone()
        if existing is not None:
            if parent["surface_handoff"] is None:
                return False
            if (
                existing["request_id"] == request_id
                and existing["attempt"] == attempt
                and existing["started_at"] == _format_dt(started_at)
                and existing["ended_at"] == (_format_dt(ended_at) if ended_at else None)
                and existing["outcome"] == outcome.value
                and existing["provider_receipt_ref"] == provider_receipt_ref
                and tuple(_from_json(existing["reason_codes"])) == reason_codes
            ):
                return False
            raise ValueError("durable delivery attempt id collision with different evidence")
        # The attempt is a child of the already-persisted request.
        with self._conn:
            self._conn.execute(
                "INSERT INTO delivery_attempts ("
                "attempt_id, request_id, attempt, started_at, ended_at,"
                " outcome, provider_receipt_ref, reason_codes"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    attempt_id,
                    request_id,
                    attempt,
                    _format_dt(started_at),
                    _format_dt(ended_at) if ended_at is not None else None,
                    outcome.value,
                    provider_receipt_ref,
                    _to_json(list(reason_codes)),
                ),
            )
        return True

    def get_attempt(self, attempt_id: str) -> DurableAttemptRow | None:
        row = self._conn.execute(
            "SELECT * FROM delivery_attempts WHERE attempt_id = ?",
            (attempt_id,),
        ).fetchone()
        if row is None:
            return None
        return _attempt_from_row(row)

    def attempts_for_request(self, request_id: str) -> tuple[DurableAttemptRow, ...]:
        rows = self._conn.execute(
            "SELECT * FROM delivery_attempts WHERE request_id = ?"
            " ORDER BY attempt, attempt_id",
            (request_id,),
        ).fetchall()
        return tuple(_attempt_from_row(row) for row in rows)

    # --- discovery ---

    def unfinished_requests(self) -> tuple[DurableRequestRow, ...]:
        """Return durable requests that are not yet in a terminal state.

        Terminal-by-default = ACCEPTED or REJECTED. UNKNOWN is NOT
        terminal (reconcile can still move it). FAILED_RETRYABLE
        is NOT terminal (the retry policy can move it to PENDING).
        PENDING and IN_FLIGHT are obviously not terminal.

        Sorted by request_id ascending for determinism.
        """
        rows = self._conn.execute(
            "SELECT * FROM delivery_requests"
            " WHERE lifecycle_state NOT IN (?, ?)"
            " ORDER BY request_id",
            (
                DeliveryLifecycleState.ACCEPTED.value,
                DeliveryLifecycleState.REJECTED.value,
            ),
        ).fetchall()
        return tuple(
            DurableRequestRow(
                request=_request_from_row(row),
                lifecycle_state=DeliveryLifecycleState(row["lifecycle_state"]),
                attempt_count=row["attempt_count"],
                last_attempt_at=_parse_dt(row["last_attempt_at"]),
                last_reconcile_at=_parse_dt(row["last_reconcile_at"]),
                last_provider_receipt_ref=row["last_provider_receipt_ref"],
            )
            for row in rows
        )


def _attempt_from_row(row: sqlite3.Row) -> DurableAttemptRow:
    raw = _from_json(row["reason_codes"])
    if not isinstance(raw, list):
        raise ValueError(
            f"delivery_attempts row {row['attempt_id']!r} reason_codes"
            " is not a JSON array"
        )
    codes = tuple(str(code) for code in raw)
    return DurableAttemptRow(
        attempt_id=row["attempt_id"],
        request_id=row["request_id"],
        attempt=int(row["attempt"]),
        started_at=_parse_required_dt(row["started_at"]),
        ended_at=_parse_dt(row["ended_at"]),
        outcome=DeliveryLifecycleState(row["outcome"]),
        provider_receipt_ref=row["provider_receipt_ref"],
        reason_codes=codes,
    )
