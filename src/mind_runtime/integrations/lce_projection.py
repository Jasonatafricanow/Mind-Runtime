"""Current LCE Path-B binding over MR-owned canonical Memory.

MR remains the factual authority. This module exposes a read-only canonical
source adapter to LCE and gives LCE its own derived projection store. No MR
Memory row is copied into an LCE factual database.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from mind_runtime.contracts import Scope
from mind_runtime.facts.persistence import SqliteFactReader
from mind_runtime.integrations.lce import (
    LceAcceptedUnderstanding,
    LceIntegrationUnavailable,
    MrMemorySubstrateAdapter,
    _accepted_understandings,
    _ensure_current_lce_layout,
    _scope_lce_root,
    _verify_binding,
)
from mind_runtime.memory.contracts import CommittedMemory, MemoryLifecycle
from mind_runtime.memory.providers.bm25 import lexical_tokens
from mind_runtime.memory.store import CanonicalMemoryStore, scope_json
from mind_runtime.runtime_binding import RuntimeBinding

if TYPE_CHECKING:
    from lce.cognition.convergence import AuthorityConfig
    from lce.cognition.line_graph import (
        CallableProjectionConfig,
        LineAssemblerConfig,
    )
    from lce.cognition.promotion import BoundedInterpreter
    from lce.core.projection import LceProjectionCore, ProcessResult
    from lce.reference_memory.contracts import RawEvidence, SemanticBlock
    from lce.semantic.contracts import SemanticDecisionProvider
    from lce.structure.surface import SurfaceConfig
    from lce.structure.trajectory import (
        NeighbourCandidateProvider,
        TrajectoryConfig,
        TrajectoryRuntimeResult,
    )


_SOURCE_PREFIX = "mr-source:"


def _effective_window_payload(window: object) -> dict[str, object] | None:
    if window is None:
        return None
    kind = getattr(window, "kind", None)
    start_at = getattr(window, "start_at", None)
    end_at = getattr(window, "end_at", None)
    return {
        "kind": getattr(kind, "value", str(kind)),
        "start_at": (
            start_at.isoformat()
            if isinstance(start_at, datetime)
            else None
        ),
        "end_at": (
            end_at.isoformat()
            if isinstance(end_at, datetime)
            else None
        ),
    }


def _semantic_time_payload(value: object) -> dict[str, object]:
    relation = getattr(value, "relation", None)
    precision = getattr(value, "precision", None)
    daypart = getattr(value, "daypart", None)
    return {
        "relation": getattr(relation, "value", str(relation)),
        "precision": getattr(precision, "value", str(precision)),
        "daypart": (
            None
            if daypart is None
            else getattr(daypart, "value", str(daypart))
        ),
    }


class MrLceCanonicalSourceAdapter:
    """Expose MR canonical Memory as grouped read-only LCE Raw Evidence.

    Multiple canonical Memory rows produced from one interaction remain one
    independent LCE source unit. This preserves the same anti-self-amplification
    rule used by Thread maturity: one turn cannot become several independent
    authority votes merely because extraction emitted several Memory rows.
    """

    def __init__(self, adapter: MrMemorySubstrateAdapter) -> None:
        if not isinstance(adapter, MrMemorySubstrateAdapter):
            raise TypeError("adapter must be MrMemorySubstrateAdapter")
        self._adapter = adapter

    @property
    def scope(self) -> Scope:
        return self._adapter.scope

    def _all_scope_memories(self) -> tuple[CommittedMemory, ...]:
        _verify_binding(self._adapter.binding, self._adapter._paths)
        store = CanonicalMemoryStore(
            self._adapter._paths.memory_db,
            read_only=True,
        )
        try:
            return tuple(
                memory
                for memory in store.load_all()
                if memory.scope == self._adapter.scope
            )
        finally:
            store.close()

    @staticmethod
    def _authority_key(memory: CommittedMemory) -> tuple[object, ...]:
        interaction_id = memory.provenance.interaction_id
        if interaction_id is not None:
            return (
                "interaction",
                memory.origin_runtime_id,
                interaction_id,
            )
        return (
            "evidence",
            memory.origin_runtime_id,
            *memory.provenance.evidence_refs,
        )

    def _source_id(
        self,
        authority_key: tuple[object, ...],
    ) -> str:
        payload = json.dumps(
            {
                "scope": scope_json(self._adapter.scope),
                "authority_key": authority_key,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        return _SOURCE_PREFIX + hashlib.sha256(
            payload.encode("utf-8")
        ).hexdigest()[:24]

    def _groups(
        self,
    ) -> dict[str, tuple[CommittedMemory, ...]]:
        grouped: dict[
            tuple[object, ...],
            list[CommittedMemory],
        ] = {}
        for memory in self._all_scope_memories():
            grouped.setdefault(
                self._authority_key(memory),
                [],
            ).append(memory)
        output: dict[str, tuple[CommittedMemory, ...]] = {}
        for key, memories in grouped.items():
            output[self._source_id(key)] = tuple(
                sorted(memories, key=lambda item: item.memory_id)
            )
        return output

    def _raw_evidence(
        self,
        evidence_id: str,
        memories: tuple[CommittedMemory, ...],
    ) -> RawEvidence:
        try:
            from lce.reference_memory.contracts import RawEvidence
        except ImportError as exc:
            raise LceIntegrationUnavailable(
                "install the current optional lce-core package"
            ) from exc

        if not memories:
            raise KeyError(evidence_id)
        reader = SqliteFactReader(self._adapter._paths.facts_db)
        try:
            occurred_points: list[datetime] = []
            known_points: list[datetime] = []
            evidence_refs: set[str] = set()
            observation_payloads: list[dict[str, object]] = []
            for memory in memories:
                source_observation = reader.find_observation(
                    self._adapter.scope,
                    memory.provenance.observation_id,
                )
                if source_observation is None:
                    raise KeyError(memory.memory_id)
                source_evidence: list[dict[str, str]] = []
                for source_ref in memory.provenance.evidence_refs:
                    pair = reader.find_evidence(
                        self._adapter.scope,
                        source_ref,
                    )
                    if pair is None:
                        raise KeyError(source_ref)
                    evidence = pair[0]
                    evidence_refs.add(evidence.id)
                    occurred_points.append(evidence.occurred_at)
                    known_points.append(evidence.received_at)
                    source_evidence.append(
                        {
                            "evidence_id": evidence.id,
                            "occurred_at": evidence.occurred_at.isoformat(),
                            "received_at": evidence.received_at.isoformat(),
                        }
                    )
                known_points.extend(
                    (
                        memory.committed_at,
                        source_observation.observed_at,
                    )
                )
                observation_payloads.append(
                    {
                        "memory_id": memory.memory_id,
                        "observation_id": source_observation.id,
                        "observed_at": source_observation.observed_at.isoformat(),
                        "semantic_time": _semantic_time_payload(
                            source_observation.semantic_time
                        ),
                        "effective_window": _effective_window_payload(
                            source_observation.effective_window
                        ),
                        "source_evidence": source_evidence,
                    }
                )
        finally:
            reader.close()

        if not occurred_points or not known_points:
            raise KeyError(evidence_id)
        all_active = all(
            memory.lifecycle is MemoryLifecycle.ACTIVE
            for memory in memories
        )
        content = "\n".join(
            dict.fromkeys(memory.content.strip() for memory in memories)
        )
        interaction_ids = tuple(
            sorted(
                {
                    memory.provenance.interaction_id
                    for memory in memories
                    if memory.provenance.interaction_id is not None
                }
            )
        )
        return RawEvidence(
            evidence_id=evidence_id,
            content=content,
            occurred_at=min(occurred_points),
            known_at=max(known_points),
            state="VALID" if all_active else "INVALID",
            provenance={
                "canonical": True,
                "source_kind": "mr-canonical-memory-group",
                "scope": scope_json(self._adapter.scope),
                "memory_ids": tuple(
                    memory.memory_id for memory in memories
                ),
                "evidence_refs": tuple(sorted(evidence_refs)),
                "observation_ids": tuple(
                    memory.provenance.observation_id
                    for memory in memories
                ),
                "interaction_ids": interaction_ids,
                "observations": observation_payloads,
            },
        )

    def get_evidence(self, evidence_id: str) -> RawEvidence:
        if (
            not isinstance(evidence_id, str)
            or not evidence_id.startswith(_SOURCE_PREFIX)
        ):
            raise KeyError(evidence_id)
        groups = self._groups()
        memories = groups.get(evidence_id)
        if memories is None:
            raise KeyError(evidence_id)
        return self._raw_evidence(evidence_id, memories)

    def list_current_valid_evidence(self) -> tuple[RawEvidence, ...]:
        materials: list[RawEvidence] = []
        for evidence_id, memories in self._groups().items():
            material = self._raw_evidence(evidence_id, memories)
            if material.current_valid:
                materials.append(material)
        return tuple(
            sorted(
                materials,
                key=lambda item: (
                    item.effective_ordering_key,
                    item.evidence_id,
                ),
            )
        )

    def evidence_for_memory_ids(
        self,
        memory_ids: tuple[str, ...],
    ) -> tuple[RawEvidence, ...]:
        selected = self._adapter._selected_memories(memory_ids)
        selected_ids = {memory.memory_id for memory in selected}
        materials = tuple(
            self._raw_evidence(evidence_id, memories)
            for evidence_id, memories in self._groups().items()
            if any(
                memory.memory_id in selected_ids
                for memory in memories
            )
        )
        return tuple(
            sorted(
                materials,
                key=lambda item: (
                    item.effective_ordering_key,
                    item.evidence_id,
                ),
            )
        )

    def memory_ids_for_source(
        self,
        evidence_id: str,
    ) -> tuple[str, ...]:
        item = self.get_evidence(evidence_id)
        raw = item.provenance.get("memory_ids", ())
        if not isinstance(raw, (list, tuple)):
            return ()
        return tuple(
            value
            for value in raw
            if isinstance(value, str) and value
        )

    def original_source_refs(
        self,
        evidence_id: str,
    ) -> tuple[str, ...]:
        item = self.get_evidence(evidence_id)
        raw = item.provenance.get("evidence_refs", ())
        if not isinstance(raw, (list, tuple)):
            return ()
        return tuple(
            value
            for value in raw
            if isinstance(value, str) and value
        )


@dataclass(frozen=True)
class LceProjectionSession:
    """Embedded current LCE projection over MR canonical Memory."""

    core: LceProjectionCore
    _source: MrLceCanonicalSourceAdapter
    _legacy_adapter: MrMemorySubstrateAdapter

    @property
    def db_path(self) -> Path:
        return Path(self.core.baselines.db_path)

    def sync_all(self) -> tuple[ProcessResult, ...]:
        """Compile every current canonical source; replay is idempotent."""
        return self.core.run_batch(
            self._source.list_current_valid_evidence()
        )

    def sync_memory_ids(
        self,
        memory_ids: tuple[str, ...],
        *,
        mode: str = "nearline",
    ) -> tuple[ProcessResult, ...]:
        if mode not in {"nearline", "batch"}:
            raise ValueError("mode must be nearline or batch")
        materials = self._source.evidence_for_memory_ids(memory_ids)
        if mode == "batch":
            return self.core.run_batch(materials)
        return tuple(
            self.core.process(material, mode="nearline")
            for material in materials
        )

    def bootstrap_trajectory(
        self,
        *,
        knowledge_cutoff: datetime,
    ) -> TrajectoryRuntimeResult:
        if knowledge_cutoff.tzinfo != UTC:
            raise ValueError("knowledge_cutoff must be UTC")
        return self.core.bootstrap_trajectory(
            knowledge_cutoff=knowledge_cutoff
        )

    def accepted_understandings(
        self,
        current_context: str | None,
        *,
        limit: int = 4,
    ) -> tuple[LceAcceptedUnderstanding, ...]:
        if type(limit) is not int or not 0 <= limit <= 100:
            raise ValueError("limit must be an integer in [0, 100]")
        if limit == 0:
            return ()

        # Path A Baselines use canonical MR Memory IDs and are intentionally
        # invisible to LCE's SemanticBlock reader.
        path_a = _accepted_understandings(
            self._legacy_adapter,
            self.core.baselines,
            current_context=current_context,
            limit=limit,
        )

        query_tokens = set(lexical_tokens(current_context or ""))
        path_b: list[LceAcceptedUnderstanding] = []
        for view in self.core.query(current_context):
            memory_ids: set[str] = set()
            source_refs: set[str] = set()
            valid = True
            for source_id in view.supporting_source_refs:
                try:
                    memory_ids.update(
                        self._source.memory_ids_for_source(source_id)
                    )
                    source_refs.update(
                        self._source.original_source_refs(source_id)
                    )
                except KeyError:
                    valid = False
                    break
            if not valid or not memory_ids:
                continue
            if query_tokens:
                searchable = set(
                    lexical_tokens(view.content)
                )
                overlap = len(query_tokens & searchable)
                relevance = overlap / len(query_tokens)
            else:
                relevance = 1.0
            path_b.append(
                LceAcceptedUnderstanding(
                    content=view.content,
                    baseline_id=view.baseline_id,
                    region_id=view.region_id,
                    revision_number=view.revision_number,
                    supporting_memory_ids=tuple(sorted(memory_ids)),
                    source_refs=tuple(sorted(source_refs)),
                    relevance=min(1.0, relevance),
                )
            )

        by_id = {
            item.baseline_id: item
            for item in (*path_a, *path_b)
        }
        ordered = sorted(
            by_id.values(),
            key=lambda item: (
                -item.relevance,
                item.region_id,
                -item.revision_number,
            ),
        )
        return tuple(ordered[:limit])

    def close(self) -> None:
        self.core.close()

    def __enter__(self) -> LceProjectionSession:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


def open_lce_projection_binding(
    binding: RuntimeBinding,
    scope: Scope,
    *,
    enabled: bool = False,
    provider: SemanticDecisionProvider | None = None,
    interpreter: BoundedInterpreter | None = None,
    trajectory_config: TrajectoryConfig | None = None,
    trajectory_neighbour_provider: NeighbourCandidateProvider | None = None,
    authority_config: AuthorityConfig | None = None,
    line_assembler_config: LineAssemblerConfig | None = None,
    callable_projection_config: CallableProjectionConfig | None = None,
    surface_config: SurfaceConfig | None = None,
    block_embedder: Callable[[SemanticBlock], tuple[float, ...]] | None = None,
    block_embedding_version: str = "mr-lce-vector-v1",
    production_root: Path | str | None = None,
    lab_root: Path | str | None = None,
) -> LceProjectionSession | None:
    """Open current Path B without granting LCE factual write authority."""
    if type(enabled) is not bool:
        raise TypeError("enabled must be bool")
    if not enabled:
        return None
    if (
        not isinstance(block_embedding_version, str)
        or not block_embedding_version.strip()
    ):
        raise ValueError("block_embedding_version must be nonempty")

    adapter = MrMemorySubstrateAdapter(
        binding,
        scope,
        production_root=production_root,
        lab_root=lab_root,
    )
    _verify_binding(binding, adapter._paths)
    CanonicalMemoryStore(
        adapter._paths.memory_db,
        read_only=True,
    ).close()
    _ensure_current_lce_layout(adapter)

    try:
        from lce.core.projection import LceProjectionCore
        from lce.reference_memory.composite import ProjectionSubstrate
        from lce.reference_memory.projection_state import (
            SqliteProjectionStateStore,
        )
    except ImportError as exc:
        raise LceIntegrationUnavailable(
            "install the current optional lce-core package"
        ) from exc

    source = MrLceCanonicalSourceAdapter(adapter)
    state = SqliteProjectionStateStore(
        _scope_lce_root(adapter) / "projection_state"
    )
    substrate = ProjectionSubstrate(
        source,
        state,
        close_source=False,
        close_state=True,
    )
    try:
        core = LceProjectionCore(
            _scope_lce_root(adapter),
            memory=substrate,
            provider=provider,
            interpreter=interpreter,
            lineage_id="mr-canonical-memory",
            trajectory_config=trajectory_config,
            trajectory_neighbour_provider=trajectory_neighbour_provider,
            authority_config=authority_config,
            line_assembler_config=line_assembler_config,
            callable_projection_config=callable_projection_config,
            surface_config=surface_config,
            block_embedder=block_embedder,
            block_embedding_version=block_embedding_version,
            close_memory=True,
        )
    except BaseException:
        substrate.close()
        raise
    return LceProjectionSession(core, source, adapter)


__all__ = [
    "LceProjectionSession",
    "MrLceCanonicalSourceAdapter",
    "open_lce_projection_binding",
]
