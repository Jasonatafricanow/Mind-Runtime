"""Incremental shadow sync: keeps cursor state so new Hermes messages flow
into the shadow store + affect trajectory continuously.

Cursor persisted in <shadow_db>.sync_state as (key='last_ts', key='last_id'):
the RAW-STORE POSITION of the last message examined — never the global newest
timestamp, which would permanently skip messages beyond one page limit
(C0 recon finding, fixed under C0.5).

Usage:
    python -m mind_runtime.shadow.sync [--dry-run] [--limit N]
"""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

from mind_runtime.shadow.affect import learn_corpus
from mind_runtime.shadow.backfill import run_backfill
from mind_runtime.shadow.runner import shadow_db_path

AFFECT_DB = str(Path.home() / ".hermes" / "profiles" / "xiyue" / "shadow_affect.db")


def _read_cursor(db: str) -> tuple[float, int]:
    con = sqlite3.connect(db)
    try:
        rows = con.execute(
            "SELECT key, value FROM sync_state WHERE key IN ('last_ts', 'last_id')"
        ).fetchall()
    finally:
        con.close()
    values = {key: value for key, value in rows}
    ts = float(values.get("last_ts", 0.0))
    content_pos = int(float(values.get("last_id", 0)))
    return ts, content_pos


def _write_cursor(db: str, ts: float, content_pos: int) -> None:
    con = sqlite3.connect(db)
    try:
        con.executemany(
            "INSERT INTO sync_state (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (("last_ts", str(ts)), ("last_id", str(content_pos))),
        )
        con.commit()
    finally:
        con.close()


def ensure_sync_table(db: str) -> None:
    con = sqlite3.connect(db)
    try:
        con.execute("CREATE TABLE IF NOT EXISTS sync_state (key TEXT PRIMARY KEY, value TEXT)")
        con.commit()
    finally:
        con.close()


def sync(
    state_db: str,
    *,
    dry_run: bool,
    limit: int,
    known_names: tuple[str, ...],
    keep_names: bool = True,
) -> dict[str, object]:
    db = str(shadow_db_path())
    ensure_sync_table(db)
    cursor, cursor_id = _read_cursor(db)
    stats = run_backfill(
        state_db,
        dry_run=dry_run,
        cursor=cursor,
        cursor_id=cursor_id,
        limit=limit,
        known_names=known_names,
        keep_names=keep_names,
    )
    if not dry_run:
        # Advance only to the raw position actually consumed by this run's
        # page; jumping to the global newest timestamp here is exactly the
        # truncation bug that used to drop messages beyond the limit.
        end_ts = float(stats["end_ts"])
        end_id = int(stats["end_id"])
        if end_ts > cursor or (end_ts == cursor and end_id > cursor_id):
            _write_cursor(db, end_ts, end_id)
        # learn new affects (idempotent; content_id UNIQUE)
        learn_corpus(db, AFFECT_DB)
    result: dict[str, object] = {}
    result.update(stats)
    result["cursor_from"] = cursor
    result["cursor_to"] = stats["end_ts"]
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="D11L incremental shadow sync")
    parser.add_argument(
        "--state-db", default=str(Path.home() / ".hermes" / "profiles" / "xiyue" / "state.db")
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=2000)
    args = parser.parse_args()

    from mind_runtime.shadow.backfill import KNOWN_NAMES

    stats = sync(
        args.state_db,
        dry_run=args.dry_run,
        limit=args.limit,
        known_names=KNOWN_NAMES,
    )
    print(f"sync: {stats}")


if __name__ == "__main__":
    main()
