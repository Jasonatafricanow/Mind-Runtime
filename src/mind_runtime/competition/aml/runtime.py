"""AML Add/Search composition over current MR public seams.

This module owns benchmark protocol policy only. Canonical Memory, Thread and
LCE keep their existing authority and persistence rules.
"""

from __future__ import annotations

import hashlib
import json
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from mind_runtime.competition.aml.contracts import (
    AmlAddRequest,
    AmlMessage,
    AmlRuntimeConfig,
    AmlSearchItem,
    AmlSearchRequest,
)
from mind_runtime.competition.aml.journal import AmlRequestJournal
from mind_runtime.competition.aml.semantic import AmlHostSemanticPort
from mind_runtime.contracts import (
    Authority,
    AuthorityLevel,
    Evidence,
    Scope,
    ScopeDomain,
    SemanticEventCandidate,
    SyncFields,
)
from mind_runtime.decision import DecisionCapability
from mind_runtime.facts.persistence import SqliteFactBackend
from mind_runtime.facts.service import FactIngestService
from mind_runtime.integrations.lce import (
    LceThreadProjectionCompiler,
    open_lce_read_binding,
)
from mind_runtime.integrations.lce_projection import (
    open_lce_projection_binding,
)
from mind_runtime.memory.admission import MemoryAdmissionService
from mind_runtime.memory.contracts import CommittedMemory, MemoryLifecycle
from mind_runtime.memory.embedding import EmbeddingProvider
from mind_runtime.memory.product import MemoryProductStore, ThreadStatus
from mind_runtime.memory.providers.bm25 import (
    BM25RetrievalProvider,
    lexical_tokens,
)
from mind_runtime.memory.providers.dense import (
    InMemoryDenseRetrievalProvider,
    SqliteCachedEmbeddingProvider,
)
from mind_runtime.memory.providers.hybrid import (
    HybridRRFProvider,
    HyDEFallbackProvider,
    QueryExpander,
    RetrievalArm,
)
from mind_runtime.memory.retrieval import (
    MemoryRetrievalQuery,
    MemoryRetrievalService,
    MemorySurfaceBudget,
    RetrievalProvider,
)
from mind_runtime.memory.store import CanonicalMemoryStore
from mind_runtime.memory.threading import ThreadAutoUpdateService
from mind_runtime.runtime_binding import (
    RuntimeBinding,
    RuntimeEnvironment,
    StoragePaths,
    bind_storage,
)

if TYPE_CHECKING:
    from lce.cognition.promotion import BoundedInterpreter
    from lce.semantic.contracts import SemanticDecisionProvider


RetrievalProviderFactory = Callable[
    [tuple[CommittedMemory, ...]],
    RetrievalProvider,
]


class _MutableClock:
    def __init__(self, value: datetime) -> None:
        self._value = value

    def set(self, value: datetime) -> None:
        if value.tzinfo != UTC:
            raise ValueError("competition clock requires aware UTC")
        self._value = value

    def now(self) -> datetime:
        return self._value


@dataclass(frozen=True, slots=True)
class _UserRuntime:
    binding: RuntimeBinding
    scope: Scope
    paths: StoragePaths


_STAGE_ORDER = {
    "reserved": 0,
    "canonical": 1,
    "thread": 2,
    "lce": 3,
    "complete": 4,
}


def _at_least(stage: str, required: str) -> bool:
    try:
        return _STAGE_ORDER[stage] >= _STAGE_ORDER[required]
    except KeyError as exc:
        raise ValueError(f"unknown AML processing stage: {stage}") from exc


def _epoch_timestamp(value: float | int) -> datetime:
    raw = float(value)
    if abs(raw) >= 100_000_000_000:
        raw /= 1000.0
    return datetime.fromtimestamp(raw, tz=UTC)


def _evidence_id(
    *,
    user_id: str,
    session_id: str,
    request_id: str,
    index: int,
) -> str:
    payload = json.dumps(
        ["aml-evidence-v2", user_id, session_id, request_id, index],
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode()
    return "aml-evidence-" + hashlib.sha256(payload).hexdigest()[:32]


def _event_payload(event: SemanticEventCandidate) -> dict[str, object]:
    return {
        "candidate_id": event.candidate_id,
        "kind": event.kind,
        "attributes": list(event.attributes),
        "confidence": event.confidence,
        "evidence_refs": list(event.evidence_refs),
    }


def _event_from_payload(
    payload: object,
    *,
    scope: Scope,
    origin_runtime_id: str,
) -> SemanticEventCandidate:
    if not isinstance(payload, dict):
        raise ValueError("stored semantic event payload must be an object")
    attributes = payload.get("attributes")
    evidence_refs = payload.get("evidence_refs")
    if not isinstance(attributes, list) or not isinstance(
        evidence_refs, list
    ):
        raise ValueError("stored semantic event payload is malformed")
    return SemanticEventCandidate(
        candidate_id=str(payload["candidate_id"]),
        scope=scope,
        origin_runtime_id=origin_runtime_id,
        kind=str(payload["kind"]),
        attributes=tuple(
            (str(item[0]), str(item[1]))
            for item in attributes
            if isinstance(item, list) and len(item) == 2
        ),
        confidence=float(payload["confidence"]),
        evidence_refs=tuple(str(item) for item in evidence_refs),
    )


class AmlCompetitionRuntime:
    """Deterministic AML processing boundary over current MR/LCE."""

    def __init__(
        self,
        root: Path | str,
        *,
        run_id: str,
        config: AmlRuntimeConfig | None = None,
        semantic: AmlHostSemanticPort | None = None,
        retrieval_provider_factory: RetrievalProviderFactory | None = None,
        embedding: EmbeddingProvider | None = None,
        hyde_expander: QueryExpander | None = None,
        decision: DecisionCapability | None = None,
        lce_provider: SemanticDecisionProvider | None = None,
        lce_interpreter: BoundedInterpreter | None = None,
    ) -> None:
        if not isinstance(run_id, str) or not run_id.strip():
            raise ValueError("run_id must be nonempty")
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.run_id = run_id
        self.config = config or AmlRuntimeConfig()
        if self.config.thread_enabled and semantic is None:
            raise ValueError(
                "thread_enabled requires a Body/Host semantic adapter"
            )
        self._semantic = semantic
        self._provider_factory = retrieval_provider_factory
        self._embedding = embedding
        self._hyde_expander = hyde_expander
        self._decision = decision
        self._lce_provider = lce_provider
        self._lce_interpreter = lce_interpreter
        self._locks_guard = threading.Lock()
        self._locks: dict[str, threading.RLock] = {}
        self._production_sentinel = (
            self.root.parent / f"{self.root.name}-no-production"
        )

    @staticmethod
    def _user_key(user_id: str) -> str:
        return hashlib.sha256(user_id.encode("utf-8")).hexdigest()[:24]

    def _lock(self, user_id: str) -> threading.RLock:
        key = self._user_key(user_id)
        with self._locks_guard:
            current = self._locks.get(key)
            if current is None:
                current = threading.RLock()
                self._locks[key] = current
            return current

    def _user(self, user_id: str) -> _UserRuntime:
        key = self._user_key(user_id)
        binding = RuntimeBinding(
            persona_id="aml-memory",
            agent_id="aml-evaluator",
            runtime_id=f"aml-{key}",
            storage_namespace=f"competition/aml/{self.run_id}/{key}",
            environment=RuntimeEnvironment.LAB,
        )
        paths = bind_storage(
            binding,
            lab_root=self.root,
            production_root=self._production_sentinel,
        )
        return _UserRuntime(
            binding=binding,
            scope=Scope(ScopeDomain.USER, user_id=user_id),
            paths=paths,
        )

    def _retrieval_provider(
        self,
        *,
        user_id: str,
        memories: tuple[CommittedMemory, ...],
    ) -> RetrievalProvider:
        if self._provider_factory is not None:
            return self._provider_factory(memories)

        lexical: RetrievalProvider = BM25RetrievalProvider(memories)
        provider: RetrievalProvider = lexical
        if self._embedding is not None:
            cache = SqliteCachedEmbeddingProvider(
                self._embedding,
                self.root
                / "_derived_embedding_cache"
                / f"{self._user_key(user_id)}.sqlite",
            )
            dense = InMemoryDenseRetrievalProvider(
                memories,
                embedding=cache,
            )
            provider = HybridRRFProvider(
                (
                    RetrievalArm("bm25", lexical),
                    RetrievalArm("dense", dense),
                ),
                rrf_k=60,
                candidate_multiplier=4,
            )
        if self._hyde_expander is not None:
            provider = HyDEFallbackProvider(
                provider,
                self._hyde_expander,
                min_results=self.config.hyde_min_results,
                rrf_k=60,
                candidate_multiplier=4,
            )
        return provider

    @staticmethod
    def _memory_ids_for_evidence(
        store: CanonicalMemoryStore,
        evidence_ids: set[str],
        *,
        scope: Scope,
    ) -> tuple[str, ...]:
        result = [
            memory
            for memory in store.load_all()
            if (
                memory.scope == scope
                and memory.lifecycle is MemoryLifecycle.ACTIVE
                and bool(
                    set(memory.provenance.evidence_refs)
                    & evidence_ids
                )
            )
        ]
        result.sort(key=lambda item: (item.committed_at, item.memory_id))
        return tuple(item.memory_id for item in result)

    def _canonical_admission(
        self,
        request: AmlAddRequest,
        user: _UserRuntime,
        *,
        received_at: datetime,
    ) -> tuple[str, ...]:
        clock = _MutableClock(received_at)
        backend = SqliteFactBackend(user.paths.facts_db)
        canonical = CanonicalMemoryStore(user.paths.memory_db)
        admission = MemoryAdmissionService(
            store=canonical,
            facts=backend,
            clock=clock,
            origin_runtime_id=user.binding.runtime_id,
            enabled=True,
        )
        facts = FactIngestService(
            clock=clock,
            backend=backend,
            after_admission=admission,
        )
        evidence_ids: list[str] = []
        try:
            for index, message in enumerate(request.messages):
                occurred_at = (
                    _epoch_timestamp(message.timestamp)
                    if message.timestamp is not None
                    else received_at + timedelta(microseconds=index)
                )
                known_at = received_at + timedelta(microseconds=index)
                clock.set(known_at)
                evidence_id = _evidence_id(
                    user_id=request.user_id,
                    session_id=request.session_id,
                    request_id=request.request_id,
                    index=index,
                )
                source_id = (
                    f"aml-transcript:{request.request_id}:{index}"
                )
                evidence = Evidence(
                    id=evidence_id,
                    source_type="typed_event",
                    source_id=source_id,
                    authority_level=AuthorityLevel.ASSERTED,
                    occurred_at=occurred_at,
                    received_at=known_at,
                    payload={
                        "text": f"{message.role}: {message.content}",
                        "role": message.role,
                    },
                    scope=user.scope,
                    origin_runtime_id=user.binding.runtime_id,
                    authority=Authority(
                        user.scope,
                        AuthorityLevel.ASSERTED,
                        source_id,
                    ),
                    sync=SyncFields(
                        user.scope,
                        user.binding.runtime_id,
                        evidence_id,
                        1,
                        f"aml:{request.request_id}:{index}",
                    ),
                )
                facts.admit(
                    evidence,
                    interaction_id=(
                        f"aml:{request.session_id}:"
                        f"{request.request_id}:{index}"
                    ),
                    writing_runtime=user.binding.runtime_id,
                    writing_persona_id=None,
                )
                evidence_ids.append(evidence_id)
            memory_ids = self._memory_ids_for_evidence(
                canonical,
                set(evidence_ids),
                scope=user.scope,
            )
            if len(memory_ids) < len(evidence_ids):
                raise RuntimeError(
                    "AML Add did not produce immediately searchable "
                    "canonical Memory for every admitted transcript item"
                )
            return memory_ids
        finally:
            canonical.close()
            backend.close()

    def _thread_stage(
        self,
        request: AmlAddRequest,
        user: _UserRuntime,
        journal: AmlRequestJournal,
        *,
        received_at: datetime,
    ) -> None:
        if not self.config.thread_enabled:
            return
        assert self._semantic is not None
        canonical = CanonicalMemoryStore(user.paths.memory_db)
        product = MemoryProductStore(user.paths.memory_db, canonical)
        compiler = (
            LceThreadProjectionCompiler(
                binding=user.binding,
                enabled=True,
                lab_root=self.root,
                production_root=self._production_sentinel,
            )
            if self.config.lce_enabled
            else None
        )
        threads = ThreadAutoUpdateService(
            canonical=canonical,
            product=product,
            projection_compiler=compiler,
            decision=self._decision,
        )
        visible: list[AmlMessage] = []
        try:
            for index, message in enumerate(request.messages):
                visible.append(message)
                evidence_id = _evidence_id(
                    user_id=request.user_id,
                    session_id=request.session_id,
                    request_id=request.request_id,
                    index=index,
                )
                artifact_name = f"thread-events:{index}"
                stored = journal.load_artifact(
                    request.request_id,
                    artifact_name,
                )
                if stored is None:
                    active = product.list_threads(
                        user.scope,
                        status=ThreadStatus.OPEN,
                        include_suppressed=True,
                    )
                    events = self._semantic.events(
                        message=message,
                        visible_messages=tuple(visible),
                        active_threads=active,
                        scope=user.scope,
                        origin_runtime_id=user.binding.runtime_id,
                        evidence_ref=evidence_id,
                    )
                    for event in events:
                        if (
                            event.scope != user.scope
                            or event.origin_runtime_id
                            != user.binding.runtime_id
                            or set(event.evidence_refs) != {evidence_id}
                        ):
                            raise ValueError(
                                "AML Host semantic event exceeded its "
                                "trusted message authority"
                            )
                    journal.save_artifact(
                        request.request_id,
                        artifact_name,
                        [_event_payload(event) for event in events],
                    )
                else:
                    if not isinstance(stored, list):
                        raise ValueError(
                            "stored thread semantic artifact is malformed"
                        )
                    events = tuple(
                        _event_from_payload(
                            item,
                            scope=user.scope,
                            origin_runtime_id=user.binding.runtime_id,
                        )
                        for item in stored
                    )
                threads.apply(
                    scope=user.scope,
                    accepted_events=events,
                    at=received_at + timedelta(microseconds=index),
                )
        finally:
            threads.close()

    def _lce_stage(
        self,
        user: _UserRuntime,
        memory_ids: tuple[str, ...],
        *,
        received_at: datetime,
    ) -> None:
        if not self.config.lce_enabled or not memory_ids:
            return
        session = open_lce_projection_binding(
            user.binding,
            user.scope,
            enabled=True,
            provider=self._lce_provider,
            interpreter=self._lce_interpreter,
            lab_root=self.root,
            production_root=self._production_sentinel,
        )
        if session is None:
            raise RuntimeError("enabled AML LCE binding was unavailable")
        with session:
            session.sync_memory_ids(memory_ids, mode="nearline")
            if self.config.lce_bootstrap_on_add:
                session.bootstrap_trajectory(
                    knowledge_cutoff=received_at
                    + timedelta(seconds=1),
                )

    def add(self, request: AmlAddRequest) -> None:
        user = self._user(request.user_id)
        with self._lock(request.user_id):
            journal = AmlRequestJournal(
                user.paths.root / "aml_request_journal.sqlite"
            )
            try:
                received_at, stage = journal.reserve(request)
                if _at_least(stage, "complete"):
                    return

                evidence_ids = {
                    _evidence_id(
                        user_id=request.user_id,
                        session_id=request.session_id,
                        request_id=request.request_id,
                        index=index,
                    )
                    for index in range(len(request.messages))
                }

                if not _at_least(stage, "canonical"):
                    memory_ids = self._canonical_admission(
                        request,
                        user,
                        received_at=received_at,
                    )
                    journal.save_artifact(
                        request.request_id,
                        "memory_ids",
                        list(memory_ids),
                    )
                    journal.stage(request.request_id, "canonical")
                    stage = "canonical"
                else:
                    stored_ids = journal.load_artifact(
                        request.request_id,
                        "memory_ids",
                    )
                    if isinstance(stored_ids, list):
                        memory_ids = tuple(str(item) for item in stored_ids)
                    else:
                        canonical = CanonicalMemoryStore(
                            user.paths.memory_db,
                            read_only=True,
                        )
                        try:
                            memory_ids = self._memory_ids_for_evidence(
                                canonical,
                                evidence_ids,
                                scope=user.scope,
                            )
                        finally:
                            canonical.close()

                if not _at_least(stage, "thread"):
                    self._thread_stage(
                        request,
                        user,
                        journal,
                        received_at=received_at,
                    )
                    journal.stage(request.request_id, "thread")
                    stage = "thread"

                if not _at_least(stage, "lce"):
                    self._lce_stage(
                        user,
                        memory_ids,
                        received_at=received_at,
                    )
                    journal.stage(request.request_id, "lce")
                    stage = "lce"

                if not _at_least(stage, "complete"):
                    journal.stage(request.request_id, "complete")
            finally:
                journal.close()

    @staticmethod
    def _thread_relevance(
        query: str,
        question: str,
        summary: str | None,
    ) -> float:
        query_tokens = set(lexical_tokens(query))
        candidate_tokens = set(
            lexical_tokens(" ".join(
                part for part in (question, summary) if part
            ))
        )
        if not query_tokens or not candidate_tokens:
            return 0.0
        return len(query_tokens & candidate_tokens) / len(query_tokens)

    def search(
        self,
        request: AmlSearchRequest,
    ) -> tuple[AmlSearchItem, ...]:
        user = self._user(request.user_id)
        with self._lock(request.user_id):
            if not user.paths.memory_db.exists():
                return ()
            query = request.query
            if request.options:
                query += " " + " ".join(
                    option for option in request.options if option.strip()
                )

            canonical = CanonicalMemoryStore(
                user.paths.memory_db,
                read_only=True,
            )
            try:
                memories = tuple(
                    memory
                    for memory in canonical.load_all()
                    if (
                        memory.scope == user.scope
                        and memory.lifecycle is MemoryLifecycle.ACTIVE
                    )
                )
                provider = self._retrieval_provider(
                    user_id=request.user_id,
                    memories=memories,
                )
                raw = MemoryRetrievalService(
                    store=canonical,
                    provider=provider,
                    decision=self._decision,
                ).search(
                    MemoryRetrievalQuery(
                        user.scope,
                        query,
                        min(100, self.config.candidate_limit),
                    ),
                    budget=MemorySurfaceBudget(
                        max_items=min(
                            100,
                            self.config.candidate_limit,
                        ),
                        max_characters=self.config.max_context_characters,
                    ),
                )

                projection_items: list[AmlSearchItem] = []
                if self.config.lce_enabled and self.config.lce_cap:
                    reader = open_lce_read_binding(
                        user.binding,
                        user.scope,
                        enabled=True,
                        lab_root=self.root,
                        production_root=self._production_sentinel,
                    )
                    if reader is not None:
                        with reader:
                            for view in reader.accepted_understandings(
                                query,
                                limit=self.config.lce_cap,
                            ):
                                support = tuple(
                                    memory
                                    for memory_id in view.supporting_memory_ids
                                    if (
                                        memory := canonical.get(memory_id)
                                    )
                                    is not None
                                )
                                if not support:
                                    continue
                                projection_items.append(
                                    AmlSearchItem(
                                        item_id=(
                                            f"lce:{view.baseline_id}"
                                        ),
                                        content=(
                                            "[LCE longitudinal understanding]\n"
                                            + view.content
                                            + "\nSupport:\n"
                                            + "\n".join(
                                                f"- {item.content}"
                                                for item in support
                                            )
                                        ),
                                        score=3.0 + view.relevance,
                                        created_at=max(
                                            item.committed_at
                                            for item in support
                                        ).isoformat(),
                                        layer="lce",
                                        covers_memory_ids=tuple(
                                            item.memory_id
                                            for item in support
                                        ),
                                    )
                                )

                if self.config.thread_enabled and self.config.thread_cap:
                    product = MemoryProductStore(
                        user.paths.memory_db,
                        canonical,
                        read_only=True,
                    )
                    try:
                        ranked_threads = []
                        for thread in product.list_threads(
                            user.scope,
                            status=ThreadStatus.OPEN,
                            include_suppressed=False,
                        ):
                            relevance = self._thread_relevance(
                                query,
                                thread.open_question,
                                thread.working_summary,
                            )
                            if relevance <= 0:
                                continue
                            support = tuple(
                                memory
                                for memory_id in thread.handoff_memory_ids
                                if (
                                    memory := canonical.get(memory_id)
                                )
                                is not None
                            )
                            content = (
                                "[Thread working context]\n"
                                + (
                                    thread.working_summary
                                    or thread.open_question
                                )
                            )
                            if support:
                                content += "\nSupport:\n" + "\n".join(
                                    f"- {item.content}"
                                    for item in support
                                )
                            ranked_threads.append(
                                (
                                    relevance,
                                    thread.updated_at,
                                    AmlSearchItem(
                                        item_id=(
                                            f"thread:{thread.thread_id}"
                                        ),
                                        content=content,
                                        score=2.0 + relevance,
                                        created_at=(
                                            thread.updated_at.isoformat()
                                        ),
                                        layer="thread",
                                        covers_memory_ids=tuple(
                                            item.memory_id
                                            for item in support
                                        ),
                                    ),
                                )
                            )
                        ranked_threads.sort(
                            key=lambda item: (item[0], item[1]),
                            reverse=True,
                        )
                        projection_items.extend(
                            item
                            for _, _, item in ranked_threads[
                                : self.config.thread_cap
                            ]
                        )
                    finally:
                        product.close()

                raw_items = tuple(
                    AmlSearchItem(
                        item_id=item.memory.memory_id,
                        content=item.memory.content,
                        score=1.0 / rank,
                        created_at=item.memory.committed_at.isoformat(),
                        layer="memory",
                        covers_memory_ids=(item.memory.memory_id,),
                    )
                    for rank, item in enumerate(raw, 1)
                )
            finally:
                canonical.close()

            projection_items.sort(
                key=lambda item: (
                    0 if item.layer == "lce" else 1,
                    -item.score,
                    item.item_id,
                )
            )
            candidates = (*projection_items, *raw_items)
            limit = min(request.top_k, self.config.result_cap)
            selected: list[AmlSearchItem] = []
            seen: set[str] = set()
            covered_memory_ids: set[str] = set()
            remaining = self.config.max_context_characters
            for item in candidates:
                if (
                    item.item_id in seen
                    or (
                        item.layer == "memory"
                        and item.item_id in covered_memory_ids
                    )
                    or len(item.content) > remaining
                ):
                    continue
                selected.append(item)
                seen.add(item.item_id)
                covered_memory_ids.update(item.covers_memory_ids)
                remaining -= len(item.content)
                if len(selected) >= limit:
                    break
            return tuple(selected)
