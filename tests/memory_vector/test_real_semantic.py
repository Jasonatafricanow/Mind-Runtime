"""Required local integration: provision the documented model fixture before running."""

import os
from dataclasses import replace
from pathlib import Path

import pytest

from mind_runtime.memory.embedding import EmbeddingIdentity
from mind_runtime.memory.projection import ProjectionWorker
from mind_runtime.memory.providers.fastembed import FastEmbedEmbedding, model_revision
from mind_runtime.memory.retrieval import MemoryRetrievalService
from tests.memory.test_contracts import memory
from tests.memory_retrieval.test_retrieval import query
from tests.memory_vector.test_qdrant import plane, project


@pytest.fixture(scope="module")
def semantic_embedding():
    pytest.importorskip("fastembed")
    directory = os.environ.get("MR_VECTOR_TEST_MODEL_DIR")
    if not directory:
        pytest.skip("Provision the local fixture; set MR_VECTOR_TEST_MODEL_DIR (see provider report)")
    path = Path(directory)
    if not path.exists():
        pytest.skip(f"MR_VECTOR_TEST_MODEL_DIR path {directory!r} does not exist")
    return FastEmbedEmbedding(
        EmbeddingIdentity(
            "fastembed",
            "BAAI/bge-small-en-v1.5",
            384,
            model_revision(path),
        ),
        model_dir=path,
    )


def memories():
    texts = [
        "A physician prescribed antibiotics for a bacterial infection.",
        "The violinist rehearsed a sonata for tonight's concert.",
        "The farmer harvested ripe tomatoes from the greenhouse.",
    ]
    return tuple(
        replace(
            memory(),
            memory_id=f"memory-{i}",
            content=text,
            sync=replace(memory().sync, object_id=f"memory-{i}"),
        )
        for i, text in enumerate(texts, 1)
    )


def test_real_pretrained_embedding_canonical_roundtrip_and_rebuild(tmp_path, semantic_embedding):
    store, index, _, _ = plane(tmp_path, embedding=semantic_embedding, rows=memories())
    before = store.load_all()
    assert project(store, index) == (3, 0)
    search = query(text="What medicine treats an illness caused by germs?", limit=3)
    reader = MemoryRetrievalService(store=store, provider=index.retrieval())
    results = reader.search(search)
    assert results[0].memory.memory_id == "memory-1"
    assert results[0].memory.content == memories()[0].content
    print("semantic ranking", [(r.memory.memory_id, r.candidate.score) for r in results])
    ids = [r.candidate.provider_ref for r in results[:2]]
    records = index._client.retrieve(index.collection, ids, with_vectors=True)
    assert len(records) == 2 and all(len(r.vector) == 384 for r in records)
    neighbors = index._client.query_points(index.collection, query=ids[0], limit=2).points
    # Native point-ID queries exclude the query point itself.
    assert len(neighbors) == 2 and ids[0] not in {str(p.id) for p in neighbors}
    vector_query = index._client.query_points(index.collection, query=records[0].vector, limit=1)
    assert str(vector_query.points[0].id) == str(records[0].id)
    for _ in range(5):
        assert reader.search(search)[0].memory.memory_id == "memory-1"
    assert store.load_all() == before
    assert index.rebuild(store.projection_queue()) == 3
    assert ProjectionWorker(
        store.projection_queue(), index.writer(), target=index.target
    ).run_once() == (3, 0)
    assert reader.search(search)[0].memory.memory_id == "memory-1"
    assert store.load_all() == before
    index.close()
    store.close()


def test_real_embedding_is_stable_and_semantic(semantic_embedding):
    import math

    a = semantic_embedding.embed("A canine is resting beside its owner.")
    b = semantic_embedding.embed("The dog sleeps next to its human.")
    c = semantic_embedding.embed("The stock exchange closed after a volatile trading session.")
    assert len(a) == 384 and a == semantic_embedding.embed("A canine is resting beside its owner.")
    def cosine(x, y):
        return sum(i * j for i, j in zip(x, y, strict=True)) / (math.hypot(*x) * math.hypot(*y))
    assert cosine(a, b) > cosine(a, c)
