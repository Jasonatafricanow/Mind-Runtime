"""Read Hermes native rows without creating a transcript mirror."""

import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from mr_mem import SourceRef
from mr_mem_aml.source_store import RawMessage


class HermesNativeSource:
    def __init__(self, path, *, scope, user_id, namespace):
        self.path, self.scope = Path(path).resolve(), scope
        self.user_id, self.namespace = str(user_id), namespace
        self.identity = json.dumps([str(self.path), scope.user_id, self.user_id, namespace])
        self.db = sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True)

    def close(self):
        self.db.close()

    def sessions(self):
        return tuple(row[0] for row in self.db.execute(
            "SELECT id FROM sessions WHERE user_id=? ORDER BY id", (self.user_id,)))

    def _rows(self, session_id, record_id=None):
        # Read ownership and rows from the same statement/snapshot. An empty foreign
        # session is an error as well; it must not be interpreted as a deletion.
        rows = self.db.execute(
            "SELECT s.user_id,m.id,m.session_id,m.role,m.content,m.timestamp,m.tool_calls "
            "FROM sessions s LEFT JOIN messages m ON m.session_id=s.id "
            "AND (m.active=1 OR m.compacted=1) AND (? IS NULL OR m.id=?) "
            "WHERE s.id=? ORDER BY m.id", (record_id, record_id, session_id)).fetchall()
        if any(str(row[0]) != self.user_id for row in rows):
            raise ValueError("native session belongs to another owner")
        return tuple(self._message(row[1:]) for row in rows if row[1] is not None)

    def _message(self, row):
        record, session, role, content, stamp, tools = row
        if not isinstance(content, str) or not isinstance(role, str):
            raise ValueError("native text/role unavailable")
        at = datetime.fromtimestamp(stamp, UTC)
        fingerprint = hashlib.sha256(json.dumps(
            [role, content, stamp, tools], ensure_ascii=False).encode()).hexdigest()
        ref = SourceRef(self.namespace, session, str(record), at, fingerprint=fingerprint)
        return RawMessage(str(record), self.scope.user_id, session, "", int(record),
                          role, content, at, fingerprint, native_ref=ref)

    def snapshot(self, session_id):
        return self._rows(session_id)

    def read(self, scope, ref):
        if scope != self.scope or ref.source_namespace != self.namespace:
            return None
        rows = self._rows(ref.session_id, ref.record_id)
        return rows[0] if rows else None
