import hashlib
import sqlite3
from dataclasses import replace

import pytest
from historical.source_curator import HistoricalSourceCurator, SourceDisposition
from historical.source_iterator import HistoricalSourceIterator
from mr_mem import Scope, ScopeDomain


@pytest.fixture
def native(tmp_path):
    path = tmp_path / "native.sqlite"
    with sqlite3.connect(path) as db:
        db.executescript(
            "CREATE TABLE sessions(id TEXT PRIMARY KEY,user_id TEXT); "
            "CREATE TABLE messages(id INTEGER PRIMARY KEY,session_id TEXT,role TEXT,"
            "content TEXT,timestamp REAL,record_type TEXT,tool_calls TEXT,"
            "active INTEGER DEFAULT 1);"
        )
        db.executemany("INSERT INTO sessions VALUES(?,?)", [("s", "owner"), ("foreign", "other")])
        db.executemany(
            "INSERT INTO messages(id,session_id,role,content,timestamp,record_type) "
            "VALUES(?,?,?,?,?,?)",
            [
                (1, "s", "assistant", "采用 A 还是 B？", 10, "assistant"),
                (2, "s", "user", "A", 11, "user"),
                (3, "s", "tool", "CI green", 12, "ci_output"),
                (4, "s", "assistant", "正在读取 compiler.py", 13, "agent_progress"),
                (5, "s", "user", "不是", 13, "user"),
                (6, "foreign", "user", "foreign", 14, "user"),
                (7, "s", "tool", "evidence", 15, "tool_result"),
                (8, "s", "unknown", "unknown", 16, None),
            ],
        )
    scope = Scope(ScopeDomain.USER, "owner")
    reader = HistoricalSourceIterator(
        path, scope=scope, namespace="fixture-native", user_id="owner"
    )
    yield path, scope, reader
    reader.close()


def test_curation_provenance_short_commitments_and_context(native):
    _, _, reader = native
    records = tuple(reader.iterate())
    curator = HistoricalSourceCurator()
    assert [curator.classify(r).value for r in records] == [
        "CONTEXT_ONLY",
        "COMPILE",
        "IGNORE",
        "IGNORE",
        "COMPILE",
        "IGNORE",
        "CONTEXT_ONLY",
    ]
    assert curator.classify(records[-2], necessary_context=True) == SourceDisposition.CONTEXT_ONLY
    assert curator.classify(records[2], necessary_context=True) == SourceDisposition.IGNORE
    assert (
        curator.classify(replace(records[1], record_type="agent_execution"))
        == SourceDisposition.IGNORE
    )


def test_exact_read_only_native_binding_and_order(native):
    path, scope, reader = native
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    records = tuple(reader.iterate())
    short = records[1]
    iid = reader.bind(short)
    assert reader.current_user_source(scope, iid) == short.source_ref
    assert reader.current_ref(scope, short.source_ref) == short.source_ref
    assert reader.current_ref(Scope(ScopeDomain.USER, "other"), short.source_ref) is None
    assert [r.source_ref.record_id for r in reader.iterate(after=records[3].ordering_key)] == [
        "5",
        "7",
        "8",
    ]
    assert reader.before(short) == (records[0],)
    with pytest.raises(ValueError, match="eligible USER"):
        reader.bind(records[0])
    with pytest.raises(sqlite3.OperationalError):
        reader._db.execute("DELETE FROM messages")
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before
    with sqlite3.connect(path) as db:
        db.execute("UPDATE messages SET content='changed' WHERE id=2")
    assert reader.current_user_source(scope, iid) != short.source_ref
