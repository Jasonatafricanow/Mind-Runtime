"""Shadow affect learning v1 (D11L shadow learning — lexicon-based).

Produces an affect trajectory from the redacted shadow corpus with a
deterministic Chinese emotion lexicon. This is the minimal meaningful
"learning" for now: each interaction gets an emotion dimension label +
confidence, stored in the shadow_affect table, so we can answer
"what was the emotional trajectory" questions offline.

A full EmotionalTransitionPort implementation (AssessmentTrace lineage,
SemanticRouter, model-based candidates) is the next step; the lexicon
classifier is the deterministic core it will build on.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

# Chinese emotion lexicon: triggers -> (dimension, weight)
_LEXICON: tuple[tuple[str, str, float], ...] = (
    # joy / positive
    ("开心", "joy", 1.0),
    ("高兴", "joy", 1.0),
    ("哈哈", "joy", 0.9),
    ("太好了", "joy", 1.0),
    ("漂亮", "joy", 0.8),
    ("牛", "joy", 0.7),
    ("舒服", "joy", 0.8),
    ("爽", "joy", 0.9),
    ("幸福", "joy", 1.0),
    ("可爱", "joy", 0.7),
    ("开心死了", "joy", 1.0),
    ("棒", "joy", 0.8),
    ("爽歪歪", "joy", 0.9),
    ("真不错", "joy", 0.8),
    ("成功", "joy", 0.7),
    ("嘻嘻", "joy", 0.9),
    ("哈哈", "joy", 0.8),
    ("好耶", "joy", 0.9),
    # anxiety / worry
    ("焦虑", "anxiety", 1.0),
    ("担心", "anxiety", 0.9),
    ("怕", "anxiety", 0.8),
    ("慌", "anxiety", 0.9),
    ("紧张", "anxiety", 0.8),
    ("不安", "anxiety", 0.9),
    ("焦虑了", "anxiety", 1.0),
    ("怎么办", "anxiety", 0.8),
    ("悬", "anxiety", 0.7),
    ("完蛋", "anxiety", 0.9),
    ("糟糕", "anxiety", 0.7),
    ("麻烦", "anxiety", 0.7),
    ("睡不着", "anxiety", 0.6),
    ("糟了", "anxiety", 0.8),
    ("头疼", "anxiety", 0.6),
    ("烦", "anxiety", 0.7),
    ("烦死了", "anxiety", 0.9),
    ("烦躁", "anxiety", 0.9),
    # anger
    ("气死", "anger", 1.0),
    ("生气", "anger", 1.0),
    ("气死了", "anger", 1.0),
    ("他妈的", "anger", 0.9),
    ("服了", "anger", 0.8),
    ("恶心", "anger", 0.8),
    ("可恶", "anger", 0.9),
    ("气人", "anger", 0.9),
    ("尼玛", "anger", 0.7),
    ("怒", "anger", 0.9),
    ("草", "anger", 0.6),
    ("md", "anger", 0.8),
    ("卧槽", "anger", 0.7),
    ("气", "anger", 0.6),
    ("受够了", "anger", 0.9),
    # sad / low
    ("难过", "sad", 1.0),
    ("伤心", "sad", 1.0),
    ("哭", "sad", 0.9),
    ("失落", "sad", 0.9),
    ("低落", "sad", 1.0),
    ("沮丧", "sad", 1.0),
    ("委屈", "sad", 0.9),
    ("心酸", "sad", 0.9),
    ("玉玉", "sad", 1.0),
    ("emo", "sad", 0.9),
    ("难受", "sad", 0.9),
    ("遗憾", "sad", 0.8),
    ("悲", "sad", 0.9),
    ("哭了", "sad", 0.9),
    # fatigue / overwhelmed
    ("累", "fatigue", 0.9),
    ("疲惫", "fatigue", 1.0),
    ("困", "fatigue", 0.8),
    ("好累", "fatigue", 1.0),
    ("没力气", "fatigue", 0.9),
    ("熬夜", "fatigue", 0.7),
    ("辛苦", "fatigue", 0.8),
    ("撑不住", "fatigue", 0.9),
    ("崩溃", "fatigue", 0.6),
    ("乏", "fatigue", 0.8),
    ("顶不住", "fatigue", 0.9),
    ("要死", "fatigue", 0.7),
)

NEUTRAL = "neutral"
DIMENSIONS = frozenset({"joy", "anxiety", "anger", "sad", "fatigue", NEUTRAL})

_AFFECT_SCHEMA = """
CREATE TABLE IF NOT EXISTS shadow_affect (
    affect_id INTEGER PRIMARY KEY AUTOINCREMENT,
    content_id INTEGER UNIQUE,
    ts TEXT NOT NULL,
    session_hash TEXT NOT NULL,
    channel TEXT NOT NULL,
    sender TEXT NOT NULL,
    dimension TEXT NOT NULL,
    confidence REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_shadow_affect_ts ON shadow_affect(ts);
"""


def classify_affect(text: str) -> tuple[str, float]:
    """Return (dimension, confidence); neutral for no trigger."""
    scores: dict[str, float] = {}
    for trigger, dim, weight in _LEXICON:
        if trigger in text:
            scores[dim] = max(scores.get(dim, 0.0), weight)
    if not scores:
        return NEUTRAL, 0.6
    best_dim = max(scores, key=lambda d: scores[d])
    return best_dim, min(0.95, scores[best_dim])


def init_affect_store(db_path: str | Path) -> None:
    with sqlite3.connect(str(db_path)) as con:
        con.executescript(_AFFECT_SCHEMA)


def learn_corpus(shadow_db: str | Path, affect_db: str | Path) -> dict[str, int]:
    """Classify every shadow record into the affect trajectory table.

    Idempotent: content_id UNIQUE + INSERT OR IGNORE.
    """
    init_affect_store(affect_db)
    stats = {"fetched": 0, "classified": 0, "skipped": 0, "total": 0}
    src_con = sqlite3.connect(str(shadow_db))
    src_con.row_factory = sqlite3.Row
    rows = src_con.execute(
        "SELECT content_id, ts, session_hash, channel, sender, redacted_text "
        "FROM shadow_events ORDER BY ts"
    ).fetchall()
    src_con.close()

    stats["fetched"] = len(rows)
    batch: list[tuple[int, str, str, str, str, str, float]] = []
    for r in rows:
        dimension, confidence = classify_affect(r["redacted_text"] or "")
        batch.append(
            (
                r["content_id"],
                r["ts"],
                r["session_hash"],
                r["channel"],
                r["sender"],
                dimension,
                confidence,
            )
        )
    stats["classified"] = len(batch)

    con = sqlite3.connect(str(affect_db))
    try:
        con.executemany(
            "INSERT OR IGNORE INTO shadow_affect "
            "(content_id, ts, session_hash, channel, sender, dimension, confidence) "
            "VALUES (?,?,?,?,?,?,?)",
            batch,
        )
        con.commit()
        stats["total"] = con.execute("SELECT COUNT(*) FROM shadow_affect").fetchone()[0]
    finally:
        con.close()
    return stats


def affect_summary(affect_db: str | Path) -> list[tuple[str, int]]:
    con = sqlite3.connect(str(affect_db))
    try:
        return con.execute(
            "SELECT dimension, COUNT(*) FROM shadow_affect "
            "GROUP BY dimension ORDER BY COUNT(*) DESC"
        ).fetchall()
    finally:
        con.close()
