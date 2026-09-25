"""MR bindings for current LCE Core plus bounded Thread handoff/readback.

MR remains the only factual Memory authority. LCE receives stable canonical
Memory IDs and owns only derived Baseline cognition.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING

from mind_runtime.contracts import Scope
from mind_runtime.memory.contracts import MemoryLifecycle
from mind_runtime.memory.providers.bm25 import lexical_tokens
from mind_runtime.memory.product import MemoryThread, ThreadStatus
from mind_runtime.memory.store import CanonicalMemoryStore, scope_json
from mind_runtime.runtime_binding import (
    BindingManifestMismatchError,
    RuntimeBinding,
    StoragePaths,
    resolve_storage_paths,
)

if TYPE_CHECKING:
    from lce.contracts.consolidation import ConsolidationResult, SemanticConsolidatorPort
    from lce.contracts.external_memory import MemoryItemView
    from lce.core.engine import LceCore
    from lce.store.sqlite_store import SqliteBaselineStore

MAX_SELECTED_MEMORIES = 100


class MemorySelectionError(ValueError):
    """The entire selected set is unavailable or unauthorized; no partial views."""


class LceIntegrationUnavailable(RuntimeError):
    """The explicitly enabled optional LCE dependency is unavailable."""


def _verify_binding(binding: RuntimeBinding, paths: StoragePaths) -> None:
    try:
        manifest = json.loads(paths.binding_manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise BindingManifestMismatchError("LCE requires an existing Runtime manifest") from exc
    if not isinstance(manifest, dict) or any(
        manifest.get(key) != value for key, value in binding.manifest_identity().items()
    ):
        raise BindingManifestMismatchError("LCE Runtime manifest mismatch")


@dataclass(frozen=True, init=False)
class MrMemorySubstrateAdapter:
    """Composition-authorized Scope, resolved only against its bound Runtime.

    Scope authorization is supplied by the trusted composition owner, never
    inferred from a selected ID or provider. Connections are read-only and
    short-lived so reconstructed processes do not depend on cached Memory.
    """

    binding: RuntimeBinding
    scope: Scope
    _paths: StoragePaths

    def __init__(
        self,
        binding: RuntimeBinding,
        scope: Scope,
        *,
        production_root: Path | str | None = None,
        lab_root: Path | str | None = None,
    ) -> None:
        if not isinstance(scope, Scope):
            raise TypeError("scope must be a structured Scope")
        paths = resolve_storage_paths(binding, production_root=production_root, lab_root=lab_root)
        object.__setattr__(self, "binding", binding)
        object.__setattr__(self, "scope", scope)
        object.__setattr__(self, "_paths", paths)

    def get_by_ids(self, memory_ids: tuple[str, ...]) -> tuple[MemoryItemView, ...]:
        if not isinstance(memory_ids, tuple) or not 1 <= len(memory_ids) <= MAX_SELECTED_MEMORIES:
            raise MemorySelectionError("expected a tuple of 1 to 100 stable Memory IDs")
        if any(not isinstance(mid, str) or not mid.strip() for mid in memory_ids):
            raise MemorySelectionError("each Memory ID must be a non-empty string")
        if len(set(memory_ids)) != len(memory_ids):
            raise MemorySelectionError("duplicate Memory IDs are not permitted")
        _verify_binding(self.binding, self._paths)
        store = CanonicalMemoryStore(self._paths.memory_db, read_only=True)
        try:
            memories = tuple(store.get(mid) for mid in memory_ids)
        finally:
            store.close()
        if any(
            m is None or m.scope != self.scope or m.lifecycle is not MemoryLifecycle.ACTIVE
            for m in memories
        ):
            raise MemorySelectionError("selected Memory set contains unavailable or ineligible IDs")
        try:
            from lce.contracts.external_memory import MemoryItemView
        except ImportError as exc:
            raise LceIntegrationUnavailable(
                "install the current optional lce-core package"
            ) from exc
        return tuple(
            MemoryItemView(m.memory_id, m.content, m.provenance.evidence_refs, MappingProxyType({}))
            for m in memories
            if m is not None
        )


@dataclass(frozen=True, slots=True)
class LceAcceptedUnderstanding:
    """Current-valid accepted LCE Baseline resolved through MR Memory."""

    content: str
    baseline_id: str
    region_id: str
    revision_number: int
    supporting_memory_ids: tuple[str, ...]
    source_refs: tuple[str, ...]
    relevance: float


class _PrecomputedThreadConsolidator:
    """Return an already-reasoned Thread product without invoking a model."""

    def __init__(self, candidate: object) -> None:
        self._candidate = candidate

    def consolidate(self, *, memories, previous_baseline, context=None):
        del memories, previous_baseline, context
        return self._candidate


def _accepted_understandings(
    adapter: MrMemorySubstrateAdapter,
    store: SqliteBaselineStore,
    *,
    current_context: str | None,
    limit: int,
) -> tuple[LceAcceptedUnderstanding, ...]:
    if type(limit) is not int or not 0 <= limit <= 100:
        raise ValueError("limit must be an integer in [0, 100]")
    if limit == 0:
        return ()
    query_tokens = set(lexical_tokens(current_context or ""))
    candidates: list[LceAcceptedUnderstanding] = []
    for region_id in store.list_regions():
        baseline = store.get_head(region_id)
        if baseline is None:
            continue
        try:
            memories = adapter.get_by_ids(baseline.supporting_memory_ids)
        except MemorySelectionError:
            # Accepted cognition whose factual support is no longer current is
            # not served back into MR context.
            continue
        if len(memories) != len(baseline.supporting_memory_ids):
            continue
        by_id = {item.memory_id: item for item in memories}
        if set(by_id) != set(baseline.supporting_memory_ids):
            continue
        searchable = " ".join(
            [baseline.content, *(by_id[mid].content for mid in baseline.supporting_memory_ids)]
        )
        searchable_tokens = set(lexical_tokens(searchable))
        if query_tokens:
            overlap = len(query_tokens & searchable_tokens)
            if overlap == 0:
                continue
            relevance = overlap / len(query_tokens)
        else:
            relevance = 1.0
        source_refs = tuple(
            sorted(
                {
                    ref
                    for memory in memories
                    for ref in memory.source_refs
                }
            )
        )
        candidates.append(
            LceAcceptedUnderstanding(
                content=baseline.content,
                baseline_id=baseline.baseline_id,
                region_id=baseline.region_id,
                revision_number=baseline.revision_number,
                supporting_memory_ids=baseline.supporting_memory_ids,
                source_refs=source_refs,
                relevance=min(1.0, relevance),
            )
        )
    candidates.sort(
        key=lambda item: (-item.relevance, item.region_id, -item.revision_number)
    )
    return tuple(candidates[:limit])


@dataclass(frozen=True)
class LceBindingSession:
    """Generic external-Memory LCE Core session."""

    core: LceCore
    _store: SqliteBaselineStore
    _adapter: MrMemorySubstrateAdapter

    @property
    def db_path(self) -> Path:
        return self._store.db_path

    def accepted_understandings(
        self, current_context: str | None, *, limit: int = 4
    ) -> tuple[LceAcceptedUnderstanding, ...]:
        return _accepted_understandings(
            self._adapter, self._store, current_context=current_context, limit=limit
        )

    def close(self) -> None:
        self._store.close()

    def __enter__(self) -> LceBindingSession:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


@dataclass(frozen=True)
class LceThreadHandoffSession:
    """No-model path from mature MR Thread to accepted LCE Baseline."""

    _adapter: MrMemorySubstrateAdapter
    _store: SqliteBaselineStore

    @property
    def db_path(self) -> Path:
        return self._store.db_path

    def handoff_thread(self, thread: MemoryThread) -> ConsolidationResult:
        if not isinstance(thread, MemoryThread):
            raise TypeError("thread must be MemoryThread")
        if thread.status is ThreadStatus.ABANDONED:
            raise ValueError("abandoned Thread cannot be handed off")
        if not thread.mature or thread.working_summary is None:
            raise ValueError("Thread is not mature for LCE handoff")
        try:
            from lce.contracts.consolidation import CandidateBaseline
            from lce.core.engine import LceCore
        except ImportError as exc:
            raise LceIntegrationUnavailable(
                "install the current optional lce-core package"
            ) from exc

        support = thread.handoff_memory_ids
        # Revalidate every canonical support point before LCE sees the candidate.
        self._adapter.get_by_ids(support)
        candidate = CandidateBaseline(
            content=thread.working_summary,
            supporting_memory_ids=support,
            model_trace={},
        )
        core = LceCore(
            memory_substrate=self._adapter,
            baseline_store=self._store,
            consolidator=_PrecomputedThreadConsolidator(candidate),
        )
        return core.consolidate(
            f"mr-thread:{thread.thread_id}",
            support,
            context={
                "source": "mr-thread",
                "open_question": thread.open_question,
                "thread_status": thread.status.value,
            },
        )

    def accepted_understandings(
        self, current_context: str | None, *, limit: int = 4
    ) -> tuple[LceAcceptedUnderstanding, ...]:
        return _accepted_understandings(
            self._adapter, self._store, current_context=current_context, limit=limit
        )

    def close(self) -> None:
        self._store.close()

    def __enter__(self) -> LceThreadHandoffSession:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


def _scope_lce_root(adapter: MrMemorySubstrateAdapter) -> Path:
    scope_address = hashlib.sha256(scope_json(adapter.scope).encode("utf-8")).hexdigest()
    return adapter._paths.lce_root / scope_address


def open_lce_thread_handoff(
    binding: RuntimeBinding,
    scope: Scope,
    *,
    enabled: bool = False,
    production_root: Path | str | None = None,
    lab_root: Path | str | None = None,
) -> LceThreadHandoffSession | None:
    """Open the no-model mature-Thread -> LCE Baseline path."""
    if type(enabled) is not bool:
        raise TypeError("enabled must be bool")
    if not enabled:
        return None
    adapter = MrMemorySubstrateAdapter(
        binding,
        scope,
        production_root=production_root,
        lab_root=lab_root,
    )
    _verify_binding(binding, adapter._paths)
    CanonicalMemoryStore(adapter._paths.memory_db, read_only=True).close()
    try:
        from lce.store.sqlite_store import SqliteBaselineStore
    except ImportError as exc:
        raise LceIntegrationUnavailable("install the current optional lce-core package") from exc
    return LceThreadHandoffSession(adapter, SqliteBaselineStore(_scope_lce_root(adapter)))


def open_lce_read_binding(
    binding: RuntimeBinding,
    scope: Scope,
    *,
    enabled: bool = False,
    production_root: Path | str | None = None,
    lab_root: Path | str | None = None,
) -> LceThreadHandoffSession | None:
    """Open accepted Baselines without creating an LCE store when none exists."""
    if type(enabled) is not bool:
        raise TypeError("enabled must be bool")
    if not enabled:
        return None
    adapter = MrMemorySubstrateAdapter(
        binding,
        scope,
        production_root=production_root,
        lab_root=lab_root,
    )
    _verify_binding(binding, adapter._paths)
    CanonicalMemoryStore(adapter._paths.memory_db, read_only=True).close()
    root = _scope_lce_root(adapter)
    db_path = root / "lce_baselines.sqlite"
    if not db_path.exists():
        return None
    try:
        from lce.store.sqlite_store import SqliteBaselineStore
    except ImportError as exc:
        raise LceIntegrationUnavailable("install the current optional lce-core package") from exc
    return LceThreadHandoffSession(adapter, SqliteBaselineStore(root))


def open_lce_binding(
    binding: RuntimeBinding,
    scope: Scope,
    *,
    enabled: bool = False,
    consolidator: SemanticConsolidatorPort | None = None,
    production_root: Path | str | None = None,
    lab_root: Path | str | None = None,
) -> LceBindingSession | None:
    """Default OFF, including filesystem access and optional dependency imports."""
    if type(enabled) is not bool:
        raise TypeError("enabled must be bool")
    if not enabled:
        return None
    if consolidator is None:
        raise ValueError("enabled LCE binding requires an explicitly injected consolidator")
    adapter = MrMemorySubstrateAdapter(
        binding,
        scope,
        production_root=production_root,
        lab_root=lab_root,
    )
    _verify_binding(binding, adapter._paths)
    # Prove canonical storage already exists before creating any LCE persistence.
    CanonicalMemoryStore(adapter._paths.memory_db, read_only=True).close()
    try:
        from lce.core.engine import LceCore
        from lce.store.sqlite_store import SqliteBaselineStore
    except ImportError as exc:
        raise LceIntegrationUnavailable("install the frozen optional lce-core package") from exc
    store = SqliteBaselineStore(_scope_lce_root(adapter))
    try:
        core = LceCore(memory_substrate=adapter, baseline_store=store, consolidator=consolidator)
        return LceBindingSession(core, store, adapter)
    except BaseException:
        store.close()
        raise
