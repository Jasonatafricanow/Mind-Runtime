"""Binding-owned Memory composition. No caller-supplied canonical Memory path."""

from mind_runtime.facts.persistence import SqliteFactBackend
from mind_runtime.facts.service import FactIngestService
from mind_runtime.memory.admission import MemoryAdmissionService
from mind_runtime.memory.extraction import MemoryExtractor
from mind_runtime.memory.product import MemoryProductStore
from mind_runtime.memory.store import CanonicalMemoryStore
from mind_runtime.memory.thread_updates import (
    DeterministicThreadUpdater,
    ThreadUpdatePolicy,
    ThreadUpdateWorker,
)
from mind_runtime.providers.clock import Clock
from mind_runtime.runtime_binding import RuntimeBinding, bind_storage


def build_bound_fact_service(
    binding: RuntimeBinding,
    *,
    clock: Clock,
    enabled: bool = False,
    extractor: MemoryExtractor | None = None,
    thread_policy: ThreadUpdatePolicy | None = None,
) -> FactIngestService:
    if type(enabled) is not bool:
        raise ValueError("enabled must be bool")
    paths = bind_storage(binding)
    backend = SqliteFactBackend(paths.facts_db)
    hook = None
    if enabled:
        store = CanonicalMemoryStore(paths.memory_db)
        product = MemoryProductStore(paths.memory_db, store)
        thread_updates = ThreadUpdateWorker(
            store.thread_update_queue(),
            DeterministicThreadUpdater(product=product, policy=thread_policy),
        )
        # Recover only already-enqueued derived work. Existing canonical Memory
        # is not backfilled automatically.
        thread_updates.run_once(limit=128)
        hook = MemoryAdmissionService(
            store=store,
            facts=backend,
            clock=clock,
            origin_runtime_id=binding.runtime_id,
            enabled=True,
            extractor=extractor,
            thread_updates=thread_updates,
        )
    return FactIngestService(clock=clock, backend=backend, after_admission=hook)
