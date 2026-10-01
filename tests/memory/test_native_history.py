import sqlite3
from datetime import UTC, datetime

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
    store = HermesSourceStore(
        path, scope=scope, source_namespace="native", user_id="native-u1"
    )
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
