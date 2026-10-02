import hashlib
import json
import sqlite3

import pytest
from historical.rebuild import HistoricalRebuild
from historical.tests.test_agy import delta


class Worker:
    def __init__(self):
        self.calls = 0

    def compile(self, context):
        self.calls += 1
        return json.dumps(
            delta(
                "用户选择 A。" if context.current.content == "A" else "无法唯一消解引用。",
                status="resolved" if context.current.content == "A" else "defer",
                refs=() if context.current.content == "A" else ("不是",),
            )
        )


def test_fresh_rebuild_resume_counts_raw_and_bitemporal_authority(native, tmp_path):
    path, _, sources = native
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    worker, root = Worker(), tmp_path / "rebuild"
    with HistoricalRebuild(root, sources=sources, worker=worker) as rebuild:
        state = rebuild.run(limit=2)
        memory = rebuild.memory.load_all()[0]
        assert memory.occurred_at.timestamp() == 11
        assert memory.known_at > memory.occurred_at
        assert memory.provenance.source_refs == (tuple(sources.iterate())[1].source_ref,)
        assert state["compile_count"] == 1
        with pytest.raises(RuntimeError, match="another historical worker"):
            HistoricalRebuild(root, sources=sources, worker=worker, resume=True)
    with HistoricalRebuild(root, sources=sources, worker=worker, resume=True) as resumed:
        state = resumed.run()
        assert len(resumed.memory.load_all()) == 1
        assert (
            state["compile_count"],
            state["ignore_count"],
            state["context_count"],
            state["defer_count"],
        ) == (2, 3, 2, 1)
        assert state["last_ordering_key"] == [16, 8]
        assert resumed.memory.get(memory.memory_id) == memory
        resumed.run()
        assert worker.calls == 2
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before
    with pytest.raises(FileExistsError):
        HistoricalRebuild(root, sources=sources, worker=worker)


def test_receipt_recovery_never_recompiles_after_admission(native, tmp_path, monkeypatch):
    _, _, sources = native
    worker, root = Worker(), tmp_path / "crash-rebuild"
    with HistoricalRebuild(root, sources=sources, worker=worker) as rebuild:
        rebuild.run(limit=1)
        original = rebuild.admission.admit_semantic_delta

        def crash(*args, **kwargs):
            original(*args, **kwargs)
            raise RuntimeError("crash after canonical commit before cursor")

        monkeypatch.setattr(rebuild.admission, "admit_semantic_delta", crash)
        with pytest.raises(RuntimeError, match="crash after"):
            rebuild.run(limit=1)
        memory = rebuild.memory.load_all()[0]
        assert rebuild.state["failure_ref"] is not None
    with HistoricalRebuild(root, sources=sources, worker=worker, resume=True) as resumed:
        resumed.run(limit=1)
        assert worker.calls == 1
        assert resumed.memory.load_all() == (memory,)
        assert resumed.state["compile_count"] == 1
        assert resumed.state["failure_ref"] is None


def test_invalid_delta_and_source_drift_have_no_partial_writes(native, tmp_path):
    path, _, sources = native

    class InvalidWorker:
        def compile(self, _):
            return json.dumps(delta(status="INVALID"))

    root = tmp_path / "invalid-rebuild"
    with HistoricalRebuild(root, sources=sources, worker=InvalidWorker()) as rebuild:
        with pytest.raises(ValueError):
            rebuild.run()
        assert rebuild.memory.load_all() == ()
        assert rebuild.state["pending"]["payload"] is not None

    class DriftWorker:
        def compile(self, _):
            with sqlite3.connect(path) as db:
                db.execute("UPDATE messages SET content='changed' WHERE id=2")
            return json.dumps(delta())

    drift_root = tmp_path / "drift-rebuild"
    with HistoricalRebuild(drift_root, sources=sources, worker=DriftWorker()) as rebuild:
        with pytest.raises(ValueError, match="stale"):
            rebuild.run()
        assert rebuild.memory.load_all() == ()
    with pytest.raises(ValueError, match="authority"):
        HistoricalRebuild(drift_root, sources=sources, worker=Worker(), resume=True)


def test_partial_update_shared_validator_closure_and_canonical_lifecycle(
    native, tmp_path, monkeypatch
):
    import mr_mem.memory.semantic_admission as authority

    path, _, sources = native
    with sqlite3.connect(path) as db:
        db.execute("UPDATE messages SET content='预算80万，车型SUV，地点北京。' WHERE id=2")
        db.execute(
            "INSERT INTO messages(id,session_id,role,content,timestamp,record_type) "
            "VALUES(9,'s','user','地点改上海，其他不变。',17,'user')"
        )
    calls = {"validator": 0, "closure": 0}
    validator, closure = authority.validate_semantic_delta, authority.compile_semantic_delta

    def validate(*args, **kwargs):
        calls["validator"] += 1
        return validator(*args, **kwargs)

    def compile_blocks(*args, **kwargs):
        calls["closure"] += 1
        return closure(*args, **kwargs)

    monkeypatch.setattr(authority, "validate_semantic_delta", validate)
    monkeypatch.setattr(authority, "compile_semantic_delta", compile_blocks)

    class PartialWorker:
        def compile(self, context):
            payload = delta("地点上海。")
            if context.current.source_ref.record_id == "2":
                payload["points"] = [
                    dict(delta(text)["points"][0], point_id=f"p{i}")
                    for i, text in enumerate(("预算80万。", "车型SUV。", "地点北京。"))
                ]
            elif context.current.source_ref.record_id == "5":
                payload = delta(status="defer", refs=("不是",))
            else:
                payload["dependencies"] = [
                    {
                        "from_point_id": "p1",
                        "target_kind": "memory",
                        "target_id": context.activated_memory_ids[0],
                        "relation": "correction",
                        "boundary_policy": "context",
                        "lifecycle_effect": "supersede",
                    }
                ]
            return json.dumps(payload)

    def selection(source, rebuild):
        if source.source_ref.record_id == "9":
            old = next(m for m in rebuild.memory.load_all() if m.content == "地点北京。")
            return {"activated_memory_ids": (old.memory_id,)}
        return {}

    with HistoricalRebuild(
        tmp_path / "partial", sources=sources, worker=PartialWorker()
    ) as rebuild:
        rebuild.run(selection=selection)
        memories = rebuild.memory.load_all()
        assert len(memories) == 4
        states = {m.content: m.lifecycle.value for m in memories}
        assert states == {
            "预算80万。": "active",
            "车型SUV。": "active",
            "地点北京。": "superseded",
            "地点上海。": "active",
        }
        new = next(m for m in memories if m.content == "地点上海。")
        old = next(m for m in memories if m.content == "地点北京。")
        assert rebuild.memory.get_semantic_metadata(new.memory_id).context_memory_ids == (
            old.memory_id,
        )
        assert rebuild.memory.semantic_relations(new.memory_id)
        assert new.provenance.source_refs[0].record_id == "9"
        assert calls == {"validator": 3, "closure": 3}


def test_resume_rejects_foreign_canonical_db_before_writer(native, tmp_path):
    from historical.rebuild import RebuildClock
    from mr_mem.memory.core import MemoryCore
    from mr_mem.memory.semantic_store import SemanticSourceBinding

    _, scope, sources = native
    root = tmp_path / "owned"
    with HistoricalRebuild(root, sources=sources, worker=Worker()) as rebuild:
        target = rebuild.db_path
    source = tuple(sources.iterate())[1]
    sources.bind(source)
    foreign_path = tmp_path / "foreign-canonical.sqlite"
    with MemoryCore(foreign_path) as foreign:
        foreign.semantic_admission(
            sources=sources, clock=RebuildClock(), origin_runtime_id="production-fixture"
        ).admit_semantic_delta(
            delta(),
            binding=SemanticSourceBinding(scope, source.interaction_id, source.source_ref),
            activated_memory_ids=(),
        )
    target.write_bytes(foreign_path.read_bytes())
    before = hashlib.sha256(target.read_bytes()).hexdigest()
    with pytest.raises(ValueError, match="not owned"):
        HistoricalRebuild(root, sources=sources, worker=Worker(), resume=True)
    assert hashlib.sha256(target.read_bytes()).hexdigest() == before
