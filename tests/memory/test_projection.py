import sqlite3

import pytest

from tests.memory.test_contracts import memory
from tests.memory.test_store import store


class Writer:
    def __init__(self):
        self.rows = {}
        self.calls = 0

    def upsert(self, memory, *, intent):
        self.calls += 1
        self.rows[intent.intent_id] = memory.content
        return "provider-ref-unrelated-to-memory-id"


def worker(queue, writer):
    from mind_runtime.memory.projection import ProjectionWorker

    return ProjectionWorker(queue, writer)


def test_worker_provider_ref_and_no_canonical_write_capability(tmp_path):
    db = store(tmp_path / "memory.sqlite")
    db._commit((memory(),))
    queue = db.projection_queue()
    assert not hasattr(queue, "_commit")
    writer = Writer()
    assert worker(queue, writer).run_once(limit=1) == (1, 0)
    assert writer.calls == 1
    assert queue.pending(10) == ()
    ref = db._conn.execute("SELECT provider_ref FROM projection_intents").fetchone()[0]
    assert ref != memory().memory_id
    assert db.load_all() == (memory(),)


def test_worker_failure_leaves_memory_immutable_and_retryable(tmp_path):
    class Broken:
        def upsert(self, memory, *, intent):
            memory.content = "unauthorized"

    db = store(tmp_path / "memory.sqlite")
    db._commit((memory(),))
    queue = db.projection_queue()
    assert worker(queue, Broken()).run_once(limit=10) == (0, 1)
    assert queue.pending(10)[0].attempts == 1
    assert db.load_all() == (memory(),)
    assert worker(queue, Writer()).run_once(limit=10) == (1, 0)


def test_provider_success_then_local_crash_retries_stable_intent(tmp_path, monkeypatch):
    path = tmp_path / "memory.sqlite"
    db = store(path)
    db._commit((memory(),))
    queue = db.projection_queue()
    writer = Writer()

    def crash(*args):
        raise KeyboardInterrupt("process dies after provider upsert")

    monkeypatch.setattr(queue, "succeed", crash)
    with pytest.raises(KeyboardInterrupt):
        worker(queue, writer).run_once(limit=1)
    db.close()
    db = store(path)
    assert worker(db.projection_queue(), writer).run_once(limit=1) == (1, 0)
    assert writer.calls == 2 and len(writer.rows) == 1
    assert db.load_all() == (memory(),)


def test_orphan_intent_fails_closed(tmp_path):
    path = tmp_path / "memory.sqlite"
    db = store(path)
    db._commit((memory(),))
    with sqlite3.connect(path) as corrupt:
        corrupt.execute("DELETE FROM canonical_memory")
    writer = Writer()
    assert worker(db.projection_queue(), writer).run_once(limit=10) == (0, 1)
    assert writer.calls == 0
    assert db.load_all() == ()


def test_wipe_and_rebuild_preserve_canonical_across_provider_replacement(tmp_path):
    db = store(tmp_path / "memory.sqlite")
    db._commit((memory(),))
    queue = db.projection_queue()
    worker(queue, Writer()).run_once(limit=10)
    queue.wipe()
    assert db.load_all() == (memory(),)
    assert queue.rebuild(target="future-provider-v2") == 1
    assert queue.rebuild(target="future-provider-v2") == 0
    assert queue.pending(10)[0].target == "future-provider-v2"
    assert worker(queue, Writer()).run_once(limit=10) == (1, 0)
    assert db.load_all() == (memory(),)
