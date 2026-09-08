"""Backfill / incremental sync: Hermes state.db -> shadow store.

Usage:
    python -m mind_runtime.shadow.backfill --dry-run          # classify+redact preview only
    python -m mind_runtime.shadow.backfill                    # real write (gate must be ON)
    python -m mind_runtime.shadow.backfill --cursor 1787750000
"""

from __future__ import annotations

import argparse
from pathlib import Path

from mind_runtime.shadow.classifier import classify
from mind_runtime.shadow.redaction import (
    count_records,
    has_sensitive_leak,
    init_store,
    redact_text,
)
from mind_runtime.shadow.runner import gate_enabled, shadow_db_path
from mind_runtime.shadow.sources.hermes import HermesMessageSource

DEFAULT_STATE_DB = str(Path.home() / ".hermes" / "profiles" / "xiyue" / "state.db")
# Names we always code out of shadow-learned content.
KNOWN_NAMES = (
    "嘉森",
    "嘻嘻",
    "溪月",
    "老婆",
    "心潮",
    "梨园",
    "金屋",
)


def run_backfill(
    state_db: str,
    *,
    dry_run: bool,
    cursor: float,
    limit: int,
    known_names: tuple[str, ...],
    keep_names: bool = True,
    cursor_id: int = 0,
) -> dict[str, int | float]:
    """Backfill ONE page of events into the shadow store.

    keep_names=True (default): person names stay plaintext — the learned
    corpus is PRIVATE (never published), and name-keeping preserves rule
    matching (ADR-0011). Only credential-class plaintext
    (phone/email/id/bank/pin) is redacted, fail-closed. keep_names=False is
    the export/publication mode.

    Page contract (C0.5 cursor fix): processes at most `limit` raw rows past
    the (cursor, cursor_id) position and reports the exact position reached
    as stats["end_ts"]/stats["end_id"]. Callers persist THAT position — never
    a global newest timestamp — so messages beyond one page are picked up by
    later runs instead of being skipped forever.
    """
    src = HermesMessageSource(state_db)
    try:
        page = src.fetch_page(after_ts=cursor, after_id=cursor_id, limit=limit)
    finally:
        src.close()
    events = page.events

    stats: dict[str, int | float] = {
        "fetched": len(events),
        "eligible": 0,
        "ineligible": 0,
        "leak_rejected": 0,
        "recorded": 0,
        "end_ts": page.end_ts,
        "end_id": page.end_id,
    }
    if dry_run:
        for ev in events:
            if classify(ev.meta):
                stats["eligible"] += 1
            else:
                stats["ineligible"] += 1
        return stats

    from datetime import UTC, datetime

    from mind_runtime.shadow.redaction import (
        hash_id,
    )

    db = shadow_db_path()
    init_store(db)
    rows: list[tuple[int, str, str, str, str, str, str, str, str, str]] = []
    name_codes = known_names if not keep_names else ()
    for ev in events:
        if not classify(ev.meta):
            stats["ineligible"] += 1
            continue
        stats["eligible"] += 1
        redacted = redact_text(ev.text, name_codes)
        if has_sensitive_leak(redacted):
            stats["leak_rejected"] += 1
            continue
        # ADR-0012: persist the ORIGINAL message time separately from the
        # ingestion-persistence ts so downstream replay never fakes recency.
        occurred_iso = datetime.fromtimestamp(ev.ts, tz=UTC).isoformat(timespec="seconds")
        rows.append(
            (
                ev.content_id,
                datetime.now(UTC).isoformat(timespec="seconds"),
                hash_id(ev.meta.session),
                hash_id(ev.meta.session),
                ev.meta.channel,
                ev.meta.sender,
                ev.meta.trigger,
                ev.meta.source_domain,
                redacted,
                occurred_iso,
            )
        )
    # Batch insert (single transaction, much faster than per-row commits).
    # INSERT OR IGNORE: content_id UNIQUE makes re-runs idempotent.
    import sqlite3

    con = sqlite3.connect(str(db))
    try:
        con.executemany(
            "INSERT OR IGNORE INTO shadow_events "
            "(content_id, ts, user_hash, session_hash, channel, sender, "
            "trigger, source_domain, redacted_text, event_ts) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            rows,
        )
        con.commit()
    finally:
        con.close()
    stats["recorded"] += len(rows)
    stats["shadow_db_total"] = count_records(db)
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description="D11L shadow backfill")
    parser.add_argument("--state-db", default=DEFAULT_STATE_DB)
    parser.add_argument("--dry-run", action="store_true", help="classify only, no store")
    parser.add_argument("--cursor", type=float, default=0.0)
    parser.add_argument("--limit", type=int, default=5000)
    args = parser.parse_args()

    stats = run_backfill(
        args.state_db,
        dry_run=args.dry_run,
        cursor=args.cursor,
        limit=args.limit,
        known_names=KNOWN_NAMES,
    )
    print(f"backfill: gate={gate_enabled()} dry={args.dry_run} stats={stats}")
    if not args.dry_run and gate_enabled():
        print(f"shadow db => {shadow_db_path()}")


if __name__ == "__main__":
    main()
