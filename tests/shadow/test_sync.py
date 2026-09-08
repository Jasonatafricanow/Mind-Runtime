"""Regression tests for the incremental shadow-sync cursor boundary (C0.5).

Locks the contract: the persisted sync cursor may only advance to the raw
store position actually consumed by this run's page (last_ts, last_id).
A per-run processing limit must never cause permanent message loss, restart
must resume from the first unprocessed item, and repeated runs must stay
idempotent (content_id UNIQUE ingestion).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from mind_runtime.shadow import sync as sync_module
from mind_runtime.shadow.redaction import count_records
from mind_runtime.shadow.sync import sync


@pytest.fixture()
def shadow_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect the shadow store + affect db into the test tmp dir."""
    monkeypatch.setenv("MIND_RUNTIME_SHADOW_DB", str(tmp_path / "shadow.db"))
    monkeypatch.setattr(sync_module, "AFFECT_DB", str(tmp_path / "affect.db"))
    return tmp_path


def _make_state_db(
    path: Path,
    rows: list[tuple[int, int, str]],
    *,
    source: str = "telegram",
) -> str:
    """Seed a Hermes-style state.db; rows are (id, timestamp, user content)."""
    con = sqlite3.connect(str(path))
    try:
        con.executescript(
            "CREATE TABLE sessions (id INTEGER PRIMARY KEY, source TEXT, session_key TEXT);"
            "CREATE TABLE messages (id INTEGER PRIMARY KEY, session_id INTEGER,"
            " timestamp REAL, role TEXT, content TEXT);"
        )
        con.execute("INSERT INTO sessions VALUES (1, ?, 'chat/1')", (source,))
        con.executemany("INSERT INTO messages VALUES (?, 1, ?, 'user', ?)", rows)
        con.commit()
    finally:
        con.close()
    return str(path)


def _stored_content_ids(shadow_db: Path) -> list[int]:
    with sqlite3.connect(str(shadow_db)) as con:
        rows = con.execute("SELECT content_id FROM shadow_events ORDER BY content_id").fetchall()
    return [int(r[0]) for r in rows]


def test_no_message_loss_when_pending_exceeds_page_limit(shadow_env: Path) -> None:
    state_db = _make_state_db(
        shadow_env / "state.db", [(i, 100 + i, f"第{i}条消息") for i in range(1, 6)]
    )
    runs = [sync(state_db, dry_run=False, limit=2, known_names=()) for _ in range(3)]
    # each page recorded exactly what fit; nothing was jumped over
    assert [r["recorded"] for r in runs] == [2, 2, 1]
    # cursor sits at the PAGE boundary, not at the global newest ts (105)
    assert runs[0]["cursor_to"] == 102.0
    assert runs[-1]["cursor_to"] == 105.0
    # every message reached the store exactly once, in order
    assert _stored_content_ids(shadow_env / "shadow.db") == [1, 2, 3, 4, 5]


def test_restart_resumes_from_first_unprocessed_item(shadow_env: Path) -> None:
    state_db = _make_state_db(
        shadow_env / "state.db", [(i, 200 + i, f"恢复测试{i}") for i in range(1, 5)]
    )
    first = sync(state_db, dry_run=False, limit=2, known_names=())
    assert _stored_content_ids(shadow_env / "shadow.db") == [1, 2]
    # simulate a fresh daemon process: state lives only in the persisted cursor
    resumed = sync(state_db, dry_run=False, limit=2, known_names=())
    assert resumed["fetched"] == 2
    assert resumed["cursor_from"] == first["cursor_to"]
    assert resumed["recorded"] == 2
    assert _stored_content_ids(shadow_env / "shadow.db") == [1, 2, 3, 4]


def test_repeat_runs_after_completion_stay_idempotent(shadow_env: Path) -> None:
    state_db = _make_state_db(
        shadow_env / "state.db", [(i, 300 + i * 10, f"幂等{i}") for i in range(1, 4)]
    )
    for _ in range(3):
        sync(state_db, dry_run=False, limit=10, known_names=())
    extra = sync(state_db, dry_run=False, limit=10, known_names=())
    assert extra["fetched"] == 0
    assert extra["recorded"] == 0
    assert count_records(shadow_env / "shadow.db") == 3


def test_tied_timestamps_and_blank_rows_are_not_lost_or_stalling(shadow_env: Path) -> None:
    state_db = _make_state_db(
        shadow_env / "state.db",
        [
            (1, 100, "消息一"),
            (2, 100, ""),  # blank content: filtered, must still advance position
            (3, 100, "消息二"),
            (4, 101, "消息三"),
        ],
    )
    first = sync(state_db, dry_run=False, limit=2, known_names=())
    # page ended inside the tied-timestamp group AND on a filtered-out row
    assert first["recorded"] == 1
    assert first["cursor_to"] == 100.0
    second = sync(state_db, dry_run=False, limit=2, known_names=())
    assert second["recorded"] == 2
    assert _stored_content_ids(shadow_env / "shadow.db") == [1, 3, 4]


def test_ineligible_source_is_counted_without_reprocess_loop(shadow_env: Path) -> None:
    state_db = _make_state_db(shadow_env / "state.db", [(7, 400, "系统渠道消息")], source="api")
    once = sync(state_db, dry_run=False, limit=10, known_names=())
    assert once["ineligible"] == 1
    assert once["recorded"] == 0
    again = sync(state_db, dry_run=False, limit=10, known_names=())
    # position advanced past the rejected row: no endless re-read
    assert again["fetched"] == 0


def test_dry_run_reports_position_without_writing_store(shadow_env: Path) -> None:
    state_db = _make_state_db(
        shadow_env / "state.db", [(i, 500 + i, f"dry{i}") for i in range(1, 4)]
    )
    preview = sync(state_db, dry_run=True, limit=2, known_names=())
    assert preview["fetched"] == 2
    # no store write bookkeeping happened during dry runs
    assert "shadow_db_total" not in preview
    # dry runs must not create/advance the canonical events store
    with sqlite3.connect(str(shadow_env / "shadow.db")) as con:
        tables = con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='shadow_events'"
        ).fetchall()
    assert tables == []
    real = sync(state_db, dry_run=False, limit=10, known_names=())
    assert real["recorded"] == 3


def test_backfill_dry_run_counts_ineligible_without_store_write(shadow_env: Path) -> None:
    """C1.5 behavior: dry-run preview classifies both ways and writes nothing."""
    state_db = _make_state_db(shadow_env / "state.db", [(1, 700, "预览消息")], source="api")
    preview = sync(state_db, dry_run=True, limit=10, known_names=())
    assert (preview["fetched"], preview["ineligible"]) == (1, 1)
    # a dry run must not create the canonical events store
    with sqlite3.connect(str(shadow_env / "shadow.db")) as con:
        tables = con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='shadow_events'"
        ).fetchall()
    assert tables == []


def test_private_mode_keeps_names_and_tokens_credentials(shadow_env: Path) -> None:
    state_db = _make_state_db(
        shadow_env / "state.db",
        [(1, 600, "嘻嘻的电话13812345678"), (2, 601, "支付验证码123456")],
    )
    stats = sync(state_db, dry_run=False, limit=10, known_names=("嘉森", "嘻嘻"))
    # PIN-like token cannot be redacted confidently -> fail-closed rejection;
    # the ordinary message is stored with names plaintext + credentials coded
    assert stats["leak_rejected"] == 1
    assert stats["recorded"] == 1
    with sqlite3.connect(str(shadow_env / "shadow.db")) as con:
        stored = con.execute("SELECT redacted_text FROM shadow_events").fetchone()[0]
    assert "嘻嘻" in stored
    assert "[PHONE]" in stored
    assert "13812345678" not in stored
    # affect pipeline consumed the plaintext corpus with intact semantics:
    # 嘻嘻 is a joy lexicon trigger and must label as joy (no person-code
    # mismatch), and the rejected PIN message contributes no affect row.
    con = sqlite3.connect(str(sync_module.AFFECT_DB))
    try:
        rows = con.execute(
            "SELECT dimension FROM shadow_affect WHERE sender='user' AND content_id=1"
        ).fetchall()
    finally:
        con.close()
    assert rows == [("joy",)]
