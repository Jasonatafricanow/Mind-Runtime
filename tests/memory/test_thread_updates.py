from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from mind_runtime.contracts import Scope, ScopeDomain, SyncFields
from mind_runtime.memory.contracts import CommittedMemory, MemoryProvenance
from mind_runtime.memory.product import MemoryProductStore, ThreadStatus
from mind_runtime.memory.store import CanonicalMemoryStore
from mind_runtime.memory.thread_updates import (
    DeterministicThreadUpdater,
    ThreadUpdateWorker,
)


BASE = datetime(2026, 9, 25, 8, 0, tzinfo=UTC)
SCOPE = Scope(ScopeDomain.USER, user_id="u")


def memory(memory_id: str, content: str, offset: int = 0) -> CommittedMemory:
    evidence_id = f"e-{memory_id}"
    observation_id = f"o-{memory_id}"
    return CommittedMemory(
        memory_id=memory_id,
        scope=SCOPE,
        content=content,
        provenance=MemoryProvenance((evidence_id,), observation_id, "text-v1"),
        origin_runtime_id="runtime-1",
        committed_at=BASE + timedelta(minutes=offset),
        sync=SyncFields(SCOPE, "runtime-1", memory_id, 1, memory_id),
    )


def plane(tmp_path):
    path = tmp_path / "memory.sqlite"
    canonical = CanonicalMemoryStore(path)
    product = MemoryProductStore(path, canonical)
    worker = ThreadUpdateWorker(
        canonical.thread_update_queue(),
        DeterministicThreadUpdater(product=product),
    )
    return canonical, product, worker


def commit_and_run(canonical, worker, item):
    canonical._commit((item,))
    assert worker.run_once(limit=32) == (1, 0)


def test_canonical_commit_durably_enqueues_thread_update(tmp_path):
    canonical, product, _ = plane(tmp_path)
    item = memory("m1", "I am considering replacing my computer.")
    canonical._commit((item,))

    pending = canonical.thread_update_queue().pending()
    assert len(pending) == 1
    assert pending[0].memory_id == "m1"
    assert pending[0].attempts == 0

    product.close()
    canonical.close()


def test_explicit_unfinished_line_opens_and_related_memory_updates_same_thread(tmp_path):
    canonical, product, worker = plane(tmp_path)
    first = memory("m1", "I am considering replacing my computer because it is old.")
    commit_and_run(canonical, worker, first)

    threads = product.surface_threads(SCOPE, now=BASE, limit=10, decay_lambda=0.0)
    assert len(threads) == 1
    thread = threads[0]
    assert thread.origin_memory_ids == ("m1",)
    assert thread.current_support_ids == ("m1",)
    assert thread.mature is False
    assert thread.working_summary is None

    second = memory("m2", "The computer is getting slower lately.", 1)
    commit_and_run(canonical, worker, second)

    updated = product.get_thread(thread.thread_id)
    assert updated is not None
    assert updated.current_support_ids == ("m1", "m2")
    assert updated.touch_count == 1
    assert updated.mature is False
    assert updated.working_summary is None

    product.close()
    canonical.close()


def test_unrelated_memory_does_not_pollute_existing_thread(tmp_path):
    canonical, product, worker = plane(tmp_path)
    commit_and_run(
        canonical,
        worker,
        memory("m1", "I am considering replacing my computer because it is old."),
    )
    original = product.surface_threads(SCOPE, now=BASE, limit=10, decay_lambda=0.0)[0]

    commit_and_run(canonical, worker, memory("m2", "The weather is warm today.", 1))
    current = product.get_thread(original.thread_id)
    assert current == original
    assert len(product.surface_threads(SCOPE, now=BASE, limit=10, decay_lambda=0.0)) == 1

    product.close()
    canonical.close()


def test_explicit_resolution_closes_the_only_matching_open_line(tmp_path):
    canonical, product, worker = plane(tmp_path)
    commit_and_run(
        canonical,
        worker,
        memory("m1", "I am considering replacing my computer because it is old."),
    )
    thread = product.surface_threads(SCOPE, now=BASE, limit=10, decay_lambda=0.0)[0]

    # The close statement may omit the topic. This fallback is allowed only
    # when exactly one open line exists in the Scope.
    commit_and_run(canonical, worker, memory("m2", "算了，不买了。", 1))

    resolved = product.get_thread(thread.thread_id)
    assert resolved is not None
    assert resolved.status is ThreadStatus.RESOLVED
    assert resolved.current_support_ids == ("m1", "m2")
    assert product.surface_threads(SCOPE, now=BASE + timedelta(minutes=2)) == ()

    product.close()
    canonical.close()


def test_short_term_state_does_not_become_medium_term_thread(tmp_path):
    canonical, product, worker = plane(tmp_path)
    commit_and_run(canonical, worker, memory("m1", "我今晚准备吃饭。"))

    assert product.surface_threads(SCOPE, now=BASE, limit=10) == ()

    product.close()
    canonical.close()


def test_ambiguous_overlap_does_not_attach_to_one_of_two_threads(tmp_path):
    canonical, product, worker = plane(tmp_path)
    first = memory("m1", "I am considering buying a computer for work.")
    second = memory("m2", "I am considering buying a computer for travel.", 1)
    # Open two independent lines explicitly; the automatic matcher must not
    # choose arbitrarily when a later item overlaps both equally.
    canonical._commit((first, second))
    product.open_thread(
        thread_id="work",
        scope=SCOPE,
        open_question=first.content,
        supporting_memory_ids=("m1",),
        at=first.committed_at,
    )
    product.open_thread(
        thread_id="travel",
        scope=SCOPE,
        open_question=second.content,
        supporting_memory_ids=("m2",),
        at=second.committed_at,
    )
    # Mark the two initial queue entries as consumed without letting them
    # create duplicate auto Threads.
    queue = canonical.thread_update_queue()
    for intent in queue.pending(10):
        queue.succeed(intent.memory_id, f"test:{intent.memory_id}")

    third = memory("m3", "The computer price changed again.", 2)
    commit_and_run(canonical, worker, third)

    assert product.get_thread("work").current_support_ids == ("m1",)
    assert product.get_thread("travel").current_support_ids == ("m2",)

    product.close()
    canonical.close()


def test_retry_after_post_mutation_crash_is_idempotent(tmp_path, monkeypatch):
    canonical, product, worker = plane(tmp_path)
    item = memory("m1", "I am considering replacing my computer.")
    canonical._commit((item,))
    queue = canonical.thread_update_queue()
    original_succeed = queue.succeed

    def crash(memory_id, thread_ref):
        raise KeyboardInterrupt("crash after Thread mutation")

    monkeypatch.setattr(queue, "succeed", crash)
    with pytest.raises(KeyboardInterrupt):
        worker.run_once(limit=1)

    threads = product.surface_threads(SCOPE, now=BASE, limit=10, decay_lambda=0.0)
    assert len(threads) == 1
    assert threads[0].touch_count == 0

    monkeypatch.setattr(queue, "succeed", original_succeed)
    assert worker.run_once(limit=1) == (1, 0)
    threads = product.surface_threads(SCOPE, now=BASE, limit=10, decay_lambda=0.0)
    assert len(threads) == 1
    assert threads[0].touch_count == 0
    assert queue.pending(10) == ()

    product.close()
    canonical.close()


def test_queue_recovery_preserves_commit_order(tmp_path):
    canonical, product, worker = plane(tmp_path)
    late_id = memory("z", "I am considering replacing my computer.", 0)
    early_lexical_id = memory("a", "The computer is getting slower lately.", 1)
    canonical._commit((late_id, early_lexical_id))

    assert [intent.memory_id for intent in canonical.thread_update_queue().pending(10)] == [
        "z",
        "a",
    ]
    assert worker.run_once(limit=10) == (2, 0)
    threads = product.surface_threads(SCOPE, now=BASE + timedelta(minutes=2), limit=10)
    assert len(threads) == 1
    assert threads[0].current_support_ids == ("z", "a")

    product.close()
    canonical.close()
