"""Tests for shadow state extractor + person-name handling (ADR-0011).

Two corpus modes reach extraction:
  * private mode (keep_names=True default): person names stored plaintext;
  * export mode: person names stored as <person:N> codes.
State rules must match both forms; name restore is an in-memory aid and is
never persisted.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from mind_runtime.shadow.redaction import hash_id, init_store
from mind_runtime.shadow.states import (
    _restore_names,
    active_states,
    extract_states,
)


def _seed_one_event(
    db: Path, content_id: int, text: str, *, ts: str = "2026-08-26T12:00:00+00:00"
) -> None:
    init_store(db)
    with sqlite3.connect(str(db)) as con:
        con.execute(
            "INSERT INTO shadow_events "
            "(content_id, ts, user_hash, session_hash, channel, sender, "
            "trigger, source_domain, redacted_text) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (
                content_id,
                ts,
                hash_id("u"),
                hash_id("s"),
                "telegram",
                "user",
                "message",
                "kayla_persona",
                text,
            ),
        )


def test_restore_names_reverses_person_codes() -> None:
    restored = _restore_names("哄<person:2>睡觉", ("嘉森", "嘻嘻"))
    assert restored == "哄嘻嘻睡觉"


def test_extract_matches_plaintext_names(tmp_path: Path) -> None:
    """Private mode (keep_names=True): corpus stores plaintext person names."""
    shadow_db = tmp_path / "shadow.db"
    states_db = tmp_path / "states.db"
    _seed_one_event(shadow_db, 1, "我去哄嘻嘻睡觉了")
    stats = extract_states(shadow_db, states_db)
    assert stats["states"] == 1
    states = active_states(states_db)
    assert any(s[1] == "child_sleep" for s in states)


def test_extract_tolerates_person_codes_without_known_names(tmp_path: Path) -> None:
    """Export mode: <person:N> codes stay on disk; rules tolerate the token."""
    shadow_db = tmp_path / "shadow.db"
    states_db = tmp_path / "states.db"
    # seed export-mode text: <person:2> stands for 嘻嘻; no restore available
    _seed_one_event(shadow_db, 2, "我去哄<person:2>睡觉了")
    stats = extract_states(shadow_db, states_db)
    assert stats["states"] == 1
    states = active_states(states_db)
    assert any(s[1] == "child_sleep" for s in states)


def test_extract_matches_coded_corpus_with_known_names(tmp_path: Path) -> None:
    """known_names restores codes in-memory before matching; disk stays coded."""
    shadow_db = tmp_path / "shadow.db"
    states_db = tmp_path / "states.db"
    _seed_one_event(shadow_db, 3, "我去哄<person:2>睡觉了")
    stats = extract_states(shadow_db, states_db, known_names=("嘉森", "嘻嘻"))
    assert stats["states"] == 1
    states = active_states(states_db)
    assert any(s[1] == "child_sleep" for s in states)


def test_extract_skips_rows_without_rule_hits(tmp_path: Path) -> None:
    """C1.5 behavior: rows without rule hits are scanned but never stored."""
    shadow_db = tmp_path / "shadow.db"
    states_db = tmp_path / "states.db"
    _seed_one_event(shadow_db, 20, "今天天气不错心情平静")
    _seed_one_event(shadow_db, 21, "我去哄嘻嘻睡觉了")
    stats = extract_states(shadow_db, states_db)
    assert stats == {"scanned": 2, "states": 1}
    states = active_states(states_db)
    assert [s[1] for s in states] == ["child_sleep"]


def test_private_cognition_keeps_persons_distinguishable(tmp_path: Path) -> None:
    """C1/P1: real persons stay distinct through private cognition.

    Canonical rows keep both names verbatim and distinguishable, and the
    state extractor maps each person's event to its own state — proving no
    entity -> <person:N> -> cognition mismatch crept back in.
    """
    shadow_db = tmp_path / "shadow.db"
    states_db = tmp_path / "states.db"
    _seed_one_event(shadow_db, 10, "嘉森在加班写代码")
    _seed_one_event(shadow_db, 11, "我去哄嘻嘻睡觉了")
    with sqlite3.connect(str(shadow_db)) as con:
        rows = con.execute("SELECT redacted_text FROM shadow_events ORDER BY content_id").fetchall()
    texts = [str(r[0]) for r in rows]
    assert "嘉森" in texts[0] and "嘉森" not in texts[1]
    assert "嘻嘻" in texts[1] and "嘻嘻" not in texts[0]
    extract_states(shadow_db, states_db)
    states = {s[1]: s[2] for s in active_states(states_db)}
    assert states["working"] == "working"
    assert states["child_sleep"] == "putting_child_to_sleep"
