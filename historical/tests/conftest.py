import sqlite3

import pytest
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
