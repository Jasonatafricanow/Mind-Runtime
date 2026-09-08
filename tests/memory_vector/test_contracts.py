import pytest

from mind_runtime.memory.projection import ProjectionWorker
from mind_runtime.memory.store import CanonicalMemoryStore
from tests.memory.test_contracts import memory


def identity(**changes):
    from mind_runtime.memory.embedding import EmbeddingIdentity

    return EmbeddingIdentity(
        **(dict(provider="test", model_id="fixture", dimension=3, revision="1") | changes)
    )


@pytest.mark.parametrize(
    "changes",
    [{"provider": ""}, {"model_id": " "}, {"dimension": True}, {"dimension": 0}, {"revision": ""}],
)
def test_invalid_embedding_identity(changes):
    with pytest.raises(ValueError):
        identity(**changes)


@pytest.mark.parametrize(
    "vector", [[1, 2], [0, 0, 0], [float("nan"), 1, 0], [float("inf"), 0, 1], [True, 0, 1]]
)
def test_invalid_embedding_vectors(vector):
    from mind_runtime.memory.embedding import validate_vector

    with pytest.raises(ValueError):
        validate_vector(vector, identity())


def test_embedding_target_is_stable_but_model_revision_independent_of_memory():
    from mind_runtime.memory.embedding import projection_target

    original = memory()
    assert projection_target(identity()) == projection_target(identity())
    assert projection_target(identity(revision="2")) != projection_target(identity())
    assert original == memory()


def test_worker_selects_target_before_limit_and_rebuild_preserves_other_targets(tmp_path):
    db = CanonicalMemoryStore(tmp_path / "memory.sqlite")
    db._commit((memory(),))
    queue = db.projection_queue()
    queue.rebuild(target="a")
    queue.rebuild(target="b")
    original = db.load_all()

    class Writer:
        def upsert(self, memory, *, intent):
            assert intent.target == "a"
            return "provider-point"

    worker = ProjectionWorker(queue, Writer(), target="a")
    assert worker.run_once(limit=1) == (1, 0)
    assert queue.pending(1, target="a") == ()
    untouched = queue.pending(100, target="b")
    assert queue.rebuild(target="a") == 0
    assert queue.rebuild(target="a", reset=True) == 1
    assert queue.pending(1, target="a")[0].provider_ref is None
    assert queue.pending(100, target="b") == untouched
    assert db.load_all() == original
    db.close()
