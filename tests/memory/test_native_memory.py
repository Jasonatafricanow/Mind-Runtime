import sqlite3
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from mr_mem import MemoryCore, Scope, ScopeDomain

pytest.importorskip("lce")

from mind_runtime.integrations.historical_compiler import SCHEMA_VERSION
from mind_runtime.integrations.native_history import HermesSourceStore
from mind_runtime.integrations.native_memory import NativeMemoryRuntime
from mind_runtime.memory.retrieval import MemorySurfaceBudget
from mind_runtime.memory.retrieval_composition import build_memory_history
from tests.host.test_runtime_binding import lab_binding
from tests.memory_retrieval.test_history import inputs

SCOPE = Scope(ScopeDomain.USER, user_id="user")
NOW = datetime(2026, 10, 2, tzinfo=UTC)


class Clock:
    def now(self):
        return NOW


class Cleaner:
    def __init__(self):
        self.calls = 0

    def compile(self, fragments, *, context):
        self.calls += 1
        return {
            "schema_version": SCHEMA_VERSION,
            "fragments": [
                {
                    "fragment_id": fragment.fragment_id,
                    "disposition": "KEEP",
                    "reason": "reviewed fixture: enduring financing progress",
                    "content": "Down payment is planned."
                    if fragment.ref.record_id == "2"
                    else "Loan is pending.",
                    "attributes": {
                        "subject": "user",
                        "holder": "user",
                        "polarity": "positive",
                        "modality": "asserted",
                        "temporal_scope": "source-time",
                        "kind": "plan",
                        "thread_action": "track",
                        "thread_question": "Will home financing complete?",
                        "thread_summary": "Down payment planned; loan pending.",
                    },
                }
                for fragment in fragments
            ],
        }


def setup(tmp_path):
    path = tmp_path / "native.sqlite"
    with sqlite3.connect(path) as db:
        db.executescript("""
            CREATE TABLE sessions(id TEXT, user_id TEXT);
            CREATE TABLE messages(id INTEGER, session_id TEXT, role TEXT, content TEXT,
                timestamp REAL, tool_calls TEXT, active INTEGER, compacted INTEGER);
            INSERT INTO sessions VALUES ('session-1','native-user');
            INSERT INTO messages VALUES
              (1,'session-1','tool','RAW-NOISE stdout',100,NULL,1,0),
              (2,'session-1','user','RAW-PRIVATE down payment plan',101,NULL,1,0),
              (3,'session-1','user','RAW-PRIVATE loan approval pending',102,NULL,1,0);
        """)
    source = HermesSourceStore(path, scope=SCOPE, source_namespace="native", user_id="native-user")
    return path, source, Cleaner()


def runtime(tmp_path, core, source, cleaner, **kwargs):
    return NativeMemoryRuntime(
        root=tmp_path / "bound-runtime",
        core=core,
        scope=SCOPE,
        sources=source,
        cleaner=cleaner,
        clock=Clock(),
        origin_runtime_id="runtime-1",
        compiler_version="fixture-v1",
        block_embedder=lambda block: (1.0, 0.0),
        embedding_version="fixture-vector-v1",
        **kwargs,
    )


def context_inputs():
    query = inputs()
    query["clock"] = NOW + timedelta(seconds=1)
    query["observations"] = (replace(query["observations"][0], value={"text": "loan financing"}),)
    return query


def test_native_hot_start_normal_turn_and_next_context_share_one_semantic_chain(tmp_path):
    native_path, source, cleaner = setup(tmp_path)
    native_bytes = native_path.read_bytes()
    core = MemoryCore(tmp_path / "semantic.sqlite")
    session = runtime(tmp_path, core, source, cleaner)
    assert session.warm_start(source, limit=2) == 2
    assert len(core.products.list_threads(SCOPE)) == 1
    next_record = source.read(after=(101.0, 2))[0]
    session.process(next_record)  # same API for a normal, already-native-committed turn
    assert cleaner.calls == 2
    assert core.products.list_threads(SCOPE) == ()
    assert len(session.projection.query(None)) == 1
    binding = lab_binding("native-history")
    port = build_memory_history(binding, native_history=session)
    assert port is session
    with pytest.raises(ValueError, match="legacy"):
        build_memory_history(binding, native_history=session, thread_enabled=True)
    bundle = port.read(**context_inputs())
    assert any(item.kind == "lce.accepted_understanding" for item in bundle.episodes)
    assert all("RAW-" not in item.proposition for item in bundle.episodes)
    assert bundle.source_refs
    session.close()
    core.close()
    core = MemoryCore(tmp_path / "semantic.sqlite")
    session = runtime(tmp_path, core, source, cleaner)
    assert session.warm_start(source) == 1  # receipt reuses the already-consumed normal turn
    assert session.warm_start(source) == 0
    assert cleaner.calls == 2
    assert len(core.load_all()) == 2
    assert core.products.list_threads(SCOPE) == ()
    assert len(session.projection.query(None)) == 1
    assert session.read(**context_inputs()) == bundle
    assert native_path.read_bytes() == native_bytes
    assert b"RAW-PRIVATE" not in (tmp_path / "semantic.sqlite").read_bytes()
    assert b"RAW-PRIVATE" not in (tmp_path / "bound-runtime" / "receipts.sqlite").read_bytes()
    session.close()
    core.close()
    source.close()


def test_receipt_catchup_resumes_failed_lce_without_semantic_reinference(tmp_path, monkeypatch):
    _, source, cleaner = setup(tmp_path)
    core = MemoryCore(tmp_path / "semantic.sqlite")
    session = runtime(tmp_path, core, source, cleaner)

    def fail(*args, **kwargs):
        raise RuntimeError("projection failed")

    monkeypatch.setattr(session.projection, "process_semantic", fail)
    with pytest.raises(RuntimeError, match="projection failed"):
        session.warm_start(source)
    assert cleaner.calls == 1
    assert len(core.load_all()) == 1
    session.close()
    core.close()
    core = MemoryCore(tmp_path / "semantic.sqlite")
    session = runtime(tmp_path, core, source, cleaner)
    assert session.warm_start(source) == 2
    assert cleaner.calls == 2
    assert len(core.load_all()) == 2
    assert len(session.projection.query(None)) == 1
    session.close()
    core.close()
    source.close()


def test_edit_invalidates_retrieval_and_projection_without_native_raw_write(tmp_path):
    native_path, source, cleaner = setup(tmp_path)
    core = MemoryCore(tmp_path / "semantic.sqlite")
    session = runtime(tmp_path, core, source, cleaner)
    session.warm_start(source)
    block = session.substrate.list_semantic_blocks()[0]
    with pytest.raises(KeyError, match="canonical"):
        session.substrate.put_semantic_block(replace(block, content="invented interpretation"))
    with sqlite3.connect(native_path) as db:
        db.execute("UPDATE messages SET content='revised native event' WHERE id=2")
    assert (
        session.projection.query(None) == ()
    )  # immediate fresh-source check, before reconciliation
    assert len(session.reconcile_sources()) == 1
    assert session.reconcile_sources() == ()
    assert len(session.substrate.list_semantic_blocks(current_valid_only=False)) == 2
    assert len(session.substrate.list_semantic_blocks()) == 1
    assert len(session.read(**context_inputs()).episodes) == 1
    assert session.read(**{**context_inputs(), "clock": NOW}) is None
    assert (
        session.read(**{**context_inputs(), "scope": replace(inputs()["scope"], user_id="other")})
        is None
    )
    session.close()
    core.close()
    source.close()


def test_root_binding_and_whole_item_budget_fail_closed(tmp_path):
    _, source, cleaner = setup(tmp_path)
    core = MemoryCore(tmp_path / "semantic.sqlite")
    session = runtime(tmp_path, core, source, cleaner, budget=MemorySurfaceBudget(5, 1))
    session.warm_start(source)
    assert session.read(**context_inputs()) is None
    session.close()
    other = MemoryCore(tmp_path / "other-semantic.sqlite")
    with pytest.raises(ValueError, match="binding mismatch"):
        runtime(tmp_path, other, source, cleaner)
    other.close()
    core.close()
    source.close()


def test_native_deletion_keeps_history_but_removes_current_derived_context(tmp_path):
    native_path, source, cleaner = setup(tmp_path)
    core = MemoryCore(tmp_path / "semantic.sqlite")
    session = runtime(tmp_path, core, source, cleaner)
    session.warm_start(source)
    region = session.projection.query(None)[0].region_id
    history = session.projection.baselines.get_history(region)
    with sqlite3.connect(native_path) as db:
        db.execute("UPDATE messages SET active=0,compacted=0 WHERE id=2")
    assert session.projection.query(None) == ()
    assert len(session.reconcile_sources()) == 1
    assert session.projection.baselines.get_history(region) == history
    assert len(core.load_all()) == 2
    assert len(session.substrate.list_semantic_blocks()) == 1
    assert len(session.substrate.list_semantic_blocks(current_valid_only=False)) == 2
    assert cleaner.calls == 2
    session.close()
    core.close()
    source.close()


def test_rejected_derived_understanding_is_not_returned_as_next_turn_context(tmp_path):
    _, source, cleaner = setup(tmp_path)
    core = MemoryCore(tmp_path / "semantic.sqlite")
    session = runtime(tmp_path, core, source, cleaner)
    session.warm_start(source)
    view = session.projection.query(None)[0]
    session.projection.reject_current_understanding(
        view.region_id,
        authority_ref="explicit-user-rejection",
    )
    bundle = session.read(**context_inputs())
    assert bundle is not None
    assert not any(item.kind == "lce.accepted_understanding" for item in bundle.episodes)
    assert all(item.kind == "memory.canonical" for item in bundle.episodes)
    assert session.projection.rejections.list()[0].active
    assert len(core.load_all()) == 2
    session.close()
    core.close()
    source.close()
