"""Transient Trace Journal backed by observation_trace.sqlite.

HARD AUTHORITY BOUNDARY (TICKET: OW-TRANSIENT-TRACE-JOURNAL-V1):
This journal persists transient runtime artifacts for human causal debugging
and observability.

MR CORE MUST NEVER READ FROM THIS DATABASE.
Only Observation Window (and test fixtures) read from it.
All write operations are fail-open (best-effort); exceptions are logged as
warnings and NEVER propagated to MR or Hermes runtime.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import re
import sqlite3
from typing import Any
import uuid

from mind_runtime.contracts.telemetry import TelemetrySinkProtocol, TelemetryStage

_logger = logging.getLogger("observation_window.transient_trace_journal")

_SENSITIVE_KEY_SUBSTRINGS = ("api_key", "secret", "token", "auth", "password", "bearer")
_SENSITIVE_PREFIXES = ("Bearer ", "sk-")
_MAX_STRING_LEN = 4000


def _sanitize_value(val: Any) -> Any:
    if isinstance(val, dict):
        out = {}
        for k, v in val.items():
            k_lower = str(k).lower()
            if any(s in k_lower for s in _SENSITIVE_KEY_SUBSTRINGS):
                out[k] = "[REDACTED]"
            elif k_lower in ("reasoning", "reasoning_content", "chain_of_thought", "internal_thought"):
                out[k] = "[REDACTED_INTERNAL_THOUGHT]"
            else:
                out[k] = _sanitize_value(v)
        return out
    elif isinstance(val, (list, tuple)):
        return [_sanitize_value(item) for item in val]
    elif isinstance(val, str):
        if any(val.startswith(p) for p in _SENSITIVE_PREFIXES):
            return "[REDACTED]"
        if len(val) > _MAX_STRING_LEN:
            return val[:_MAX_STRING_LEN] + " ... [TRUNCATED]"
        return val
    elif isinstance(val, (int, float, bool)) or val is None:
        return val
    from datetime import timedelta as _td, datetime as _dt
    if isinstance(val, _td):
        return val.total_seconds()
    if isinstance(val, _dt):
        return val.isoformat()
    return str(val)


class TransientTraceJournal(TelemetrySinkProtocol):
    """Observer SQLite journal for transient execution artifacts."""

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = Path(db_path)
        self._init_db()

    @property
    def db_path(self) -> Path:
        return self._db_path

    def _get_connection(self, readonly: bool = False) -> sqlite3.Connection:
        if readonly:
            uri = f"file:{self._db_path.as_posix()}?mode=ro"
            conn = sqlite3.connect(uri, uri=True, timeout=5.0)
        else:
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(self._db_path), timeout=10.0)
            conn.execute("PRAGMA journal_mode = WAL;")
            conn.execute("PRAGMA synchronous = NORMAL;")
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        try:
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            with self._get_connection() as conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS trace_events (
                        event_id TEXT PRIMARY KEY,
                        interaction_id TEXT NOT NULL,
                        stage TEXT NOT NULL,
                        occurred_at TEXT NOT NULL,
                        sequence_no INTEGER NOT NULL,
                        status TEXT NOT NULL,
                        payload_json TEXT NOT NULL,
                        source_refs_json TEXT NOT NULL,
                        created_at TEXT NOT NULL
                    );
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS journal_metadata (
                        key TEXT PRIMARY KEY,
                        value TEXT NOT NULL
                    );
                    """
                )
                now_iso = datetime.now(timezone.utc).isoformat()
                conn.execute(
                    "INSERT OR IGNORE INTO journal_metadata (key, value) VALUES ('activation_at', ?);",
                    (now_iso,),
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_trace_events_interaction "
                    "ON trace_events(interaction_id, sequence_no);"
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_trace_events_stage "
                    "ON trace_events(stage);"
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_trace_events_occurred_at "
                    "ON trace_events(occurred_at);"
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS llm_usage_records (
                        record_id TEXT PRIMARY KEY,
                        interaction_id TEXT NOT NULL,
                        stage TEXT NOT NULL,
                        provider TEXT NOT NULL,
                        model TEXT NOT NULL,
                        prompt_tokens INTEGER,
                        completion_tokens INTEGER,
                        total_tokens INTEGER,
                        usage_source TEXT NOT NULL,
                        latency_ms REAL,
                        success INTEGER NOT NULL,
                        retry_count INTEGER NOT NULL DEFAULT 0,
                        error_message TEXT,
                        occurred_at TEXT NOT NULL,
                        created_at TEXT NOT NULL
                    );
                    """
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_llm_usage_interaction "
                    "ON llm_usage_records(interaction_id);"
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_llm_usage_occurred_at "
                    "ON llm_usage_records(occurred_at);"
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_llm_usage_stage "
                    "ON llm_usage_records(stage);"
                )
                conn.commit()
        except Exception as exc:
            _logger.warning("Failed to initialize trace journal DB %s: %s", self._db_path, exc)

    def get_activation_at(self) -> str | None:
        """Query positive persisted activation boundary from metadata or earliest trace."""
        try:
            with self._get_connection() as conn:
                row = conn.execute(
                    "SELECT value FROM journal_metadata WHERE key = 'activation_at' LIMIT 1"
                ).fetchone()
                if row and row[0]:
                    return row[0]
                min_row = conn.execute(
                    "SELECT MIN(created_at) FROM trace_events WHERE created_at IS NOT NULL"
                ).fetchone()
                if min_row and min_row[0]:
                    return min_row[0]
        except Exception:
            pass
        return None

    def record(
        self,
        interaction_id: str,
        stage: str,
        status: str,
        occurred_at: datetime,
        payload: dict[str, Any],
        source_refs: tuple[str, ...] = (),
    ) -> None:
        """Append one non-authoritative telemetry event (strictly fail-open)."""
        try:
            event_id = f"tevt-{uuid.uuid4().hex[:12]}"
            sanitized = _sanitize_value(payload)
            payload_json = json.dumps(sanitized, ensure_ascii=False)
            source_refs_json = json.dumps(list(source_refs), ensure_ascii=False)

            if isinstance(occurred_at, datetime):
                if occurred_at.tzinfo is None:
                    occurred_at = occurred_at.replace(tzinfo=timezone.utc)
                occ_str = occurred_at.isoformat()
            else:
                occ_str = str(occurred_at)

            now_str = datetime.now(timezone.utc).isoformat()

            with self._get_connection() as conn:
                conn.execute(
                    """
                    INSERT INTO trace_events (
                        event_id, interaction_id, stage, occurred_at, sequence_no,
                        status, payload_json, source_refs_json, created_at
                    ) VALUES (
                        ?, ?, ?, ?,
                        (SELECT COALESCE(MAX(sequence_no), 0) + 1 FROM trace_events WHERE interaction_id = ?),
                        ?, ?, ?, ?
                    )
                    """,
                    (
                        event_id,
                        interaction_id,
                        stage,
                        occ_str,
                        interaction_id,
                        status,
                        payload_json,
                        source_refs_json,
                        now_str,
                    ),
                )
                conn.commit()
        except Exception as exc:
            _logger.warning(
                "TransientTraceJournal.record failed fail-open (stage=%s, interaction=%s): %s",
                stage,
                interaction_id,
                exc,
            )

    def get_events_for_interaction(self, interaction_id: str) -> list[dict[str, Any]]:
        """Reader for Observation Window: returns all events for interaction in order."""
        if not self._db_path.exists():
            return []
        try:
            with self._get_connection(readonly=True) as conn:
                rows = conn.execute(
                    """
                    SELECT event_id, interaction_id, stage, occurred_at, sequence_no,
                           status, payload_json, source_refs_json, created_at
                    FROM trace_events
                    WHERE interaction_id = ?
                    ORDER BY sequence_no ASC
                    """,
                    (interaction_id,),
                ).fetchall()
                result = []
                for r in rows:
                    try:
                        p = json.loads(r["payload_json"])
                    except Exception:
                        p = {}
                    try:
                        s_refs = json.loads(r["source_refs_json"])
                    except Exception:
                        s_refs = []
                    result.append(
                        {
                            "event_id": r["event_id"],
                            "interaction_id": r["interaction_id"],
                            "stage": r["stage"],
                            "occurred_at": r["occurred_at"],
                            "sequence_no": r["sequence_no"],
                            "status": r["status"],
                            "payload": p,
                            "source_refs": s_refs,
                            "created_at": r["created_at"],
                        }
                    )
                return result
        except Exception as exc:
            _logger.warning("get_events_for_interaction failed: %s", exc)
            return []

    def get_latest_event_by_stage(
        self, interaction_id: str, stage: str
    ) -> dict[str, Any] | None:
        events = self.get_events_for_interaction(interaction_id)
        for ev in reversed(events):
            if ev["stage"] == stage:
                return ev
        return None

    def get_distinct_interaction_ids(self, limit: int = 50) -> list[str]:
        if not self._db_path.exists():
            return []
        try:
            with self._get_connection(readonly=True) as conn:
                rows = conn.execute(
                    """
                    SELECT interaction_id
                    FROM trace_events
                    GROUP BY interaction_id
                    ORDER BY MAX(occurred_at) DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
                return [r[0] for r in rows]
        except Exception as exc:
            _logger.warning("get_distinct_interaction_ids failed: %s", exc)
            return []

    def record_llm_usage(
        self,
        *,
        interaction_id: str,
        stage: str,
        provider: str,
        model: str,
        prompt_tokens: int | None,
        completion_tokens: int | None,
        total_tokens: int | None,
        usage_source: str,
        latency_ms: float | None = None,
        success: bool = True,
        retry_count: int = 0,
        error_message: str | None = None,
        occurred_at: datetime | None = None,
    ) -> None:
        """Record an LLM call token usage and execution event (fail-open)."""
        try:
            record_id = f"usg-{uuid.uuid4().hex[:12]}"
            if occurred_at is None:
                occ_dt = datetime.now(timezone.utc)
            elif isinstance(occurred_at, datetime):
                occ_dt = occurred_at if occurred_at.tzinfo is not None else occurred_at.replace(tzinfo=timezone.utc)
            else:
                occ_dt = datetime.now(timezone.utc)
            occ_str = occ_dt.isoformat()
            now_str = datetime.now(timezone.utc).isoformat()

            valid_source = usage_source if usage_source in ("ACTUAL", "ESTIMATED", "UNAVAILABLE") else "UNAVAILABLE"
            if prompt_tokens is None and total_tokens is None:
                valid_source = "UNAVAILABLE"

            with self._get_connection() as conn:
                conn.execute(
                    """
                    INSERT INTO llm_usage_records (
                        record_id, interaction_id, stage, provider, model,
                        prompt_tokens, completion_tokens, total_tokens,
                        usage_source, latency_ms, success, retry_count,
                        error_message, occurred_at, created_at
                    ) VALUES (
                        ?, ?, ?, ?, ?,
                        ?, ?, ?,
                        ?, ?, ?, ?,
                        ?, ?, ?
                    )
                    """,
                    (
                        record_id,
                        interaction_id,
                        stage,
                        provider,
                        model,
                        prompt_tokens,
                        completion_tokens,
                        total_tokens,
                        valid_source,
                        float(latency_ms) if latency_ms is not None else None,
                        1 if success else 0,
                        retry_count,
                        error_message,
                        occ_str,
                        now_str,
                    ),
                )
                conn.commit()
        except Exception as exc:
            _logger.warning(
                "TransientTraceJournal.record_llm_usage failed fail-open (stage=%s, interaction=%s): %s",
                stage,
                interaction_id,
                exc,
            )

    def get_interaction_llm_usage(self, interaction_id: str) -> list[dict[str, Any]]:
        """Return all LLM usage records for an interaction in chronological order."""
        if not self._db_path.exists():
            return []
        try:
            with self._get_connection(readonly=True) as conn:
                rows = conn.execute(
                    """
                    SELECT record_id, interaction_id, stage, provider, model,
                           prompt_tokens, completion_tokens, total_tokens,
                           usage_source, latency_ms, success, retry_count,
                           error_message, occurred_at, created_at
                    FROM llm_usage_records
                    WHERE interaction_id = ?
                    ORDER BY occurred_at ASC, record_id ASC
                    """,
                    (interaction_id,),
                ).fetchall()
                return [
                    {
                        "record_id": r["record_id"],
                        "interaction_id": r["interaction_id"],
                        "stage": r["stage"],
                        "provider": r["provider"],
                        "model": r["model"],
                        "prompt_tokens": r["prompt_tokens"],
                        "completion_tokens": r["completion_tokens"],
                        "total_tokens": r["total_tokens"],
                        "usage_source": r["usage_source"],
                        "latency_ms": r["latency_ms"],
                        "success": bool(r["success"]),
                        "retry_count": r["retry_count"],
                        "error_message": r["error_message"],
                        "occurred_at": r["occurred_at"],
                        "created_at": r["created_at"],
                    }
                    for r in rows
                ]
        except Exception as exc:
            _logger.warning("get_interaction_llm_usage failed: %s", exc)
            return []

    def get_aggregated_llm_usage(
        self,
        *,
        since_iso: str | None = None,
        hours: int | None = None,
    ) -> dict[str, Any]:
        """Compute aggregated LLM usage summary for a time window."""
        if not self._db_path.exists():
            return {
                "call_count": 0,
                "successful_calls": 0,
                "failed_calls": 0,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
                "by_model": {},
                "completeness": "EMPTY",
            }
        from datetime import timedelta
        if since_iso is None and hours is not None:
            cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
            since_iso = cutoff.isoformat()

        try:
            with self._get_connection(readonly=True) as conn:
                if since_iso:
                    rows = conn.execute(
                        """
                        SELECT record_id, provider, model, prompt_tokens,
                               completion_tokens, total_tokens, usage_source, success
                        FROM llm_usage_records
                        WHERE occurred_at >= ?
                        """,
                        (since_iso,),
                    ).fetchall()
                else:
                    rows = conn.execute(
                        """
                        SELECT record_id, provider, model, prompt_tokens,
                               completion_tokens, total_tokens, usage_source, success
                        FROM llm_usage_records
                        """
                    ).fetchall()

                call_count = len(rows)
                if call_count == 0:
                    return {
                        "call_count": 0,
                        "successful_calls": 0,
                        "failed_calls": 0,
                        "prompt_tokens": 0,
                        "completion_tokens": 0,
                        "total_tokens": 0,
                        "by_model": {},
                        "completeness": "EMPTY",
                    }

                succ = sum(1 for r in rows if r["success"])
                failed = call_count - succ
                p_tokens = sum((r["prompt_tokens"] or 0) for r in rows)
                c_tokens = sum((r["completion_tokens"] or 0) for r in rows)
                t_tokens = sum((r["total_tokens"] or 0) for r in rows)

                has_actual = any(r["usage_source"] in ("ACTUAL", "ESTIMATED") for r in rows)
                has_unavail = any(r["usage_source"] == "UNAVAILABLE" for r in rows)
                if has_actual and not has_unavail:
                    completeness = "FULL"
                elif has_actual and has_unavail:
                    completeness = "PARTIAL"
                else:
                    completeness = "NONE"

                by_model: dict[str, dict[str, int]] = {}
                for r in rows:
                    m = r["model"] or "unknown"
                    if m not in by_model:
                        by_model[m] = {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
                    by_model[m]["calls"] += 1
                    by_model[m]["prompt_tokens"] += (r["prompt_tokens"] or 0)
                    by_model[m]["completion_tokens"] += (r["completion_tokens"] or 0)
                    by_model[m]["total_tokens"] += (r["total_tokens"] or 0)

                return {
                    "call_count": call_count,
                    "successful_calls": succ,
                    "failed_calls": failed,
                    "prompt_tokens": p_tokens,
                    "completion_tokens": c_tokens,
                    "total_tokens": t_tokens,
                    "by_model": by_model,
                    "completeness": completeness,
                }
        except Exception as exc:
            _logger.warning("get_aggregated_llm_usage failed: %s", exc)
            return {
                "call_count": 0,
                "successful_calls": 0,
                "failed_calls": 0,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
                "by_model": {},
                "completeness": "NONE",
            }

    def get_recent_windows_usage(self) -> dict[str, Any]:
        return {
            "1h": self.get_aggregated_llm_usage(hours=1),
            "24h": self.get_aggregated_llm_usage(hours=24),
        }
