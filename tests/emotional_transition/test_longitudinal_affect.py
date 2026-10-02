"""Forward-port tests for read-only longitudinal affect structure."""

# ruff: noqa: I001

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from mind_runtime.contracts.longitudinal_affect import (
    LongitudinalAffectQuery,
    LongitudinalAffectRecord,
)
from mind_runtime.contracts.scope import Scope, ScopeDomain
from mind_runtime.emotional_transition import (
    derive_longitudinal_affect_view,
    resolve_affect_occurrence_id,
)
from mind_runtime.expression import compile_longitudinal_affect_condition


NOW = datetime(2026, 10, 2, 8, 0, tzinfo=UTC)
OWNER_SCOPE = Scope(
    domain=ScopeDomain.RELATIONSHIP,
    relationship_id="alice",
    persona_id="kayla_v0",
)


def record(
    record_id: str,
    *,
    days_ago: int,
    valence: str = "positive",
    occurrence_id: str | None = None,
    source_refs: tuple[str, ...] | None = None,
    assessed_days_ago: int | None = None,
    relationship_id: str = "alice",
    verbal_repair: bool = False,
    behavioral_repair: bool = False,
    unresolved: bool = False,
) -> LongitudinalAffectRecord:
    resolved_occurrence_id = (
        None
        if unresolved
        else occurrence_id if occurrence_id is not None else f"occ-{record_id}"
    )
    refs = source_refs if source_refs is not None else (f"ev-{record_id}",)
    assessed_delta = days_ago if assessed_days_ago is None else assessed_days_ago
    return LongitudinalAffectRecord(
        record_id=record_id,
        relationship_id=relationship_id,
        source_occurrence_id=resolved_occurrence_id,
        source_refs=refs,
        source_occurred_at=NOW - timedelta(days=days_ago),
        assessed_at=NOW - timedelta(days=assessed_delta),
        valence=valence,
        verbal_repair_signal=verbal_repair,
        behavioral_repair_signal=behavioral_repair,
    )


def query(**overrides: object) -> LongitudinalAffectQuery:
    values: dict[str, object] = {
        "owner_scope": OWNER_SCOPE,
        "relationship_id": "alice",
        "as_of": NOW,
    }
    values.update(overrides)
    return LongitudinalAffectQuery(**values)  # type: ignore[arg-type]


def test_record_and_query_contracts_fail_closed() -> None:
    with pytest.raises(ValueError, match="record_id"):
        LongitudinalAffectRecord(
            record_id="",
            relationship_id="alice",
            source_occurrence_id="occ-1",
            source_refs=("ev-1",),
            source_occurred_at=NOW,
            assessed_at=NOW,
            valence="positive",
        )
    with pytest.raises(ValueError, match="source_refs"):
        LongitudinalAffectRecord(
            record_id="r1",
            relationship_id="alice",
            source_occurrence_id="occ-1",
            source_refs=("",),
            source_occurred_at=NOW,
            assessed_at=NOW,
            valence="positive",
        )
    with pytest.raises(ValueError, match="source_occurred_at"):
        LongitudinalAffectRecord(
            record_id="r1",
            relationship_id="alice",
            source_occurrence_id=None,
            source_refs=(),
            source_occurred_at=datetime(2026, 1, 1),
            assessed_at=NOW,
            valence="positive",
        )
    with pytest.raises(ValueError, match="as_of"):
        LongitudinalAffectQuery(
            owner_scope=OWNER_SCOPE,
            relationship_id="alice",
            as_of=datetime(2026, 1, 1),
        )
    with pytest.raises(ValueError, match="max_occurrences"):
        query(max_occurrences=0)
    with pytest.raises(ValueError, match="recent_window_days"):
        query(recent_window_days=-1)
    with pytest.raises(ValueError, match="min_earlier_occurrences"):
        query(min_earlier_occurrences=-1)
    with pytest.raises(ValueError, match="min_recent_occurrences"):
        query(min_recent_occurrences=-1)
    with pytest.raises(ValueError, match="must be an integer"):
        query(max_occurrences=True)
    with pytest.raises(ValueError, match="recent_since"):
        query(recent_since=datetime(2026, 1, 1))


def test_occurrence_identity_is_explicit_and_fail_closed() -> None:
    explicit = record("r1", days_ago=2, occurrence_id="occ-1")
    assert resolve_affect_occurrence_id(explicit) == "occ-1"

    summary = record(
        "r2",
        days_ago=2,
        occurrence_id="summary-1",
        source_refs=("occ-root", "ev-2"),
    )
    assert resolve_affect_occurrence_id(summary) == "occ-root"

    fallback = record(
        "r3",
        days_ago=2,
        source_refs=("ev-only",),
        unresolved=True,
    )
    assert resolve_affect_occurrence_id(fallback) == "ev-only"

    unresolved = record(
        "r4",
        days_ago=2,
        source_refs=("ev-a", "ev-b"),
        unresolved=True,
    )
    assert resolve_affect_occurrence_id(unresolved) is None


def test_empty_and_unresolved_records_do_not_create_occurrences() -> None:
    unresolved = record(
        "u1",
        days_ago=1,
        source_refs=("ev-a", "ev-b"),
        unresolved=True,
    )

    view = derive_longitudinal_affect_view([unresolved], query=query())
    assert view.is_empty is True
    assert view.total_occurrence_count == 0
    assert view.raw_record_count == 1
    assert view.unresolved_record_count == 1
    assert view.revision_trajectories == ()


def test_relationship_and_knowledge_cutoff_are_respected() -> None:
    visible = record("visible", days_ago=3)
    other_relationship = record(
        "other",
        days_ago=2,
        relationship_id="bob",
    )
    future_assessment = record(
        "future",
        days_ago=1,
        assessed_days_ago=-1,
    )
    view = derive_longitudinal_affect_view(
        [visible, other_relationship, future_assessment],
        query=query(),
    )
    assert view.total_occurrence_count == 1
    assert view.raw_record_count == 1
    assert view.revision_trajectories[0].effective_record == visible


def test_same_occurrence_revisions_count_once_and_keep_trajectory() -> None:
    first = record(
        "rev-1",
        days_ago=20,
        assessed_days_ago=20,
        occurrence_id="occ-shared",
        valence="negative",
    )
    revised = record(
        "rev-2",
        days_ago=20,
        assessed_days_ago=2,
        occurrence_id="occ-shared",
        valence="neutral",
    )
    view = derive_longitudinal_affect_view([first, revised], query=query())

    assert view.raw_record_count == 2
    assert view.total_occurrence_count == 1
    trajectory = view.revision_trajectories[0]
    assert trajectory.has_reappraisal is True
    assert trajectory.initial_valence == "negative"
    assert trajectory.effective_valence == "neutral"
    assert trajectory.effective_record == revised
    assert trajectory.revisions == (first, revised)


def test_long_stable_history_and_recent_deviation() -> None:
    earlier = [
        record(f"early-{index}", days_ago=40 - index, valence="positive")
        for index in range(12)
    ]
    recent = [
        record(f"recent-{index}", days_ago=3 - index, valence="negative")
        for index in range(3)
    ]
    view = derive_longitudinal_affect_view(
        earlier + recent,
        query=query(recent_window_days=7),
    )

    assert view.earlier_pattern.occurrence_count == 12
    assert view.earlier_pattern.predominant_valence == "positive"
    assert view.recent_segment.occurrence_count == 3
    assert view.recent_segment.predominant_valence == "negative"
    assert view.recent_segment.consecutive_valence_streak == 3
    assert view.recent_segment.has_recent_deviation is True
    assert view.recent_segment.deviation_reason == "earlier_positive_recent_negative"


def test_insufficient_coverage_does_not_claim_deviation() -> None:
    view = derive_longitudinal_affect_view(
        [
            record("old", days_ago=10, valence="positive"),
            record("new", days_ago=1, valence="negative"),
        ],
        query=query(min_earlier_occurrences=3),
    )
    assert view.recent_segment.has_recent_deviation is False
    assert view.recent_segment.deviation_reason == "insufficient_coverage"


def test_recent_streak_can_surface_deviation_when_recent_mode_is_neutral() -> None:
    earlier = [
        record(f"old-{i}", days_ago=20 - i, valence="positive")
        for i in range(4)
    ]
    recent = [
        record("recent-neutral-1", days_ago=5, valence="neutral"),
        record("recent-neutral-2", days_ago=4, valence="neutral"),
        record("recent-neutral-3", days_ago=3, valence="neutral"),
        record("recent-neg-1", days_ago=2, valence="negative"),
        record("recent-neg-2", days_ago=1, valence="negative"),
    ]
    view = derive_longitudinal_affect_view(
        earlier + recent,
        query=query(min_recent_occurrences=2),
    )
    assert view.recent_segment.consecutive_valence_streak == 2
    assert view.recent_segment.streak_valence == "negative"
    assert view.recent_segment.has_recent_deviation is True
    assert view.recent_segment.deviation_reason == "recent_2_negative_streak"


def test_repair_evidence_is_structural_not_a_relationship_verdict() -> None:
    verbal = record(
        "verbal",
        days_ago=5,
        valence="neutral",
        verbal_repair=True,
    )
    behavioral = record(
        "behavior",
        days_ago=2,
        valence="positive",
        behavioral_repair=True,
    )
    view = derive_longitudinal_affect_view([verbal, behavioral], query=query())
    repair = view.repair_evidence

    assert repair.has_verbal_repair is True
    assert repair.has_behavioral_repair is True
    assert repair.repair_assessment == "behavioral_supported"
    assert repair.verbal_repair_count == 1
    assert repair.behavioral_repair_count == 1


def test_verbal_only_repair_is_distinct() -> None:
    view = derive_longitudinal_affect_view(
        [record("verbal", days_ago=2, verbal_repair=True)],
        query=query(),
    )
    assert view.repair_evidence.repair_assessment == "verbal_only"


def test_max_occurrences_keeps_latest_occurrence_identities() -> None:
    records = [
        record(f"r{i}", days_ago=10 - i)
        for i in range(6)
    ]
    view = derive_longitudinal_affect_view(
        records,
        query=query(max_occurrences=3),
    )
    assert [item.effective_record.record_id for item in view.revision_trajectories] == [
        "r3",
        "r4",
        "r5",
    ]


def test_explicit_recent_since_overrides_window() -> None:
    view = derive_longitudinal_affect_view(
        [
            record("old", days_ago=9),
            record("mid", days_ago=6),
            record("new", days_ago=1),
        ],
        query=query(recent_since=NOW - timedelta(days=8)),
    )
    assert view.earlier_pattern.occurrence_count == 1
    assert view.recent_segment.occurrence_count == 2


def test_condition_omits_objective_and_zero_history() -> None:
    empty = derive_longitudinal_affect_view([], query=query())
    zero = compile_longitudinal_affect_condition(
        user_message="Hello.",
        participant_id="alice",
        view=empty,
    )
    assert zero.is_omitted is True
    assert zero.omission_reason == "zero_history_omission"

    nonempty = derive_longitudinal_affect_view(
        [record("r1", days_ago=2)],
        query=query(),
    )
    objective = compile_longitudinal_affect_condition(
        user_message="Check grammar: I am here.",
        participant_id="alice",
        view=nonempty,
    )
    assert objective.is_omitted is True
    assert objective.omission_reason == "objective_task_omission"


def test_condition_preserves_temporal_structure_without_entity_verdicts() -> None:
    earlier = [
        record(f"early-{i}", days_ago=30 - i, valence="positive")
        for i in range(6)
    ]
    revised_first = record(
        "shared-a",
        days_ago=3,
        assessed_days_ago=3,
        occurrence_id="shared",
        valence="negative",
        verbal_repair=True,
    )
    revised_later = record(
        "shared-b",
        days_ago=3,
        assessed_days_ago=1,
        occurrence_id="shared",
        valence="negative",
        verbal_repair=True,
    )
    behavioral = record(
        "behavior",
        days_ago=1,
        valence="negative",
        behavioral_repair=True,
    )
    view = derive_longitudinal_affect_view(
        earlier + [revised_first, revised_later, behavioral],
        query=query(min_recent_occurrences=1),
    )
    condition = compile_longitudinal_affect_condition(
        user_message="How should I respond?",
        participant_id="alice",
        view=view,
    )

    assert condition.is_omitted is False
    assert "Earlier covered appraisal history for alice" in condition.text
    assert "differing from the earlier distribution" in condition.text
    assert "behavior marked as repair evidence" in condition.text
    assert "later reappraised" in condition.text
    lowered = condition.text.lower()
    for forbidden in (
        "forgiven",
        "trust restored",
        "relationship repaired",
        "unreliable",
        "deteriorating",
    ):
        assert forbidden not in lowered


def test_condition_with_only_recent_history_stays_bounded() -> None:
    view = derive_longitudinal_affect_view(
        [record("recent", days_ago=1, valence="neutral")],
        query=query(),
    )
    condition = compile_longitudinal_affect_condition(
        user_message="Hello",
        participant_id="alice",
        view=view,
    )
    assert condition.is_omitted is False
    assert "1 independent occurrences" in condition.text
    assert "Recent covered segment: 1 occurrences" in condition.text
    assert condition.coverage_summary == "1_occurrences"
