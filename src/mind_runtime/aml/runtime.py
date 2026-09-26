"""AML Add/Search runtime composed from MR Memory, Thread, LCE and decision seams."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from collections import OrderedDict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from mind_runtime.aml.contracts import (
    AmlAddRequest,
    AmlMessage,
    AmlRuntimeConfig,
    AmlSearchItem,
    AmlSearchRequest,
)
from mind_runtime.aml.providers import AmlThreadSemanticPort
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
from mind_runtime.facts.persistence import SqliteFactBackend, SqliteFactReader
from mind_runtime.facts.service import FactIngestService
from mind_runtime.memory.admission import MemoryAdmissionService
from mind_runtime.memory.contracts import CommittedMemory
from mind_runtime.memory.core import MemoryCore
from mind_runtime.memory.embedding import EmbeddingProvider
from mind_runtime.memory.product import MemoryProductStore, ThreadStatus
from mind_runtime.memory.providers.bm25 import (
    BM25RetrievalProvider,
    lexical_tokens,
)
from mind_runtime.memory.providers.dense import InMemoryDenseRetrievalProvider
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
    from lce.cognition.promotion import BoundedInterpreter, PromotionPolicy
    from lce.semantic.contracts import SemanticDecisionProvider
    from lce.structure.contracts import StructureConfig


class AmlRequestConflict(ValueError):
    """A request_id was replayed with different immutable content."""


class _MutableClock:
    def __init__(self, value: datetime) -> None:
        self._value = value

    def set(self, value: datetime) -> None:
        if value.tzinfo is not UTC:
            raise ValueError("AML runtime clock requires UTC")
        self._value = value

    def now(self) -> datetime:
        return self._value


class _RequestJournal:
    def __init__(self, path: Path) -> None:
        self._conn = sqlite3.connect(path)
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS aml_add_requests (
                request_id TEXT PRIMARY KEY,
                fingerprint TEXT NOT NULL,
                received_at TEXT NOT NULL,
                complete INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        self._conn.commit()

    def reserve(
        self,
        request_id: str,
        fingerprint: str,
        *,
        now: datetime,
    ) -> tuple[datetime, bool]:
        row = self._conn.execute(
            "SELECT fingerprint, received_at, complete "
            "FROM aml_add_requests WHERE request_id=?",
            (request_id,),
        ).fetchone()
        if row is not None:
            if row[0] != fingerprint:
                raise AmlRequestConflict(
                    "request_id replayed with different content"
                )
            return datetime.fromisoformat(row[1]), bool(row[2])
        with self._conn:
            self._conn.execute(
                "INSERT INTO aml_add_requests VALUES (?, ?, ?, 0)",
                (request_id, fingerprint, now.isoformat()),
            )
        return now, False

    def complete(self, request_id: str) -> None:
        with self._conn:
            self._conn.execute(
                "UPDATE aml_add_requests SET complete=1 WHERE request_id=?",
                (request_id,),
            )

    def close(self) -> None:
        self._conn.close()


@dataclass(frozen=True, slots=True)
class _UserBinding:
    binding: RuntimeBinding
    scope: Scope
    paths: StoragePaths


def _request_fingerprint(request: AmlAddRequest) -> str:
    payload = {
        "user_id": request.user_id,
        "session_id": request.session_id,
        "messages": [
            {
                "role": item.role,
                "content": item.content,
                "timestamp": item.timestamp,
            }
            for item in request.messages
        ],
    }
    encoded = json.dumps(
        payload,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


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
    encoded = json.dumps(
        ["aml-evidence-v1", user_id, session_id, request_id, index],
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode()
    return "aml-evidence-" + hashlib.sha256(encoded).hexdigest()[:32]


def _thread_candidate_id(evidence_id: str) -> str:
    return "aml-thread-" + hashlib.sha256(evidence_id.encode()).hexdigest()[:24]


class AmlMemoryRuntime:
    """AML protocol-independent service logic over the reusable Memory stack."""

    def __init__(
        self,
        root: Path | str,
        *,
        config: AmlRuntimeConfig | None = None,
        embedding: EmbeddingProvider | None = None,
        hyde_expander: QueryExpander | None = None,
        decision: DecisionCapability | None = None,
        thread_semantics: AmlThreadSemanticPort | None = None,
        lce_semantic_provider: SemanticDecisionProvider | None = None,
        lce_interpreter: BoundedInterpreter | None = None,
        lce_policy: PromotionPolicy | None = None,
        lce_structure_config: StructureConfig | None = None,
    ) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.config = config or AmlRuntimeConfig()
        self._embedding = embedding
        self._hyde_expander = hyde_expander
        self._decision = decision
        self._thread_semantics = thread_semantics
        self._lce_semantic_provider = lce_semantic_provider
        self._lce_interpreter = lce_interpreter
        self._lce_policy = lce_policy
        self._lce_structure_config = lce_structure_config
        self._locks_guard = threading.Lock()
        self._locks: dict[str, threading.RLock] = {}
        self._retrieval_cache: OrderedDict[str, RetrievalProvider] = OrderedDict()
        self._cache_guard = threading.Lock()
        self._production_sentinel = self.root.parent / (
            self.root.name + "-aml-production-sentinel"
        )

    @staticmethod
    def _user_key(user_id: str) -> str:
        return hashlib.sha256(user_id.encode("utf-8")).hexdigest()[:24]

    def _lock(self, user_id: str) -> threading.RLock:
        key = self._user_key(user_id)
        with self._locks_guard:
            lock = self._locks.get(key)
            if lock is None:
                lock = threading.RLock()
                self._locks[key] = lock
            return lock

    def _user(self, user_id: str) -> _UserBinding:
        key = self._user_key(user_id)
        binding = RuntimeBinding(
            persona_id="aml-memory",
            agent_id="aml-evaluator",
            runtime_id=f"aml-{key}",
            storage_namespace=f"aml/{key}",
            environment=RuntimeEnvironment.LAB,
        )
        paths = bind_storage(
            binding,
            lab_root=self.root,
            production_root=self._production_sentinel,
        )
        return _UserBinding(
            binding,
            Scope(ScopeDomain.USER, user_id=user_id),
            paths,
        )

    def _invalidate_retrieval(self, user_id: str) -> None:
        key = self._user_key(user_id)
        with self._cache_guard:
            self._retrieval_cache.pop(key, None)

    def _provider(
        self,
        *,
        user_id: str,
        memories: tuple[CommittedMemory, ...],
    ) -> RetrievalProvider:
        key = self._user_key(user_id)
        with self._cache_guard:
            cached = self._retrieval_cache.get(key)
            if cached is not None:
                self._retrieval_cache.move_to_end(key)
                return cached

        lexical: RetrievalProvider = BM25RetrievalProvider(memories)
        provider: RetrievalProvider = lexical
        if self._embedding is not None:
            dense = InMemoryDenseRetrievalProvider(
                memories,
                embedding=self._embedding,
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

        with self._cache_guard:
            self._retrieval_cache[key] = provider
            self._retrieval_cache.move_to_end(key)
            while (
                len(self._retrieval_cache)
                > self.config.retrieval_cache_users
            ):
                self._retrieval_cache.popitem(last=False)
        return provider

    @staticmethod
    def _memory_ids_for_evidence(
        store: CanonicalMemoryStore,
        evidence_ids: set[str],
    ) -> tuple[str, ...]:
        matches = [
            memory
            for memory in store.load_all()
            if set(memory.provenance.evidence_refs) & evidence_ids
        ]
        matches.sort(
            key=lambda item: (item.committed_at, item.memory_id)
        )
        return tuple(item.memory_id for item in matches)

    def add(self, request: AmlAddRequest) -> None:
        user = self._user(request.user_id)
        with self._lock(request.user_id):
            journal = _RequestJournal(
                user.paths.root / "aml_adapter.sqlite"
            )
            fingerprint = _request_fingerprint(request)
            now = datetime.now(UTC)
            received_at, complete = journal.reserve(
                request.request_id,
                fingerprint,
                now=now,
            )
            if complete:
                journal.close()
                return

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
            product = MemoryProductStore(
                user.paths.memory_db,
                canonical,
            )
            threads = ThreadAutoUpdateService(
                canonical=canonical,
                product=product,
            )

            evidence_ids: list[str] = []
            try:
                visible: list[AmlMessage] = []
                for index, message in enumerate(request.messages):
                    occurred_at = (
                        _epoch_timestamp(message.timestamp)
                        if message.timestamp is not None
                        else received_at + timedelta(microseconds=index)
                    )
                    event_received_at = max(received_at, occurred_at)
                    clock.set(event_received_at)
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
                        received_at=event_received_at,
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
                            f"aml:{fingerprint}:{index}",
                        ),
                    )
                    interaction_id = (
                        f"aml:{request.session_id}:"
                        f"{request.request_id}:{index}"
                    )
                    facts.admit(
                        evidence,
                        interaction_id=interaction_id,
                        writing_runtime=user.binding.runtime_id,
                        writing_persona_id=None,
                    )
                    evidence_ids.append(evidence_id)
                    visible.append(message)

                    if (
                        self.config.thread_enabled
                        and self._thread_semantics is not None
                    ):
                        try:
                            active_threads = tuple(
                                " :: ".join(
                                    part
                                    for part in (
                                        thread.open_question,
                                        thread.working_summary,
                                    )
                                    if part
                                )
                                for thread in product.list_threads(
                                    user.scope,
                                    status=ThreadStatus.OPEN,
                                    include_suppressed=False,
                                )
                            )
                            semantic = self._thread_semantics.analyze(
                                message=message,
                                context=tuple(visible),
                                active_threads=active_threads,
                            )
                        except Exception:
                            semantic = None
                        if semantic is not None and semantic.action != "none":
                            attrs = [
                                ("thread_action", semantic.action),
                            ]
                            if semantic.question is not None:
                                attrs.append(
                                    ("thread_question", semantic.question)
                                )
                            if semantic.summary is not None:
                                attrs.append(
                                    ("thread_summary", semantic.summary)
                                )
                            if semantic.mature:
                                attrs.append(("thread_mature", "true"))
                            event = SemanticEventCandidate(
                                candidate_id=_thread_candidate_id(
                                    evidence_id
                                ),
                                scope=user.scope,
                                origin_runtime_id=user.binding.runtime_id,
                                kind="aml.thread_signal",
                                attributes=tuple(attrs),
                                confidence=float(semantic.confidence),
                                evidence_refs=(evidence_id,),
                            )
                            threads.apply(
                                scope=user.scope,
                                accepted_events=(event,),
                                at=occurred_at,
                            )

                memory_ids = self._memory_ids_for_evidence(
                    canonical,
                    set(evidence_ids),
                )
                if len(memory_ids) < len(evidence_ids):
                    raise RuntimeError(
                        "AML Add completed factual admission without "
                        "immediately searchable canonical Memory"
                    )
            finally:
                threads.close()
                backend.close()

            if self.config.lce_enabled:
                from mind_runtime.integrations.lce import (
                    open_lce_projection_binding,
                )

                session = open_lce_projection_binding(
                    user.binding,
                    user.scope,
                    enabled=True,
                    semantic_provider=self._lce_semantic_provider,
                    interpreter=self._lce_interpreter,
                    policy=self._lce_policy,
                    structure_config=self._lce_structure_config,
                    lab_root=self.root,
                    production_root=self._production_sentinel,
                )
                if session is None:
                    journal.close()
                    raise RuntimeError(
                        "enabled LCE projection binding was unavailable"
                    )
                with session:
                    session.process_memories(memory_ids)

            self._invalidate_retrieval(request.user_id)
            journal.complete(request.request_id)
            journal.close()

    @staticmethod
    def _occurred_at(
        paths: StoragePaths,
        memory: CommittedMemory,
    ) -> datetime:
        reader = SqliteFactReader(paths.facts_db)
        try:
            occurred = []
            for evidence_id in memory.provenance.evidence_refs:
                pair = reader.find_evidence(
                    memory.scope,
                    evidence_id,
                )
                if pair is not None:
                    occurred.append(pair[0].occurred_at)
        finally:
            reader.close()
        return max(occurred, default=memory.committed_at)

    def _raw_items(
        self,
        *,
        user: _UserBinding,
        query: str,
        output_limit: int,
    ) -> tuple[AmlSearchItem, ...]:
        if not user.paths.memory_db.exists():
            return ()
        with MemoryCore(
            user.paths.memory_db,
            read_only=True,
        ) as core:
            memories = tuple(
                memory
                for memory in core.load_all()
                if memory.scope == user.scope
            )
            if not memories:
                return ()
            candidate_limit = max(
                output_limit,
                self.config.candidate_limit,
            )
            provider = self._provider(
                user_id=user.scope.user_id or "",
                memories=memories,
            )
            service = MemoryRetrievalService(
                store=core.canonical,
                provider=provider,
                decision=self._decision,
            )
            resolved = service.search(
                MemoryRetrievalQuery(
                    user.scope,
                    query,
                    min(100, candidate_limit),
                ),
                budget=MemorySurfaceBudget(
                    max_items=min(100, candidate_limit),
                    max_characters=self.config.max_context_characters,
                ),
            )
            return tuple(
                AmlSearchItem(
                    id=item.memory.memory_id,
                    content=(
                        f"[{self._occurred_at(user.paths, item.memory).date().isoformat()}] "
                        f"{item.memory.content}"
                    ),
                    score=1.0 / rank,
                    created_at=self._occurred_at(
                        user.paths, item.memory
                    ).isoformat(),
                    layer="memory",
                )
                for rank, item in enumerate(resolved, 1)
            )

    def _thread_items(
        self,
        *,
        user: _UserBinding,
        query: str,
    ) -> tuple[AmlSearchItem, ...]:
        if (
            not self.config.thread_enabled
            or self.config.thread_cap == 0
            or not user.paths.memory_db.exists()
        ):
            return ()
        query_tokens = set(lexical_tokens(query))
        if not query_tokens:
            return ()
        with MemoryCore(
            user.paths.memory_db,
            read_only=True,
        ) as core:
            ranked = []
            for thread in core.products.list_threads(
                user.scope,
                status=ThreadStatus.OPEN,
                include_suppressed=False,
            ):
                text = " ".join(
                    item
                    for item in (
                        thread.open_question,
                        thread.working_summary,
                    )
                    if item
                )
                tokens = set(lexical_tokens(text))
                overlap = len(tokens & query_tokens)
                if overlap == 0:
                    continue
                relevance = overlap / max(1, len(query_tokens))
                support = tuple(
                    memory
                    for memory_id in thread.handoff_memory_ids
                    if (
                        memory := core.get(memory_id)
                    ) is not None
                )
                support_lines = [
                    (
                        f"[{self._occurred_at(user.paths, memory).date().isoformat()}] "
                        f"{memory.content}"
                    )
                    for memory in support
                ]
                content = (
                    "[Thread working context]\n"
                    + (thread.working_summary or thread.open_question)
                )
                if support_lines:
                    content += "\nSupport:\n" + "\n".join(
                        f"- {line}" for line in support_lines
                    )
                ranked.append(
                    (
                        relevance,
                        thread.updated_at,
                        AmlSearchItem(
                            id=f"thread:{thread.thread_id}",
                            content=content,
                            score=2.0 + relevance,
                            created_at=thread.updated_at.isoformat(),
                            layer="thread",
                        ),
                    )
                )
        ranked.sort(
            key=lambda item: (item[0], item[1]),
            reverse=True,
        )
        return tuple(
            item[2] for item in ranked[: self.config.thread_cap]
        )

    def _lce_items(
        self,
        *,
        user: _UserBinding,
        query: str,
    ) -> tuple[AmlSearchItem, ...]:
        if (
            not self.config.lce_enabled
            or self.config.lce_cap == 0
            or not user.paths.memory_db.exists()
        ):
            return ()
        from mind_runtime.integrations.lce import (
            open_lce_projection_binding,
        )

        session = open_lce_projection_binding(
            user.binding,
            user.scope,
            enabled=True,
            semantic_provider=self._lce_semantic_provider,
            interpreter=self._lce_interpreter,
            policy=self._lce_policy,
            structure_config=self._lce_structure_config,
            lab_root=self.root,
            production_root=self._production_sentinel,
        )
        if session is None:
            return ()
        with session:
            views = session.accepted_understandings(
                query,
                limit=self.config.lce_cap,
            )

        with MemoryCore(
            user.paths.memory_db,
            read_only=True,
        ) as core:
            items = []
            for view in views:
                support = tuple(
                    memory
                    for memory_id in view.supporting_memory_ids
                    if (
                        memory := core.get(memory_id)
                    ) is not None
                )
                support_lines = [
                    (
                        f"[{self._occurred_at(user.paths, memory).date().isoformat()}] "
                        f"{memory.content}"
                    )
                    for memory in support
                ]
                content = (
                    "[LCE longitudinal understanding]\n"
                    + view.content
                )
                if support_lines:
                    content += "\nSupport:\n" + "\n".join(
                        f"- {line}" for line in support_lines
                    )
                created_at = max(
                    (
                        self._occurred_at(user.paths, memory)
                        for memory in support
                    ),
                    default=datetime.now(UTC),
                )
                items.append(
                    AmlSearchItem(
                        id=f"lce:{view.baseline_id}",
                        content=content,
                        score=3.0 + view.relevance,
                        created_at=created_at.isoformat(),
                        layer="lce",
                    )
                )
        return tuple(items)

    def search(
        self, request: AmlSearchRequest
    ) -> tuple[AmlSearchItem, ...]:
        user = self._user(request.user_id)
        with self._lock(request.user_id):
            query = request.query
            if request.options:
                query += " " + " ".join(
                    item for item in request.options if item.strip()
                )
            output_limit = min(
                request.top_k,
                self.config.result_cap,
            )
            candidates = (
                *self._lce_items(user=user, query=query),
                *self._thread_items(user=user, query=query),
                *self._raw_items(
                    user=user,
                    query=query,
                    output_limit=output_limit,
                ),
            )
            selected: list[AmlSearchItem] = []
            seen: set[str] = set()
            remaining = self.config.max_context_characters
            for item in candidates:
                if item.id in seen or len(item.content) > remaining:
                    continue
                seen.add(item.id)
                selected.append(item)
                remaining -= len(item.content)
                if len(selected) >= output_limit:
                    break
            return tuple(selected)
