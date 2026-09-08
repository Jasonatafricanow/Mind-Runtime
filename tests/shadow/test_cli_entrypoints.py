"""Thin CLI entrypoints stay behavior-tested (C1.5).

Each main() is a thin shell: argparse -> the already behavior-tested
application function -> print. These tests drive them end-to-end through
injected argv/env so no CLI logic is exempt from coverage.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

from mind_runtime.shadow import sync as sync_module
from mind_runtime.shadow.backfill import main as backfill_main
from mind_runtime.shadow.runner import main as runner_main
from mind_runtime.shadow.sync import main as sync_main


def _make_state_db(
    path: Path, rows: list[tuple[int, int, str]], *, source: str = "telegram"
) -> str:
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


def test_backfill_main_dry_run_reports_stats(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    state_db = _make_state_db(tmp_path / "state.db", [(1, 100, "入口测试")])
    monkeypatch.setenv("MIND_RUNTIME_SHADOW_DB", str(tmp_path / "shadow.db"))
    monkeypatch.setattr(
        sys,
        "argv",
        ["backfill", "--state-db", state_db, "--dry-run", "--cursor", "0", "--limit", "5"],
    )
    backfill_main()
    out = capsys.readouterr().out
    assert "gate=False" in out
    assert "'fetched': 1" in out and "'eligible': 1" in out


def test_sync_main_executes_one_real_pass(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    state_db = _make_state_db(tmp_path / "state.db", [(1, 200, "入口同步")])
    shadow_db = tmp_path / "shadow.db"
    monkeypatch.setenv("MIND_RUNTIME_SHADOW_DB", str(shadow_db))
    monkeypatch.setattr(sync_module, "AFFECT_DB", str(tmp_path / "affect.db"))
    monkeypatch.setattr(sys, "argv", ["sync", "--state-db", state_db, "--limit", "5"])
    sync_main()
    assert "'recorded': 1" in capsys.readouterr().out
    # cursor persisted exactly like the library-level contract
    from mind_runtime.shadow.sync import _read_cursor

    assert _read_cursor(str(shadow_db)) == (200.0, 1)


def test_backfill_main_real_run_gate_off_prints_stats_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    state_db = _make_state_db(tmp_path / "state.db", [(1, 150, "真实落库")])
    monkeypatch.delenv("MIND_RUNTIME_SHADOW_ENABLED", raising=False)
    monkeypatch.setenv("MIND_RUNTIME_SHADOW_DB", str(tmp_path / "shadow.db"))
    monkeypatch.setattr(sys, "argv", ["backfill", "--state-db", state_db, "--limit", "5"])
    backfill_main()
    out = capsys.readouterr().out
    assert "'recorded': 1" in out
    # gate OFF: the CLI must not advertise a shadow-db location
    assert "shadow db =>" not in out


def test_backfill_main_real_run_gate_on_announces_store(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    state_db = _make_state_db(tmp_path / "state.db", [(1, 160, "开启门禁")])
    monkeypatch.setenv("MIND_RUNTIME_SHADOW_ENABLED", "1")
    shadow_db = tmp_path / "shadow.db"
    monkeypatch.setenv("MIND_RUNTIME_SHADOW_DB", str(shadow_db))
    monkeypatch.setattr(sys, "argv", ["backfill", "--state-db", state_db, "--limit", "5"])
    backfill_main()
    out = capsys.readouterr().out
    assert f"shadow db => {shadow_db}" in out


def test_runner_main_prints_status_lines(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("MIND_RUNTIME_SHADOW_ENABLED", raising=False)
    monkeypatch.setattr(sys, "argv", ["runner"])
    runner_main()
    assert "awaiting source adapter" in capsys.readouterr().out
    monkeypatch.setattr(sys, "argv", ["runner", "--once"])
    runner_main()
    second = capsys.readouterr().out
    assert "gate=False" in second and "source adapter wiring pending" in second
