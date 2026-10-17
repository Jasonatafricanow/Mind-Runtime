"""Restart-safe exactly-once request journal for AML Add."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from mind_runtime.competition.aml.contracts import AmlAddRequest


class AmlRequestConflict(ValueError):
    """One request_id was replayed with different immutable content."""


def request_fingerprint(request: AmlAddRequest) -> str:
    payload = {
        "user_id": request.user_id,
        "session_id": request.session_id,
        "messages": [
            {
                "role": item.role,
                "content": item.content,
                "timestamp": item.timestamp,
            }
            for item in request.messages
        ],
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


class AmlRequestJournal:
    """Durable processing state; safe to reopen after process failure."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.path), timeout=30.0)
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS aml_add_requests (
                request_id TEXT PRIMARY KEY,
                fingerprint TEXT NOT NULL,
                received_at TEXT NOT NULL,
                stage TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS aml_request_artifacts (
                request_id TEXT NOT NULL,
                name TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                PRIMARY KEY (request_id, name),
                FOREIGN KEY (request_id)
                    REFERENCES aml_add_requests(request_id)
                    ON DELETE CASCADE
            );
            """
        )
        self._conn.commit()

    def reserve(
        self,
        request: AmlAddRequest,
        *,
        now: datetime | None = None,
    ) -> tuple[datetime, str]:
        fingerprint = request_fingerprint(request)
        row = self._conn.execute(
            """
            SELECT fingerprint, received_at, stage
            FROM aml_add_requests
            WHERE request_id=?
            """,
            (request.request_id,),
        ).fetchone()
        if row is not None:
            if str(row[0]) != fingerprint:
                raise AmlRequestConflict(
                    "request_id replayed with different content"
                )
            return datetime.fromisoformat(str(row[1])), str(row[2])
        received_at = now or datetime.now(UTC)
        if received_at.tzinfo != UTC:
            raise ValueError("journal time must be aware UTC")
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO aml_add_requests(
                    request_id, fingerprint, received_at, stage
                ) VALUES (?, ?, ?, 'reserved')
                """,
                (
                    request.request_id,
                    fingerprint,
                    received_at.isoformat(),
                ),
            )
        return received_at, "reserved"

    def stage(self, request_id: str, stage: str) -> None:
        if not isinstance(stage, str) or not stage.strip():
            raise ValueError("stage must be nonempty")
        with self._conn:
            changed = self._conn.execute(
                """
                UPDATE aml_add_requests
                SET stage=?
                WHERE request_id=?
                """,
                (stage, request_id),
            )
        if changed.rowcount != 1:
            raise KeyError(request_id)

    def save_artifact(
        self,
        request_id: str,
        name: str,
        payload: object,
    ) -> None:
        if not isinstance(name, str) or not name.strip():
            raise ValueError("artifact name must be nonempty")
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO aml_request_artifacts(
                    request_id, name, payload_json
                ) VALUES (?, ?, ?)
                ON CONFLICT(request_id, name) DO NOTHING
                """,
                (request_id, name, encoded),
            )

    def load_artifact(
        self,
        request_id: str,
        name: str,
    ) -> object | None:
        row = self._conn.execute(
            """
            SELECT payload_json
            FROM aml_request_artifacts
            WHERE request_id=? AND name=?
            """,
            (request_id, name),
        ).fetchone()
        return None if row is None else json.loads(str(row[0]))

    def close(self) -> None:
        self._conn.close()
