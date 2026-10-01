"""Host composition of native sources, accepted semantics, Thread/LCE and context.

The caller supplies the sole MR-Mem core and providers. This module neither
discovers a production database nor constructs a model or copies native raw.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from lce.cognition.block_adapter import SemanticBlockMemoryAdapter
from lce.cognition.external import (
    PrecomputedDraftInput,
    PrecomputedDraftIntake,
    RejectedDerivedProposalError,
)
from lce.cognition.promotion import BoundedInterpreter
from lce.core.projection import LceProjectionCore
from lce.reference_memory.composite import ExternalSourceMutationError, ProjectionSubstrate
from lce.reference_memory.contracts import AuthorizedSelectedSupport, RawEvidence, SemanticBlock
from lce.reference_memory.projection_state import SqliteProjectionStateStore
from mr_mem import (
    CommittedMemory,
    MemoryCore,
    MemoryLifecycle,
    MemoryRetrievalQuery,
    MemoryRetrievalService,
    SemanticAdmissionService,
    SourceRef,
    SourceRefReader,
    ThreadAutoUpdateService,
)
from mr_mem import (
    Scope as MemoryScope,
)
from mr_mem import (
    ScopeDomain as MemoryScopeDomain,
)
from mr_mem.memory.product import MemoryThread
from mr_mem.memory.providers.bm25 import BM25RetrievalProvider, lexical_tokens
from mr_mem.memory.source import Clock
from mr_mem.memory.store import scope_json

from mind_runtime.contracts import Observation, Scope, Situation
from mind_runtime.contracts.historical import HistoricalContextBundle, HistoricalContextItem
from mind_runtime.integrations.historical_compiler import (
    HistoricalSemanticPipeline,
    SemanticCleaner,
)
from mind_runtime.integrations.native_history import NativeRecord, NativeSourceStore, SourceFragment
from mind_runtime.memory.retrieval import DEFAULT_SURFACE_BUDGET, MemorySurfaceBudget


def _source_id(ref: SourceRef) -> str:
    return "source-ref:" + ref.version_key


def _memory_scope(scope: Scope) -> MemoryScope:
    return MemoryScope(
        MemoryScopeDomain(scope.domain.value),
        user_id=scope.user_id,
        agent_id=scope.agent_id,
        persona_id=scope.persona_id,
        relationship_id=scope.relationship_id,
        world_id=scope.world_id,
        interaction_id=scope.interaction_id,
    )


class NativeSourceViews:
    """Legacy LCE source views containing references only, never raw bodies."""

    def __init__(self, core: MemoryCore, scope: MemoryScope, sources: SourceRefReader) -> None:
        self.core, self.scope, self.sources = core, scope, sources

    def _refs(self) -> dict[str, tuple[SourceRef, datetime]]:
        refs: dict[str, tuple[SourceRef, datetime]] = {}
        for memory in self.core.load_all():
            if memory.scope != self.scope:
                continue
            for ref in memory.provenance.source_refs:
                key = _source_id(ref)
                previous = refs.get(key)
                refs[key] = (
                    ref,
                    min(memory.known_at, previous[1]) if previous else memory.known_at,
                )
        return refs

    def get_evidence(self, evidence_id: str) -> RawEvidence:
        ref, known_at = self._refs()[evidence_id]
        current = self.sources.current_ref(self.scope, ref) == ref
        return RawEvidence(
            evidence_id=evidence_id,
            content="[native SourceRef metadata]",
            occurred_at=ref.occurred_at,
            known_at=known_at,
            provenance={
                "source": ref.source_namespace,
                "canonical": True,
                "session_id": ref.session_id,
                "record_id": ref.record_id,
                "version_key": ref.version_key,
                "event_key": ref.source_key,
                "known_at_basis": "first-host-semantic-admission",
            },
            state="VALID" if current else "INVALID",
        )

    def list_current_valid_evidence(self) -> tuple[RawEvidence, ...]:
        return tuple(view for key in self._refs() if (view := self.get_evidence(key)).current_valid)


class AcceptedSemanticSubstrate(ProjectionSubstrate):
    """LCE caches exact accepted views; MR-Mem remains semantic authority."""

    def __init__(
        self,
        core: MemoryCore,
        scope: MemoryScope,
        sources: SourceRefReader,
        root: Path,
    ) -> None:
        self.canonical, self.scope, self.sources = core, scope, sources
        super().__init__(NativeSourceViews(core, scope, sources), SqliteProjectionStateStore(root))

    def _eligible(self, memory_id: str, *, current_valid: bool = True) -> CommittedMemory:
        memory = self.canonical.get(memory_id)
        if (
            memory is None
            or memory.scope != self.scope
            or not memory.provenance.source_refs
            or (
                current_valid
                and (
                    memory.lifecycle is not MemoryLifecycle.ACTIVE
                    or any(
                        self.sources.current_ref(self.scope, ref) != ref
                        for ref in memory.provenance.source_refs
                    )
                )
            )
        ):
            raise KeyError(memory_id)
        return memory

    @staticmethod
    def _view(memory: CommittedMemory) -> SemanticBlock:
        refs = memory.provenance.source_refs
        return SemanticBlock(
            block_id=memory.memory_id,
            content=memory.content,
            raw_evidence_ids=tuple(_source_id(ref) for ref in refs),
            occurred_start=min(ref.occurred_at for ref in refs),
            occurred_end=max(ref.occurred_at for ref in refs),
            derived_known_at=memory.known_at,
            compiler_version=memory.provenance.extractor_version,
            lineage_id="native-mr-mem",
            metadata={
                "attributes": dict(memory.attributes),
                "supports_memory_ids": memory.supports_memory_ids,
                "contradicts_memory_ids": memory.contradicts_memory_ids,
                "supersedes_memory_id": memory.supersedes_memory_id,
            },
        )

    def _verify(self, block: SemanticBlock, *, current_valid: bool = True) -> SemanticBlock:
        expected = self._view(self._eligible(block.block_id, current_valid=current_valid))
        if replace(block, state_id=None) != expected:
            raise KeyError("projection differs from canonical accepted semantic state")
        return block

    def register(self, memories: tuple[CommittedMemory, ...]) -> None:
        for memory in memories:
            super().put_semantic_block(self._view(self._eligible(memory.memory_id)))

    def put_semantic_block(self, block: SemanticBlock) -> SemanticBlock:
        return super().put_semantic_block(self._verify(block))

    def get_semantic_block(self, block_id: str) -> SemanticBlock:
        return self._verify(super().get_semantic_block(block_id))

    def get_semantic_block_state(self, state_id: str) -> SemanticBlock:
        return self._verify(super().get_semantic_block_state(state_id))

    def list_semantic_blocks(self, *, current_valid_only: bool = True) -> tuple[SemanticBlock, ...]:
        blocks = super().list_semantic_blocks(current_valid_only=current_valid_only)
        accepted = []
        for block in blocks:
            try:
                accepted.append(self._verify(block, current_valid=current_valid_only))
            except KeyError:
                continue
        return tuple(accepted)

    def list_semantic_block_states(
        self,
        *,
        current_valid_only: bool = True,
    ) -> tuple[SemanticBlock, ...]:
        return self.list_semantic_blocks(current_valid_only=current_valid_only)

    def list_semantic_blocks_at_cutoff(
        self,
        cutoff: datetime,
        *,
        current_valid_only: bool = True,
    ) -> tuple[SemanticBlock, ...]:
        if cutoff.tzinfo != UTC:
            raise ValueError("knowledge cutoff must be UTC")
        return tuple(
            block
            for block in self.list_semantic_blocks(current_valid_only=current_valid_only)
            if block.derived_known_at is not None and block.derived_known_at <= cutoff
        )

    def list_semantic_blocks_at_knowledge_cutoff(
        self,
        cutoff: datetime,
        *,
        current_valid_only: bool = True,
    ) -> tuple[SemanticBlock, ...]:
        return self.list_semantic_blocks_at_cutoff(cutoff, current_valid_only=current_valid_only)

    def extend_semantic_block(
        self,
        block_id: str,
        *,
        content: str | None,
        evidence_id: str,
        occurred_at: datetime,
        derived_known_at: datetime,
    ) -> SemanticBlock:
        raise ExternalSourceMutationError("LCE cannot revise host-accepted canonical semantics")


class _PointConsumer:
    def __init__(self, substrate: AcceptedSemanticSubstrate, projection: LceProjectionCore) -> None:
        self.substrate, self.projection = substrate, projection

    def consume(self, memories: tuple[CommittedMemory, ...]) -> None:
        self.substrate.register(memories)
        for memory in memories:
            self.projection.process_semantic(memory.memory_id)


class _ThreadConsumer:
    def __init__(
        self,
        core: MemoryCore,
        substrate: AcceptedSemanticSubstrate,
        projection: LceProjectionCore,
    ) -> None:
        self.core, self.substrate, self.projection = core, substrate, projection
        self.intake = PrecomputedDraftIntake(
            memory_substrate=SemanticBlockMemoryAdapter(substrate),
            semantic_substrate=substrate,
            baseline_store=projection.baselines,
            draft_store=projection.worktrees,
            rejection_store=projection.rejections,
        )
        self.updates = ThreadAutoUpdateService(
            canonical=core.canonical,
            product=core.products,
            projection_compiler=self,
        )

    def compile(self, thread: MemoryThread) -> str | None:
        if thread.working_summary is None:
            return None
        blocks = tuple(self.substrate.get_semantic_block(mid) for mid in thread.handoff_memory_ids)
        selected = tuple(
            AuthorizedSelectedSupport(block.block_id, block.state_id or "") for block in blocks
        )
        identity = json.dumps(
            [
                thread.thread_id,
                thread.working_summary,
                [(s.block_id, s.state_id) for s in selected],
            ],
            ensure_ascii=False,
        )
        try:
            result = self.intake.stage_and_promote(
                PrecomputedDraftInput(
                    region_id="mr-thread:" + thread.thread_id,
                    content=thread.working_summary,
                    supporting_memory_ids=thread.handoff_memory_ids,
                    selected_support=selected,
                    processing_input_id="thread-handoff:"
                    + hashlib.sha256(identity.encode()).hexdigest(),
                )
            )
        except RejectedDerivedProposalError:
            return None
        return str(result.baseline.baseline_id)

    def consume(self, memories: tuple[CommittedMemory, ...]) -> None:
        self.substrate.register(memories)
        self.updates.apply(
            scope=self.substrate.scope,
            accepted_events=memories,
            at=max(memory.known_at for memory in memories),
        )


class NativeMemoryRuntime:
    """One explicitly composed memory path for hot start and normal native turns."""

    def __init__(
        self,
        *,
        root: Path,
        core: MemoryCore,
        scope: MemoryScope,
        sources: SourceRefReader,
        cleaner: SemanticCleaner,
        clock: Clock,
        origin_runtime_id: str,
        compiler_version: str,
        block_embedder: Callable[[SemanticBlock], tuple[float, ...]],
        embedding_version: str,
        interpreter: BoundedInterpreter | None = None,
        budget: MemorySurfaceBudget = DEFAULT_SURFACE_BUDGET,
    ) -> None:
        if not callable(block_embedder) or not embedding_version.strip():
            raise ValueError("an explicit versioned semantic embedder is required")
        root.mkdir(parents=True, exist_ok=True)
        binding = {
            "scope": json.loads(scope_json(scope)),
            "semantic_store": str(core.path.resolve()),
            "origin_runtime_id": origin_runtime_id,
        }
        manifest = root / "native-memory-binding.json"
        try:
            with manifest.open("x", encoding="utf-8") as stream:
                json.dump(binding, stream, ensure_ascii=False)
        except FileExistsError:
            if json.loads(manifest.read_text(encoding="utf-8")) != binding:
                raise ValueError("native memory root binding mismatch") from None
        self.origin_runtime_id = origin_runtime_id
        self.core, self.scope, self.sources, self.clock, self.budget = (
            core,
            scope,
            sources,
            clock,
            budget,
        )
        self.substrate = AcceptedSemanticSubstrate(core, scope, sources, root / "projection-state")
        self.projection = LceProjectionCore(
            root / "lce",
            memory=self.substrate,
            block_embedder=block_embedder,
            block_embedding_version=embedding_version,
            interpreter=interpreter,
            lineage_id="native-mr-mem",
        )
        self.pipeline = HistoricalSemanticPipeline(
            path=root / "receipts.sqlite",
            core=core,
            scope=scope,
            sources=sources,
            cleaner=cleaner,
            compiler_version=compiler_version,
            admission=SemanticAdmissionService(
                store=core.canonical,
                sources=sources,
                clock=clock,
                origin_runtime_id=origin_runtime_id,
            ),
            consumers={
                "lce:accepted-v1:" + embedding_version: _PointConsumer(
                    self.substrate, self.projection
                ),
                "thread:accepted-v1": _ThreadConsumer(core, self.substrate, self.projection),
            },
        )

    def process(
        self,
        record: NativeRecord,
        *,
        context: tuple[SourceFragment, ...] = (),
    ) -> tuple[CommittedMemory, ...]:
        """Call after the native store commits the normal turn or a bounded backfill row."""
        return self.pipeline.process(record, context=context)

    def reconcile_sources(self) -> tuple[str, ...]:
        changed = {}
        for memory in self.core.load_all():
            if memory.scope != self.scope or memory.lifecycle is not MemoryLifecycle.ACTIVE:
                continue
            for ref in memory.provenance.source_refs:
                current = self.sources.current_ref(self.scope, ref)
                if current != ref:
                    changed[_source_id(ref)] = (ref, current)
        for ref, current in changed.values():
            self.core.canonical.invalidate_source(
                self.scope,
                current or ref,
                deleted=current is None,
            )
        if changed:
            self.projection.sources_changed_and_rebuild(tuple(changed), cutoff=self.clock.now())
        return tuple(changed)

    def warm_start(self, source: NativeSourceStore, *, limit: int = 100) -> int:
        """One bounded page: reconcile accepted refs, repair receipts, then append."""
        if source.scope != self.scope:
            raise ValueError("native source scope differs from runtime binding")
        self.reconcile_sources()
        self.pipeline.recover(lambda ref: source.get_record(self.scope, ref), limit=limit)
        key = source.namespace + ":" + scope_json(self.scope)
        rows = source.read(limit=limit, after=self.pipeline.source_cursor(key))
        for record in rows:
            self.process(record)
            self.pipeline.advance_source_cursor(key, record.ordering_key)
        if rows:
            self.projection.bootstrap_trajectory(knowledge_cutoff=self.clock.now())
        return len(rows)

    def read(
        self,
        *,
        interaction_id: str,
        context: Situation,
        observations: tuple[Observation, ...],
        scope: Scope,
        clock: datetime,
    ) -> HistoricalContextBundle | None:
        """Existing HistoricalContextPort; reads are source-fresh and bounded."""
        if (
            _memory_scope(scope) != self.scope
            or context.scope != scope
            or context.origin_runtime_id != self.origin_runtime_id
            or any(o.scope != scope for o in observations)
            or clock.tzinfo != UTC
        ):
            return None
        texts = [
            str(o.value["text"])
            for o in observations
            if o.interaction_id == interaction_id
            and o.type == "factual"
            and o.key == "user_message.observed"
            and isinstance(o.value, Mapping)
            and isinstance(o.value.get("text"), str)
        ]
        text = "\n".join(texts)[:4096]
        if not text.strip() or self.budget.max_items == 0:
            return None
        memories = tuple(
            memory
            for memory in self.core.load_all()
            if memory.scope == self.scope
            and memory.known_at < clock
            and memory.lifecycle is MemoryLifecycle.ACTIVE
            and memory.provenance.source_refs
            and all(
                self.sources.current_ref(self.scope, ref) == ref
                for ref in memory.provenance.source_refs
            )
        )
        by_id = {m.memory_id: m for m in memories}
        items: list[HistoricalContextItem] = []

        def add(key: str, kind: str, proposition: str, ids: tuple[str, ...]) -> None:
            if not ids or any(mid not in by_id for mid in ids):
                return
            refs = tuple(
                sorted(
                    {_source_id(ref) for mid in ids for ref in by_id[mid].provenance.source_refs}
                )
            )
            items.append(
                HistoricalContextItem(
                    key,
                    scope,
                    key,
                    kind,
                    proposition,
                    refs,
                    None,
                    None,
                )
            )

        for view in self.projection.query(text):
            head = self.projection.baselines.get_head(view.region_id)
            if (
                head is None
                or head.created_at >= clock
                or head.baseline_id != view.baseline_id
                or head.revision_number != view.revision_number
            ):
                continue
            add(
                view.baseline_id,
                "lce.accepted_understanding",
                view.content,
                view.supporting_semantic_block_ids,
            )
        tokens = set(lexical_tokens(text))
        for thread in self.core.products.surface_threads(self.scope, now=clock):
            proposition = thread.working_summary or thread.open_question
            if tokens & set(lexical_tokens(proposition)):
                add(
                    thread.thread_id,
                    "memory.thread_projection",
                    proposition,
                    thread.handoff_memory_ids,
                )
        retrieved = MemoryRetrievalService(
            store=self.core.canonical,
            provider=BM25RetrievalProvider(memories),
        ).search(MemoryRetrievalQuery(self.scope, text, self.budget.max_items))
        for hit in retrieved:
            add(
                hit.memory.memory_id,
                "memory.canonical",
                hit.memory.content,
                (hit.memory.memory_id,),
            )
        remaining, selected = self.budget.max_characters, []
        for item in items:
            if len(item.proposition) > remaining:
                continue
            selected.append(item)
            remaining -= len(item.proposition)
            if len(selected) == self.budget.max_items:
                break
        if not selected:
            return None
        return HistoricalContextBundle(
            "native-memory:" + interaction_id,
            scope,
            context.origin_runtime_id,
            tuple(selected),
            (),
            (),
            (),
            tuple(sorted({ref for item in selected for ref in item.source_refs})),
            "native-source/accepted-semantic/thread-lce",
        )

    def close(self) -> None:
        self.pipeline.close()
        self.projection.close()
        self.substrate.close()
