from dataclasses import replace

import pytest

from mind_runtime.memory.projection import ProjectionWorker
from mind_runtime.memory.retrieval import MemoryRetrievalService, RetrievalProviderUnavailable
from mind_runtime.memory.store import CanonicalMemoryStore
from mind_runtime.runtime_binding import bind_storage
from tests.host.test_runtime_binding import lab_binding
from tests.memory.test_contracts import memory
from tests.memory_retrieval.test_retrieval import query
from tests.memory_vector.test_contracts import identity


class FixtureEmbedding:
    identity = identity()

    def embed(self, text):
        return (1.0, 0.0, 0.1)


def plane(tmp_path, *, namespace="one", embedding=None, rows=None):
    from mind_runtime.memory.providers.qdrant import open_qdrant_index

    binding = lab_binding(namespace)
    paths = bind_storage(binding, lab_root=tmp_path / "lab")
    store = CanonicalMemoryStore(paths.memory_db)
    store._commit((memory(),) if rows is None else rows)
    index = open_qdrant_index(
        binding, embedding=embedding or FixtureEmbedding(), create=True, lab_root=tmp_path / "lab"
    )
    return store, index, binding, paths


def project(store, index):
    queue = store.projection_queue()
    queue.rebuild(target=index.target)
    return ProjectionWorker(queue, index.writer(), target=index.target).run_once()


def test_real_qdrant_upsert_restart_uuid_and_native_vector_access(tmp_path):
    from mind_runtime.memory.providers.qdrant import open_qdrant_index

    store, index, binding, paths = plane(tmp_path)
    assert paths.semantic_index_root == paths.root / "semantic_index"
    assert project(store, index) == (1, 0)
    hits = index.retrieval().search(query())
    assert hits[0].memory_id == "memory-1"
    assert hits[0].provider_ref != hits[0].memory_id
    # Native bounded vector access is a Lab proof, not a production LCE API.
    points = index._client.retrieve(index.collection, [hits[0].provider_ref], with_vectors=True)
    assert points[0].payload["mr_memory_id"] == "memory-1"
    assert len(points[0].vector) == 3
    assert index._client.count(index.collection).count == 1
    original = store.load_all()
    index.close()
    store.close()
    store = CanonicalMemoryStore(paths.memory_db)
    index = open_qdrant_index(binding, embedding=FixtureEmbedding(), lab_root=tmp_path / "lab")
    restarted = index.retrieval().search(query())
    assert replace(restarted[0], score=None) == replace(hits[0], score=None)
    assert restarted[0].score == pytest.approx(hits[0].score)
    assert store.projection_queue().pending(10, target=index.target) == ()
    for _ in range(5):
        assert (
            MemoryRetrievalService(store=store, provider=index.retrieval())
            .search(query())[0]
            .memory
            == memory()
        )
    assert store.load_all() == original
    index.close()
    store.close()


def test_remote_success_local_completion_failure_retries_one_point(tmp_path, monkeypatch):
    store, index, _, _ = plane(tmp_path)
    queue = store.projection_queue()
    queue.rebuild(target=index.target)
    worker = ProjectionWorker(queue, index.writer(), target=index.target)
    succeed = queue.succeed
    monkeypatch.setattr(queue, "succeed", lambda *args: (_ for _ in ()).throw(OSError("crash")))
    assert worker.run_once() == (0, 1)
    assert index._client.count(index.collection).count == 1
    monkeypatch.setattr(queue, "succeed", succeed)
    assert worker.run_once() == (1, 0)
    assert index._client.count(index.collection).count == 1
    assert store.get("memory-1") == memory()
    index.close()
    store.close()


def test_provider_text_scope_and_malformed_identity_cannot_surface(tmp_path):
    store, index, _, _ = plane(tmp_path)
    project(store, index)
    hit = index.retrieval().search(query())[0]
    index._client.set_payload(index.collection, {"text": "provider lie"}, [hit.provider_ref])
    reader = MemoryRetrievalService(store=store, provider=index.retrieval())
    assert reader.search(query())[0].memory.content == "hello"
    for payload in (
        {"mr_memory_id": ""},
        {"mr_memory_id": 42},
        {"mr_memory_id": "unknown"},
        {"mr_namespace": "other"},
        {"mr_scope": "other"},
    ):
        original = index._client.retrieve(index.collection, [hit.provider_ref])[0].payload
        index._client.set_payload(index.collection, payload, [hit.provider_ref])
        assert reader.search(query()) == ()
        index._client.overwrite_payload(index.collection, original, [hit.provider_ref])
    index.close()
    store.close()


def test_namespace_scope_and_embedding_revision_isolation(tmp_path):
    a, ia, _, _ = plane(tmp_path, namespace="a")
    b, ib, _, _ = plane(tmp_path, namespace="b", rows=())
    project(a, ia)
    assert ib.retrieval().search(query()) == ()
    assert ia.retrieval().search(query(scope=replace(memory().scope, user_id="other"))) == ()
    assert project(b, ib) == (0, 0)
    for store, index in [(a, ia), (b, ib)]:
        index.close()
        store.close()


def test_wipe_rebuild_keeps_canonical_and_other_target(tmp_path):
    store, index, _, _ = plane(tmp_path)
    project(store, index)
    before = store.load_all()
    index.wipe()
    with pytest.raises(RetrievalProviderUnavailable):
        index.retrieval().search(query())
    index._create()
    assert index._client.count(index.collection).count == 0
    assert index.retrieval().search(query()) == ()
    assert store.load_all() == before
    assert index.rebuild(store.projection_queue()) == 1
    assert project(store, index) == (1, 0)
    assert index.retrieval().search(query())[0].memory_id == "memory-1"
    assert store.load_all() == before
    index.close()
    store.close()


def test_enabled_missing_index_never_created_by_read(tmp_path):
    from mind_runtime.memory.providers.qdrant import open_qdrant_index

    binding = lab_binding("missing")
    paths = bind_storage(binding, lab_root=tmp_path / "lab")
    with pytest.raises(RetrievalProviderUnavailable):
        open_qdrant_index(binding, embedding=FixtureEmbedding(), lab_root=tmp_path / "lab")
    assert not paths.semantic_index_root.exists()


def test_wrong_target_and_collection_identity_fail_closed(tmp_path):
    store, index, _, _ = plane(tmp_path)
    queue = store.projection_queue()
    intent = queue.pending(1)[0]
    with pytest.raises(ValueError):
        index.writer().upsert(memory(), intent=intent)
    assert index._client.count(index.collection).count == 0
    index._client.update_collection(index.collection, metadata={"mr_namespace": "wrong"})
    with pytest.raises(RetrievalProviderUnavailable):
        index.retrieval().search(query())
    assert store.load_all() == (memory(),)
    index.close()
    store.close()
