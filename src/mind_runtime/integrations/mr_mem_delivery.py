"""Incremental native-host delivery to the current core; metadata-only retry journal.

The caller supplies an explicit native message-ID cutoff. No old history is
compiled implicitly. Edits/deletions fail closed: the core API is append-only.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

from mind_runtime.integrations.mr_mem_core import MrMemClient


class NativeSourceChanged(RuntimeError):
    """An enrolled source changed; append-only core history requires reconciliation."""


class NativeMemoryDelivery:
    def __init__(self, native_db: Path, journal: Path, client: MrMemClient, *,
                 native_user: str, runtime_id: str, baseline: int) -> None:
        if type(baseline) is not int or baseline < 0:
            raise ValueError("native baseline must be an explicit nonnegative message ID")
        if not native_db.is_absolute() or not journal.is_absolute():
            raise ValueError("native database and journal paths must be absolute")
        if not native_user or not runtime_id:
            raise ValueError("native owner and runtime identity required")
        self.native_db, self.client = native_db.resolve(), client
        if journal.resolve() == self.native_db:
            raise ValueError("native journal must be separate from host history")
        identity = [str(self.native_db), native_user, runtime_id, client.user_id,
                    client.base_url.rstrip("/"), baseline]
        self.identity = json.dumps(identity)
        self.namespace = hashlib.sha256(self.identity.encode()).hexdigest()
        self.native_user, self.baseline = native_user, baseline
        journal.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(journal)
        self.db.executescript(
            "CREATE TABLE IF NOT EXISTS binding(identity TEXT PRIMARY KEY);"
            "CREATE TABLE IF NOT EXISTS enrolled(session TEXT PRIMARY KEY);"
            "CREATE TABLE IF NOT EXISTS batches("
            "request_id TEXT PRIMARY KEY,session TEXT,refs TEXT,status TEXT);"
        )
        bound = self.db.execute("SELECT identity FROM binding").fetchall()
        if bound and bound != [(self.identity,)]:
            self.db.close()
            raise ValueError("native memory journal binding changed")
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO binding VALUES (?)", (self.identity,))

    def close(self) -> None:
        self.db.close()

    def _snapshot(self, session: str) -> dict[int, dict[str, Any]]:
        with sqlite3.connect(self.native_db.as_uri() + "?mode=ro", uri=True) as db:
            rows = db.execute(
                "SELECT s.user_id,m.id,m.role,m.content,m.timestamp,m.tool_calls "
                "FROM sessions s LEFT JOIN messages m ON m.session_id=s.id "
                "AND (m.active=1 OR m.compacted=1) WHERE s.id=? ORDER BY m.id", (session,),
            ).fetchall()
        if not rows:
            raise NativeSourceChanged("enrolled native session is missing")
        if any(str(r[0]) != self.native_user for r in rows):
            raise ValueError("native session belongs to another owner")
        result = {}
        for _, mid, role, content, stamp, tools in rows:
            if mid is None:
                continue
            if (type(mid) is not int or not isinstance(content, str)
                    or not isinstance(role, str) or type(stamp) not in (int, float)):
                raise ValueError("native message needs a stable ID, text and source timestamp")
            message = {"role": role, "content": content, "timestamp": stamp * 1000}
            fingerprint = hashlib.sha256(json.dumps(
                [message, tools], ensure_ascii=False, allow_nan=False,
            ).encode()).hexdigest()
            result[mid] = {"message": message, "fingerprint": fingerprint}
        return result

    def synchronize(self, session: str, *, after_commit: bool = False) -> dict[str, Any]:
        # Check current session ownership before enrollment, including empty sessions.
        snapshots = {session: self._snapshot(session)}
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO enrolled VALUES (?)", (session,))
        for (sid,) in self.db.execute("SELECT session FROM enrolled"):
            if sid not in snapshots:
                snapshots[sid] = self._snapshot(sid)
        covered: set[tuple[str, int]] = set()
        batches = list(self.db.execute("SELECT request_id,session,refs,status FROM batches"))
        for _, sid, encoded, _ in batches:
            for mid, fingerprint in json.loads(encoded):
                current = snapshots[sid].get(mid)
                if current is None or current["fingerprint"] != fingerprint:
                    raise NativeSourceChanged(
                        "enrolled native source changed; core reconciliation required",
                    )
                covered.add((sid, mid))
        if not after_commit:
            return {"status": "validated", "enrolled_sessions": len(snapshots)}
        # Freeze source identities BEFORE HTTP. A lost receipt retries exactly this batch.
        for sid, rows in snapshots.items():
            refs = [[mid, value["fingerprint"]] for mid, value in rows.items()
                    if mid > self.baseline and (sid, mid) not in covered]
            if not refs:
                continue
            encoded = json.dumps(refs)
            rid = "mr-native-" + hashlib.sha256(
                (self.identity + sid + encoded).encode(),
            ).hexdigest()
            with self.db:
                self.db.execute("INSERT INTO batches VALUES (?,?,?,?)",
                                (rid, sid, encoded, "pending"))
        sent = 0
        for rid, sid, encoded in self.db.execute(
            "SELECT request_id,session,refs FROM batches WHERE status='pending' ORDER BY rowid",
        ).fetchall():
            self.client.add(request_id=rid, session_id=self.namespace + ":" + sid,
                            messages=[snapshots[sid][mid]["message"]
                                      for mid, _ in json.loads(encoded)])
            with self.db:
                self.db.execute("UPDATE batches SET status='accepted' WHERE request_id=?", (rid,))
            sent += 1
        return {"status": "accepted", "sent_batches": sent,
                "note": "Add acceptance is separate from semantic compilation completion"}
