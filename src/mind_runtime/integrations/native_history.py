"""Read-only Hermes source adapter; raw text never enters sidecar persistence."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from mr_mem import Scope, SourceRef, SourceRefReader


@dataclass(frozen=True, slots=True)
class NativeRecord:
    ref: SourceRef
    role: str
    text: str
    ordering_key: tuple[float, int]
    tool_only: bool = False


class NativeSourceStore(SourceRefReader, Protocol):
    """Hermes and future AML adapters share this read-only source surface."""

    @property
    def scope(self) -> Scope: ...

    @property
    def namespace(self) -> str: ...

    def read(
        self,
        *,
        limit: int = 100,
        after: tuple[float, int] | None = None,
    ) -> tuple[NativeRecord, ...]: ...

    def get_record(self, scope: Scope, ref: SourceRef) -> NativeRecord | None: ...


@dataclass(frozen=True, slots=True)
class SourceFragment:
    fragment_id: str
    ref: SourceRef
    role: str
    text: str
    start: int
    end: int


def structural_drop(record: NativeRecord) -> str | None:
    if record.role in {"tool", "function", "system", "session_meta"}:
        return "machine-role"
    if record.role == "assistant" and record.tool_only and not record.text.strip():
        return "empty-tool-envelope"
    if not record.text.strip():
        return "empty-record"
    if re.fullmatch(
        r"\[IMPORTANT: Background process [a-zA-Z0-9_]+ exited \(exit code -?\d+\)\."
        r"\nCommand: [\s\S]*\nOutput:\n[\s\S]*\]",
        record.text,
    ):
        return "host-background-process-envelope"
    return None


def source_fragments(
    record: NativeRecord,
    *,
    max_characters: int = 1200,
) -> tuple[SourceFragment, ...]:
    """Host binds sentence/line slices; models select IDs, never compute offsets."""
    if type(max_characters) is not int or not 100 <= max_characters <= 4096:
        raise ValueError("invalid fragment bound")
    fragments = []
    start = 0
    boundaries = [match.end() for match in re.finditer(r"[\n;；。!?！？]", record.text)]
    boundaries.append(len(record.text))
    for boundary in boundaries:
        while start < boundary:
            end = min(boundary, start + max_characters)
            text = record.text[start:end]
            if text.strip():
                key = f"{record.ref.version_key}:{start}:{end}"
                fragments.append(
                    SourceFragment(
                        hashlib.sha256(key.encode()).hexdigest(),
                        record.ref,
                        record.role,
                        text,
                        start,
                        end,
                    )
                )
            start = end
    return tuple(fragments)


class HermesSourceStore:
    """A configured native user/session boundary, not a second history store."""

    def __init__(
        self,
        path: Path,
        *,
        scope: Scope,
        source_namespace: str,
        user_id: str | None,
        session_ids: tuple[str, ...] = (),
    ) -> None:
        if not source_namespace.strip() or (user_id is None and not session_ids):
            raise ValueError("explicit native namespace and user or session ownership required")
        if user_id is not None and not user_id.strip():
            raise ValueError("native user ID must be nonempty")
        if any(not session.strip() for session in session_ids):
            raise ValueError("session IDs must be nonempty")
        self._scope, self._namespace, self._user = scope, source_namespace, user_id
        self._sessions = session_ids
        self._db = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
        self._db.execute("PRAGMA query_only=ON")

    def close(self) -> None:
        self._db.close()

    @property
    def scope(self) -> Scope:
        return self._scope

    @property
    def namespace(self) -> str:
        return self._namespace

    def _record(self, row: tuple[int, str, str, str | None, float, str | None]) -> NativeRecord:
        mid, session, role, content, timestamp, tools = row
        text = content if isinstance(content, str) else ""
        fingerprint = hashlib.sha256(
            json.dumps([role, text, timestamp, tools], ensure_ascii=False).encode()
        ).hexdigest()
        return NativeRecord(
            SourceRef(
                self._namespace,
                str(session),
                str(mid),
                datetime.fromtimestamp(float(timestamp), UTC),
                fingerprint=fingerprint,
            ),
            str(role),
            text,
            (float(timestamp), int(mid)),
            bool(tools),
        )

    def _ownership(self) -> tuple[str, tuple[str, ...]]:
        condition = "s.user_id IS NULL" if self._user is None else "s.user_id=?"
        parameters: tuple[str, ...] = () if self._user is None else (self._user,)
        if self._sessions:
            placeholders = ",".join("?" for _ in self._sessions)
            condition += f" AND s.id IN ({placeholders})"
            parameters += self._sessions
        return condition, parameters

    def read(
        self,
        *,
        limit: int = 100,
        after: tuple[float, int] | None = None,
    ) -> tuple[NativeRecord, ...]:
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError("bounded native read requires 1..1000 records")
        timestamp, mid = after if after is not None else (float("-inf"), -1)
        owner_sql, owner_params = self._ownership()
        rows = self._db.execute(
            "SELECT m.id,m.session_id,m.role,m.content,m.timestamp,m.tool_calls "
            "FROM messages m JOIN sessions s ON s.id=m.session_id "
            f"WHERE {owner_sql} AND (m.active=1 OR m.compacted=1) "
            "AND (m.timestamp>? OR (m.timestamp=? AND m.id>?)) "
            "ORDER BY m.timestamp,m.id LIMIT ?",
            (*owner_params, timestamp, timestamp, mid, limit),
        ).fetchall()
        return tuple(self._record(row) for row in rows)

    def current_ref(self, scope: Scope, ref: SourceRef) -> SourceRef | None:
        record = self.get_record(scope, ref)
        return None if record is None else record.ref

    def get_record(self, scope: Scope, ref: SourceRef) -> NativeRecord | None:
        """Fetch one scoped receipt pointer; never rescan the complete history."""
        if scope != self._scope or ref.source_namespace != self._namespace:
            return None
        owner_sql, owner_params = self._ownership()
        row = self._db.execute(
            "SELECT m.id,m.session_id,m.role,m.content,m.timestamp,m.tool_calls "
            "FROM messages m JOIN sessions s ON s.id=m.session_id "
            f"WHERE m.id=? AND m.session_id=? AND {owner_sql} "
            "AND (m.active=1 OR m.compacted=1)",
            (ref.record_id, ref.session_id, *owner_params),
        ).fetchone()
        return None if row is None else self._record(row)
