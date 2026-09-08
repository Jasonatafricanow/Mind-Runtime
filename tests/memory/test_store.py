import sqlite3
from dataclasses import replace

import pytest

from mind_runtime.contracts import Scope, ScopeDomain
from tests.memory.test_contracts import memory


def store(path):
    from mind_runtime.memory.store import CanonicalMemoryStore

    return CanonicalMemoryStore(path)


@pytest.mark.parametrize(
    "scope",
    [
        Scope(ScopeDomain.USER, user_id="用户"),
        Scope(ScopeDomain.AGENT, agent_id="domain-agent", persona_id="p"),
        Scope(ScopeDomain.RELATIONSHIP, relationship_id="r", persona_id="p"),
        Scope(ScopeDomain.WORLD, world_id="w"),
        Scope(ScopeDomain.INTERACTION, interaction_id="i"),
    ],
)
def test_scope_origin_sync_and_content_survive_restart(tmp_path, scope):
    path = tmp_path / "memory.sqlite"
    original = memory()
    original = replace(original, scope=scope, sync=replace(original.sync, scope=scope))
    db = store(path)
    db._commit((original,))
    db.close()
    db = store(path)
    assert db.get(original.memory_id) == original
    assert db.load_all() == (original,)
    assert len(db.projection_queue().pending(10)) == 1
    db.close()


def test_exact_replay_and_conflicting_immutable_payload(tmp_path):
    from mind_runtime.memory.store import MemoryConflict

    db = store(tmp_path / "memory.sqlite")
    db._commit((memory(),))
    db._commit((memory(),))
    with pytest.raises(MemoryConflict):
        db._commit((replace(memory(), content="changed"),))
    assert db.load_all() == (memory(),)
    assert len(db.projection_queue().pending(10)) == 1
    db.close()


def test_atomic_canonical_and_outbox_on_sql_failure(tmp_path):
    path = tmp_path / "memory.sqlite"
    db = store(path)
    with sqlite3.connect(path) as fault:
        fault.execute(
            "CREATE TRIGGER fail_intent BEFORE INSERT ON projection_intents "
            "BEGIN SELECT RAISE(ABORT, 'crash between inserts'); END"
        )
    with pytest.raises(sqlite3.IntegrityError):
        db._commit((memory(),))
    db.close()


def test_second_intent_failure_rolls_back_entire_memory_batch(tmp_path):
    path = tmp_path / "memory.sqlite"
    db = store(path)
    first = memory()
    second = replace(
        first,
        memory_id="memory-2",
        sync=replace(first.sync, object_id="memory-2", idempotency_key="memory-2"),
    )
    with sqlite3.connect(path) as fault:
        fault.execute(
            "CREATE TRIGGER fail_second BEFORE INSERT ON projection_intents "
            "WHEN NEW.memory_id='memory-2' "
            "BEGIN SELECT RAISE(ABORT, 'second intent'); END"
        )
    with pytest.raises(sqlite3.IntegrityError):
        db._commit((first, second))
    assert db.load_all() == ()
    assert db.projection_queue().pending(10) == ()
    db.close()
    db = store(path)
    assert db.load_all() == ()
    assert db.projection_queue().pending(10) == ()
    db.close()


def test_memory_path_uses_binding_namespace(tmp_path, monkeypatch):
    from mind_runtime.runtime_binding import (
        RuntimeBinding,
        RuntimeEnvironment,
        bind_storage,
        production_binding,
    )

    monkeypatch.delenv("MR_STATE_DB", raising=False)
    monkeypatch.delenv("MR_FACTS_DB", raising=False)
    prod = bind_storage(
        production_binding("p"), production_root=tmp_path / "prod", lab_root=tmp_path / "lab"
    )
    lab = bind_storage(
        RuntimeBinding("p", "body", "lab", "experiment", RuntimeEnvironment.LAB),
        production_root=tmp_path / "prod",
        lab_root=tmp_path / "lab",
    )
    assert prod.memory_db == prod.root / "memory.sqlite"
    a, b = store(prod.memory_db), store(lab.memory_db)
    a._commit((memory(),))
    assert b.load_all() == ()
    a.close()
    b.close()
