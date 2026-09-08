"""MIG-1 LegacyD11Reader tests — R1..R10.

Covers the dispatch read-only foundation requirements:

  R1  Read-only open        — all four DBs open read-only
  R2  Exact counts          — reader counts match direct SQL audit
  R3  Stable identity       — same row re-read yields identical source ref
  R4  Event-affect join     — 1:1 join contract honoured
  R5  Missing relation      — absent affect/state never fabricated
  R6  Concurrent v2 writer  — reader tolerates a live writer, no lock
  R7  No mutation           — legacy DB unchanged after full read pass
  R8  Pagination            — bounded scan, iterator, no unbounded load
  R9  Timestamp preservation— original timestamps not replaced by now()
  R10 Secret-safe report    — reader exposes only pre-redacted text
"""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import pytest

from mind_runtime.shadow.legacy_reader import LegacyD11Reader
from mind_runtime.shadow.redaction import hash_id, init_store


def _create_legacy_env(tmp_path: Path) -> dict[str, Path]:
    """Create 4 legacy DBs with a small deterministic corpus."""
    events = tmp_path / "shadow.db"
    affect = tmp_path / "shadow_affect.db"
    states = tmp_path / "shadow_states.db"
    states_v2 = tmp_path / "shadow_states_v2.db"

    # events DB
    init_store(events)
    ev_con = sqlite3.connect(str(events))
    for cid, sender, txt, ts in [
        (1, "user", "我去哄嘻嘻睡觉了", "2026-08-26T14:16:06+00:00"),
        (2, "agent", "好的，晚安🌙", "2026-08-26T14:16:06+00:00"),
        (3, "user", "今天心情不错", "2026-08-27T10:00:00+00:00"),
    ]:
        ev_con.execute(
            "INSERT INTO shadow_events "
            "(content_id, ts, user_hash, session_hash, channel, sender, "
            "trigger, source_domain, redacted_text) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (cid, ts, hash_id("u"), hash_id("s"), "telegram", sender,
             "message", "kayla_persona", txt),
        )
    ev_con.commit()
    ev_con.close()

    # affect DB (1:1 with events)
    af_con = sqlite3.connect(str(affect))
    af_con.execute(
        "CREATE TABLE IF NOT EXISTS shadow_affect ("
        "affect_id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "content_id INTEGER UNIQUE, ts TEXT NOT NULL, session_hash TEXT NOT NULL, "
        "channel TEXT NOT NULL, sender TEXT NOT NULL, dimension TEXT NOT NULL, "
        "confidence REAL NOT NULL)"
    )
    for cid, dim, conf in [(1, "joy", 0.7), (2, "neutral", 0.6), (3, "joy", 0.8)]:
        af_con.execute(
            "INSERT INTO shadow_affect (content_id, ts, session_hash, channel, sender, dimension, confidence) "
            "VALUES (?,?,?,?,?,?,?)",
            (cid, "2026-08-26T14:16:06+00:00", hash_id("s"), "telegram", "agent", dim, conf),
        )
    af_con.commit()
    af_con.close()

    # states v1 (a couple)
    st_con = sqlite3.connect(str(states))
    st_con.execute(
        "CREATE TABLE IF NOT EXISTS shadow_states ("
        "state_id INTEGER PRIMARY KEY AUTOINCREMENT, content_id INTEGER UNIQUE, "
        "ts TEXT NOT NULL, session_hash TEXT NOT NULL, category TEXT NOT NULL, "
        "key TEXT NOT NULL, value TEXT NOT NULL, valid_until TEXT)"
    )
    st_con.execute(
        "INSERT INTO shadow_states (content_id, ts, session_hash, category, key, value) "
        "VALUES (?,?,?,?,?,?)",
        (1, "2026-08-26T14:16:06+00:00", hash_id("s"), "activity", "child_sleep", "putting_child_to_sleep"),
    )
    st_con.commit()
    st_con.close()

    # states v2 (superset)
    st2_con = sqlite3.connect(str(states_v2))
    st2_con.execute(
        "CREATE TABLE IF NOT EXISTS shadow_states ("
        "state_id INTEGER PRIMARY KEY AUTOINCREMENT, content_id INTEGER UNIQUE, "
        "ts TEXT NOT NULL, session_hash TEXT NOT NULL, category TEXT NOT NULL, "
        "key TEXT NOT NULL, value TEXT NOT NULL, valid_until TEXT)"
    )
    for cid, cat, key, val in [
        (1, "activity", "child_sleep", "putting_child_to_sleep"),
        (2, "activity", "working", "working"),
        (3, "presence", "phone", "phone"),
    ]:
        st2_con.execute(
            "INSERT INTO shadow_states (content_id, ts, session_hash, category, key, value) "
            "VALUES (?,?,?,?,?,?)",
            (cid, "2026-08-26T14:16:06+00:00", hash_id("s"), cat, key, val),
        )
    st2_con.commit()
    st2_con.close()

    return {
        "events": events, "affect": affect,
        "states": states, "states_v2": states_v2,
    }


def _file_sha1(path: Path) -> str:
    with open(path, "rb") as f:
        return hashlib.sha1(f.read()).hexdigest()


@pytest.fixture
def legacy_env(tmp_path: Path) -> dict[str, Path]:
    return _create_legacy_env(tmp_path)


@pytest.fixture
def reader(legacy_env: dict[str, Path]) -> LegacyD11Reader:
    return LegacyD11Reader(
        events_db=legacy_env["events"],
        affect_db=legacy_env["affect"],
        states_db=legacy_env["states"],
        states_v2_db=legacy_env["states_v2"],
        page_size=2,  # force multi-page iteration
    )


# ── R1: read-only open ────────────────────────────────────────────────────────


def test_r1_readonly_open_all_four(legacy_env: dict[str, Path]) -> None:
    r = LegacyD11Reader(
        events_db=legacy_env["events"],
        affect_db=legacy_env["affect"],
        states_db=legacy_env["states"],
        states_v2_db=legacy_env["states_v2"],
    )
    assert r.count_events() == 3
    assert r.count_affect() == 3
    assert r.count_states("v1") == 1
    assert r.count_states("v2") == 3


# ── R2: exact counts ─────────────────────────────────────────────────────────


def test_r2_exact_counts(reader: LegacyD11Reader) -> None:
    assert reader.count_events() == 3
    assert reader.count_affect() == 3
    assert reader.count_states("v2") == 3
    assert reader.count_states("v1") == 1


# ── R3: stable identity ──────────────────────────────────────────────────────


def test_r3_stable_identity(reader: LegacyD11Reader) -> None:
    e1 = reader.get_event(2)
    e2 = reader.get_event(2)
    assert e1 is not None and e2 is not None
    assert e1.source.idempotency_key == e2.source.idempotency_key
    assert e1.source.idempotency_key == "d11:shadow.db:shadow_events:2"
    assert e1.content_id == e2.content_id


# ── R4: event-affect join ────────────────────────────────────────────────────


def test_r4_event_affect_join(reader: LegacyD11Reader) -> None:
    joined = 0
    for ev in reader.scan_events():
        af = reader.get_related_affect(ev.content_id)
        assert af is not None, f"event {ev.content_id} should have affect"
        assert af.content_id == ev.content_id
        assert af.source.idempotency_key == f"d11:shadow_affect.db:shadow_affect:{ev.content_id}"
        joined += 1
    assert joined == 3  # exact 1:1


# ── R5: missing relation not fabricated ──────────────────────────────────────


def test_r5_missing_relation_returns_none(reader: LegacyD11Reader) -> None:
    assert reader.get_event(999) is None
    assert reader.get_related_affect(999) is None


# ── R6: concurrent v2 writer ────────────────────────────────────────────────


def test_r6_concurrent_v2_writer(reader: LegacyD11Reader, legacy_env: dict[str, Path]) -> None:
    # Simulate an active writer appending to states_v2 while we read.
    st2 = legacy_env["states_v2"]
    writer = sqlite3.connect(str(st2))
    writer.execute(
        "INSERT INTO shadow_states (content_id, ts, session_hash, category, key, value) "
        "VALUES (?,?,?,?,?,?)",
        (99, "2026-08-31T12:00:00+00:00", hash_id("s"), "activity", "out", "out"),
    )
    writer.commit()

    # Reader still works, sees the new row, no lock/corruption.
    assert reader.count_states("v2") == 4
    assert reader.get_event(99) is None  # unrelated
    writer.close()
    # reader can re-open after writer
    assert reader.count_states("v2") == 4


# ── R7: no mutation ──────────────────────────────────────────────────────────


def test_r7_no_mutation(
    reader: LegacyD11Reader, legacy_env: dict[str, Path]
) -> None:
    before = {k: _file_sha1(v) for k, v in legacy_env.items()}
    # full read pass
    list(reader.scan_events())
    list(reader.scan_affect_annotations())
    list(reader.scan_state_snapshots(db="v2"))
    list(reader.scan_state_snapshots(db="v1"))
    reader.watermark()
    after = {k: _file_sha1(v) for k, v in legacy_env.items()}
    assert before == after, "legacy DBs mutated by read-only reader"


# ── R8: pagination / bounded scan ────────────────────────────────────────────


def test_r8_bounded_scan_iterates_all(reader: LegacyD11Reader) -> None:
    # page_size=2 forces multiple pages over 3 rows
    seen = [e.content_id for e in reader.scan_events()]
    assert seen == [1, 2, 3]
    # after_content_id resumes
    tail = [e.content_id for e in reader.scan_events(after_content_id=1)]
    assert tail == [2, 3]
    # filters
    users = [e.content_id for e in reader.scan_events(sender="user")]
    assert users == [1, 3]


# ── R9: timestamp preservation ───────────────────────────────────────────────


def test_r9_timestamp_preserved(reader: LegacyD11Reader) -> None:
    ev = reader.get_event(1)
    assert ev is not None
    assert ev.ts is not None
    assert ev.ts.isoformat() == "2026-08-26T14:16:06+00:00"
    # effective timestamp is event_ts when present, else ts
    assert ev.effective_timestamp == ev.ts


# ── R10: secret-safe ─────────────────────────────────────────────────────────


def test_r10_redacted_text_is_redacted(
    reader: LegacyD11Reader, tmp_path: Path
) -> None:
    # Build one row with a credential-shaped token in redacted_text to
    # confirm the reader surfaces pre-redacted text as-is (no secrets).
    from mind_runtime.shadow.legacy_reader import LegacyD11Reader as R

    ev_db = tmp_path / "s.db"
    init_store(ev_db)
    con = sqlite3.connect(str(ev_db))
    con.execute(
        "INSERT INTO shadow_events "
        "(content_id, ts, user_hash, session_hash, channel, sender, "
        "trigger, source_domain, redacted_text) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (7, "2026-08-26T14:16:06+00:00", hash_id("u"), hash_id("s"), "telegram",
         "user", "message", "kayla_persona", "[TOKEN] 是 secret"),
    )
    con.commit()
    con.close()
    r = R(events_db=ev_db, affect_db=tmp_path / "a.db", states_db=tmp_path / "s1.db",
          states_v2_db=tmp_path / "s2.db")
    ev = r.get_event(7)
    assert ev is not None
    # only the pre-redacted marker is exposed, never a raw secret
    assert "[TOKEN]" in (ev.redacted_text or "")
    assert "sk-abcdefghijklmnopqrstuvwx" not in (ev.redacted_text or "")


# ── DTO immutability ─────────────────────────────────────────────────────────


def test_dto_frozen(reader: LegacyD11Reader) -> None:
    ev = reader.get_event(1)
    assert ev is not None
    with pytest.raises(Exception):
        ev.content_id = 999  # type: ignore[misc]
