"""Durable projection store (C7C).

Sqlite-backed append-only tables that record the fact that a
receipt_id has already been projected. The projector is the only
writer; the only reader is the projector itself (idempotency
check + dedup query).

Schema note: ``derived_counter_value`` and ``derived_counter_key``
are stored as strings so the schema is uniform across the
two projection shapes (cadence counter increment, cooldown
timestamp). The projector is the authority on the value semantics;
this store is the durable existence record.

C7C-R3: the second table ``projection_frozen_plans`` freezes the
exact derived result BEFORE any fact side effect so a replay that
happens after a crash between fact admission and the marker write
can re-admit the *frozen* values rather than re-derive against
later mutable state. The plan is the durable binding between a
receipt and the exact (fact_key, fact_value) pairs the projector
intended to write.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from mind_runtime.contracts import Scope
from mind_runtime.contracts.common import require_aware_utc, require_non_empty

# Schema is intentionally narrow: one row per projected receipt.
_SCHEMA = """
CREATE TABLE IF NOT EXISTS settled_action_projections (
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
    derived_counter_key TEXT NOT NULL,
    derived_counter_value TEXT NOT NULL,
    derived_settled_at TEXT NOT NULL,
    projected_at TEXT NOT NULL,
    sync_version INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS projection_frozen_plans (
    receipt_id TEXT PRIMARY KEY,
    request_id TEXT NOT NULL,
    action_type TEXT NOT NULL,
    settled_at TEXT NOT NULL,
    plan_json TEXT NOT NULL,
    completed INTEGER NOT NULL DEFAULT 0
);
"""


@dataclass(frozen=True, slots=True)
class ProjectionRecord:
    """The durable record that one receipt has been projected once.

    Fields mirror the storage layer plus the public accounting
    fields the projector surfaces in ProjectionOutcome.
    """

    receipt_id: str
    request_id: str
    message_id: str
    scope: Scope
    origin_runtime_id: str
    derived_counter_key: str
    derived_counter_value: str
    derived_settled_at: datetime
    projected_at: datetime
    sync_version: int

    def __post_init__(self) -> None:
        require_non_empty(self.receipt_id, "receipt_id")
        require_non_empty(self.request_id, "request_id")
        require_non_empty(self.message_id, "message_id")
        require_non_empty(self.origin_runtime_id, "origin_runtime_id")
        require_non_empty(self.derived_counter_key, "derived_counter_key")
        require_non_empty(self.derived_counter_value, "derived_counter_value")
        require_aware_utc(self.derived_settled_at, "derived_settled_at")
        require_aware_utc(self.projected_at, "projected_at")


@dataclass(frozen=True, slots=True)
class FrozenPlan:
    """C7C-R3: the durable pre-side-effect derivation of a receipt.

    The projector writes this BEFORE the first fact admission. A
    replay that finds a non-completed plan must replay from the
    plan, NOT re-derive against current state. The plan carries
    the exact (fact_key, fact_value) pairs and the original
    settled_at the projector used.
    """

    receipt_id: str
    request_id: str
    action_type: str
    settled_at: datetime
    facts: tuple[tuple[str, str], ...]
    completed: bool

    def __post_init__(self) -> None:
        require_non_empty(self.receipt_id, "receipt_id")
        require_non_empty(self.request_id, "request_id")
        require_non_empty(self.action_type, "action_type")
        require_aware_utc(self.settled_at, "settled_at")
        for pair in self.facts:
            if (
                not isinstance(pair, tuple)
                or len(pair) != 2
                or not isinstance(pair[0], str)
                or not isinstance(pair[1], str)
                or not pair[0]
                or not pair[1]
            ):
                raise ValueError(
                    f"frozen plan fact pair must be (str, str) of"
                    f" non-empty values; got {pair!r}"
                )


class SqliteProjectionStore:
    """Durable idempotency log for settled-action projections.

    The single public surface used by the projector:
      * has(receipt_id): bool
      * record(...) : one-time insert; raises on receipt_id collision
      * get(receipt_id) : ProjectionRecord | None (for diagnostics
        and crash-window tests)

    The store does not interpret derived_counter_key/value; it
    is a log. The projector owns the policy.
    """

    def __init__(self, path: str | Path) -> None:
        self._path = str(path)
        self._conn = sqlite3.connect(self._path)
        self._conn.row_factory = sqlite3.Row
        with self._conn:
            self._conn.executescript(_SCHEMA)
        # Reopen validation: every persisted row must have non-empty
        # string fields. A manually-corrupted row fails closed with a
        # clear ValueError naming the bad receipt_id (defense in
        # depth, matching the C7B delivery backend pattern).
        for row in self._conn.execute(
            "SELECT receipt_id, derived_counter_key, derived_counter_value,"
            " origin_runtime_id, derived_settled_at, projected_at,"
            " request_id, message_id FROM settled_action_projections"
        ).fetchall():
            for field in (
                "receipt_id",
                "derived_counter_key",
                "derived_counter_value",
                "origin_runtime_id",
                "request_id",
                "message_id",
            ):
                if not isinstance(row[field], str) or not row[field]:
                    raise ValueError(
                        f"settled_action_projections row {row['receipt_id']!r}"
                        f" has empty or non-string field {field!r}"
                    )

    @property
    def path(self) -> str:
        return self._path

    def has(self, receipt_id: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM settled_action_projections WHERE receipt_id = ?",
            (receipt_id,),
        ).fetchone()
        return row is not None

    def get(self, receipt_id: str) -> ProjectionRecord | None:
        row = self._conn.execute(
            "SELECT * FROM settled_action_projections WHERE receipt_id = ?",
            (receipt_id,),
        ).fetchone()
        if row is None:
            return None
        return _row_to_record(row)

    def record(self, record: ProjectionRecord) -> None:
        if self.has(record.receipt_id):
            # Idempotent reopen: a second caller should be checking
            # has() before reaching record(). Surface a clear error
            # if it isn't (this is a programmer error, not a runtime
            # branch).
            raise ValueError(
                f"projection record already exists for receipt_id"
                f" {record.receipt_id!r}"
            )
        with self._conn:
            self._conn.execute(
                "INSERT INTO settled_action_projections ("
                "receipt_id, request_id, message_id, scope_domain,"
                " scope_user_id, scope_agent_id, scope_persona_id,"
                " scope_relationship_id, scope_world_id,"
                " scope_interaction_id, origin_runtime_id,"
                " derived_counter_key, derived_counter_value,"
                " derived_settled_at, projected_at, sync_version"
                ") VALUES ("
                "?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?"
                ")",
                _record_to_row(record),
            )

    def close(self) -> None:
        self._conn.close()

    # ---- C7C-R3 frozen plan surface ----

    def has_frozen_plan(self, receipt_id: str) -> bool:
        """Whether an incomplete frozen plan exists for this receipt_id.

        A plan is written BEFORE the first fact admission. A
        crash between the plan write and the marker write leaves
        the plan in place; on recovery the projector must replay
        from the plan, NOT re-derive against current state.
        """
        require_non_empty(receipt_id, "receipt_id")
        row = self._conn.execute(
            "SELECT 1 FROM projection_frozen_plans"
            " WHERE receipt_id = ? AND completed = 0",
            (receipt_id,),
        ).fetchone()
        return row is not None

    def get_frozen_plan(self, receipt_id: str) -> FrozenPlan | None:
        """Return the crash-window frozen plan for this receipt_id.

        C7C-R3 semantics:
        - A plan with completed=False is a crash-window plan: the
          process died between the plan write and the marker write.
          Return it so the projector replays verbatim.
        - A plan with completed=True means all phases completed
          normally. Return None here so the marker's has() fast-path
          handles the already-applied case. The plan row is harmless
          but irrelevant once completed.
        """
        require_non_empty(receipt_id, "receipt_id")
        row = self._conn.execute(
            "SELECT * FROM projection_frozen_plans"
            " WHERE receipt_id = ? AND completed = 0",
            (receipt_id,),
        ).fetchone()
        if row is None:
            return None
        return _row_to_frozen_plan(row)

    def get_frozen_plan_any(self, receipt_id: str) -> FrozenPlan | None:
        """Return the frozen plan regardless of completed state.

        The projector uses this for state-consistency diagnosis: if
        a marker is missing and the plan is completed=True, the
        state is inconsistent and the projector must fail closed.
        """
        require_non_empty(receipt_id, "receipt_id")
        row = self._conn.execute(
            "SELECT * FROM projection_frozen_plans WHERE receipt_id = ?",
            (receipt_id,),
        ).fetchone()
        if row is None:
            return None
        return _row_to_frozen_plan(row)

    def record_frozen_plan(self, plan: FrozenPlan) -> None:
        """Write the frozen plan BEFORE the first fact admission.

        C7C-R3 contract: a frozen plan is the immutable binding
        between a ``receipt_id`` and the exact (fact_key, fact_value)
        pairs the projector intends to write. Once written, the plan
        is a fact of the system; it cannot be silently overwritten,
        repaired, or reinterpreted. Three outcomes are possible:

        - No existing plan row: insert the plan.

        - Existing plan row with byte-identical immutable content
          (request_id, action_type, settled_at, ordered fact pairs):
          the plan is unchanged; return the existing row. The
          caller's content is verified against the durable record.

        - Existing plan row with ANY different immutable field:
          fail closed. This is either a corruption (the DB was
          rewritten out-of-band) or a contract violation (two
          callers raced with different derivations for the same
          receipt_id). The projector never overrides a plan to
          match a re-derived value; re-derivation is forbidden.

        The DB UNIQUE constraint on receipt_id is the durability
        boundary; this method does NOT use INSERT OR IGNORE.
        """
        existing = self.get_frozen_plan_any(plan.receipt_id)
        if existing is not None:
            if _frozen_plan_equivalent(existing, plan):
                # Same content, same receipt_id: the durable plan
                # is the authority. Re-use it; do not re-insert.
                return
            raise ValueError(
                f"frozen plan conflict for receipt_id"
                f" {plan.receipt_id!r}: existing plan differs from"
                f" the caller's plan in an immutable field. The"
                f" plan is immutable; re-derivation is forbidden."
                f" Existing settled_at={existing.settled_at!r},"
                f" facts={existing.facts!r};"
                f" caller settled_at={plan.settled_at!r},"
                f" facts={plan.facts!r}."
            )
        with self._conn:
            self._conn.execute(
                "INSERT INTO projection_frozen_plans ("
                "receipt_id, request_id, action_type, settled_at,"
                " plan_json, completed"
                ") VALUES (?, ?, ?, ?, ?, ?)",
                (
                    plan.receipt_id,
                    plan.request_id,
                    plan.action_type,
                    _format_dt(plan.settled_at),
                    json.dumps(plan.facts),
                    1 if plan.completed else 0,
                ),
            )

    def mark_plan_completed(self, receipt_id: str) -> None:
        """Mark an existing frozen plan as completed (after all
        fact side effects and the marker have been written).

        A plan that is not completed on recovery signals a crash
        between the plan write and completion; the projector
        must replay the plan verbatim.
        """
        require_non_empty(receipt_id, "receipt_id")
        with self._conn:
            self._conn.execute(
                "UPDATE projection_frozen_plans SET completed = 1"
                " WHERE receipt_id = ?",
                (receipt_id,),
            )


def _record_to_row(record: ProjectionRecord) -> tuple[object, ...]:
    return (
        record.receipt_id,
        record.request_id,
        record.message_id,
        record.scope.domain.value,
        record.scope.user_id or "",
        record.scope.agent_id or "",
        record.scope.persona_id or "",
        record.scope.relationship_id or "",
        record.scope.world_id or "",
        record.scope.interaction_id or "",
        record.origin_runtime_id,
        record.derived_counter_key,
        record.derived_counter_value,
        _format_dt(record.derived_settled_at),
        _format_dt(record.projected_at),
        record.sync_version,
    )


def _row_to_record(row: sqlite3.Row) -> ProjectionRecord:
    from mind_runtime.contracts import ScopeDomain
    scope = Scope(
        domain=ScopeDomain(row["scope_domain"]),
        user_id=row["scope_user_id"] or None,
        agent_id=row["scope_agent_id"] or None,
        persona_id=row["scope_persona_id"] or None,
        relationship_id=row["scope_relationship_id"] or None,
        world_id=row["scope_world_id"] or None,
        interaction_id=row["scope_interaction_id"] or None,
    )
    return ProjectionRecord(
        receipt_id=row["receipt_id"],
        request_id=row["request_id"],
        message_id=row["message_id"],
        scope=scope,
        origin_runtime_id=row["origin_runtime_id"],
        derived_counter_key=row["derived_counter_key"],
        derived_counter_value=row["derived_counter_value"],
        derived_settled_at=_parse_dt(row["derived_settled_at"]),
        projected_at=_parse_dt(row["projected_at"]),
        sync_version=int(row["sync_version"]),
    )


def _row_to_frozen_plan(row: sqlite3.Row) -> FrozenPlan:
    raw = row["plan_json"]
    decoded: Any = json.loads(raw)
    if not isinstance(decoded, list):
        raise ValueError(
            f"frozen plan fact list must be a list of [key, value]"
            f" pairs; got {type(decoded).__name__}"
        )
    facts: list[tuple[str, str]] = []
    for item in decoded:
        if (
            not isinstance(item, list)
            or len(item) != 2
            or not isinstance(item[0], str)
            or not isinstance(item[1], str)
        ):
            raise ValueError(
                f"frozen plan fact entry must be [str, str]; got {item!r}"
            )
        facts.append((item[0], item[1]))
    return FrozenPlan(
        receipt_id=row["receipt_id"],
        request_id=row["request_id"],
        action_type=row["action_type"],
        settled_at=_parse_dt(row["settled_at"]),
        facts=tuple(facts),
        completed=bool(int(row["completed"])),
    )


def _frozen_plan_equivalent(a: FrozenPlan, b: FrozenPlan) -> bool:
    """Whether two frozen plans are byte-equivalent on the immutable
    surface. Used by record_frozen_plan to detect a benign re-write
    (same plan, both sides claim identical immutable content) and
    fail-closed on any divergence.

    Compares: receipt_id, request_id, action_type, settled_at (exact
    ISO-8601 with tz), and the ordered tuple of (fact_key, fact_value)
    pairs (the order is part of the immutability contract; the
    projector writes them in derivation order).
    """
    return (
        a.receipt_id == b.receipt_id
        and a.request_id == b.request_id
        and a.action_type == b.action_type
        and a.settled_at == b.settled_at
        and a.facts == b.facts
    )


def _format_dt(value: datetime) -> str:
    require_aware_utc(value, "datetime")
    return value.isoformat()


def _parse_dt(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    require_aware_utc(parsed, f"stored datetime {value!r}")
    return parsed
