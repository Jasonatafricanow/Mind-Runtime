"""LegacyD11Reader — read-only access layer for D11 legacy shadow DBs.

Per migration dispatch MIG-1. Hard boundaries:

  * READ ONLY. Every connection uses SQLite ``mode=ro`` URI so the
    reader physically cannot INSERT/UPDATE/DELETE/ALTER/VACUUM.
  * Never writes a migration marker back into a legacy DB.
  * Never invents a relation: `get_related_affect` joins on the frozen
    JOIN CONTRACT (content_id EXACT_1_TO_1) and returns None when no
    row exists — it never fabricates an annotation.
  * Bounded scans: every scan is a paged generator over a cursor, so
    75,997 rows are never loaded into memory at once.
  * Tolerates a concurrent writer on shadow_states_v2.db: connections
    are short-lived per call and opened read-only, so no write lock is
    ever requested and no corruption is caused.

The reader returns legacy DTOs (LegacyEventRecord / LegacyAffectAnnotation
/ LegacyStateSnapshot), never canonical MR contracts.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterator

from mind_runtime.shadow.legacy_dto import (
    LegacyAffectAnnotation,
    LegacyEventRecord,
    LegacySourceRef,
    LegacyStateSnapshot,
)

# Default legacy locations (Hermes profile).
DEFAULT_PROFILE_DIR = Path.home() / ".hermes" / "profiles" / "xiyue"
DEFAULT_EVENTS_DB = DEFAULT_PROFILE_DIR / "shadow.db"
DEFAULT_AFFECT_DB = DEFAULT_PROFILE_DIR / "shadow_affect.db"
DEFAULT_STATES_DB = DEFAULT_PROFILE_DIR / "shadow_states.db"
DEFAULT_STATES_V2_DB = DEFAULT_PROFILE_DIR / "shadow_states_v2.db"

_PAGE_SIZE = 2000


def _ro_connect(path: str | Path) -> sqlite3.Connection:
    """Open a SQLite DB strictly read-only (mode=ro URI)."""
    p = str(path).replace("'", "''")
    con = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


@dataclass(frozen=True, slots=True)
class LegacyWatermark:
    """Immutable source snapshot identity / max sequence position.

    For stopped writers this is the final max id. For the active v2
    writer it is a T0 watermark; the future cutover must scan delta > T0.
    """

    db: str
    max_content_id: int | None
    max_event_id: int | None
    max_affect_id: int | None
    max_state_id: int | None
    max_ts: str | None
    writer_active: bool


class LegacyD11Reader:
    """Read-only access to D11 legacy shadow databases.

    Each scan is a bounded paged generator. All connections are
    short-lived (context-managed per operation) and read-only.
    """

    def __init__(
        self,
        *,
        events_db: str | Path = DEFAULT_EVENTS_DB,
        affect_db: str | Path = DEFAULT_AFFECT_DB,
        states_db: str | Path = DEFAULT_STATES_DB,
        states_v2_db: str | Path = DEFAULT_STATES_V2_DB,
        page_size: int = _PAGE_SIZE,
    ) -> None:
        self._events_db = str(events_db)
        self._affect_db = str(affect_db)
        self._states_db = str(states_db)
        self._states_v2_db = str(states_v2_db)
        self._page_size = page_size

    # ── internal helpers ──────────────────────────────────────────────────

    def _rows(
        self,
        db: str,
        table: str,
        sql_where: str,
        params: tuple,
        order_col: str,
    ) -> Iterator[sqlite3.Row]:
        """Yield rows from a read-only connection in bounded pages."""
        con = _ro_connect(db)
        try:
            cur = con.execute(
                f"SELECT * FROM {table} WHERE {sql_where} "
                f"ORDER BY {order_col} LIMIT ?",
                params + (self._page_size,),
            )
            rows = cur.fetchall()
            while rows:
                for r in rows:
                    yield r
                last = rows[-1]
                cur = con.execute(
                    f"SELECT * FROM {table} WHERE {sql_where} AND {order_col} > ? "
                    f"ORDER BY {order_col} LIMIT ?",
                    params + (last[order_col], self._page_size),
                )
                rows = cur.fetchall()
        finally:
            con.close()

    # ── events ─────────────────────────────────────────────────────────────

    def scan_events(
        self,
        *,
        after_content_id: int = 0,
        channel: str | None = None,
        sender: str | None = None,
    ) -> Iterator[LegacyEventRecord]:
        """Page over shadow_events, oldest first (by content_id)."""
        conds, params = ["content_id > ?"], [after_content_id]
        if channel:
            conds.append("channel = ?")
            params.append(channel)
        if sender:
            conds.append("sender = ?")
            params.append(sender)
        where = " AND ".join(conds)
        for r in self._rows(self._events_db, "shadow_events", where, tuple(params), "content_id"):
            yield self._event_from_row(r)

    @staticmethod
    def _event_from_row(r: sqlite3.Row) -> LegacyEventRecord:
        return LegacyEventRecord(
            source=LegacySourceRef(db="shadow.db", table="shadow_events", legacy_pk=r["content_id"]),
            content_id=r["content_id"],
            event_id=r["event_id"],
            ts=_parse_dt(r["ts"]),
            event_ts=_parse_dt(r["event_ts"]),
            user_hash=r["user_hash"],
            session_hash=r["session_hash"],
            channel=r["channel"],
            sender=r["sender"],
            trigger=r["trigger"],
            source_domain=r["source_domain"],
            redacted_text=r["redacted_text"],
        )

    def get_event(self, content_id: int) -> LegacyEventRecord | None:
        """Fetch one event by content_id (None when absent)."""
        con = _ro_connect(self._events_db)
        try:
            r = con.execute(
                "SELECT * FROM shadow_events WHERE content_id = ?", (content_id,)
            ).fetchone()
            return self._event_from_row(r) if r else None
        finally:
            con.close()

    # ── affect ─────────────────────────────────────────────────────────────

    def scan_affect_annotations(
        self,
        *,
        after_content_id: int = 0,
        dimension: str | None = None,
    ) -> Iterator[LegacyAffectAnnotation]:
        conds, params = ["content_id > ?"], [after_content_id]
        if dimension:
            conds.append("dimension = ?")
            params.append(dimension)
        where = " AND ".join(conds)
        for r in self._rows(self._affect_db, "shadow_affect", where, tuple(params), "content_id"):
            yield self._affect_from_row(r)

    @staticmethod
    def _affect_from_row(r: sqlite3.Row) -> LegacyAffectAnnotation:
        return LegacyAffectAnnotation(
            source=LegacySourceRef(
                db="shadow_affect.db", table="shadow_affect", legacy_pk=r["content_id"]
            ),
            content_id=r["content_id"],
            affect_id=r["affect_id"],
            ts=_parse_dt(r["ts"]),
            session_hash=r["session_hash"],
            channel=r["channel"],
            sender=r["sender"],
            dimension=r["dimension"],
            confidence=r["confidence"],
        )

    def get_related_affect(self, content_id: int) -> LegacyAffectAnnotation | None:
        """Fetch the affect annotation joined by content_id (1:1 contract).

        Returns None when the event has no affect row — NEVER fabricates
        an annotation (MIG-1 R5).
        """
        con = _ro_connect(self._affect_db)
        try:
            r = con.execute(
                "SELECT * FROM shadow_affect WHERE content_id = ?", (content_id,)
            ).fetchone()
            return self._affect_from_row(r) if r else None
        finally:
            con.close()

    # ── states ─────────────────────────────────────────────────────────────

    def scan_state_snapshots(
        self,
        *,
        after_content_id: int = 0,
        db: str = "v2",
        category: str | None = None,
    ) -> Iterator[LegacyStateSnapshot]:
        """Page over shadow_states (v1 or v2) by content_id.

        db: 'v2' (default, active writer) or 'v1' (stopped).
        """
        path = self._states_v2_db if db == "v2" else self._states_db
        conds, params = ["content_id > ?"], [after_content_id]
        if category:
            conds.append("category = ?")
            params.append(category)
        where = " AND ".join(conds)
        for r in self._rows(path, "shadow_states", where, tuple(params), "content_id"):
            yield self._state_from_row(r, db)

    @staticmethod
    def _state_from_row(r: sqlite3.Row, db_label: str) -> LegacyStateSnapshot:
        return LegacyStateSnapshot(
            source=LegacySourceRef(
                db=f"shadow_states{'_v2' if db_label == 'v2' else ''}.db",
                table="shadow_states",
                legacy_pk=r["content_id"],
            ),
            content_id=r["content_id"],
            state_id=r["state_id"],
            ts=_parse_dt(r["ts"]),
            session_hash=r["session_hash"],
            category=r["category"],
            key=r["key"],
            value=r["value"],
            valid_until=_parse_dt(r["valid_until"]),
        )

    # ── watermark ──────────────────────────────────────────────────────────

    def watermark(self) -> LegacyWatermark:
        """Return immutable source snapshot identity / max positions.

        For stopped DBs (shadow.db, shadow_affect.db, shadow_states.db)
        this is the final max id. For the active shadow_states_v2.db it
        is a T0 watermark: the future cutover must scan delta > T0.
        """
        ev = self._max_positions(self._events_db, "shadow_events", "content_id", "event_id", "ts")
        af = self._max_positions(
            self._affect_db, "shadow_affect", "content_id", "affect_id", "ts"
        )
        st1 = self._max_positions(self._states_db, "shadow_states", "content_id", "state_id", "ts")
        st2 = self._max_positions(
            self._states_v2_db, "shadow_states", "content_id", "state_id", "ts"
        )
        return LegacyWatermark(
            db="shadow.db",
            max_content_id=ev["content_id"],
            max_event_id=ev["id"],
            max_affect_id=af["id"],
            max_state_id=st2["id"],
            max_ts=ev["ts"],
            writer_active=False,
        )

    @staticmethod
    def _max_positions(
        db: str, table: str, cid_col: str, id_col: str, ts_col: str
    ) -> dict:
        con = _ro_connect(db)
        try:
            r = con.execute(
                f"SELECT MAX({cid_col}) cid, MAX({id_col}) id, MAX({ts_col}) ts "
                f"FROM {table}"
            ).fetchone()
            return {"content_id": r["cid"], "id": r["id"], "ts": r["ts"]}
        finally:
            con.close()

    # ── counts (R2 exact-count support) ────────────────────────────────────

    def count_events(self) -> int:
        return self._count(self._events_db, "shadow_events")

    def count_affect(self) -> int:
        return self._count(self._affect_db, "shadow_affect")

    def count_states(self, db: str = "v2") -> int:
        path = self._states_v2_db if db == "v2" else self._states_db
        return self._count(path, "shadow_states")

    @staticmethod
    def _count(db: str, table: str) -> int:
        con = _ro_connect(db)
        try:
            r = con.execute(f"SELECT COUNT(*) c FROM {table}").fetchone()
            return int(r["c"])
        finally:
            con.close()


def _parse_dt(value: str | None) -> datetime | None:
    """Parse ISO-8601 string to aware datetime, or None when absent/invalid."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None
