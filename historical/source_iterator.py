"""Read-only Hermes native source authority, independently bound to MR-Mem."""

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from mr_mem import ScopeDomain, SourceRef

from historical.source_curator import HistoricalSourceCurator, SourceDisposition


@dataclass(frozen=True)
class HistoricalSource:
    source_ref: SourceRef
    ordering_key: tuple[float, int]
    role: str
    record_type: str
    content: str | None
    user_id: str

    @property
    def interaction_id(self):
        return "historical:" + hashlib.sha256(self.source_ref.source_key.encode()).hexdigest()


class HistoricalSourceIterator:
    def __init__(self, path, *, scope, namespace, user_id):
        if not namespace.strip() or not user_id.strip():
            raise ValueError("explicit namespace and native user owner required")
        if scope.domain != ScopeDomain.USER or scope.user_id != user_id:
            raise ValueError("historical USER scope must match native user owner")
        self.path = Path(path).resolve(strict=True)
        self.scope, self.namespace, self.user_id = scope, namespace, user_id
        self._db = sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True)
        self._db.execute("PRAGMA query_only=ON")
        self._db.row_factory = sqlite3.Row
        self._columns = {r[1] for r in self._db.execute("PRAGMA table_info(messages)")}
        self._bindings = {}

    def close(self):
        self._db.close()

    def _query(self, *, after=None, record_id=None, session_id=None, limit=None):
        fields = ["m.id", "m.session_id", "m.role", "m.content", "m.timestamp", "s.user_id"]
        for name in ("record_type", "tool_calls", "tool_name", "active", "compacted"):
            if name in self._columns:
                fields.append("m." + name)
        sql = (
            "SELECT "
            + ",".join(fields)
            + " FROM messages m JOIN sessions s ON s.id=m.session_id WHERE s.user_id=?"
        )
        args = [self.user_id]
        if after is not None:
            sql += " AND (m.timestamp>? OR (m.timestamp=? AND m.id>?))"
            args += [after[0], after[0], after[1]]
        if record_id is not None:
            sql += " AND m.id=?"
            args.append(record_id)
        if session_id is not None:
            sql += " AND m.session_id=?"
            args.append(session_id)
        sql += " ORDER BY m.timestamp,m.id"
        if limit is not None:
            sql += " LIMIT ?"
            args.append(limit)
        return self._db.execute(sql, args)

    def _source(self, row):
        data = dict(row)
        at = datetime.fromtimestamp(data["timestamp"], UTC)
        fingerprint = hashlib.sha256(
            json.dumps(data, ensure_ascii=False, sort_keys=True).encode()
        ).hexdigest()
        calls = data.get("tool_calls")
        if isinstance(calls, str):
            try:
                calls = json.loads(calls)
            except ValueError:
                calls = True  # Unreadable execution marker cannot gain cognition eligibility.
        kind = "tool_call" if calls else (data.get("record_type") or data["role"])
        if not data.get("active", 1) and not data.get("compacted", 0):
            kind = "agent_execution"  # Inactive/rewound rows have no semantic eligibility.
        ref = SourceRef(
            self.namespace, data["session_id"], str(data["id"]), at, fingerprint=fingerprint
        )
        return HistoricalSource(
            ref,
            (float(data["timestamp"]), data["id"]),
            data["role"],
            kind,
            data["content"],
            data["user_id"],
        )

    def iterate(self, *, after=None):
        # Release every SELECT before invoking the worker. A live cursor would
        # pin an old SQLite snapshot and hide source drift from exact validation.
        cursor = after
        while rows := self._query(after=cursor, limit=1).fetchall():
            source = self._source(rows[0])
            cursor = source.ordering_key
            yield source

    def get(self, ref):
        if ref.source_namespace != self.namespace:
            return None
        rows = self._query(record_id=ref.record_id, session_id=ref.session_id).fetchall()
        return self._source(rows[0]) if len(rows) == 1 else None

    def before(self, source, *, limit=4):
        if not 0 < limit <= 8:
            raise ValueError("context lookback must be in [1,8]")
        # Bounded same-session context lookup; never materialize a transcript.
        fields = "m.id,m.session_id,m.role,m.content,m.timestamp,s.user_id"
        for name in ("record_type", "tool_calls", "tool_name", "active", "compacted"):
            if name in self._columns:
                fields += ",m." + name
        rows = self._db.execute(
            "SELECT " + fields + " FROM messages m JOIN sessions s ON s.id=m.session_id "
            "WHERE s.user_id=? AND m.session_id=? "
            "AND (m.timestamp<? OR (m.timestamp=? AND m.id<?)) "
            "ORDER BY m.timestamp DESC,m.id DESC LIMIT ?",
            (
                self.user_id,
                source.source_ref.session_id,
                source.ordering_key[0],
                source.ordering_key[0],
                source.ordering_key[1],
                limit,
            ),
        ).fetchall()
        return tuple(self._source(r) for r in reversed(rows))

    def bind(self, source):
        current = self.get(source.source_ref)
        if (
            current != source
            or HistoricalSourceCurator().classify(source) != SourceDisposition.COMPILE
        ):
            raise ValueError("exact current eligible USER source required")
        self._bindings[source.interaction_id] = source.source_ref
        return source.interaction_id

    def current_ref(self, scope, ref):
        if scope != self.scope:
            return None
        source = self.get(ref)
        return None if source is None else source.source_ref

    def current_user_source(self, scope, interaction_id):
        ref = self._bindings.get(interaction_id)
        if scope != self.scope or ref is None:
            return None
        source = self.get(ref)
        if source is None or source.interaction_id != interaction_id:
            return None
        if HistoricalSourceCurator().classify(source) != SourceDisposition.COMPILE:
            return None
        return source.source_ref
