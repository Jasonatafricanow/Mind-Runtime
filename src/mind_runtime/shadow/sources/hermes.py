"""Hermes message-store source adapter (D11L shadow pipeline input).

Reads incremental private-chat messages from the Hermes profile state.db
(sessions + messages tables) and maps them to shadow EventMeta + text.

Exclusions applied here (belt-and-braces on top of the classifier):
  * sessions whose source is cron/webhook/subagent (not real private chat)
  * tool/session_meta roles (not dialogue)
  * messages without text content

The adapter is READ-ONLY on state.db; all writes go to the shadow store
after classifier + redaction.

Paging is position-based: a page reports the exact (timestamp, id) raw-store
position it consumed, including rows dropped by the dialogue filters, so a
caller can resume exactly there instead of jumping to the global newest ts
(which would permanently skip messages beyond the page limit).
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from mind_runtime.shadow.classifier import EventMeta

# Mapping Heres-style role -> shadow sender (E1: user | agent)
_ROLE_TO_SENDER = {
    "user": "user",
    "assistant": "agent",
    "human": "user",
    "agent": "agent",
}


@dataclass(frozen=True)
class HermesEvent:
    meta: EventMeta
    text: str
    ts: float
    content_id: int


@dataclass(frozen=True)
class HermesPage:
    """One fetch window plus the raw-store position it consumed.

    end_ts/end_id are the (timestamp, id) of the LAST RAW ROW examined —
    whether or not that row produced an event — so resuming from them can
    neither lose nor repeat messages across runs.
    """

    events: list[HermesEvent] = field(default_factory=list)
    end_ts: float = 0.0
    end_id: int = 0


class HermesMessageSource:
    def __init__(self, db_path: str | Path) -> None:
        self._db = str(db_path)
        self._con = sqlite3.connect(f"file:{self._db}?mode=ro", uri=True)
        self._con.row_factory = sqlite3.Row

    def close(self) -> None:
        self._con.close()

    def fetch_page(self, after_ts: float = 0.0, after_id: int = 0, limit: int = 2000) -> HermesPage:
        """Fetch dialogue messages after the (ts, id) position, oldest first.

        The composite position keeps pages correct even when several messages
        share a timestamp: the id tiebreak orders them, and resuming at
        (ts=T, id=N) still delivers remaining T-timestamped rows with id > N.
        """
        rows = self._con.execute(
            """
            SELECT m.id, m.timestamp, m.role, m.content, s.source, s.session_key
            FROM messages m
            JOIN sessions s ON m.session_id = s.id
            WHERE (m.timestamp > ? OR (m.timestamp = ? AND m.id > ?))
              AND m.role IN ('user', 'assistant', 'human', 'agent')
              AND s.source NOT IN ('cron', 'webhook', 'subagent', 'cli')
              AND m.content IS NOT NULL
            ORDER BY m.timestamp ASC, m.id ASC
            LIMIT ?
            """,
            (after_ts, after_ts, after_id, limit),
        ).fetchall()
        out: list[HermesEvent] = []
        end_ts, end_id = after_ts, after_id
        for r in rows:
            # Position advances for every raw row examined, including rows
            # dropped by the dialogue filters: the page consumed them either way.
            end_ts = float(r["timestamp"])
            end_id = int(r["id"])
            sender = _ROLE_TO_SENDER.get(r["role"] or "")
            text = (r["content"] or "").strip()
            if sender is None or not text:
                continue
            source = r["source"] or "unknown"
            meta = EventMeta(
                channel=str(source),
                sender=sender,
                session=str(r["session_key"] or r["id"]),
                trigger="message",
                source_domain="kayla_persona",
            )
            out.append(HermesEvent(meta=meta, text=text, ts=end_ts, content_id=end_id))
        return HermesPage(events=out, end_ts=end_ts, end_id=end_id)
