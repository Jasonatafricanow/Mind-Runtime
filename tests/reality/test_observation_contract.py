"""Tests for the frozen Reality Observation contract (RED 1)."""

from datetime import UTC, datetime, timedelta

import pytest

from mind_runtime.contracts import (
    EffectiveWindow,
    EffectiveWindowKind,
    Observation,
    ObservationModality,
    Scope,
    ScopeDomain,
    SemanticDaypart,
    SemanticPrecision,
    SemanticRelation,
    SemanticTime,
    SyncFields,
)

NOW = datetime(2026, 9, 9, 14, 0, tzinfo=UTC)


def make_scope() -> Scope:
    return Scope(domain=ScopeDomain.USER, user_id="u1")


def make_sync(obs_id: str, scope: Scope) -> SyncFields:
    return SyncFields(scope, "r1", obs_id, 1, f"idem-{obs_id}")


def make_observation(
    obs_id: str = "obs-1",
    *,
    key: str = "user.health.stomach_pain.observed",
    value: object = "active",
    confidence: float = 0.9,
    observed_at: datetime = NOW,
    modality: ObservationModality = ObservationModality.ASSERTED,
    semantic_time: SemanticTime | None = None,
    effective_window: EffectiveWindow | None = None,
) -> Observation:
    s = make_scope()
    kwargs: dict[str, object] = {
        "id": obs_id,
        "interaction_id": "i1",
        "scope": s,
        "origin_runtime_id": "r1",
        "type": "factual",
        "key": key,
        "value": value,
        "confidence": confidence,
        "observed_at": observed_at,
        "evidence_refs": ("ev-1",),
        "sync": make_sync(obs_id, s),
        "modality": modality,
    }
    if semantic_time is not None:
        kwargs["semantic_time"] = semantic_time
    if effective_window is not None:
        kwargs["effective_window"] = effective_window
    return Observation(**kwargs)  # type: ignore[arg-type]


def test_observation_legacy_defaults() -> None:
    s = make_scope()
    obs = Observation(
        id="legacy-1",
        interaction_id="i1",
        scope=s,
        origin_runtime_id="r1",
        type="factual",
        key="user.sleep.phase.observed",
        value="awake",
        confidence=1.0,
        observed_at=NOW,
        evidence_refs=("ev-1",),
        sync=make_sync("legacy-1", s),
    )
    assert obs.modality == ObservationModality.ASSERTED
    assert obs.semantic_time.relation == SemanticRelation.UNRESOLVED
    assert obs.semantic_time.precision == SemanticPrecision.UNRESOLVED
    assert obs.semantic_time.daypart is None
    assert obs.effective_window is None


def test_observation_round_trip_with_all_semantic_fields() -> None:
    st = SemanticTime(
        relation=SemanticRelation.FUTURE,
        precision=SemanticPrecision.DAYPART,
        daypart=SemanticDaypart.AFTERNOON,
    )
    ew = EffectiveWindow(
        kind=EffectiveWindowKind.INTERVAL,
        start_at=NOW + timedelta(hours=1),
        end_at=NOW + timedelta(hours=5),
    )
    obs = make_observation(
        modality=ObservationModality.PLANNED,
        semantic_time=st,
        effective_window=ew,
        confidence=0.95,
    )
    assert obs.modality == ObservationModality.PLANNED
    assert obs.semantic_time == st
    assert obs.effective_window == ew
    assert obs.confidence == 0.95


def test_confidence_independent_from_modality() -> None:
    """confidence=0.99 and modality=TENTATIVE is completely valid."""
    obs = make_observation(
        modality=ObservationModality.TENTATIVE,
        confidence=0.99,
        semantic_time=SemanticTime(
            relation=SemanticRelation.FUTURE,
            precision=SemanticPrecision.DAYPART,
            daypart=SemanticDaypart.AFTERNOON,
        ),
    )
    assert obs.modality == ObservationModality.TENTATIVE
    assert obs.confidence == 0.99


def test_reject_unresolved_temporal_semantics_with_absolute_bounds() -> None:
    ew = EffectiveWindow(
        kind=EffectiveWindowKind.INTERVAL,
        start_at=NOW,
        end_at=NOW + timedelta(hours=1),
    )
    st = SemanticTime(
        relation=SemanticRelation.UNRESOLVED,
        precision=SemanticPrecision.UNRESOLVED,
    )
    with pytest.raises(ValueError, match="UNRESOLVED"):
        make_observation(semantic_time=st, effective_window=ew)


def test_reject_point_with_end_at() -> None:
    with pytest.raises(ValueError, match="POINT"):
        EffectiveWindow(
            kind=EffectiveWindowKind.POINT,
            start_at=NOW,
            end_at=NOW + timedelta(hours=1),
        )


def test_reject_interval_without_end_at() -> None:
    with pytest.raises(ValueError, match="INTERVAL"):
        EffectiveWindow(
            kind=EffectiveWindowKind.INTERVAL,
            start_at=NOW,
            end_at=None,
        )


def test_reject_interval_start_at_ge_end_at() -> None:
    with pytest.raises(ValueError, match="start_at < end_at"):
        EffectiveWindow(
            kind=EffectiveWindowKind.INTERVAL,
            start_at=NOW + timedelta(hours=2),
            end_at=NOW + timedelta(hours=1),
        )

    with pytest.raises(ValueError, match="start_at < end_at"):
        EffectiveWindow(
            kind=EffectiveWindowKind.INTERVAL,
            start_at=NOW,
            end_at=NOW,
        )


def test_reject_open_interval_with_end_at() -> None:
    with pytest.raises(ValueError, match="OPEN_INTERVAL"):
        EffectiveWindow(
            kind=EffectiveWindowKind.OPEN_INTERVAL,
            start_at=NOW,
            end_at=NOW + timedelta(hours=1),
        )


def test_reject_daypart_without_daypart() -> None:
    with pytest.raises(ValueError, match="DAYPART"):
        SemanticTime(
            relation=SemanticRelation.CURRENT,
            precision=SemanticPrecision.DAYPART,
            daypart=None,
        )


def test_reject_non_daypart_with_daypart() -> None:
    with pytest.raises(ValueError, match="non-DAYPART"):
        SemanticTime(
            relation=SemanticRelation.CURRENT,
            precision=SemanticPrecision.INSTANT,
            daypart=SemanticDaypart.MORNING,
        )


def test_reject_naive_datetimes() -> None:
    naive_dt = datetime(2026, 9, 9, 14, 0)
    with pytest.raises(ValueError, match="UTC"):
        EffectiveWindow(
            kind=EffectiveWindowKind.INTERVAL,
            start_at=naive_dt,
            end_at=NOW,
        )
    with pytest.raises(ValueError, match="UTC"):
        EffectiveWindow(
            kind=EffectiveWindowKind.INTERVAL,
            start_at=NOW,
            end_at=naive_dt,
        )


def test_domain_effective_window_kind_has_no_unresolved_enum() -> None:
    """The domain enum must contain only POINT, INTERVAL, OPEN_INTERVAL."""
    assert set(EffectiveWindowKind) == {
        EffectiveWindowKind.POINT,
        EffectiveWindowKind.INTERVAL,
        EffectiveWindowKind.OPEN_INTERVAL,
    }
    assert "unresolved" not in [k.value for k in EffectiveWindowKind]
