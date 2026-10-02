"""Read-only longitudinal structure over accepted affect appraisals."""

from __future__ import annotations

from datetime import timedelta

from mind_runtime.contracts.longitudinal_affect import (
    AffectRepairEvidence,
    AffectRevisionTrajectory,
    EarlierAffectPattern,
    LongitudinalAffectQuery,
    LongitudinalAffectRecord,
    LongitudinalAffectView,
    RecentAffectSegment,
)


def resolve_affect_occurrence_id(record: LongitudinalAffectRecord) -> str | None:
    """Resolve one canonical occurrence without inventing identity."""

    occurrence_id = record.source_occurrence_id
    if occurrence_id is not None:
        if occurrence_id.startswith(("occ-sum", "summary")):
            return record.source_refs[0] if record.source_refs else None
        return occurrence_id
    if len(record.source_refs) == 1:
        return record.source_refs[0]
    return None


def _valence_bucket(value: str) -> str:
    normalized = value.strip().lower()
    if normalized == "positive":
        return "positive"
    if normalized == "negative":
        return "negative"
    return "neutral"


def _predominant_valence(
    trajectories: list[AffectRevisionTrajectory],
) -> str:
    counts = {"positive": 0, "negative": 0, "neutral": 0}
    for trajectory in trajectories:
        counts[_valence_bucket(trajectory.effective_valence)] += 1
    if not trajectories:
        return "neutral"
    highest = max(counts.values())
    tied = {name for name, count in counts.items() if count == highest}
    for preferred in ("neutral", "positive", "negative"):
        if preferred in tied:
            return preferred
    return "neutral"


def _count_valence(
    trajectories: list[AffectRevisionTrajectory],
) -> tuple[int, int, int]:
    positive = sum(
        _valence_bucket(item.effective_valence) == "positive"
        for item in trajectories
    )
    negative = sum(
        _valence_bucket(item.effective_valence) == "negative"
        for item in trajectories
    )
    neutral = len(trajectories) - positive - negative
    return positive, negative, neutral


def derive_longitudinal_affect_view(
    records: tuple[LongitudinalAffectRecord, ...]
    | list[LongitudinalAffectRecord],
    *,
    query: LongitudinalAffectQuery,
) -> LongitudinalAffectView:
    """Derive a bounded relationship-affect view at query.as_of.

    Only records known by the cutoff are visible. Multiple revisions of one
    occurrence count once; the latest visible appraisal is effective while the
    revision trajectory remains inspectable.
    """

    matched = [
        record
        for record in records
        if record.relationship_id == query.relationship_id
        and record.assessed_at <= query.as_of
    ]
    raw_record_count = len(matched)

    groups: dict[str, list[LongitudinalAffectRecord]] = {}
    unresolved_record_count = 0
    for record in matched:
        occurrence_id = resolve_affect_occurrence_id(record)
        if occurrence_id is None:
            unresolved_record_count += 1
            continue
        groups.setdefault(occurrence_id, []).append(record)

    trajectories: list[AffectRevisionTrajectory] = []
    for occurrence_id, revisions in groups.items():
        ordered = sorted(
            revisions,
            key=lambda item: (
                item.assessed_at,
                item.source_occurred_at,
                item.record_id,
            ),
        )
        initial = ordered[0]
        effective = ordered[-1]
        trajectories.append(
            AffectRevisionTrajectory(
                occurrence_id=occurrence_id,
                source_occurred_at=effective.source_occurred_at,
                revisions=tuple(ordered),
                effective_record=effective,
                has_reappraisal=len(ordered) > 1,
                initial_valence=initial.valence,
                effective_valence=effective.valence,
            )
        )

    trajectories.sort(
        key=lambda item: (item.source_occurred_at, item.occurrence_id)
    )
    if len(trajectories) > query.max_occurrences:
        trajectories = trajectories[-query.max_occurrences :]

    cutoff = (
        query.recent_since
        if query.recent_since is not None
        else query.as_of - timedelta(days=query.recent_window_days)
    )
    earlier = [
        item for item in trajectories if item.source_occurred_at <= cutoff
    ]
    recent = [
        item for item in trajectories if item.source_occurred_at > cutoff
    ]

    earlier_positive, earlier_negative, earlier_neutral = _count_valence(earlier)
    recent_positive, recent_negative, recent_neutral = _count_valence(recent)
    all_positive, all_negative, all_neutral = _count_valence(trajectories)

    earlier_predominant = _predominant_valence(earlier)
    recent_predominant = (
        _predominant_valence(recent) if recent else earlier_predominant
    )

    earlier_span_days = 0.0
    if len(earlier) >= 2:
        earlier_span_days = max(
            0.0,
            (
                earlier[-1].source_occurred_at
                - earlier[0].source_occurred_at
            ).total_seconds()
            / 86400.0,
        )

    streak_valence = "neutral"
    streak_count = 0
    if recent:
        streak_valence = _valence_bucket(recent[-1].effective_valence)
        for item in reversed(recent):
            if _valence_bucket(item.effective_valence) != streak_valence:
                break
            streak_count += 1

    has_deviation = False
    deviation_reason: str | None = None
    if (
        len(earlier) < query.min_earlier_occurrences
        or len(recent) < query.min_recent_occurrences
    ):
        deviation_reason = "insufficient_coverage"
    elif (
        recent_predominant != "neutral"
        and recent_predominant != earlier_predominant
    ):
        has_deviation = True
        deviation_reason = (
            f"earlier_{earlier_predominant}_recent_{recent_predominant}"
        )
    elif (
        streak_valence != "neutral"
        and streak_valence != earlier_predominant
        and streak_count >= query.min_recent_occurrences
    ):
        has_deviation = True
        deviation_reason = (
            f"recent_{streak_count}_{streak_valence}_streak"
        )

    verbal_repair_count = sum(
        item.effective_record.verbal_repair_signal for item in trajectories
    )
    behavioral_repair_count = sum(
        item.effective_record.behavioral_repair_signal
        for item in trajectories
    )
    has_verbal_repair = verbal_repair_count > 0
    has_behavioral_repair = behavioral_repair_count > 0
    if has_behavioral_repair:
        repair_assessment = "behavioral_supported"
    elif has_verbal_repair:
        repair_assessment = "verbal_only"
    else:
        repair_assessment = "none"

    total_span_days = 0.0
    if len(trajectories) >= 2:
        total_span_days = max(
            0.0,
            (
                trajectories[-1].source_occurred_at
                - trajectories[0].source_occurred_at
            ).total_seconds()
            / 86400.0,
        )

    return LongitudinalAffectView(
        relationship_id=query.relationship_id,
        total_occurrence_count=len(trajectories),
        raw_record_count=raw_record_count,
        unresolved_record_count=unresolved_record_count,
        positive_count=all_positive,
        negative_count=all_negative,
        neutral_count=all_neutral,
        covered_time_span_days=total_span_days,
        earlier_pattern=EarlierAffectPattern(
            occurrence_count=len(earlier),
            positive_count=earlier_positive,
            negative_count=earlier_negative,
            neutral_count=earlier_neutral,
            covered_time_span_days=earlier_span_days,
            predominant_valence=earlier_predominant,
            first_occurrence_at=(
                earlier[0].source_occurred_at if earlier else None
            ),
            last_occurrence_at=(
                earlier[-1].source_occurred_at if earlier else None
            ),
        ),
        recent_segment=RecentAffectSegment(
            occurrence_count=len(recent),
            positive_count=recent_positive,
            negative_count=recent_negative,
            neutral_count=recent_neutral,
            predominant_valence=recent_predominant,
            consecutive_valence_streak=streak_count,
            streak_valence=streak_valence,
            has_recent_deviation=has_deviation,
            deviation_reason=deviation_reason,
        ),
        repair_evidence=AffectRepairEvidence(
            verbal_repair_count=verbal_repair_count,
            behavioral_repair_count=behavioral_repair_count,
            has_verbal_repair=has_verbal_repair,
            has_behavioral_repair=has_behavioral_repair,
            repair_assessment=repair_assessment,
        ),
        revision_trajectories=tuple(trajectories),
        is_empty=not trajectories,
    )
