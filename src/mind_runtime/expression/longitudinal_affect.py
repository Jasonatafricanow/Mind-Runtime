"""Bounded expression projection for longitudinal affect structure."""

from __future__ import annotations

from mind_runtime.contracts.longitudinal_affect import (
    LongitudinalAffectCondition,
    LongitudinalAffectView,
)

_OBJECTIVE_MARKERS = (
    "check grammar",
    "translate:",
    "summarize:",
    "proofread:",
    "format code:",
)


def compile_longitudinal_affect_condition(
    *,
    user_message: str,
    participant_id: str,
    view: LongitudinalAffectView,
) -> LongitudinalAffectCondition:
    """Render structure without turning it into an entity or relationship verdict."""

    if any(marker in user_message.strip().lower() for marker in _OBJECTIVE_MARKERS):
        return LongitudinalAffectCondition(
            text="",
            is_omitted=True,
            omission_reason="objective_task_omission",
            coverage_summary="omitted",
        )

    if view.total_occurrence_count == 0:
        return LongitudinalAffectCondition(
            text="",
            is_omitted=True,
            omission_reason="zero_history_omission",
            coverage_summary="no_relationship_history",
        )

    earlier = view.earlier_pattern
    recent = view.recent_segment
    repair = view.repair_evidence
    parts: list[str] = []

    if earlier.occurrence_count:
        if earlier.covered_time_span_days >= 14:
            span = (
                f" across "
                f"{int(round(earlier.covered_time_span_days / 7.0))} weeks"
            )
        elif earlier.covered_time_span_days > 0:
            span = f" over {int(earlier.covered_time_span_days)} days"
        else:
            span = ""
        parts.append(
            f"Earlier covered appraisal history for {participant_id}: "
            f"{earlier.occurrence_count} independent occurrences{span}; "
            f"appraisal valence predominantly {earlier.predominant_valence} "
            f"({earlier.positive_count} positive, "
            f"{earlier.neutral_count} neutral, "
            f"{earlier.negative_count} negative)."
        )
    else:
        parts.append(
            f"Covered appraisal history for {participant_id}: "
            f"{view.total_occurrence_count} independent occurrences."
        )

    if recent.occurrence_count:
        if recent.has_recent_deviation:
            parts.append(
                f"Recent covered segment: "
                f"{recent.consecutive_valence_streak} consecutive "
                f"{recent.streak_valence} appraisal occurrences, "
                "differing from the earlier distribution."
            )
        else:
            parts.append(
                f"Recent covered segment: {recent.occurrence_count} "
                "occurrences, with no supported deviation from the earlier "
                "pattern."
            )

    if repair.has_behavioral_repair:
        parts.append(
            "Subsequent behavior marked as repair evidence was observed "
            f"({repair.behavioral_repair_count} occurrences)."
        )
    elif repair.has_verbal_repair:
        parts.append(
            "Verbal repair evidence was recorded; no later behavioral repair "
            "evidence is present in the covered history."
        )

    if any(
        trajectory.has_reappraisal
        for trajectory in view.revision_trajectories
    ):
        parts.append(
            "At least one occurrence was later reappraised after additional "
            "context."
        )

    return LongitudinalAffectCondition(
        text=" ".join(parts),
        is_omitted=False,
        omission_reason=None,
        coverage_summary=f"{view.total_occurrence_count}_occurrences",
    )
