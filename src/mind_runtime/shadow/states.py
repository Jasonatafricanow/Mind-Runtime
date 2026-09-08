"""State extractor v1: pulls event/situational states from shadow corpus.

Mirrors the statebar design (observations -> states with validity windows)
for the activity/situational layer that lexicon emotion classification
cannot express: "哄嘻嘻睡觉", "去洗澡", "加班", "睡不着" ...

Writes shadow_states:
    content_id | ts | session_hash | category | key | value | valid_until

Rule-based for now; a model extractor (gemini via statebar) can supersede it.
"""

from __future__ import annotations

import re as _re
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

# (category, key, regex, value, valid_minutes)
# NOTE: extraction receives both corpus modes: private mode stores person
# names plaintext (keep_names=True), export mode stores <person:N> codes —
# regexes must tolerate both forms (ADR-0011).
_RULES: tuple[tuple[str, str, str, str, int], ...] = (
    (
        "activity",
        "child_sleep",
        r"哄(?:<person:\d+>|嘻嘻|她).{0,6}睡",
        "putting_child_to_sleep",
        90,
    ),
    ("presence", "shower", r"洗澡|洗个澡|冲个澡", "showering", 45),
    ("activity", "eating", r"吃饭|吃外卖|烤串|夜宵|早餐|午餐|晚餐", "eating", 60),
    ("activity", "out", r"出门|外出|出去一下|走了|去上班", "out", 120),
    ("activity", "working", r"加班|上班|开会|写代码|开发|在处理|干活", "working", 240),
    ("body", "unwell", r"生病|发烧|胃疼|头疼|不舒服|难受|感冒", "unwell", 300),
    ("sleep", "deprived", r"熬夜|睡不着|失眠|只睡|睡了[34]小时", "sleep_deprived", 300),
    ("activity", "code_review", r"验收|审查|控制台|codex", "reviewing_console", 180),
    ("activity", "python_ops", r"部署|git|推送|提交|跑测试|pytest", "doing_ops", 180),
    ("presence", "phone", r"手机|充电", "on_phone", 60),
)


def _rule_hits(text: str) -> list[tuple[str, str, str, int]]:
    out: list[tuple[str, str, str, int]] = []
    for category, key, pattern, value, minutes in _RULES:
        if _re.search(pattern, text):
            out.append((category, key, value, minutes))
    return out


def _restore_names(text: str, known_names: tuple[str, ...]) -> str:
    """Restore <person:N> placeholders back to names (in-memory only).

    Lets state rules match on redacted text without weakening the on-disk
    privacy posture: the restored text is used for matching only and never
    persisted.
    """
    for idx, name in enumerate(known_names, start=1):
        text = text.replace(f"<person:{idx}>", name)
    return text


_STATES_SCHEMA = """
CREATE TABLE IF NOT EXISTS shadow_states (
    state_id INTEGER PRIMARY KEY AUTOINCREMENT,
    content_id INTEGER UNIQUE,
    ts TEXT NOT NULL,
    session_hash TEXT NOT NULL,
    category TEXT NOT NULL,
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    valid_until TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_shadow_states_ts ON shadow_states(ts);
"""


def init_states_store(db_path: str | Path) -> None:
    with sqlite3.connect(str(db_path)) as con:
        con.executescript(_STATES_SCHEMA)


def extract_states(
    shadow_db: str | Path,
    states_db: str | Path,
    *,
    since_ts: float = 0.0,
    known_names: tuple[str, ...] = (),
) -> dict[str, int]:
    """Scan eligible user events and write detected states (idempotent).

    known_names: used to restore <person:N> placeholders in-memory before
    rule matching; the restored text is never persisted.
    """
    init_states_store(states_db)
    src = sqlite3.connect(str(shadow_db))
    src.row_factory = sqlite3.Row
    rows = src.execute(
        "SELECT content_id, ts, session_hash, sender, redacted_text "
        "FROM shadow_events WHERE sender='user' ORDER BY ts"
    ).fetchall()
    src.close()

    stats = {"scanned": len(rows), "states": 0}
    now = datetime.now(UTC)
    batch: list[tuple[int, str, str, str, str, str, str]] = []
    for r in rows:
        text = r["redacted_text"] or ""
        if known_names:
            text = _restore_names(text, known_names)
        hits = _rule_hits(text)
        if not hits:
            continue
        # one row per rule hit set: keep the first (highest-priority) rule
        category, key, value, minutes = hits[0]
        valid_until = (now + timedelta(minutes=minutes)).isoformat(timespec="seconds")
        batch.append(
            (
                r["content_id"],
                r["ts"],
                r["session_hash"],
                category,
                key,
                value,
                valid_until,
            )
        )
    stats["states"] = len(batch)

    con = sqlite3.connect(str(states_db))
    try:
        con.executemany(
            "INSERT OR IGNORE INTO shadow_states "
            "(content_id, ts, session_hash, category, key, value, valid_until) "
            "VALUES (?,?,?,?,?,?,?)",
            batch,
        )
        con.commit()
    finally:
        con.close()
    return stats


def active_states(
    states_db: str | Path, now: datetime | None = None
) -> list[tuple[str, str, str, str]]:
    """Return currently-valid states: (category, key, value, valid_until)."""
    now = now or datetime.now(UTC)
    con = sqlite3.connect(str(states_db))
    try:
        rows = con.execute(
            "SELECT category, key, value, valid_until FROM shadow_states "
            "WHERE valid_until > ? ORDER BY ts DESC LIMIT 30",
            (now.isoformat(timespec="seconds"),),
        ).fetchall()
        return [(r[0], r[1], r[2], r[3]) for r in rows]
    finally:
        con.close()
