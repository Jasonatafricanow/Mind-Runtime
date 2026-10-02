"""Read-only native record adapter; the host stamps platform identity when appending."""

import hashlib
import json
import sqlite3
from datetime import UTC, datetime

from mr_mem import SourceRef


class HermesDeltaSources:
    def __init__(
        self, path, *, scope, namespace, session_id, message_id, user_id, interaction_id, channel
    ):
        from mind_runtime.host.xiyue_adapter import _interaction_id

        if interaction_id != _interaction_id(channel, session_id, message_id):
            raise ValueError("source/interaction association does not match host message identity")
        if not all(
            isinstance(v, str) and v for v in (namespace, session_id, message_id, interaction_id)
        ):
            raise ValueError("exact host session/message/interaction identities required")
        self.scope, self.namespace = scope, namespace
        self.session_id, self.message_id, self.user_id = session_id, message_id, user_id
        self.interaction_id = interaction_id
        self._db = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
        self._db.execute("PRAGMA query_only=ON")

    def close(self):
        self._db.close()

    def _read(self, record_id=None):
        sql = (
            "SELECT m.id,m.session_id,m.role,m.content,m.timestamp,m.tool_calls "
            "FROM messages m JOIN sessions s ON s.id=m.session_id "
            "WHERE m.session_id=? AND m.platform_message_id=? "
            "AND m.role='user' AND (m.active=1 OR m.compacted=1)"
        )
        args = [self.session_id, self.message_id]
        if self.user_id is not None:
            sql += " AND s.user_id=?"
            args.append(self.user_id)
        if record_id is not None:
            sql += " AND m.id=?"
            args.append(record_id)
        rows = self._db.execute(sql, args).fetchall()
        if len(rows) != 1:
            return None
        mid, session, role, content, at, tools = rows[0]
        fingerprint = hashlib.sha256(
            json.dumps([role, content, at, tools], ensure_ascii=False).encode()
        ).hexdigest()
        return SourceRef(
            self.namespace,
            session,
            str(mid),
            datetime.fromtimestamp(at, UTC),
            fingerprint=fingerprint,
        )

    def current_ref(self, scope, ref):
        if (
            scope != self.scope
            or ref.source_namespace != self.namespace
            or ref.session_id != self.session_id
        ):
            return None
        return self._read(ref.record_id)

    def current_user_source(self, scope, interaction_id):
        if scope != self.scope or interaction_id != self.interaction_id:
            return None
        return self._read()
