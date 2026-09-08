"""Shadow affect learning tests (C1.5 behavior closure: affect_summary)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from mind_runtime.shadow.affect import (
    affect_summary,
    classify_affect,
    init_affect_store,
    learn_corpus,
)


def _seed_dimensions(db: Path, dimension: str, count: int, start_id: int) -> None:
    with sqlite3.connect(str(db)) as con:
        for offset in range(count):
            con.execute(
                "INSERT INTO shadow_affect "
                "(content_id, ts, session_hash, channel, sender, dimension, confidence) "
                "VALUES (?,?,?,?,?,?,?)",
                (
                    start_id + offset,
                    "2026-08-27T10:00:00+00:00",
                    "s",
                    "telegram",
                    "user",
                    dimension,
                    0.9,
                ),
            )


def test_classify_lexicon_triggers_map_to_dimensions() -> None:
    assert classify_affect("今天好开心") == ("joy", 0.95)
    assert classify_affect("没什么特别的日常") == ("neutral", 0.6)


def test_learn_corpus_is_idempotent(tmp_path: Path) -> None:
    from mind_runtime.shadow.redaction import init_store

    shadow_db = tmp_path / "shadow.db"
    init_store(shadow_db)
    with sqlite3.connect(str(shadow_db)) as con:
        con.execute(
            "INSERT INTO shadow_events "
            "(content_id, ts, user_hash, session_hash, channel, sender, "
            "trigger, source_domain, redacted_text) VALUES (?,?,?,?,?,?,?,?,?)",
            (
                1,
                "2026-08-27T10:00:00+00:00",
                "u",
                "s",
                "telegram",
                "user",
                "message",
                "kayla_persona",
                "今天好开心",
            ),
        )
    affect_db = tmp_path / "affect.db"
    first = learn_corpus(str(shadow_db), str(affect_db))
    assert (first["fetched"], first["classified"], first["total"]) == (1, 1, 1)
    second = learn_corpus(str(shadow_db), str(affect_db))
    # content_id UNIQUE + INSERT OR IGNORE: the repeat adds nothing new
    assert second["total"] == first["total"]
    assert affect_summary(str(affect_db)) == [("joy", 1)]


def test_affect_summary_empty_store_is_empty_list(tmp_path: Path) -> None:
    db = tmp_path / "affect.db"
    init_affect_store(db)
    assert affect_summary(db) == []


def test_affect_summary_counts_grouped_descending(tmp_path: Path) -> None:
    db = tmp_path / "affect.db"
    init_affect_store(db)
    _seed_dimensions(db, "sad", 1, start_id=100)
    _seed_dimensions(db, "joy", 3, start_id=200)
    assert affect_summary(db) == [("joy", 3), ("sad", 1)]


def test_affect_summary_single_row_boundary(tmp_path: Path) -> None:
    db = tmp_path / "affect.db"
    init_affect_store(db)
    _seed_dimensions(db, "fatigue", 1, start_id=300)
    assert affect_summary(db) == [("fatigue", 1)]
