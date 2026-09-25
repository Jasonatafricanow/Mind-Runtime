"""Binding-owned Memory composition. No caller-supplied canonical Memory path."""

from mind_runtime.facts.persistence import SqliteFactBackend
from mind_runtime.facts.service import FactIngestService
from mind_runtime.memory.admission import MemoryAdmissionService
from mind_runtime.memory.extraction import MemoryExtractor
from mind_runtime.memory.product import MemoryProductStore
from mind_runtime.memory.store import CanonicalMemoryStore
from mind_runtime.memory.threading import ThreadAutoUpdateService, ThreadProjectionCompiler
from mind_runtime.providers.clock import Clock
from mind_runtime.runtime_binding import RuntimeBinding, bind_storage


def build_bound_fact_service(
    binding: RuntimeBinding,
    *,
    clock: Clock,
    enabled: bool = False,
    extractor: MemoryExtractor | None = None,
) -> FactIngestService:
    if type(enabled) is not bool:
        raise ValueError("enabled must be bool")
    paths = bind_storage(binding)
    backend = SqliteFactBackend(paths.facts_db)
    hook = None
    if enabled:
        hook = MemoryAdmissionService(
            store=CanonicalMemoryStore(paths.memory_db),
            facts=backend,
            clock=clock,
            origin_runtime_id=binding.runtime_id,
            enabled=True,
            extractor=extractor,
        )
    return FactIngestService(clock=clock, backend=backend, after_admission=hook)


def build_bound_thread_updates(
    binding: RuntimeBinding,
    *,
    enabled: bool = False,
    projection_compiler: ThreadProjectionCompiler | None = None,
) -> ThreadAutoUpdateService | None:
    """Compose Thread maintenance without importing a higher projection engine.

    The Memory core owns the temporary projection lifecycle. A higher
    composition root may inject an optional compiler port (for example LCE)
    without making Memory depend on that implementation.
    """
    if type(enabled) is not bool:
        raise ValueError("enabled must be bool")
    if projection_compiler is not None and not isinstance(
        projection_compiler, ThreadProjectionCompiler
    ):
        raise ValueError("projection_compiler must implement ThreadProjectionCompiler")
    if not enabled:
        return None
    paths = bind_storage(binding)
    canonical = CanonicalMemoryStore(paths.memory_db)
    product = MemoryProductStore(paths.memory_db, canonical)
    return ThreadAutoUpdateService(
        canonical=canonical,
        product=product,
        projection_compiler=projection_compiler,
    )
