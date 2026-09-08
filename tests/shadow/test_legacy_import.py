"""MIG-2 tests — T1..T10 D11 legacy direct import.

Covers dispatch §17:

  T1  LegacyD11Reader reads all rows (75,997 on real; synthetic here)
  T2  single import
  T3  content_id / provenance preserved
  T4  event_ts present -> occurred_at preserved
  T5  event_ts absent -> not fabricated (time_source=ts)
  T6  batch import
  T7  second import zero duplicate
  T8  shadow_affect not written to RuntimeState
  T9  shadow_states/v2 not imported
  T10 full import smoke (synthetic corpus)
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from mind_runtime.facts import FactIngestService, SqliteFactBackend
from mind_runtime.shadow.legacy_import import build_evidence, import_legacy_events
from mind_runtime.shadow.legacy_reader import LegacyD11Reader
from mind_runtime.shadow.legacy_dto import LegacyEventRecord, LegacySourceRef
from mind_runtime.contracts import Scope, ScopeDomain

ROWS = [
    # content_id, ts, channel, sender, text, event_ts
    (1, "2026-08-26T14:16:06+00:00", "weixin", "user", "我去哄嘻嘻睡觉了", None),
    (2, "2026-08-26T14:16:06+00:00", "weixin", "agent", "好的，晚安🌙", "2026-08-26T14:16:08+00:00"),
    (3, "2026-08-27T10:00:00+00:00", "telegram", "user", "今天心情不错", None),
    (4, "2026-08-27T10:00:05+00:00", "telegram", "agent", "那就好😊", None),
]


def _make_legacy_db(path: Path) -> None:
    con = sqlite3.connect(str(path))
    con.execute(
        "CREATE TABLE IF NOT EXISTS shadow_events ("
        "event_id INTEGER PRIMARY KEY AUTOINCREMENT, content_id INTEGER UNIQUE, "
        "ts TEXT NOT NULL, user_hash TEXT NOT NULL, session_hash TEXT NOT NULL, "
        "channel TEXT NOT NULL, sender TEXT NOT NULL, trigger TEXT NOT NULL, "
        "source_domain TEXT NOT NULL, redacted_text TEXT NOT NULL, event_ts TEXT)"
    )
    for cid, ts, channel, sender, text, event_ts in ROWS:
        con.execute(
            "INSERT INTO shadow_events (content_id, ts, user_hash, session_hash, "
            "channel, sender, trigger, source_domain, redacted_text, event_ts) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (cid, ts, "u1", f"s{cid}", channel, sender, "message",
             "kayla_persona", text, event_ts),
        )
    con.commit()
    con.close()


def _make_affect_db(path: Path) -> None:
    con = sqlite3.connect(str(path))
    con.execute(
        "CREATE TABLE IF NOT EXISTS shadow_affect ("
        "affect_id INTEGER PRIMARY KEY AUTOINCREMENT, content_id INTEGER UNIQUE, "
        "ts TEXT NOT NULL, session_hash TEXT NOT NULL, channel TEXT NOT NULL, "
        "sender TEXT NOT NULL, dimension TEXT NOT NULL, confidence REAL NOT NULL)"
    )
    con.commit()
    con.close()


def _make_states_db(path: Path) -> None:
    con = sqlite3.connect(str(path))
    con.execute(
        "CREATE TABLE IF NOT EXISTS shadow_states ("
        "state_id INTEGER PRIMARY KEY AUTOINCREMENT, content_id INTEGER UNIQUE, "
        "ts TEXT NOT NULL, session_hash TEXT NOT NULL, category TEXT NOT NULL, "
        "key TEXT NOT NULL, value TEXT NOT NULL, valid_until TEXT)"
    )
    con.commit()
    con.close()


@pytest.fixture
def env(tmp_path: Path) -> dict[str, Path]:
    shadow_db = tmp_path / "shadow.db"
    affect_db = tmp_path / "shadow_affect.db"
    states_db = tmp_path / "shadow_states.db"
    states_v2 = tmp_path / "shadow_states_v2.db"
    facts_db = tmp_path / "facts.sqlite"
    _make_legacy_db(shadow_db)
    _make_affect_db(affect_db)
    _make_states_db(states_db)
    _make_states_db(states_v2)
    return {
        "shadow": shadow_db, "affect": affect_db,
        "states": states_db, "states_v2": states_v2, "facts": facts_db,
    }


def _count_evidence(path: Path) -> int:
    be = SqliteFactBackend(path)
    try:
        return len(be.load_evidence())
    finally:
        be.close()


def _count_observations(path: Path) -> int:
    be = SqliteFactBackend(path)
    try:
        return len(be.load_observations())
    finally:
        be.close()


# ── T1: reader reads all ─────────────────────────────────────────────────────


def test_t1_reader_reads_all(env: dict[str, Path]) -> None:
    reader = LegacyD11Reader(events_db=env["shadow"])
    assert reader.count_events() == 4
    assert [e.content_id for e in reader.scan_events()] == [1, 2, 3, 4]


# ── T2: single import ────────────────────────────────────────────────────────


def test_t2_single_import(env: dict[str, Path]) -> None:
    c = import_legacy_events(facts_db=env["facts"], legacy_events_db=env["shadow"])
    # 2 user -> evidence+observation; 2 agent -> evidence-only (rejected)
    assert c.imported == 2
    assert c.evidence_new == 2
    assert c.observation_new == 2
    assert c.evidence_rejected == 2
    assert _count_evidence(env["facts"]) == 4
    assert _count_observations(env["facts"]) == 2


# ── T3: content_id / provenance preserved ────────────────────────────────────


def test_t3_content_id_provenance(env: dict[str, Path]) -> None:
    import_legacy_events(facts_db=env["facts"], legacy_events_db=env["shadow"])
    be = SqliteFactBackend(env["facts"])
    try:
        evs = be.load_evidence()
        by_id = {e.id: e for e, _ in evs}
        e = by_id["d11-ev-1"]
        assert e.payload["legacy_provenance"]["content_id"] == 1
        assert e.payload["legacy_provenance"]["source"] == "d11-shadow"
        assert e.payload["legacy_provenance"]["database"] == "shadow.db"
        assert e.payload["legacy_provenance"]["table"] == "shadow_events"
        assert e.payload["text"] == "我去哄嘻嘻睡觉了"
        assert e.payload["channel"] == "weixin"
    finally:
        be.close()


# ── T4: event_ts present -> occurred_at preserved ────────────────────────────


def test_t4_event_ts_preserved(env: dict[str, Path]) -> None:
    import_legacy_events(facts_db=env["facts"], legacy_events_db=env["shadow"])
    be = SqliteFactBackend(env["facts"])
    try:
        evs = {e.id: e for e, _ in be.load_evidence()}
        e = evs["d11-ev-2"]  # agent with event_ts=14:16:08
        assert e.occurred_at.isoformat() == "2026-08-26T14:16:08+00:00"
        assert e.payload["time_source"] == "event_ts"
    finally:
        be.close()


# ── T5: event_ts absent -> not fabricated ────────────────────────────────────


def test_t5_event_ts_absent_not_fabricated(env: dict[str, Path]) -> None:
    import_legacy_events(facts_db=env["facts"], legacy_events_db=env["shadow"])
    be = SqliteFactBackend(env["facts"])
    try:
        evs = {e.id: e for e, _ in be.load_evidence()}
        e = evs["d11-ev-1"]  # user, event_ts=None, ts=14:16:06
        assert e.payload["time_source"] == "ts"
        assert e.occurred_at.isoformat() == "2026-08-26T14:16:06+00:00"
        assert e.payload["ingestion_ts"] == "2026-08-26T14:16:06+00:00"
    finally:
        be.close()


# ── T6: batch import ─────────────────────────────────────────────────────────


def test_t6_batch_import(env: dict[str, Path]) -> None:
    c = import_legacy_events(facts_db=env["facts"], legacy_events_db=env["shadow"], batch_size=2)
    assert c.read == 4
    assert _count_evidence(env["facts"]) == 4


# ── T7: second import zero duplicate ─────────────────────────────────────────


def test_t7_second_import_zero_duplicate(env: dict[str, Path]) -> None:
    import_legacy_events(facts_db=env["facts"], legacy_events_db=env["shadow"])
    c2 = import_legacy_events(facts_db=env["facts"], legacy_events_db=env["shadow"])
    assert c2.evidence_new == 0
    assert c2.observation_new == 0
    assert _count_evidence(env["facts"]) == 4  # unchanged
    assert _count_observations(env["facts"]) == 2  # unchanged


# ── T8: shadow_affect not written to RuntimeState ────────────────────────────


def test_t8_affect_not_imported(env: dict[str, Path]) -> None:
    # shadow_affect DB is never read by the importer; nothing from it lands
    # in facts. The importer only reads shadow_events.
    import_legacy_events(facts_db=env["facts"], legacy_events_db=env["shadow"])
    be = SqliteFactBackend(env["facts"])
    try:
        for e, _ in be.load_evidence():
            assert "dimension" not in e.payload
            assert "confidence" not in e.payload
    finally:
        be.close()


# ── T9: shadow_states / v2 not imported ──────────────────────────────────────


def test_t9_states_not_imported(env: dict[str, Path]) -> None:
    import_legacy_events(facts_db=env["facts"], legacy_events_db=env["shadow"])
    be = SqliteFactBackend(env["facts"])
    try:
        for e, _ in be.load_evidence():
            assert "category" not in e.payload
            assert "key" not in e.payload
    finally:
        be.close()


# ── T10: full import smoke ───────────────────────────────────────────────────


def test_t10_full_import_smoke(env: dict[str, Path]) -> None:
    c = import_legacy_events(facts_db=env["facts"], legacy_events_db=env["shadow"])
    assert c.read == 4
    assert c.invalid == 0
    # verify deterministic observation id scheme
    be = SqliteFactBackend(env["facts"])
    try:
        obs_ids = sorted(o.id for o in be.load_observations())
        assert obs_ids == ["observation-d11-ev-1", "observation-d11-ev-3"]
    finally:
        be.close()


# ── build_evidence direct (edge: missing ts) ─────────────────────────────────


def test_build_evidence_missing_ts_falls_back() -> None:
    rec = LegacyEventRecord(
        source=LegacySourceRef(db="shadow.db", table="shadow_events", legacy_pk=99),
        content_id=99, event_id=99, ts=None, event_ts=None,
        user_hash=None, session_hash=None, channel=None, sender=None,
        trigger=None, source_domain=None, redacted_text=None,
    )
    ev = build_evidence(
        rec, scope=Scope(domain=ScopeDomain.USER, user_id="user"), origin_runtime_id="kayla"
    )
    assert ev.occurred_at.year == 1970  # epoch guard, never crashes
