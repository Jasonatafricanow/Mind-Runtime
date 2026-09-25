"""MR -> LCE temporal authority integration without a second factual store."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from mind_runtime.contracts import (
    EffectiveWindow,
    EffectiveWindowKind,
    Evidence,
    ObservationModality,
    SemanticPrecision,
    SemanticRelation,
    SemanticTime,
)
from mind_runtime.facts.persistence import SqliteFactBackend
from mind_runtime.facts.ports import FactAdmissionResult, RealityAdmissionRequest
from mind_runtime.facts.service import FactIngestService
from mind_runtime.integrations.lce import (
    TEMPORAL_CONTEXT_KEY,
    MemorySelectionError,
    MrMemorySubstrateAdapter,
    TemporalMemoryView,
    open_lce_binding,
)
from mind_runtime.memory.contracts import CommittedMemory
from mind_runtime.memory.store import CanonicalMemoryStore
from mind_runtime.runtime_binding import RuntimeBinding, RuntimeEnvironment, bind_storage
from tests.facts.test_admission import NOW, make_evidence, make_scope
from tests.memory.test_admission import admit, setup_plane

if TYPE_CHECKING:
    from lce.contracts.baseline import Baseline
    from lce.contracts.consolidation import CandidateBaseline
    from lce.contracts.external_memory import MemoryItemView


@dataclass
class TemporalPlane:
    binding: RuntimeBinding
    production_root: Path
    lab_root: Path
    service: FactIngestService
    store: CanonicalMemoryStore
    backend: SqliteFactBackend
    source: Evidence
    memory: CommittedMemory

    def close(self) -> None:
        self.store.close()
        self.backend.close()


def _build_plane(tmp_path: Path, *, evidence: Evidence | None = None) -> TemporalPlane:
    binding = RuntimeBinding(
        "persona", "body", "runtime-1", "lab/temporal", RuntimeEnvironment.LAB
    )
    production_root = tmp_path / "production"
    lab_root = tmp_path / "lab"
    paths = bind_storage(binding, production_root=production_root, lab_root=lab_root)
    service, _, store, backend = setup_plane(paths.root)
    source = evidence or make_evidence()
    admit(service, source)
    memories = store.load_all()
    assert len(memories) == 1
    return TemporalPlane(
        binding,
        production_root,
        lab_root,
        service,
        store,
        backend,
        source,
        memories[0],
    )


def _adapter(plane: TemporalPlane) -> MrMemorySubstrateAdapter:
    return MrMemorySubstrateAdapter(
        plane.binding,
        make_scope(),
        production_root=plane.production_root,
        lab_root=plane.lab_root,
    )


def _future_reality(plane: TemporalPlane) -> FactAdmissionResult:
    start = NOW + timedelta(days=1)
    return plane.service.admit_reality(
        RealityAdmissionRequest(
            source_evidence=plane.source,
            interaction_id="interaction-1",
            writing_runtime="runtime-1",
            writing_persona_id=None,
            observation_id=f"reality-observation-{plane.source.id}-0",
            key="user.plan.calligraphy.observed",
            value="planned",
            confidence=1.0,
            modality=ObservationModality.PLANNED,
            semantic_time=SemanticTime(
                relation=SemanticRelation.FUTURE,
                precision=SemanticPrecision.RANGE,
            ),
            effective_window=EffectiveWindow(
                kind=EffectiveWindowKind.INTERVAL,
                start_at=start,
                end_at=start + timedelta(hours=2),
            ),
        )
    )


def test_unknown_temporal_semantics_remain_unknown(tmp_path: Path) -> None:
    plane = _build_plane(tmp_path)
    try:
        view = _adapter(plane).get_temporal_by_ids((plane.memory.memory_id,))[0]
        assert view.source_semantic_time.relation is SemanticRelation.UNRESOLVED
        assert view.source_semantic_time.precision is SemanticPrecision.UNRESOLVED
        assert view.source_effective_window is None
        assert view.proposition_observations == ()
        assert view.evidence[0].source_occurred_at == NOW
        assert view.evidence[0].received_at == NOW
        assert view.knowledge_available_at == NOW
    finally:
        plane.close()


def test_future_proposition_is_visible_after_knowledge_cutoff(tmp_path: Path) -> None:
    plane = _build_plane(tmp_path)
    try:
        _future_reality(plane)
        adapter = _adapter(plane)
        view = adapter.get_temporal_by_ids(
            (plane.memory.memory_id,),
            cutoff=NOW + timedelta(hours=1),
        )[0]
        assert len(view.proposition_observations) == 1
        proposition = view.proposition_observations[0]
        assert proposition.modality is ObservationModality.PLANNED
        assert proposition.semantic_time.relation is SemanticRelation.FUTURE
        assert proposition.effective_window is not None
        assert proposition.effective_window.start_at > NOW

        with pytest.raises(MemorySelectionError, match="unavailable at cutoff"):
            adapter.get_temporal_by_ids(
                (plane.memory.memory_id,),
                cutoff=NOW - timedelta(seconds=1),
            )
    finally:
        plane.close()


def test_late_arriving_past_source_does_not_backdate_knowledge(tmp_path: Path) -> None:
    source = replace(
        make_evidence(),
        occurred_at=NOW - timedelta(days=4),
        received_at=NOW,
    )
    plane = _build_plane(tmp_path, evidence=source)
    try:
        adapter = _adapter(plane)
        with pytest.raises(MemorySelectionError, match="unavailable at cutoff"):
            adapter.get_temporal_by_ids(
                (plane.memory.memory_id,),
                cutoff=NOW - timedelta(days=1),
            )
        view = adapter.get_temporal_by_ids(
            (plane.memory.memory_id,),
            cutoff=NOW + timedelta(seconds=1),
        )[0]
        assert view.evidence[0].source_occurred_at == NOW - timedelta(days=4)
        assert view.evidence[0].received_at == NOW
        assert view.knowledge_available_at == NOW
    finally:
        plane.close()


def test_multiple_reality_observations_remain_separate(tmp_path: Path) -> None:
    plane = _build_plane(tmp_path)
    try:
        _future_reality(plane)
        plane.service.admit_reality(
            RealityAdmissionRequest(
                source_evidence=plane.source,
                interaction_id="interaction-1",
                writing_runtime="runtime-1",
                writing_persona_id=None,
                observation_id=f"reality-observation-{plane.source.id}-1",
                key="user.plan.swimming.observed",
                value="possible",
                confidence=0.8,
                modality=ObservationModality.TENTATIVE,
                semantic_time=SemanticTime(
                    relation=SemanticRelation.FUTURE,
                    precision=SemanticPrecision.UNRESOLVED,
                ),
                effective_window=None,
            )
        )
        view = _adapter(plane).get_temporal_by_ids((plane.memory.memory_id,))[0]
        assert tuple(item.observation_id for item in view.proposition_observations) == (
            f"reality-observation-{plane.source.id}-0",
            f"reality-observation-{plane.source.id}-1",
        )
        assert view.proposition_observations[0].effective_window is not None
        assert view.proposition_observations[1].effective_window is None
    finally:
        plane.close()


def test_path_b_smoke_injects_real_mr_temporal_context(tmp_path: Path) -> None:
    pytest.importorskip("lce")
    from lce.contracts.consolidation import CandidateBaseline

    class CapturingConsolidator:
        def __init__(self) -> None:
            self.context: Mapping[str, object] | None = None

        def consolidate(
            self,
            *,
            memories: tuple[MemoryItemView, ...],
            previous_baseline: Baseline | None,
            context: Mapping[str, object] | None = None,
        ) -> CandidateBaseline:
            del previous_baseline
            self.context = context
            return CandidateBaseline(
                content="Temporal path B smoke",
                supporting_memory_ids=tuple(item.memory_id for item in memories),
            )

    plane = _build_plane(tmp_path)
    try:
        _future_reality(plane)
        consolidator = CapturingConsolidator()
        session = open_lce_binding(
            plane.binding,
            make_scope(),
            enabled=True,
            consolidator=consolidator,
            production_root=plane.production_root,
            lab_root=plane.lab_root,
        )
        assert session is not None
        with session:
            result = session.consolidate_temporal(
                "latent:smoke",
                (plane.memory.memory_id,),
                cutoff=NOW + timedelta(hours=1),
            )
        assert result.revised
        assert consolidator.context is not None
        views = consolidator.context[TEMPORAL_CONTEXT_KEY]
        assert isinstance(views, tuple)
        assert len(views) == 1
        assert isinstance(views[0], TemporalMemoryView)
        assert views[0].memory_id == plane.memory.memory_id
        assert (
            views[0].proposition_observations[0].semantic_time.relation
            is SemanticRelation.FUTURE
        )
    finally:
        plane.close()
