"""Tests for Reality Observation replay provenance, conflicts, and protected namespaces."""

from datetime import UTC, datetime
from pathlib import Path

import pytest
from tests.support.fake_clock import FakeClock

from mind_runtime.contracts import (
    Authority,
    AuthorityLevel,
    EffectiveWindow,
    EffectiveWindowKind,
    Evidence,
    ObservationModality,
    Scope,
    ScopeDomain,
    SemanticPrecision,
    SemanticRelation,
    SemanticTime,
    SyncFields,
)
from mind_runtime.facts.persistence import SqliteFactBackend
from mind_runtime.facts.ports import (
    FactAdmissionDisposition,
    RealityAdmissionRequest,
)
from mind_runtime.facts.service import FactAdmissionConflictError, FactIngestService
from mind_runtime.facts.validators import AuthorityError

T1 = datetime(2026, 9, 9, 10, 0, tzinfo=UTC)
T2 = datetime(2026, 9, 9, 10, 5, tzinfo=UTC)


def make_scope() -> Scope:
    return Scope(domain=ScopeDomain.USER, user_id="u1")


def make_evidence(interaction_id: str = "orig-interaction", received_at: datetime = T1) -> Evidence:
    s = make_scope()
    ev_id = "ev-test-1"
    return Evidence(
        id=ev_id,
        source_type="user_message",
        source_id="src-1",
        authority_level=AuthorityLevel.ASSERTED,
        occurred_at=received_at,
        received_at=received_at,
        payload={"text": "我现在胃疼"},
        scope=s,
        origin_runtime_id="r1",
        authority=Authority(scope=s, level=AuthorityLevel.ASSERTED, source_id="src-1"),
        sync=SyncFields(s, "r1", ev_id, 1, f"idem-{ev_id}"),
    )


def test_crash_window_retry_preserves_original_evidence_provenance(tmp_path: Path) -> None:
    """Proves that a retry turn preserves original interaction provenance."""
    db_path = tmp_path / "facts.db"
    backend = SqliteFactBackend(db_path)
    clock = FakeClock(T1)
    service = FactIngestService(backend=backend, clock=clock)

    ev = make_evidence(interaction_id="orig-interaction", received_at=T1)
    # Admitting Evidence first establishes original durable provenance
    service.admit(
        ev, interaction_id="orig-interaction", writing_runtime="r1", writing_persona_id=None
    )

    # Crash / retry occurs under retry-interaction at T2
    clock.set(T2)
    req = RealityAdmissionRequest(
        source_evidence=ev,
        interaction_id="retry-interaction",
        writing_runtime="r1",
        writing_persona_id=None,
        observation_id="reality-obs-1",
        key="user.health.stomach_pain.observed",
        value="active",
        confidence=1.0,
        modality=ObservationModality.ASSERTED,
        semantic_time=SemanticTime(
            relation=SemanticRelation.CURRENT, precision=SemanticPrecision.INSTANT
        ),
        effective_window=EffectiveWindow(
            kind=EffectiveWindowKind.OPEN_INTERVAL,
            start_at=T1,
            end_at=None,
        ),
    )

    result = service.admit_reality(req)
    assert result.disposition is FactAdmissionDisposition.NEW
    # Provenance invariant: causal interaction is original Evidence, NOT retry
    assert result.observation.interaction_id == "orig-interaction"
    assert result.observation.observed_at == T1
    assert result.observation.evidence_refs == (ev.id,)


def test_immutable_semantic_conflicts_raise_conflict_error(tmp_path: Path) -> None:
    db_path = tmp_path / "facts.db"
    backend = SqliteFactBackend(db_path)
    service = FactIngestService(backend=backend, clock=FakeClock(T1))

    ev = make_evidence(interaction_id="orig-interaction", received_at=T1)
    service.admit(
        ev, interaction_id="orig-interaction", writing_runtime="r1", writing_persona_id=None
    )

    base_req = RealityAdmissionRequest(
        source_evidence=ev,
        interaction_id="orig-interaction",
        writing_runtime="r1",
        writing_persona_id=None,
        observation_id="reality-conflict-obs",
        key="user.health.stomach_pain.observed",
        value="active",
        confidence=0.9,
        modality=ObservationModality.ASSERTED,
        semantic_time=SemanticTime(
            relation=SemanticRelation.CURRENT, precision=SemanticPrecision.INSTANT
        ),
        effective_window=EffectiveWindow(
            kind=EffectiveWindowKind.OPEN_INTERVAL, start_at=T1, end_at=None
        ),
    )
    service.admit_reality(base_req)

    # Identical replay returns REPLAY
    replay_result = service.admit_reality(base_req)
    assert replay_result.disposition is FactAdmissionDisposition.REPLAY

    # Changed modality raises FactAdmissionConflictError
    with pytest.raises(FactAdmissionConflictError, match="conflicts"):
        service.admit_reality(
            RealityAdmissionRequest(
                source_evidence=ev,
                interaction_id="orig-interaction",
                writing_runtime="r1",
                writing_persona_id=None,
                observation_id="reality-conflict-obs",
                key="user.health.stomach_pain.observed",
                value="active",
                confidence=0.9,
                modality=ObservationModality.TENTATIVE,
                semantic_time=SemanticTime(
                    relation=SemanticRelation.CURRENT, precision=SemanticPrecision.INSTANT
                ),
                effective_window=EffectiveWindow(
                    kind=EffectiveWindowKind.OPEN_INTERVAL, start_at=T1, end_at=None
                ),
            )
        )

    # Changed confidence raises FactAdmissionConflictError
    with pytest.raises(FactAdmissionConflictError, match="conflicts"):
        service.admit_reality(
            RealityAdmissionRequest(
                source_evidence=ev,
                interaction_id="orig-interaction",
                writing_runtime="r1",
                writing_persona_id=None,
                observation_id="reality-conflict-obs",
                key="user.health.stomach_pain.observed",
                value="active",
                confidence=0.5,
                modality=ObservationModality.ASSERTED,
                semantic_time=SemanticTime(
                    relation=SemanticRelation.CURRENT, precision=SemanticPrecision.INSTANT
                ),
                effective_window=EffectiveWindow(
                    kind=EffectiveWindowKind.OPEN_INTERVAL, start_at=T1, end_at=None
                ),
            )
        )

    # Changed semantic time raises FactAdmissionConflictError
    with pytest.raises(FactAdmissionConflictError, match="conflicts"):
        service.admit_reality(
            RealityAdmissionRequest(
                source_evidence=ev,
                interaction_id="orig-interaction",
                writing_runtime="r1",
                writing_persona_id=None,
                observation_id="reality-conflict-obs",
                key="user.health.stomach_pain.observed",
                value="active",
                confidence=0.9,
                modality=ObservationModality.ASSERTED,
                semantic_time=SemanticTime(
                    relation=SemanticRelation.PAST, precision=SemanticPrecision.INSTANT
                ),
                effective_window=EffectiveWindow(
                    kind=EffectiveWindowKind.OPEN_INTERVAL, start_at=T1, end_at=None
                ),
            )
        )

    # Changed effective window raises FactAdmissionConflictError
    with pytest.raises(FactAdmissionConflictError, match="conflicts"):
        service.admit_reality(
            RealityAdmissionRequest(
                source_evidence=ev,
                interaction_id="orig-interaction",
                writing_runtime="r1",
                writing_persona_id=None,
                observation_id="reality-conflict-obs",
                key="user.health.stomach_pain.observed",
                value="active",
                confidence=0.9,
                modality=ObservationModality.ASSERTED,
                semantic_time=SemanticTime(
                    relation=SemanticRelation.CURRENT, precision=SemanticPrecision.INSTANT
                ),
                effective_window=None,
            )
        )


def test_protected_namespace_side_door_rejected_before_persistence() -> None:
    service = FactIngestService(clock=FakeClock(T1))
    ev = make_evidence()
    service.admit(ev, interaction_id="i1", writing_runtime="r1", writing_persona_id=None)

    forbidden_keys = [
        "user.persona.observed",
        "memory.user_fact.observed",
        "relationship.trust.observed",
        "affect.valence.observed",
        "intent.scheduled.observed",
        "decision.context.observed",
        "user.unreviewed.dimension.observed",
    ]

    for key in forbidden_keys:
        req = RealityAdmissionRequest(
            source_evidence=ev,
            interaction_id="i1",
            writing_runtime="r1",
            writing_persona_id=None,
            observation_id=f"obs-bad-{key}",
            key=key,
            value="x",
            confidence=1.0,
        )
        with pytest.raises(AuthorityError, match="Reality namespace"):
            service.admit_reality(req)
