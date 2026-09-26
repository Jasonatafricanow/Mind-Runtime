"""MR bindings for current LCE Core plus bounded Thread handoff/readback.

MR remains the only factual Memory authority. LCE receives stable canonical
Memory IDs and owns only derived Baseline cognition.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

from mind_runtime.contracts import EffectiveWindow, ObservationModality, Scope, SemanticTime
from mind_runtime.contracts.common import require_aware_utc
from mind_runtime.facts.persistence import SqliteFactReader
from mind_runtime.memory.contracts import CommittedMemory, MemoryLifecycle
from mind_runtime.memory.core import MemoryCore, MemoryCoreSelectionError
from mind_runtime.memory.product import MemoryProductStore, MemoryThread, ThreadStatus
from mind_runtime.memory.providers.bm25 import lexical_tokens
from mind_runtime.memory.store import CanonicalMemoryStore, scope_json
from mind_runtime.runtime_binding import (
    BindingManifestMismatchError,
    RuntimeBinding,
    StoragePaths,
    resolve_storage_paths,
)

if TYPE_CHECKING:
    from lce.contracts.baseline import Baseline
    from lce.contracts.consolidation import (
        CandidateBaseline,
        ConsolidationResult,
        SemanticConsolidatorPort,
    )
    from lce.contracts.external_memory import MemoryItemView
    from lce.core.engine import LceCore
    from lce.core.projection import LceProjectionCore
    from lce.reference_memory.contracts import RawEvidence
    from lce.store.sqlite_store import SqliteBaselineStore

MAX_SELECTED_MEMORIES = 100
MAX_TEMPORAL_OBSERVATIONS_PER_MEMORY = 32
TEMPORAL_CONTEXT_KEY = "mr.temporal_memory_views.v1"
_THREAD_REGION_PREFIX = "mr-thread:"


@dataclass(frozen=True, slots=True)
class TemporalEvidenceView:
    """Source chronology without pretending it is proposition-valid time."""

    evidence_id: str
    source_occurred_at: datetime
    received_at: datetime


@dataclass(frozen=True, slots=True)
class TemporalPropositionView:
    """One authoritative Reality Observation over supporting Evidence."""

    observation_id: str
    key: str
    modality: ObservationModality
    observed_at: datetime
    evidence_refs: tuple[str, ...]
    semantic_time: SemanticTime
    effective_window: EffectiveWindow | None


@dataclass(frozen=True, slots=True)
class TemporalMemoryView:
    """Read-only MR temporal authority adjacent to LCE factual Memory views."""

    memory_id: str
    content: str
    source_refs: tuple[str, ...]
    source_observation_id: str
    source_observed_at: datetime
    source_semantic_time: SemanticTime
    source_effective_window: EffectiveWindow | None
    evidence: tuple[TemporalEvidenceView, ...]
    proposition_observations: tuple[TemporalPropositionView, ...]
    committed_at: datetime

    @property
    def knowledge_available_at(self) -> datetime:
        points = (self.committed_at, self.source_observed_at) + tuple(
            item.received_at for item in self.evidence
        ) + tuple(item.observed_at for item in self.proposition_observations)
        return max(points)



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

    def _selected_memories(
        self, memory_ids: tuple[str, ...]
    ) -> tuple[CommittedMemory, ...]:
        _verify_binding(self.binding, self._paths)
        try:
            with MemoryCore(self._paths.memory_db, read_only=True) as core:
                return core.select(
                    memory_ids,
                    scope=self.scope,
                    active_only=True,
                    max_items=MAX_SELECTED_MEMORIES,
                )
        except MemoryCoreSelectionError as exc:
            raise MemorySelectionError(str(exc)) from exc

    def get_by_ids(self, memory_ids: tuple[str, ...]) -> tuple[MemoryItemView, ...]:
        memories = self._selected_memories(memory_ids)
        try:
            from lce.contracts.external_memory import MemoryItemView
        except ImportError as exc:
            raise LceIntegrationUnavailable(
                "install the current optional lce-core package"
            ) from exc
        return tuple(
            MemoryItemView(
                memory.memory_id,
                memory.content,
                memory.provenance.evidence_refs,
                MappingProxyType({}),
            )
            for memory in memories
        )

    def get_temporal_by_ids(
        self,
        memory_ids: tuple[str, ...],
        *,
        cutoff: datetime | None = None,
    ) -> tuple[TemporalMemoryView, ...]:
        """Resolve MR-owned temporal authority without changing Memory authority."""
        memories = self._selected_memories(memory_ids)
        if cutoff is not None:
            require_aware_utc(cutoff, "cutoff")

        reader = SqliteFactReader(self._paths.facts_db)
        try:
            observations = reader.load_observations()
            views: list[TemporalMemoryView] = []
            for memory in memories:
                source_observation = reader.find_observation(
                    self.scope, memory.provenance.observation_id
                )
                if source_observation is None:
                    raise MemorySelectionError(
                        "selected Memory has no authoritative source Observation"
                    )
                source_refs = set(memory.provenance.evidence_refs)
                if (
                    not source_observation.evidence_refs
                    or not set(source_observation.evidence_refs).issubset(source_refs)
                ):
                    raise MemorySelectionError(
                        "selected Memory provenance disagrees with its source Observation"
                    )

                evidence_views: list[TemporalEvidenceView] = []
                for evidence_id in memory.provenance.evidence_refs:
                    pair = reader.find_evidence(self.scope, evidence_id)
                    if pair is None:
                        raise MemorySelectionError(
                            "selected Memory has unavailable supporting Evidence"
                        )
                    evidence = pair[0]
                    evidence_views.append(
                        TemporalEvidenceView(
                            evidence_id=evidence.id,
                            source_occurred_at=evidence.occurred_at,
                            received_at=evidence.received_at,
                        )
                    )

                related = tuple(
                    observation
                    for observation in observations
                    if observation.scope == self.scope
                    and observation.id != source_observation.id
                    and observation.id.startswith("reality-observation-")
                    and observation.evidence_refs
                    and set(observation.evidence_refs).issubset(source_refs)
                )
                if len(related) > MAX_TEMPORAL_OBSERVATIONS_PER_MEMORY:
                    raise MemorySelectionError(
                        "selected Memory exceeds bounded temporal Observation fanout"
                    )
                related = tuple(sorted(related, key=lambda item: (item.observed_at, item.id)))
                proposition_views = tuple(
                    TemporalPropositionView(
                        observation_id=observation.id,
                        key=observation.key,
                        modality=observation.modality,
                        observed_at=observation.observed_at,
                        evidence_refs=observation.evidence_refs,
                        semantic_time=observation.semantic_time,
                        effective_window=observation.effective_window,
                    )
                    for observation in related
                )
                view = TemporalMemoryView(
                    memory_id=memory.memory_id,
                    content=memory.content,
                    source_refs=memory.provenance.evidence_refs,
                    source_observation_id=source_observation.id,
                    source_observed_at=source_observation.observed_at,
                    source_semantic_time=source_observation.semantic_time,
                    source_effective_window=source_observation.effective_window,
                    evidence=tuple(evidence_views),
                    proposition_observations=proposition_views,
                    committed_at=memory.committed_at,
                )
                if cutoff is not None and view.knowledge_available_at > cutoff:
                    raise MemorySelectionError(
                        "selected Memory set contains knowledge unavailable at cutoff"
                    )
                views.append(view)
            return tuple(views)
        finally:
            reader.close()


@dataclass(frozen=True, slots=True)
class MrCanonicalLceSource:
    """Read-only LCE source view over authoritative MR canonical Memory."""

    adapter: MrMemorySubstrateAdapter

    def _memory(self, memory_id: str) -> CommittedMemory:
        _verify_binding(self.adapter.binding, self.adapter._paths)
        try:
            with MemoryCore(
                self.adapter._paths.memory_db,
                read_only=True,
            ) as core:
                return core.select(
                    (memory_id,),
                    scope=self.adapter.scope,
                    active_only=False,
                    max_items=1,
                )[0]
        except MemoryCoreSelectionError as exc:
            raise MemorySelectionError(str(exc)) from exc

    @staticmethod
    def _raw_from_memory(
        memory: CommittedMemory,
        reader: SqliteFactReader,
    ) -> RawEvidence:
        try:
            from lce.reference_memory.contracts import RawEvidence
        except ImportError as exc:
            raise LceIntegrationUnavailable(
                "install the current optional lce-core package"
            ) from exc

        occurred: list[datetime] = []
        for evidence_id in memory.provenance.evidence_refs:
            pair = reader.find_evidence(memory.scope, evidence_id)
            if pair is None:
                raise MemorySelectionError(
                    "canonical Memory has unavailable supporting Evidence"
                )
            occurred.append(pair[0].occurred_at)
        if not occurred:
            raise MemorySelectionError(
                "canonical Memory has no supporting Evidence chronology"
            )
        occurred_at = max(occurred)
        if occurred_at.tzinfo is not UTC:
            raise MemorySelectionError(
                "canonical Memory source chronology must be UTC"
            )

        if memory.lifecycle is MemoryLifecycle.ACTIVE:
            state = "VALID"
        elif memory.lifecycle is MemoryLifecycle.SUPERSEDED:
            state = "SUPERSEDED"
        else:
            state = "INVALID"
        return RawEvidence(
            evidence_id=memory.memory_id,
            content=memory.content,
            occurred_at=occurred_at,
            ordering_key=f"{occurred_at.isoformat()}::{memory.memory_id}",
            provenance={
                "source": "mr.canonical_memory",
                "canonical": True,
                "derived": False,
                "memory_id": memory.memory_id,
                "observation_id": memory.provenance.observation_id,
                "evidence_refs": memory.provenance.evidence_refs,
            },
            state=state,
        )

    def get_evidence(self, evidence_id: str) -> RawEvidence:
        memory = self._memory(evidence_id)
        reader = SqliteFactReader(self.adapter._paths.facts_db)
        try:
            return self._raw_from_memory(memory, reader)
        finally:
            reader.close()

    def list_current_valid_evidence(self) -> tuple[RawEvidence, ...]:
        _verify_binding(self.adapter.binding, self.adapter._paths)
        with MemoryCore(
            self.adapter._paths.memory_db,
            read_only=True,
        ) as core:
            memories = tuple(
                memory
                for memory in core.load_all()
                if memory.scope == self.adapter.scope
                and memory.lifecycle is MemoryLifecycle.ACTIVE
            )
        reader = SqliteFactReader(self.adapter._paths.facts_db)
        try:
            result = tuple(
                self._raw_from_memory(memory, reader)
                for memory in memories
            )
        finally:
            reader.close()
        return tuple(
            sorted(
                result,
                key=lambda item: (
                    item.effective_ordering_key,
                    item.evidence_id,
                ),
            )
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

    def __init__(self, candidate: CandidateBaseline) -> None:
        self._candidate = candidate

    def consolidate(
        self,
        *,
        memories: tuple[MemoryItemView, ...],
        previous_baseline: Baseline | None,
        context: Mapping[str, object] | None = None,
    ) -> CandidateBaseline:
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


class _GenericLceCore:
    """Guard generic LCE writes from claiming the MR Thread namespace."""

    def __init__(self, core: LceCore) -> None:
        self._core = core

    def consolidate(self, region_id: str, *args: Any, **kwargs: Any) -> Any:
        if region_id.startswith(_THREAD_REGION_PREFIX):
            raise ValueError(
                "mr-thread:* regions are reserved for durable Thread handoff"
            )
        return self._core.consolidate(region_id, *args, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._core, name)


@dataclass(frozen=True)
class LceBindingSession:
    """Generic external-Memory LCE Core session."""

    core: _GenericLceCore
    _store: SqliteBaselineStore
    _adapter: MrMemorySubstrateAdapter

    @property
    def db_path(self) -> Path:
        return Path(self._store.db_path)

    def temporal_memory_views(
        self,
        memory_ids: tuple[str, ...],
        *,
        cutoff: datetime | None = None,
    ) -> tuple[TemporalMemoryView, ...]:
        return self._adapter.get_temporal_by_ids(memory_ids, cutoff=cutoff)

    def consolidate_temporal(
        self,
        region_id: str,
        memory_ids: tuple[str, ...],
        *,
        cutoff: datetime | None = None,
        context: Mapping[str, object] | None = None,
    ) -> ConsolidationResult:
        """Path B entry: inject MR-authoritative time into LCE consolidation."""
        temporal_views = self.temporal_memory_views(memory_ids, cutoff=cutoff)
        merged_context = dict(context or {})
        if TEMPORAL_CONTEXT_KEY in merged_context:
            raise ValueError(f"{TEMPORAL_CONTEXT_KEY} is reserved for MR authority")
        merged_context[TEMPORAL_CONTEXT_KEY] = temporal_views
        return self.core.consolidate(
            region_id,
            memory_ids,
            context=MappingProxyType(merged_context),
        )

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
        return Path(self._store.db_path)

    def handoff_thread(self, thread: MemoryThread) -> ConsolidationResult:
        if not isinstance(thread, MemoryThread):
            raise TypeError("thread must be MemoryThread")
        if thread.scope != self._adapter.scope:
            raise MemorySelectionError(
                "Thread Scope does not match the bound LCE Scope"
            )

        canonical = CanonicalMemoryStore(
            self._adapter._paths.memory_db,
            read_only=True,
        )
        product = MemoryProductStore(
            self._adapter._paths.memory_db,
            canonical,
            read_only=True,
        )
        try:
            authoritative = product.thread_handoff(thread.thread_id)
        finally:
            product.close()
            canonical.close()
        if authoritative != thread:
            raise ValueError("Thread must match durable MR product state")
        thread = authoritative

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
            f"{_THREAD_REGION_PREFIX}{thread.thread_id}",
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


@dataclass(frozen=True)
class LceReadSession:
    """Read-only capability for accepted LCE cognition."""

    _adapter: MrMemorySubstrateAdapter
    _store: SqliteBaselineStore

    @property
    def db_path(self) -> Path:
        return Path(self._store.db_path)

    def accepted_understandings(
        self, current_context: str | None, *, limit: int = 4
    ) -> tuple[LceAcceptedUnderstanding, ...]:
        return _accepted_understandings(
            self._adapter,
            self._store,
            current_context=current_context,
            limit=limit,
        )

    def close(self) -> None:
        self._store.close()

    def __enter__(self) -> LceReadSession:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


@dataclass(frozen=True, slots=True)
class LceThreadProjectionCompiler:
    """Optional adapter that compiles mature Thread projections into LCE.

    It does not own Memory or Thread lifecycle. A returned Baseline ID only
    tells the Memory product layer that an accepted higher-level projection
    now exists for the same logical line.
    """

    binding: RuntimeBinding
    enabled: bool = False
    production_root: Path | str | None = None
    lab_root: Path | str | None = None

    def compile(self, thread: MemoryThread) -> str | None:
        if not isinstance(thread, MemoryThread):
            raise TypeError("thread must be MemoryThread")
        session = open_lce_thread_handoff(
            self.binding,
            thread.scope,
            enabled=self.enabled,
            production_root=self.production_root,
            lab_root=self.lab_root,
        )
        if session is None:
            return None
        with session:
            result = session.handoff_thread(thread)
        return result.baseline.baseline_id


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
) -> LceReadSession | None:
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
    return LceReadSession(adapter, SqliteBaselineStore(root))


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
        return LceBindingSession(_GenericLceCore(core), store, adapter)
    except BaseException:
        store.close()
        raise
