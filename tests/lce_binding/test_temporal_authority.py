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
from mind_runtime.memory.admission import MemoryAdmissionService
from mind_runtime.memory.contracts import CommittedMemory
from mind_runtime.memory.store import CanonicalMemoryStore
from mind_runtime.runtime_binding import RuntimeBinding, RuntimeEnvironment, bind_storage
from tests.facts.test_admission import NOW, make_evidence, make_scope
from tests.support.fake_clock import FakeClock

if TYPE_CHECKING:
    from lce.contracts.baseline import Baseline
    from lce.contracts.consolidation import CandidateBaseline
    from lce.contracts.external_memory import MemoryItemView


@dataclass
class TemporalPlane:
    binding: RuntimeBinding
    production_root: Path
    lab_root: Path
    clock: FakeClock
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
    clock = FakeClock(NOW)
    backend = SqliteFactBackend(paths.facts_db)
    store = CanonicalMemoryStore(paths.memory_db)
    admission = MemoryAdmissionService(
        store=store,
        facts=backend,
        clock=clock,
        origin_runtime_id="runtime-1",
        enabled=True,
    )
    service = FactIngestService(clock=clock, backend=backend, after_admission=admission)
    source = evidence or make_evidence()
    service.admit(
        source,
        interaction_id="interaction-1",
        writing_runtime="runtime-1",
        writing_persona_id=None,
    )
    memories = store.load_all()
    assert len(memories) == 1
    return TemporalPlane(
        binding,
        production_root,
        lab_root,
        clock,
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


def _admit_reality(
    plane: TemporalPlane,
    *,
    ordinal: int,
    key: str,
    modality: ObservationModality,
    relation: SemanticRelation,
    precision: SemanticPrecision,
    window: EffectiveWindow | None,
    value: str = "observed",
) -> FactAdmissionResult:
    return plane.service.admit_reality(
        RealityAdmissionRequest(
            source_evidence=plane.source,
            interaction_id="interaction-1",
            writing_runtime="runtime-1",
            writing_persona_id=None,
            observation_id=f"reality-observation-{plane.source.id}-{ordinal}",
            key=key,
            value=value,
            confidence=1.0,
            modality=modality,
            semantic_time=SemanticTime(relation=relation, precision=precision),
            effective_window=window,
        )
    )


def _future_reality(plane: TemporalPlane) -> FactAdmissionResult:
    start = NOW + timedelta(days=1)
    return _admit_reality(
        plane,
        ordinal=0,
        key="user.plan.calligraphy.observed",
        modality=ObservationModality.PLANNED,
        relation=SemanticRelation.FUTURE,
        precision=SemanticPrecision.RANGE,
        window=EffectiveWindow(
            kind=EffectiveWindowKind.INTERVAL,
            start_at=start,
            end_at=start + timedelta(hours=2),
        ),
        value="planned",
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


@pytest.mark.parametrize(
    ("relation", "precision", "window", "modality"),
    (
        (
            SemanticRelation.CURRENT,
            SemanticPrecision.INSTANT,
            EffectiveWindow(kind=EffectiveWindowKind.POINT, start_at=NOW),
            ObservationModality.ASSERTED,
        ),
        (
            SemanticRelation.PAST,
            SemanticPrecision.RANGE,
            EffectiveWindow(
                kind=EffectiveWindowKind.INTERVAL,
                start_at=NOW - timedelta(hours=3),
                end_at=NOW - timedelta(hours=2),
            ),
            ObservationModality.ASSERTED,
        ),
        (
            SemanticRelation.FUTURE,
            SemanticPrecision.RANGE,
            EffectiveWindow(
                kind=EffectiveWindowKind.OPEN_INTERVAL,
                start_at=NOW + timedelta(days=1),
            ),
            ObservationModality.PLANNED,
        ),
    ),
)
def test_semantic_time_and_effective_window_survive(
    tmp_path: Path,
    relation: SemanticRelation,
    precision: SemanticPrecision,
    window: EffectiveWindow,
    modality: ObservationModality,
) -> None:
    plane = _build_plane(tmp_path)
    try:
        _admit_reality(
            plane,
            ordinal=0,
            key="user.activity.temporal_case.observed",
            modality=modality,
            relation=relation,
            precision=precision,
            window=window,
        )
        view = _adapter(plane).get_temporal_by_ids((plane.memory.memory_id,))[0]
        proposition = view.proposition_observations[0]
        assert proposition.semantic_time.relation is relation
        assert proposition.semantic_time.precision is precision
        assert proposition.effective_window == window
        assert view.evidence[0].source_occurred_at == NOW
        assert view.committed_at == NOW
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
        proposition = view.proposition_observations[0]
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
        assert view.committed_at == NOW
        assert view.knowledge_available_at == NOW
    finally:
        plane.close()


def test_multiple_reality_observations_remain_separate_and_ordered(tmp_path: Path) -> None:
    plane = _build_plane(tmp_path)
    try:
        _admit_reality(
            plane,
            ordinal=1,
            key="user.plan.swimming.observed",
            modality=ObservationModality.TENTATIVE,
            relation=SemanticRelation.FUTURE,
            precision=SemanticPrecision.UNRESOLVED,
            window=None,
            value="possible",
        )
        _future_reality(plane)
        first = _adapter(plane).get_temporal_by_ids((plane.memory.memory_id,))[0]
        assert tuple(item.observation_id for item in first.proposition_observations) == (
            f"reality-observation-{plane.source.id}-0",
            f"reality-observation-{plane.source.id}-1",
        )
        assert first.proposition_observations[0].effective_window is not None
        assert first.proposition_observations[1].effective_window is None

        plane.close()
        restarted = _adapter(plane).get_temporal_by_ids((plane.memory.memory_id,))[0]
        assert restarted == first
    except Exception:
        try:
            plane.close()
        except Exception:
            pass
        raise


def test_multi_evidence_support_does_not_fabricate_proposition_interval(
    tmp_path: Path,
) -> None:
    source = replace(
        make_evidence(),
        occurred_at=NOW - timedelta(days=3),
        received_at=NOW - timedelta(hours=3),
    )
    plane = _build_plane(tmp_path, evidence=source)
    try:
        second = replace(
            make_evidence(evidence_id="evidence-2"),
            occurred_at=NOW - timedelta(days=1),
            received_at=NOW - timedelta(hours=1),
            payload={"text": "second support"},
        )
        plane.service.admit(
            second,
            interaction_id="interaction-2",
            writing_runtime="runtime-1",
            writing_persona_id=None,
        )
        multi_id = "memory-multi-temporal"
        multi = replace(
            plane.memory,
            memory_id=multi_id,
            content="combined support",
            provenance=replace(
                plane.memory.provenance,
                evidence_refs=(plane.source.id, second.id),
            ),
            sync=replace(
                plane.memory.sync,
                object_id=multi_id,
                idempotency_key=multi_id,
            ),
        )
        plane.store._commit((multi,))
        view = _adapter(plane).get_temporal_by_ids((multi_id,))[0]
        assert tuple(item.evidence_id for item in view.evidence) == (
            plane.source.id,
            second.id,
        )
        assert tuple(item.source_occurred_at for item in view.evidence) == (
            NOW - timedelta(days=3),
            NOW - timedelta(days=1),
        )
        assert view.source_effective_window is None
        assert view.proposition_observations == ()
    finally:
        plane.close()


def test_later_completion_does_not_rewrite_earlier_memory_view(tmp_path: Path) -> None:
    plane = _build_plane(tmp_path)
    try:
        _future_reality(plane)
        adapter = _adapter(plane)
        earlier = adapter.get_temporal_by_ids(
            (plane.memory.memory_id,),
            cutoff=NOW + timedelta(hours=1),
        )[0]

        plane.clock.advance(timedelta(days=1))
        later_time = plane.clock.now()
        completion = replace(
            make_evidence(evidence_id="evidence-2"),
            occurred_at=later_time,
            received_at=later_time,
            payload={"text": "calligraphy completed"},
        )
        plane.service.admit(
            completion,
            interaction_id="interaction-2",
            writing_runtime="runtime-1",
            writing_persona_id=None,
        )
        completion_result = plane.service.admit_reality(
            RealityAdmissionRequest(
                source_evidence=completion,
                interaction_id="interaction-2",
                writing_runtime="runtime-1",
                writing_persona_id=None,
                observation_id="reality-observation-evidence-2-0",
                key="user.activity.calligraphy.completed",
                value="completed",
                confidence=1.0,
                modality=ObservationModality.ASSERTED,
                semantic_time=SemanticTime(
                    relation=SemanticRelation.CURRENT,
                    precision=SemanticPrecision.INSTANT,
                ),
                effective_window=EffectiveWindow(
                    kind=EffectiveWindowKind.POINT,
                    start_at=later_time,
                ),
            )
        )
        assert completion_result.observation.evidence_refs == (completion.id,)

        reread = adapter.get_temporal_by_ids(
            (plane.memory.memory_id,),
            cutoff=NOW + timedelta(hours=1),
        )[0]
        assert reread == earlier
        assert len(reread.proposition_observations) == 1

        later_memory = next(
            item
            for item in plane.store.load_all()
            if completion.id in item.provenance.evidence_refs
        )
        with pytest.raises(MemorySelectionError, match="unavailable at cutoff"):
            adapter.get_temporal_by_ids(
                (later_memory.memory_id,),
                cutoff=NOW + timedelta(hours=1),
            )
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
            with pytest.raises(ValueError, match="reserved for MR authority"):
                session.consolidate_temporal(
                    "latent:spoof",
                    (plane.memory.memory_id,),
                    context={TEMPORAL_CONTEXT_KEY: ()},
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
