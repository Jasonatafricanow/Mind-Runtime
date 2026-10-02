import sqlite3
from dataclasses import replace
from datetime import UTC, datetime

import pytest
from mr_mem import Scope, ScopeDomain, SourceRef

from mind_runtime.integrations.native_history import (
    HermesSourceStore,
    NativeRecord,
    source_fragments,
    structural_drop,
)


def test_machine_noise_only_and_lossless_host_fragment_ids():
    ref = SourceRef("hermes", "s1", "1", datetime(2026, 10, 1, tzinfo=UTC), "1")
    text = r"Tests failed; always preserve C:\new\test logs."
    record = NativeRecord(ref, "user", text, (1.0, 1))
    assert structural_drop(record) is None
    fragments = source_fragments(record)
    assert "".join(f.text for f in fragments) == text
    assert len(fragments) == 2
    assert source_fragments(record) == fragments
    assert structural_drop(NativeRecord(ref, "tool", text, (1.0, 1))) == "machine-role"
    envelope = (
        "[IMPORTANT: Background process proc_1 exited (exit code 1).\n"
        "Command: pytest\nOutput:\nfailed\n]"
    )
    assert structural_drop(NativeRecord(ref, "user", envelope, (1.0, 1)))
    mixed = NativeRecord(ref, "user", envelope + "\nAlways retain logs.", (1.0, 1))
    assert structural_drop(mixed) is None
    assert (
        structural_drop(NativeRecord(ref, "assistant", "", (1.0, 1), True)) == "empty-tool-envelope"
    )
    assert structural_drop(NativeRecord(ref, "user", " ", (1.0, 1))) == "empty-record"
    assert structural_drop(NativeRecord(ref, "assistant", text, (1.0, 1), True)) is None


def test_native_adapter_orders_ties_and_revalidates_source_revision_and_scope(tmp_path):
    path = tmp_path / "native.sqlite"
    with sqlite3.connect(path) as db:
        db.executescript("""
            CREATE TABLE sessions(id TEXT, user_id TEXT);
            CREATE TABLE messages(id INTEGER, session_id TEXT, role TEXT, content TEXT,
                timestamp REAL, tool_calls TEXT, active INTEGER, compacted INTEGER);
            INSERT INTO sessions VALUES ('s1','native-u1'),('s2','native-u2');
            INSERT INTO messages VALUES
                (2,'s1','user','second',100,NULL,1,0),
                (1,'s1','user','first',100,NULL,1,0),
                (3,'s2','user','other user',100,NULL,1,0);
        """)
    scope = Scope(ScopeDomain.USER, user_id="u1")
    store = HermesSourceStore(path, scope=scope, source_namespace="native", user_id="native-u1")
    try:
        records = store.read()
        assert [r.ref.record_id for r in records] == ["1", "2"]
        assert store.read(after=records[0].ordering_key) == (records[1],)
        assert store.current_ref(scope, records[0].ref) == records[0].ref
        assert store.current_ref(Scope(ScopeDomain.USER, user_id="u2"), records[0].ref) is None
        with sqlite3.connect(path) as db:
            db.execute("UPDATE messages SET content='edited' WHERE id=1")
        revised = store.current_ref(scope, records[0].ref)
        assert revised.source_key == records[0].ref.source_key
        assert revised.version_key != records[0].ref.version_key
        with sqlite3.connect(path) as db:
            db.execute("UPDATE messages SET active=0 WHERE id=1")
        assert store.current_ref(scope, records[0].ref) is None
    finally:
        store.close()


def test_fragment_boundaries_preserve_original_slices_after_empty_chunks():
    ref = SourceRef("native", "s1", "1", datetime(2026, 10, 1, tzinfo=UTC), "1")
    text = " " * 200 + "\n" + "保留历史来源" * 80 + "\n"
    record = NativeRecord(ref, "user", text, (1.0, 1))
    fragments = source_fragments(record, max_characters=100)
    assert fragments and fragments[0].start == 201
    assert all(f.text == text[f.start : f.end] and 0 < len(f.text) <= 100 for f in fragments)
    assert "".join(f.text for f in fragments) == text[201:]
    assert source_fragments(record, max_characters=100) == fragments


def test_source_unavailable_does_not_create_a_second_empty_history(tmp_path):
    path = tmp_path / "missing-native.sqlite"
    with pytest.raises(ValueError, match="ownership"):
        HermesSourceStore(
            path,
            scope=Scope(ScopeDomain.USER, user_id="u1"),
            source_namespace="native",
            user_id=None,
        )
    with pytest.raises(sqlite3.OperationalError):
        HermesSourceStore(
            path,
            scope=Scope(ScopeDomain.USER, user_id="u1"),
            source_namespace="native",
            user_id="native-user",
        )
    assert not path.exists()


def test_native_session_allowlist_and_incremental_cursor_handle_changes(tmp_path):
    path = tmp_path / "native.sqlite"
    with sqlite3.connect(path) as db:
        db.executescript("""
            CREATE TABLE sessions(id TEXT, user_id TEXT);
            CREATE TABLE messages(id INTEGER, session_id TEXT, role TEXT, content TEXT,
                timestamp REAL, tool_calls TEXT, active INTEGER, compacted INTEGER);
            INSERT INTO sessions VALUES ('owned','native-u1'),('other','native-u2'),
                ('anonymous',NULL),('anonymous-other',NULL);
            INSERT INTO messages VALUES
                (1,'owned','user','owned-only',100,NULL,1,0),
                (2,'anonymous','user','compacted but retained source',100,NULL,0,1),
                (3,'anonymous-other','user','not allowlisted',100,NULL,1,0),
                (4,'anonymous','assistant',NULL,101,'[]',1,0),
                (5,'other','user','another user',102,NULL,1,0);
        """)
    scope = Scope(ScopeDomain.USER, user_id="u1")
    source = HermesSourceStore(
        path, scope=scope, source_namespace="native", user_id=None, session_ids=("anonymous",)
    )
    try:
        rows = source.read(limit=1)
        assert [r.ref.record_id for r in rows] == ["2"]
        assert source.current_ref(scope, replace(rows[0].ref, source_namespace="another")) is None
        assert source.current_ref(scope, replace(rows[0].ref, session_id="anonymous-other")) is None
        assert source.current_ref(scope, replace(rows[0].ref, record_id="99")) is None
        tail = source.read(after=rows[0].ordering_key)
        assert len(tail) == 1 and tail[0].text == "" and tail[0].tool_only
        assert source.read(after=tail[0].ordering_key) == ()
        with sqlite3.connect(path) as db:
            db.execute(
                "INSERT INTO messages VALUES (6,'anonymous','user','backdated delta',99,NULL,1,0)"
            )
            db.execute(
                "INSERT INTO messages VALUES (7,'anonymous','user','same-time append',101,NULL,1,0)"
            )
        appended = source.read(after=tail[0].ordering_key)
        assert [r.ref.record_id for r in appended] == ["7"]
        delta = source.read()[0]
        assert delta.ref.record_id == "6"  # host must deliver backdated deltas explicitly
        assert source.current_ref(scope, delta.ref) == delta.ref
        assert source.read(after=appended[0].ordering_key) == ()
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            source._db.execute("DELETE FROM messages")
    finally:
        source.close()
