"""Provider-neutral, bounded, read-only historical context assembly."""

from collections.abc import Mapping
from dataclasses import replace
from datetime import datetime, timedelta
from typing import Any, Protocol, runtime_checkable

from mind_runtime.contracts import (
    HistoricalContextBundle,
    HistoricalContextItem,
    HistoricalContextQuery,
    LongitudinalQuery,
    LongitudinalView,
    Observation,
    PatternMatchSummary,
    PatternQuery,
    Scope,
    ScopeDomain,
    Situation,
)


class HistoryProviderUnavailable(RuntimeError):
    """A declared availability failure; current-turn logic may continue."""


@runtime_checkable
class HistoricalContextProvider(Protocol):
    """Query-only provider surface; no touch/reinforce/write operations."""

    def query(self, query: HistoricalContextQuery) -> HistoricalContextBundle:
        """Return immutable historical facts for one bounded query."""
        ...


class NullHistoricalContext:
    """Deterministic no-history path."""

    def read(
        self,
        *,
        interaction_id: str,
        context: Situation,
        observations: tuple[Observation, ...],
        scope: Scope,
        clock: datetime,
    ) -> HistoricalContextBundle | None:
        del interaction_id, context, observations, scope, clock
        return None


class BoundedHistoricalContextAdapter:
    """Validate, deduplicate, and clip facts returned by a query-only provider."""

    def __init__(self, *, provider: HistoricalContextProvider, budget: int) -> None:
        if isinstance(budget, bool) or budget < 0:
            raise ValueError("budget must be non-negative")
        self._provider = provider
        self._budget = budget

    def read(
        self,
        *,
        interaction_id: str,
        context: Situation,
        observations: tuple[Observation, ...],
        scope: Scope,
        clock: datetime,
    ) -> HistoricalContextBundle | None:
        del clock
        if context.scope != scope:
            raise ValueError("context scope must match history read scope")
        if any(observation.scope != scope for observation in observations):
            raise ValueError("observation scope must match history read scope")
        query = HistoricalContextQuery(
            query_id=f"history-query-{interaction_id}",
            scope=scope,
            origin_runtime_id=context.origin_runtime_id,
            situation_hint=context.situation_id,
            query_text=None,
            pattern_queries=tuple(
                PatternQuery(
                    query_id=f"pattern-{interaction_id}-{index}",
                    scope=scope,
                    origin_runtime_id=context.origin_runtime_id,
                    signature=signature,
                    time_window="all",
                    filters=(),
                )
                for index, signature in enumerate(self._typed_signatures(observations), start=1)
            ),
            budget=self._budget,
        )
        try:
            bundle = self._provider.query(query)
        except HistoryProviderUnavailable:
            return None
        return self._bounded_copy(bundle, scope=scope)

    @staticmethod
    def _typed_signatures(observations: tuple[Observation, ...]) -> tuple[str, ...]:
        signatures: set[str] = set()
        for observation in observations:
            if observation.key != "typed_event.observed" or not isinstance(
                observation.value, Mapping
            ):
                continue
            kind = observation.value.get("kind")
            if isinstance(kind, str) and kind.strip():
                signatures.add(kind)
        return tuple(sorted(signatures))

    def _bounded_copy(
        self, bundle: HistoricalContextBundle, *, scope: Scope
    ) -> HistoricalContextBundle:
        if bundle.scope != scope:
            raise ValueError("historical bundle scope must match read scope")
        categorized: tuple[tuple[str, HistoricalContextItem], ...] = tuple(
            (category, item)
            for category, items in (
                ("episodes", bundle.episodes),
                ("stable_facts", bundle.stable_facts),
                ("relationship_events", bundle.relationship_events),
            )
            for item in items
        )
        for _category, item in categorized:
            if item.scope != scope:
                raise ValueError("historical item scope must match read scope")
        for summary in bundle.pattern_summaries:
            if summary.scope != scope:
                raise ValueError("pattern summary scope must match read scope")
        self._validate_relationship_provenance(bundle, scope=scope)

        selected: list[tuple[str, HistoricalContextItem]] = []
        seen_items: set[str] = set()
        for category, item in sorted(categorized, key=lambda entry: entry[1].item_id):
            if item.item_id in seen_items:
                continue
            seen_items.add(item.item_id)
            if len(selected) >= self._budget:
                continue
            selected.append((category, item))

        remaining = self._budget - len(selected)
        selected_relationship_ids = {
            item.item_id for category, item in selected if category == "relationship_events"
        }
        selected_summaries: list[PatternMatchSummary] = []
        seen_summaries: set[str] = set()
        for summary in sorted(bundle.pattern_summaries, key=lambda entry: entry.summary_id):
            if summary.summary_id in seen_summaries:
                continue
            seen_summaries.add(summary.summary_id)
            if (
                scope.domain is ScopeDomain.RELATIONSHIP
                and not set(summary.matched_refs) <= selected_relationship_ids
            ):
                continue
            if len(selected_summaries) >= remaining:
                continue
            selected_summaries.append(
                replace(summary, matched_refs=tuple(dict.fromkeys(summary.matched_refs)))
            )

        return HistoricalContextBundle(
            bundle_id=bundle.bundle_id,
            scope=bundle.scope,
            origin_runtime_id=bundle.origin_runtime_id,
            episodes=tuple(item for category, item in selected if category == "episodes"),
            stable_facts=tuple(item for category, item in selected if category == "stable_facts"),
            relationship_events=tuple(
                item for category, item in selected if category == "relationship_events"
            ),
            pattern_summaries=tuple(selected_summaries),
            source_refs=tuple(sorted(set(bundle.source_refs))),
            provider_trace=bundle.provider_trace,
        )

    @staticmethod
    def _validate_relationship_provenance(
        bundle: HistoricalContextBundle,
        *,
        scope: Scope,
    ) -> None:
        if bundle.relationship_events and scope.domain is not ScopeDomain.RELATIONSHIP:
            raise ValueError("relationship_events require relationship scope")
        if scope.domain is not ScopeDomain.RELATIONSHIP:
            return
        relationship_ids = {item.item_id for item in bundle.relationship_events}
        for item in bundle.relationship_events:
            if not item.source_refs:
                raise ValueError("private relationship items require source refs")
        for summary in bundle.pattern_summaries:
            if not summary.matched_refs:
                raise ValueError("relationship summaries require matched refs")
            if not set(summary.matched_refs) <= relationship_ids:
                raise ValueError(
                    "relationship summary refs must resolve to selected relationship items"
                )


def resolve_occurrence_identity(record: object) -> str | None:
    """Resolve canonical occurrence identity from an appraisal record.

    Authority order:
    1. If source_occurrence_id is present:
       - If it is an internally derived summary (e.g. prefixed with 'occ-sum' or 'summary'),
         the root occurrence is resolved from source_refs[0] if available.
       - Otherwise, source_occurrence_id is the canonical occurrence identity.
    2. Fallback legacy hint: record.source_refs[0] ONLY if source_occurrence_id is not set.
    If neither is present/valid, returns None (representing 'unresolved').
    """
    occ_id = getattr(record, "source_occurrence_id", None)
    refs = getattr(record, "source_refs", None)
    primary_ref = (
        refs[0].strip()
        if refs and isinstance(refs, (tuple, list)) and len(refs) > 0 and isinstance(refs[0], str) and refs[0].strip()
        else None
    )

    if occ_id and isinstance(occ_id, str) and occ_id.strip():
        occ_str = occ_id.strip()
        # If this occurrence is explicitly a summary or re-summary, resolve to root occurrence
        if (occ_str.startswith("occ-sum") or occ_str.startswith("summary")) and primary_ref:
            return primary_ref
        return occ_str

    if primary_ref:
        return primary_ref

    return None


def derive_longitudinal_view(
    records: tuple[object, ...] | list[object],
    query: LongitudinalQuery,
    now: datetime,
) -> LongitudinalView:
    """Derive a bounded, read-time longitudinal view over accepted appraisals.

    Read-only derivation: never mutates, reinforces, or writes back to memory.
    """
    from mind_runtime.contracts.historical import (
        AppraisalRevisionTrajectory,
        EarlierPatternSummary,
        RecentSegmentSummary,
        RepairEvidenceSummary,
    )

    matched: list[Any] = []
    for r in records:
        rel_id = (
            getattr(getattr(r, "resolved_relationship_scope", None), "relationship_id", None)
            or getattr(getattr(r, "resolved_relationship_scope", None), "user_id", None)
            or getattr(getattr(r, "source_scope", None), "relationship_id", None)
            or getattr(getattr(r, "source_scope", None), "user_id", None)
        )
        if rel_id == query.relationship_id:
            matched.append(r)

    raw_record_count = len(matched)

    # Separate unresolved records from resolved occurrences
    unresolved_records: list[Any] = []
    resolved_groups: dict[str, list[Any]] = {}
    for r in matched:
        occ_id = resolve_occurrence_identity(r)
        if occ_id is None:
            unresolved_records.append(r)
        else:
            resolved_groups.setdefault(occ_id, []).append(r)
    unresolved_record_count = len(unresolved_records)

    if not resolved_groups:
        return LongitudinalView(
            total_record_count=0,
            positive_count=0,
            negative_count=0,
            neutral_count=0,
            covered_time_span_days=0.0,
            earlier_segment_count=0,
            recent_segment_count=0,
            earlier_predominant_valence="neutral",
            recent_predominant_valence="neutral",
            exceptions=(),
            is_empty=True,
            distinct_root_count=0,
            raw_record_count=raw_record_count,
            earlier_pattern=EarlierPatternSummary(
                occurrence_count=0,
                positive_count=0,
                negative_count=0,
                neutral_count=0,
                covered_time_span_days=0.0,
                predominant_valence="neutral",
                is_empty=True,
            ),
            recent_segment=RecentSegmentSummary(
                occurrence_count=0,
                positive_count=0,
                negative_count=0,
                neutral_count=0,
                predominant_valence="neutral",
                is_empty=True,
            ),
            repair_evidence=RepairEvidenceSummary(
                verbal_repair_count=0,
                behavioral_repair_count=0,
                has_verbal_repair=False,
                has_behavioral_repair=False,
                repair_assessment="none",
            ),
            revision_trajectories=(),
            unresolved_record_count=unresolved_record_count,
        )

    # Build AppraisalRevisionTrajectory for each occurrence
    trajectories: list[AppraisalRevisionTrajectory] = []
    for occ_id, group in resolved_groups.items():
        sorted_revs = sorted(
            group,
            key=lambda rec: (
                getattr(rec, "assessed_at", now),
                getattr(rec, "source_occurred_at", now),
                getattr(rec, "acceptance_id", ""),
            ),
        )
        effective = sorted_revs[-1]
        initial = sorted_revs[0]
        initial_val = getattr(initial, "valence", "neutral")
        eff_val = getattr(effective, "valence", "neutral")
        has_reappraisal = (len(sorted_revs) > 1 and initial_val != eff_val) or (len(sorted_revs) > 1)
        occ_time = getattr(effective, "source_occurred_at", now)

        trajectories.append(
            AppraisalRevisionTrajectory(
                occurrence_id=occ_id,
                source_occurred_at=occ_time,
                revisions=tuple(sorted_revs),
                effective_appraisal=effective,
                has_reappraisal=has_reappraisal,
                initial_valence=initial_val,
                effective_valence=eff_val,
            )
        )

    trajectories.sort(key=lambda t: t.source_occurred_at)
    if len(trajectories) > query.max_records:
        trajectories = trajectories[-query.max_records:]

    # Determine temporal cutoff
    if query.recent_since is not None:
        cutoff = query.recent_since
    else:
        window_days = getattr(query, "recent_window_days", None) or getattr(query, "recent_days", 7)
        cutoff = now - timedelta(days=window_days)

    earlier_trajs = [t for t in trajectories if t.source_occurred_at <= cutoff]
    recent_trajs = [t for t in trajectories if t.source_occurred_at > cutoff]

    def _predominant_valence_from_trajectories(trajs: list[AppraisalRevisionTrajectory]) -> str:
        if not trajs:
            return "neutral"
        counts = {"positive": 0, "negative": 0, "neutral": 0}
        for t in trajs:
            v = t.effective_valence
            if v in counts:
                counts[v] += 1
            else:
                counts["neutral"] += 1
        return max(
            counts.keys(),
            key=lambda k: (counts[k], 1 if k == "positive" else (0 if k == "neutral" else -1)),
        )

    # Earlier pattern summary
    earlier_pos = sum(1 for t in earlier_trajs if t.effective_valence == "positive")
    earlier_neg = sum(1 for t in earlier_trajs if t.effective_valence == "negative")
    earlier_neu = sum(1 for t in earlier_trajs if t.effective_valence not in ("positive", "negative"))
    earlier_pred = _predominant_valence_from_trajectories(earlier_trajs) if earlier_trajs else "neutral"

    earlier_span_days = 0.0
    if len(earlier_trajs) >= 2:
        earlier_span_days = max(
            0.0,
            (earlier_trajs[-1].source_occurred_at - earlier_trajs[0].source_occurred_at).total_seconds() / 86400.0,
        )

    earlier_pattern = EarlierPatternSummary(
        occurrence_count=len(earlier_trajs),
        positive_count=earlier_pos,
        negative_count=earlier_neg,
        neutral_count=earlier_neu,
        covered_time_span_days=earlier_span_days,
        predominant_valence=earlier_pred,
        first_occurrence_at=earlier_trajs[0].source_occurred_at if earlier_trajs else None,
        last_occurrence_at=earlier_trajs[-1].source_occurred_at if earlier_trajs else None,
        is_empty=(len(earlier_trajs) == 0),
    )

    # Recent segment summary
    recent_pos = sum(1 for t in recent_trajs if t.effective_valence == "positive")
    recent_neg = sum(1 for t in recent_trajs if t.effective_valence == "negative")
    recent_neu = sum(1 for t in recent_trajs if t.effective_valence not in ("positive", "negative"))
    recent_pred = _predominant_valence_from_trajectories(recent_trajs) if recent_trajs else earlier_pred

    streak_val = "neutral"
    streak_count = 0
    if recent_trajs:
        streak_val = recent_trajs[-1].effective_valence
        for t in reversed(recent_trajs):
            if t.effective_valence == streak_val:
                streak_count += 1
            else:
                break

    min_early = getattr(query, "min_earlier_occurrences", 3)
    min_recent = getattr(query, "min_recent_occurrences", 1)

    has_deviation = False
    deviation_reason = None
    if len(earlier_trajs) < min_early or len(recent_trajs) < min_recent:
        has_deviation = False
        deviation_reason = "insufficient_coverage"
    else:
        if earlier_pred != recent_pred and recent_pred != "neutral":
            has_deviation = True
            deviation_reason = f"earlier predominantly {earlier_pred}, recent predominantly {recent_pred}"
        elif streak_val != earlier_pred and streak_count >= min_recent and streak_val != "neutral":
            has_deviation = True
            deviation_reason = f"recent {streak_count} consecutive {streak_val} occurrences differ from earlier {earlier_pred} pattern"
        else:
            has_deviation = False
            deviation_reason = None

    recent_segment = RecentSegmentSummary(
        occurrence_count=len(recent_trajs),
        positive_count=recent_pos,
        negative_count=recent_neg,
        neutral_count=recent_neu,
        predominant_valence=recent_pred,
        consecutive_valence_streak=streak_count,
        streak_valence=streak_val,
        has_recent_deviation=has_deviation,
        deviation_reason=deviation_reason,
        is_empty=(len(recent_trajs) == 0),
    )

    # Repair evidence summary
    verbal_reps: list[AppraisalRevisionTrajectory] = []
    behavioral_reps: list[AppraisalRevisionTrajectory] = []
    for t in trajectories:
        meanings = getattr(t.effective_appraisal, "meanings", ()) or ()
        is_verbal = any(m in ("verbal_apology", "apology", "repair_attempt", "apologized") for m in meanings)
        is_behavioral = any(m in ("promise_kept", "commitment_fulfilled", "repaired_behavior", "kept_promise") for m in meanings)
        if is_verbal:
            verbal_reps.append(t)
        if is_behavioral:
            behavioral_reps.append(t)

    verbal_repair_count = len(verbal_reps)
    behavioral_repair_count = len(behavioral_reps)
    has_verbal = (verbal_repair_count > 0)
    has_behavioral = (behavioral_repair_count > 0)
    repair_assessment = "behavioral_supported" if has_behavioral else ("verbal_only" if has_verbal else "none")

    details = []
    if has_verbal:
        details.append(f"verbal_apology_occurrences={verbal_repair_count}")
    if has_behavioral:
        details.append(f"behavioral_fulfillment_occurrences={behavioral_repair_count}")

    repair_evidence = RepairEvidenceSummary(
        verbal_repair_count=verbal_repair_count,
        behavioral_repair_count=behavioral_repair_count,
        has_verbal_repair=has_verbal,
        has_behavioral_repair=has_behavioral,
        repair_assessment=repair_assessment,
        details=tuple(details),
    )

    # Overall view metrics
    total_count = len(trajectories)
    distinct_root_count = len(trajectories)
    pos_count = sum(1 for t in trajectories if t.effective_valence == "positive")
    neg_count = sum(1 for t in trajectories if t.effective_valence == "negative")
    neu_count = sum(1 for t in trajectories if t.effective_valence not in ("positive", "negative"))

    time_span_days = 0.0
    if len(trajectories) >= 2:
        time_span_days = max(
            0.0,
            (trajectories[-1].source_occurred_at - trajectories[0].source_occurred_at).total_seconds() / 86400.0,
        )

    exceptions = tuple(
        t.effective_appraisal
        for t in recent_trajs
        if t.effective_valence != earlier_pred
    )

    return LongitudinalView(
        total_record_count=total_count,
        positive_count=pos_count,
        negative_count=neg_count,
        neutral_count=neu_count,
        covered_time_span_days=time_span_days,
        earlier_segment_count=len(earlier_trajs),
        recent_segment_count=len(recent_trajs),
        earlier_predominant_valence=earlier_pred if earlier_trajs else _predominant_valence_from_trajectories(trajectories),
        recent_predominant_valence=recent_pred if recent_trajs else earlier_pred,
        exceptions=exceptions,
        is_empty=False,
        distinct_root_count=distinct_root_count,
        raw_record_count=raw_record_count,
        earlier_pattern=earlier_pattern,
        recent_segment=recent_segment,
        repair_evidence=repair_evidence,
        revision_trajectories=tuple(trajectories),
        unresolved_record_count=unresolved_record_count,
    )

