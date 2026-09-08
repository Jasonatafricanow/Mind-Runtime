"""SQLite-backed ShadowRecordStore.

Follows existing Mind Runtime durable persistence conventions:
  - stdlib sqlite3 (no aiosqlite)
  - Strategy A: SELECT-then-INSERT (same as SqliteDeliveryBackend)
  - Fail-closed on identity collision with divergent content
  - Idempotent on identical records
  - Reopen-safe via CREATE TABLE IF NOT EXISTS

Idempotency contract:
  - same shadow_run_id + identical ShadowRunRecord → no-op
  - same shadow_run_id + divergent ShadowRunRecord → ValueError
  - same shadow_run_id + FAILED record when COMPLETED needed → ValueError
    (a FAILED record can be overwritten by another FAILED record with
    the same id and same content, or by a COMPLETED record — this
    is the natural behavior since we compare the full record)
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from .contracts import ShadowRecordStore as ShadowRecordStoreProtocol
from .contracts import (
    ComparisonResult,
    HostOutcome,
    ShadowRunRecord,
    ShadowStatus,
    ShadowSnapshot,
)

if TYPE_CHECKING:
    pass

# ── Schema ──────────────────────────────────────────────────────────────────────


_SCHEMA = """
CREATE TABLE IF NOT EXISTS shadow_runs (
    shadow_run_id         TEXT PRIMARY KEY,
    scope                 TEXT NOT NULL,
    source_interaction_id TEXT NOT NULL,
    source_event_ref      TEXT,
    runtime_config_digest TEXT NOT NULL,
    started_at            TEXT NOT NULL,   -- ISO 8601
    completed_at          TEXT NOT NULL,   -- ISO 8601
    status                TEXT NOT NULL,   -- ShadowStatus value

    -- MR outcome
    mr_situation_summary  TEXT,
    mr_intent_type        TEXT,
    mr_policy_decision    TEXT,
    mr_policy_reason_codes TEXT,           -- JSON array
    mr_expression_ref     TEXT,
    mr_would_send         INTEGER,         -- 0 or 1 (SQLite has no bool)

    -- Host side
    host_outcome_json     TEXT,            -- JSON or NULL

    -- Comparison
    comparison_json       TEXT,             -- JSON or NULL

    -- Failure
    failure_stage         TEXT,
    failure_reason         TEXT,

    -- Audit metadata
    captured_snapshot_json TEXT,           -- JSON or NULL
    record_serialized_json TEXT NOT NULL   -- full record JSON for identity comparison
);
"""


# ── Serialization helpers ───────────────────────────────────────────────────────


def _serialize_host_outcome(ho: HostOutcome | None) -> str | None:
    if ho is None:
        return None
    return json.dumps(
        {
            "host_action_taken": ho.host_action_taken,
            "host_action_type": ho.host_action_type,
            "host_expression_ref": ho.host_expression_ref,
        },
        sort_keys=True,
    )


def _deserialize_host_outcome(raw: str | None) -> HostOutcome | None:
    if raw is None:
        return None
    d = json.loads(raw)
    return HostOutcome(
        host_action_taken=d["host_action_taken"],
        host_action_type=d.get("host_action_type"),
        host_expression_ref=d.get("host_expression_ref"),
    )


def _serialize_comparison(c: ComparisonResult | None) -> str | None:
    if c is None:
        return None
    return json.dumps(
        {
            "comparable": c.comparable,
            "action_presence_match": c.action_presence_match,
            "action_type_match": c.action_type_match,
            "policy_divergence": c.policy_divergence,
        },
        sort_keys=True,
    )


def _deserialize_comparison(raw: str | None) -> ComparisonResult | None:
    if raw is None:
        return None
    d = json.loads(raw)
    return ComparisonResult(
        comparable=d["comparable"],
        action_presence_match=d.get("action_presence_match"),
        action_type_match=d.get("action_type_match"),
        policy_divergence=d.get("policy_divergence"),
    )


def _serialize_snapshot(s: ShadowSnapshot | None) -> str | None:
    if s is None:
        return None
    return json.dumps(
        {
            "interaction_id": s.interaction_id,
            "situation": None,  # audit-only; Situation is not JSON-serializable
            "intent": None,    # audit-only
            "expression_outcome_id": (
                s.expression_outcome.outcome_id
                if s.expression_outcome
                else None
            ),
            "expression_outcome_origin_runtime_id": (
                s.expression_outcome.origin_runtime_id
                if s.expression_outcome
                else None
            ),
            "expression_outcome_accepted_expression": (
                s.expression_outcome.accepted_expression
                if s.expression_outcome
                else None
            ),
            "expression_outcome_disposition": (
                s.expression_outcome.final_disposition.value
                if s.expression_outcome
                else None
            ),
            "expression_outcome_attempts": [
                {
                    "attempt_id": a.attempt_id,
                    "context_id": a.context_id,
                    "render_id": a.render_id,
                    "draft_id": a.draft_id,
                    "attempt": a.attempt,
                    "disposition": (
                        a.disposition.value if a.disposition else None
                    ),
                    "reason_codes": list(a.reason_codes),
                }
                for a in (s.expression_outcome.attempts or ())
            ],
            "observations": list(s.observations),
            "captured_at": s.captured_at.isoformat(),
        },
        sort_keys=True,
        default=_json_default,
    )


def _deserialize_snapshot(raw: str | None) -> ShadowSnapshot | None:
    if raw is None:
        return None
    d = json.loads(raw)

    expr_outcome = None
    disp_str = d.get("expression_outcome_disposition")
    outcome_id = d.get("expression_outcome_id")
    if outcome_id:
        from mind_runtime.contracts import ExpressionDisposition
        from mind_runtime.contracts.expression import ExpressionOutcome, ExpressionAttemptTrace

        attempts = []
        for raw_attempt in d.get("expression_outcome_attempts", []):
            disp_attempt = raw_attempt.get("disposition")
            attempts.append(
                ExpressionAttemptTrace(
                    attempt_id=raw_attempt["attempt_id"],
                    context_id=raw_attempt["context_id"],
                    render_id=raw_attempt["render_id"],
                    draft_id=raw_attempt.get("draft_id"),
                    attempt=raw_attempt["attempt"],
                    disposition=ExpressionDisposition(disp_attempt) if disp_attempt else None,
                    reason_codes=tuple(raw_attempt.get("reason_codes", [])),
                )
            )

        expr_outcome = ExpressionOutcome(
            outcome_id=outcome_id,
            scope=None,  # not stored
            origin_runtime_id=d.get("expression_outcome_origin_runtime_id") or "snapshot-store",
            accepted_expression=d.get("expression_outcome_accepted_expression") or "",
            final_disposition=ExpressionDisposition(disp_str) if disp_str else ExpressionDisposition.ACCEPT,
            attempts=tuple(attempts) if attempts else (ExpressionAttemptTrace(
                attempt_id="fallback",
                context_id="snapshot-store",
                render_id="fallback",
                draft_id=None,
                attempt=0,
                disposition=None,
                reason_codes=(),
            ),),
        )

    from mind_runtime.contracts import ExpressionDisposition

    captured_at_str = d.get("captured_at")
    captured_at = datetime.now(timezone.utc)
    if captured_at_str:
        from dateutil.parser import isoparse

        captured_at = isoparse(captured_at_str)

    return ShadowSnapshot(
        interaction_id=d["interaction_id"],
        situation=None,  # not stored
        projected=None,  # not stored
        intent=None,     # not stored
        expression_outcome=expr_outcome,
        action_receipt=None,
        observations=tuple(d.get("observations", [])),
        decision_context=None,
        captured_at=captured_at,
    )


def _serialize_record(record: ShadowRunRecord) -> str:
    return json.dumps(
        {
            "shadow_run_id": record.shadow_run_id,
            "scope": record.scope,
            "source_interaction_id": record.source_interaction_id,
            "source_event_ref": record.source_event_ref,
            "runtime_config_digest": record.runtime_config_digest,
            "started_at": record.started_at.isoformat(),
            "completed_at": record.completed_at.isoformat(),
            "status": record.status.value,
            "mr_situation_summary": record.mr_situation_summary,
            "mr_intent_type": record.mr_intent_type,
            "mr_policy_decision": record.mr_policy_decision,
            "mr_policy_reason_codes": list(record.mr_policy_reason_codes),
            "mr_expression_ref": record.mr_expression_ref,
            "mr_would_send": record.mr_would_send,
            "host_outcome": _serialize_host_outcome(record.host_outcome),
            "comparison": _serialize_comparison(record.comparison),
            "failure_stage": record.failure_stage,
            "failure_reason": record.failure_reason,
            "captured_snapshot": _serialize_snapshot(record.captured_snapshot),
        },
        sort_keys=True,
        default=_json_default,
    )


def _json_default(obj):
    raise TypeError(f"Cannot serialize {obj!r} to JSON")


def _record_from_row(row: sqlite3.Row) -> ShadowRunRecord:
    """Reconstruct a ShadowRunRecord from a database row."""
    reason_codes_raw = row["mr_policy_reason_codes"]
    reason_codes: tuple[str, ...] = ()
    if reason_codes_raw:
        reason_codes = tuple(json.loads(reason_codes_raw))

    mr_would_send = row["mr_would_send"]
    return ShadowRunRecord(
        shadow_run_id=row["shadow_run_id"],
        scope=row["scope"],
        source_interaction_id=row["source_interaction_id"],
        source_event_ref=row["source_event_ref"],
        runtime_config_digest=row["runtime_config_digest"],
        started_at=datetime.fromisoformat(row["started_at"]),
        completed_at=datetime.fromisoformat(row["completed_at"]),
        status=ShadowStatus(row["status"]),
        mr_situation_summary=row["mr_situation_summary"],
        mr_intent_type=row["mr_intent_type"],
        mr_policy_decision=row["mr_policy_decision"],
        mr_policy_reason_codes=reason_codes,
        mr_expression_ref=row["mr_expression_ref"],
        mr_would_send=bool(mr_would_send) if mr_would_send is not None else None,
        host_outcome=_deserialize_host_outcome(row["host_outcome_json"]),
        comparison=_deserialize_comparison(row["comparison_json"]),
        failure_stage=row["failure_stage"],
        failure_reason=row["failure_reason"],
        captured_snapshot=_deserialize_snapshot(row["captured_snapshot_json"]),
    )


# ── SqliteShadowRecordStore ────────────────────────────────────────────────────


class SqliteShadowRecordStore:
    """SQLite-backed audit store for ShadowRunRecords.

    Implements ShadowRecordStore Protocol.
    Reopen-safe, idempotent, fail-closed on identity collision.

    Args:
        path: Path to the SQLite database file. Parent directory is created
              if it does not exist.
    """

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._path))
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)

    def save(self, record: ShadowRunRecord) -> None:
        """Persist a shadow run record.

        Idempotency:
          - same shadow_run_id + identical record → no-op (returns silently)
          - same shadow_run_id + divergent content → raises ValueError
        """
        existing = self._conn.execute(
            "SELECT record_serialized_json FROM shadow_runs WHERE shadow_run_id = ?",
            (record.shadow_run_id,),
        ).fetchone()

        if existing is not None:
            # Same id exists — check identity via serialized form
            incoming = _serialize_record(record)
            if incoming == existing["record_serialized_json"]:
                return  # idempotent no-op
            raise ValueError(
                f"durable shadow record identity collision: "
                f"shadow_run_id={record.shadow_run_id!r} exists with different "
                f"immutable content. A failed idempotent insert means the record "
                f"was already saved with different content."
            )

        record_json = _serialize_record(record)
        self._conn.execute(
            """
            INSERT INTO shadow_runs (
                shadow_run_id, scope, source_interaction_id, source_event_ref,
                runtime_config_digest, started_at, completed_at, status,
                mr_situation_summary, mr_intent_type, mr_policy_decision,
                mr_policy_reason_codes, mr_expression_ref, mr_would_send,
                host_outcome_json, comparison_json,
                failure_stage, failure_reason,
                captured_snapshot_json, record_serialized_json
            ) VALUES (
                :id, :scope, :src_it, :src_ev, :cfg_dg, :started, :completed,
                :status, :sit_sum, :intent, :policy, :reason_codes,
                :expr_ref, :would_send,
                :ho_json, :cmp_json,
                :fail_stage, :fail_reason,
                :snap_json, :rec_json
            )
            """,
            {
                "id": record.shadow_run_id,
                "scope": record.scope,
                "src_it": record.source_interaction_id,
                "src_ev": record.source_event_ref,
                "cfg_dg": record.runtime_config_digest,
                "started": record.started_at.isoformat(),
                "completed": record.completed_at.isoformat(),
                "status": record.status.value,
                "sit_sum": record.mr_situation_summary,
                "intent": record.mr_intent_type,
                "policy": record.mr_policy_decision,
                "reason_codes": json.dumps(list(record.mr_policy_reason_codes), sort_keys=True),
                "expr_ref": record.mr_expression_ref,
                "would_send": int(record.mr_would_send) if record.mr_would_send is not None else None,
                "ho_json": _serialize_host_outcome(record.host_outcome),
                "cmp_json": _serialize_comparison(record.comparison),
                "fail_stage": record.failure_stage,
                "fail_reason": record.failure_reason,
                "snap_json": _serialize_snapshot(record.captured_snapshot),
                "rec_json": record_json,
            },
        )
        self._conn.commit()

    def get(self, shadow_run_id: str) -> ShadowRunRecord | None:
        """Retrieve a record by shadow_run_id, or None if not found."""
        row = self._conn.execute(
            "SELECT * FROM shadow_runs WHERE shadow_run_id = ?",
            (shadow_run_id,),
        ).fetchone()
        if row is None:
            return None
        return _record_from_row(row)

    def all(self) -> list[ShadowRunRecord]:
        """Return all records ordered by started_at descending."""
        rows = self._conn.execute(
            "SELECT * FROM shadow_runs ORDER BY started_at DESC"
        ).fetchall()
        return [_record_from_row(row) for row in rows]

    def close(self) -> None:
        """Close the database connection."""
        self._conn.close()
