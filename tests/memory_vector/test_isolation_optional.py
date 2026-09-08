import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from mind_runtime.memory.retrieval import MemoryRetrievalService
from mind_runtime.memory.store import CanonicalMemoryStore
from mind_runtime.runtime_binding import bind_storage, production_binding
from tests.host.test_runtime_binding import lab_binding
from tests.memory.test_contracts import memory
from tests.memory_retrieval.test_retrieval import query
from tests.memory_vector.test_contracts import identity
from tests.memory_vector.test_qdrant import FixtureEmbedding, plane, project


def test_missing_qdrant_package_is_distinct(tmp_path, monkeypatch):
    from mind_runtime.memory.providers.errors import ProviderPackageMissing
    from mind_runtime.memory.providers.qdrant import open_qdrant_index

    monkeypatch.setitem(sys.modules, "qdrant_client", None)
    with pytest.raises(ProviderPackageMissing):
        open_qdrant_index(lab_binding("absent"), embedding=FixtureEmbedding(), lab_root=tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_real_production_lab_and_embedding_revision_isolation(tmp_path, monkeypatch):
    from mind_runtime.memory.providers.qdrant import open_qdrant_index

    monkeypatch.delenv("MR_FACTS_DB", raising=False)
    monkeypatch.delenv("MR_STATE_DB", raising=False)
    roots = dict(production_root=tmp_path / "prod", lab_root=tmp_path / "lab")
    prod, lab = production_binding("fixture"), lab_binding("fixture")
    paths = bind_storage(prod, **roots)
    bind_storage(lab, **roots)
    store = CanonicalMemoryStore(paths.memory_db)
    store._commit((memory(),))
    before = store.load_all()
    a = open_qdrant_index(prod, embedding=FixtureEmbedding(), create=True, **roots)
    b = open_qdrant_index(lab, embedding=FixtureEmbedding(), create=True, **roots)
    project(store, a)
    assert b.retrieval().search(query()) == ()
    new_embedding = FixtureEmbedding()
    new_embedding.identity = identity(revision="next")
    revised = open_qdrant_index(prod, embedding=new_embedding, create=True, **roots)
    assert a.target != revised.target and revised.retrieval().search(query()) == ()
    assert project(store, revised) == (1, 0)
    revised.rebuild(store.projection_queue())
    assert a.retrieval().search(query())[0].memory_id == "memory-1"
    assert store.projection_queue().pending(100, target=a.target) == ()
    assert store.load_all() == before
    for index in (a, b, revised):
        index.close()
    store.close()


def test_canonical_scope_still_wins_if_provider_payload_is_forged(tmp_path):
    from mind_runtime.memory.store import scope_json

    other = replace(memory().scope, user_id="other")
    row = replace(memory(), scope=other, sync=replace(memory().sync, scope=other))
    store, index, _, _ = plane(tmp_path, rows=(row,))
    project(store, index)
    index._client.set_payload(
        index.collection, {"mr_scope": scope_json(memory().scope)}, [index.point_id(row.memory_id)]
    )
    assert index.retrieval().search(query())
    assert MemoryRetrievalService(store=store, provider=index.retrieval()).search(query()) == ()
    index.close()
    store.close()


def test_hard_process_death_after_real_upsert_retries_without_duplicate(tmp_path):
    from mind_runtime.memory.projection import ProjectionWorker
    from mind_runtime.memory.providers.qdrant import open_qdrant_index

    store, index, binding, _ = plane(tmp_path)
    target = index.target
    store.projection_queue().rebuild(target=target)
    index.close()
    code = """
import os, sys
from pathlib import Path
sys.path.insert(0, str(Path.cwd() / 'src'))
from tests.memory_vector.test_qdrant import FixtureEmbedding
from tests.host.test_runtime_binding import lab_binding
from mind_runtime.memory.providers.qdrant import open_qdrant_index
from mind_runtime.memory.store import CanonicalMemoryStore
from mind_runtime.memory.projection import ProjectionWorker
root = Path(sys.argv[1])
index = open_qdrant_index(lab_binding('one'), embedding=FixtureEmbedding(), lab_root=root/'lab')
db = CanonicalMemoryStore(root/'lab'/'one'/'memory.sqlite')
class CrashWriter:
    def upsert(self, memory, *, intent):
        index.writer().upsert(memory, intent=intent)
        os._exit(23)
ProjectionWorker(db.projection_queue(), CrashWriter(), target=index.target).run_once()
"""
    result = subprocess.run(
        [sys.executable, "-c", code, str(tmp_path)], capture_output=True, text=True
    )
    assert result.returncode == 23, result.stderr
    index = open_qdrant_index(binding, embedding=FixtureEmbedding(), lab_root=tmp_path / "lab")
    assert index._client.count(index.collection).count == 1
    assert store.projection_queue().pending(10, target=target)
    assert ProjectionWorker(store.projection_queue(), index.writer(), target=target).run_once() == (
        1,
        0,
    )
    assert index._client.count(index.collection).count == 1
    assert store.get("memory-1") == memory()
    index.close()
    store.close()


def test_stdlib_core_and_null_with_all_provider_packages_absent(tmp_path):
    source = Path(__file__).resolve().parents[2] / "src"
    metadata = tmp_path / "mind_runtime-0.0.0.dist-info"
    metadata.mkdir()
    (metadata / "METADATA").write_text("Name: mind-runtime\nVersion: 0.0.0\n")
    store = CanonicalMemoryStore(tmp_path / "memory.sqlite")
    store._commit((memory(),))
    store.close()
    code = """
import sys
sys.path[:0] = sys.argv[1:3]
from pathlib import Path
from mind_runtime.memory.providers.qdrant import open_qdrant_index
from mind_runtime.memory.providers.fastembed import FastEmbedEmbedding
from mind_runtime.memory.providers.errors import ProviderPackageMissing
from mind_runtime.memory.store import CanonicalMemoryStore
from mind_runtime.memory.admission import MemoryAdmissionService
from mind_runtime.memory.retrieval import MemoryRetrievalService, MemoryRetrievalQuery
from mind_runtime.memory.embedding import EmbeddingIdentity
from mind_runtime.runtime_binding import production_binding
db = CanonicalMemoryStore(Path(sys.argv[2])/'memory.sqlite', read_only=True)
m = db.get('memory-1')
assert m.content == 'hello'
assert MemoryRetrievalService(store=db).search(MemoryRetrievalQuery(m.scope,'hello')) == ()
try:
    open_qdrant_index(production_binding('fixture'), embedding=None)
except ProviderPackageMissing:
    pass
else:
    raise AssertionError('missing package must remain explicit')
db.close()
prefixes = ('qdrant_client','fastembed','mem0','onnxruntime')
assert not any(k.startswith(prefixes) for k in sys.modules)
"""
    result = subprocess.run(
        [sys.executable, "-S", "-c", code, str(source), str(tmp_path)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_wrong_runtime_queue_and_content_rejected_before_projection(tmp_path):
    from mind_runtime.memory.projection import ProjectionWorker

    a, ia, _, _ = plane(tmp_path, namespace="a", rows=())
    b, ib, _, _ = plane(tmp_path, namespace="b")
    before_b = b.projection_queue().pending(100)
    with pytest.raises(ValueError, match="Runtime"):
        ia.rebuild(b.projection_queue())
    with pytest.raises(ValueError, match="Runtime"):
        ProjectionWorker(b.projection_queue(), ia.writer(), target=ia.target)
    b.projection_queue().rebuild(target=ia.target)
    foreign = b.projection_queue().pending(100, target=ia.target)[0]
    with pytest.raises(ValueError, match="canonical"):
        ia.writer().upsert(memory(), intent=foreign)
    assert ia._client.count(ia.collection).count == 0
    assert all(intent in b.projection_queue().pending(100) for intent in before_b)
    for store, index in [(a, ia), (b, ib)]:
        index.close()
        store.close()


def test_rebuild_durably_enqueues_before_destructive_step(tmp_path, monkeypatch):
    from mind_runtime.memory.projection import ProjectionWorker

    store, index, _, _ = plane(tmp_path)
    project(store, index)
    before = store.load_all()
    create = index._create
    monkeypatch.setattr(index, "_create", lambda: (_ for _ in ()).throw(OSError("crash")))
    with pytest.raises(OSError):
        index.rebuild(store.projection_queue())
    assert store.projection_queue().pending(100, target=index.target)
    monkeypatch.setattr(index, "_create", create)
    assert ProjectionWorker(
        store.projection_queue(), index.writer(), target=index.target
    ).run_once() == (1, 0)
    assert index.retrieval().search(query())[0].memory_id == "memory-1"
    assert store.load_all() == before
    index.close()
    store.close()


def test_failed_local_rebuild_reset_leaves_provider_untouched(tmp_path, monkeypatch):
    store, index, _, _ = plane(tmp_path)
    project(store, index)
    queue = store.projection_queue()
    monkeypatch.setattr(queue, "rebuild", lambda **kwargs: (_ for _ in ()).throw(OSError("db")))
    with pytest.raises(OSError):
        index.rebuild(queue)
    assert index.retrieval().search(query())[0].memory_id == "memory-1"
    assert store.get("memory-1") == memory()
    index.close()
    store.close()
