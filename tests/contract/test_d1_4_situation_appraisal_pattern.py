"""D1.4 Situation / Appraisal / Pattern contract tests."""

from dataclasses import FrozenInstanceError, fields
from datetime import UTC, datetime

import pytest

from mind_runtime.contracts import (
    AmbiguityAssessment,
    AppraisalPath,
    AppraisalRouteDecision,
    HistoricalContextBundle,
    HistoricalContextItem,
    HistoricalContextQuery,
    PatternMatchSummary,
    PatternQuery,
    Scope,
    ScopeDomain,
    SemanticAppraisal,
    Situation,
)

NOW = datetime(2026, 8, 20, 11, 0, tzinfo=UTC)


def make_scope() -> Scope:
    return Scope(domain=ScopeDomain.USER, user_id="user-1")


def make_pattern_query(query_id: str = "pq-1") -> PatternQuery:
    return PatternQuery(
        query_id=query_id,
        scope=make_scope(),
        origin_runtime_id="runtime-1",
        signature="cancellation_after_plan",
        time_window="14d",
        filters=(("domain", "user"),),
    )


def make_pattern_summary(summary_id: str = "ps-1") -> PatternMatchSummary:
    return PatternMatchSummary(
        summary_id=summary_id,
        scope=make_scope(),
        origin_runtime_id="runtime-1",
        match_count=3,
        first_seen_at=NOW,
        last_seen_at=NOW,
        matched_refs=("evidence-1", "evidence-2", "evidence-3"),
        confidence=0.7,
    )


def make_history_item(item_id: str = "hc-1") -> HistoricalContextItem:
    return HistoricalContextItem(
        item_id=item_id,
        scope=make_scope(),
        external_id="ext-1",
        kind="episode",
        proposition="user cancelled a plan last week",
        source_refs=("evidence-1",),
        confidence=0.8,
        relevance_hint=0.6,
    )


def make_history_bundle(bundle_id: str = "hb-1") -> HistoricalContextBundle:
    return HistoricalContextBundle(
        bundle_id=bundle_id,
        scope=make_scope(),
        origin_runtime_id="runtime-1",
        episodes=(make_history_item(),),
        stable_facts=(),
        relationship_events=(),
        pattern_summaries=(make_pattern_summary(),),
        source_refs=("evidence-1",),
        provider_trace="fixture-provider",
    )


def make_history_query(query_id: str = "hq-1") -> HistoricalContextQuery:
    return HistoricalContextQuery(
        query_id=query_id,
        scope=make_scope(),
        origin_runtime_id="runtime-1",
        situation_hint="user mentioned cancellation",
        query_text=None,
        pattern_queries=(make_pattern_query(),),
        budget=50,
    )


def make_situation(situation_id: str = "situation-1") -> Situation:
    return Situation(
        situation_id=situation_id,
        scope=make_scope(),
        origin_runtime_id="runtime-1",
        derived_facts=(("user_activity", "awake_and_engaged"), ("conversation_mode", "active")),
        effective_state_ref="state-1",
        observed_at=NOW,
        historical_context=make_history_bundle(),
        persona_id="persona-1",
        relationship_ids=("relationship-1",),
        evidence_refs=("evidence-1",),
    )


def make_semantic_appraisal(appraisal_id: str = "appraisal-1") -> SemanticAppraisal:
    return SemanticAppraisal(
        appraisal_id=appraisal_id,
        scope=make_scope(),
        origin_runtime_id="runtime-1",
        situation_ref="situation-1",
        meanings=("possible_rejection",),
        valence="negative",
        relationship_relevance="moderate",
        confidence=0.71,
        evidence_refs=("evidence-1",),
    )


def make_route() -> AppraisalRouteDecision:
    return AppraisalRouteDecision(
        route_id="route-1",
        scope=make_scope(),
        path=AppraisalPath.TYPED_MAPPING,
        ambiguity_score=None,
        confidence=0.9,
        reason_codes=("typed_event",),
    )


# --- DECISION-015 field preservation ---


def test_semantic_appraisal_preserves_decision_015_fields() -> None:
    field_names = {field.name for field in fields(SemanticAppraisal)}
    assert {
        "meanings",
        "valence",
        "relationship_relevance",
        "confidence",
        "evidence_refs",
    } <= field_names


def test_semantic_appraisal_has_no_affect_numbers() -> None:
    field_names = {field.name for field in fields(SemanticAppraisal)}
    assert "current_value" not in field_names
    assert "final_affect" not in field_names


def test_semantic_appraisal_is_immutable() -> None:
    appraisal = make_semantic_appraisal()
    with pytest.raises(FrozenInstanceError):
        appraisal.valence = "positive"  # type: ignore[misc]


def test_confidence_is_bounded() -> None:
    scope = make_scope()
    for value in (-0.1, 1.1, True):
        with pytest.raises(ValueError, match="confidence"):
            SemanticAppraisal(
                appraisal_id="a",
                scope=scope,
                origin_runtime_id="runtime-1",
                situation_ref="situation-1",
                meanings=(),
                valence="neutral",
                relationship_relevance="low",
                confidence=value,
                evidence_refs=(),
            )


# --- DECISION-025 route ---


def test_appraisal_path_values() -> None:
    assert {path.value for path in AppraisalPath} == {
        "deterministic",
        "typed_mapping",
        "llm",
    }


def test_route_preserves_decision_025_fields() -> None:
    field_names = {field.name for field in fields(AppraisalRouteDecision)}
    assert {"path", "ambiguity_score", "confidence", "reason_codes"} <= field_names


def test_route_ambiguity_score_bounded_when_present() -> None:
    scope = make_scope()
    with pytest.raises(ValueError, match="ambiguity_score"):
        AppraisalRouteDecision(
            route_id="route-bad",
            scope=scope,
            path=AppraisalPath.LLM,
            ambiguity_score=1.5,
            confidence=0.9,
            reason_codes=("ambiguous",),
        )
    route = AppraisalRouteDecision(
        route_id="route-1",
        scope=scope,
        path=AppraisalPath.DETERMINISTIC,
        ambiguity_score=None,
        confidence=0.9,
        reason_codes=("computed",),
    )
    assert route.ambiguity_score is None


def test_route_rejects_unknown_path() -> None:
    scope = make_scope()
    with pytest.raises(ValueError, match="path"):
        AppraisalRouteDecision(
            route_id="route-bad",
            scope=scope,
            path="nonsense",  # type: ignore[arg-type]
            ambiguity_score=None,
            confidence=0.9,
            reason_codes=(),
        )


def test_route_rejects_out_of_range_confidence() -> None:
    scope = make_scope()
    with pytest.raises(ValueError, match="confidence"):
        AppraisalRouteDecision(
            route_id="route-bad",
            scope=scope,
            path=AppraisalPath.DETERMINISTIC,
            ambiguity_score=None,
            confidence=1.1,
            reason_codes=(),
        )


def test_route_rejects_empty_reason_codes_entry() -> None:
    scope = make_scope()
    with pytest.raises(ValueError, match="non-empty"):
        AppraisalRouteDecision(
            route_id="route-bad",
            scope=scope,
            path=AppraisalPath.DETERMINISTIC,
            ambiguity_score=None,
            confidence=0.9,
            reason_codes=("",),
        )


def test_ambiguity_assessment_rejects_empty_reason() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        AmbiguityAssessment(ambiguous=True, score=0.6, reasons=(" ",))


def test_ambiguity_assessment_rejects_non_bool_flag() -> None:
    with pytest.raises(ValueError, match="ambiguous"):
        AmbiguityAssessment(ambiguous="yes", score=0.6, reasons=())  # type: ignore[arg-type]


def test_ambiguity_assessment_bounds_score() -> None:
    with pytest.raises(ValueError, match="score"):
        AmbiguityAssessment(ambiguous=True, score=2.0, reasons=("conflict",))
    assessment = AmbiguityAssessment(ambiguous=True, score=0.6, reasons=("conflict",))
    assert assessment.ambiguous is True


# --- DECISION-030 pattern ---


def test_pattern_query_preserves_decision_030_fields() -> None:
    field_names = {field.name for field in fields(PatternQuery)}
    assert {"signature", "scope", "time_window", "filters"} <= field_names


def test_pattern_summary_preserves_decision_030_fields() -> None:
    field_names = {field.name for field in fields(PatternMatchSummary)}
    assert {
        "match_count",
        "first_seen_at",
        "last_seen_at",
        "matched_refs",
        "confidence",
    } <= field_names


def test_pattern_query_accepts_valid_filters() -> None:
    query = make_pattern_query()
    assert query.filters == (("domain", "user"),)
    assert query.signature == "cancellation_after_plan"
    assert query.time_window == "14d"


def test_pattern_query_rejects_blank_signature_or_window() -> None:
    scope = make_scope()
    for field_value in ("", "  "):
        with pytest.raises(ValueError, match="non-empty"):
            PatternQuery(
                query_id="pq-bad",
                scope=scope,
                origin_runtime_id="runtime-1",
                signature=field_value,
                time_window="14d",
                filters=(),
            )
        with pytest.raises(ValueError, match="non-empty"):
            PatternQuery(
                query_id="pq-bad",
                scope=scope,
                origin_runtime_id="runtime-1",
                signature="sig",
                time_window=field_value,
                filters=(),
            )
    with pytest.raises(ValueError, match="non-empty"):
        PatternQuery(
            query_id="pq-bad",
            scope=scope,
            origin_runtime_id="runtime-1",
            signature="sig",
            time_window="14d",
            filters=(("", "value"),),
        )
    with pytest.raises(ValueError, match="non-empty"):
        PatternQuery(
            query_id="pq-bad",
            scope=scope,
            origin_runtime_id="runtime-1",
            signature="sig",
            time_window="14d",
            filters=(("key", ""),),
        )


def test_pattern_summary_rejects_blank_matched_ref() -> None:
    scope = make_scope()
    with pytest.raises(ValueError, match="non-empty"):
        PatternMatchSummary(
            summary_id="ps-bad",
            scope=scope,
            origin_runtime_id="runtime-1",
            match_count=1,
            first_seen_at=None,
            last_seen_at=None,
            matched_refs=("",),
            confidence=0.5,
        )


def test_pattern_summary_accepts_null_timestamps() -> None:
    scope = make_scope()
    summary = PatternMatchSummary(
        summary_id="ps-ok",
        scope=scope,
        origin_runtime_id="runtime-1",
        match_count=0,
        first_seen_at=None,
        last_seen_at=None,
        matched_refs=(),
        confidence=0.0,
    )
    assert summary.first_seen_at is None
    assert summary.last_seen_at is None


def test_pattern_summary_timestamps_aware_utc_when_present() -> None:
    scope = make_scope()
    with pytest.raises(ValueError, match="aware UTC"):
        PatternMatchSummary(
            summary_id="ps-bad",
            scope=scope,
            origin_runtime_id="runtime-1",
            match_count=1,
            first_seen_at=datetime(2026, 8, 20, 11, 0),
            last_seen_at=None,
            matched_refs=(),
            confidence=0.5,
        )


def test_pattern_summary_rejects_negative_match_count() -> None:
    scope = make_scope()
    with pytest.raises(ValueError, match="match_count"):
        PatternMatchSummary(
            summary_id="ps-bad",
            scope=scope,
            origin_runtime_id="runtime-1",
            match_count=-1,
            first_seen_at=None,
            last_seen_at=None,
            matched_refs=(),
            confidence=0.5,
        )


def test_pattern_summary_rejects_out_of_range_confidence() -> None:
    scope = make_scope()
    with pytest.raises(ValueError, match="confidence"):
        PatternMatchSummary(
            summary_id="ps-bad",
            scope=scope,
            origin_runtime_id="runtime-1",
            match_count=1,
            first_seen_at=None,
            last_seen_at=None,
            matched_refs=(),
            confidence=1.5,
        )


# --- MR-2 read contract ---


def test_history_query_preserves_read_contract_fields() -> None:
    field_names = {field.name for field in fields(HistoricalContextQuery)}
    assert {
        "scope",
        "situation_hint",
        "query_text",
        "pattern_queries",
        "budget",
    } <= field_names


def test_history_item_preserves_read_contract_fields() -> None:
    field_names = {field.name for field in fields(HistoricalContextItem)}
    assert {
        "external_id",
        "kind",
        "proposition",
        "source_refs",
        "confidence",
        "relevance_hint",
    } <= field_names


def test_history_bundle_preserves_read_contract_fields() -> None:
    field_names = {field.name for field in fields(HistoricalContextBundle)}
    assert {
        "episodes",
        "stable_facts",
        "relationship_events",
        "pattern_summaries",
        "source_refs",
        "provider_trace",
    } <= field_names


def test_history_bundle_rejects_blank_source_ref() -> None:
    scope = make_scope()
    with pytest.raises(ValueError, match="non-empty"):
        HistoricalContextBundle(
            bundle_id="hb-bad",
            scope=scope,
            origin_runtime_id="runtime-1",
            episodes=(),
            stable_facts=(),
            relationship_events=(),
            pattern_summaries=(),
            source_refs=(" ",),
            provider_trace="provider",
        )


def test_history_bundle_is_immutable() -> None:
    bundle = make_history_bundle()
    with pytest.raises(FrozenInstanceError):
        bundle.episodes = ()  # type: ignore[misc]


def test_history_query_accepts_valid_construction() -> None:
    query = make_history_query()
    assert query.situation_hint == "user mentioned cancellation"
    assert query.query_text is None
    assert query.budget == 50
    assert query.pattern_queries == (make_pattern_query(),)


def test_history_query_rejects_blank_hints() -> None:
    scope = make_scope()
    with pytest.raises(ValueError, match="non-empty"):
        HistoricalContextQuery(
            query_id="hq-bad",
            scope=scope,
            origin_runtime_id="runtime-1",
            situation_hint="   ",
            query_text=None,
            pattern_queries=(),
            budget=10,
        )
    with pytest.raises(ValueError, match="non-empty"):
        HistoricalContextQuery(
            query_id="hq-bad",
            scope=scope,
            origin_runtime_id="runtime-1",
            situation_hint=None,
            query_text="",
            pattern_queries=(),
            budget=10,
        )


def test_history_query_rejects_negative_budget() -> None:
    scope = make_scope()
    with pytest.raises(ValueError, match="budget"):
        HistoricalContextQuery(
            query_id="hq-bad",
            scope=scope,
            origin_runtime_id="runtime-1",
            situation_hint=None,
            query_text=None,
            pattern_queries=(),
            budget=-1,
        )


def test_history_item_confidence_bounded_when_present() -> None:
    scope = make_scope()
    with pytest.raises(ValueError, match="confidence"):
        HistoricalContextItem(
            item_id="hc-bad",
            scope=scope,
            external_id="ext-1",
            kind="episode",
            proposition="p",
            source_refs=(),
            confidence=1.5,
            relevance_hint=None,
        )
    with pytest.raises(ValueError, match="relevance_hint"):
        HistoricalContextItem(
            item_id="hc-bad",
            scope=scope,
            external_id="ext-1",
            kind="episode",
            proposition="p",
            source_refs=(),
            confidence=None,
            relevance_hint=-0.5,
        )


# --- Situation ---


def test_situation_is_interpretation_not_raw_dump() -> None:
    situation = make_situation()
    assert situation.derived_facts == (
        ("user_activity", "awake_and_engaged"),
        ("conversation_mode", "active"),
    )
    field_names = {field.name for field in fields(Situation)}
    assert "raw_state" not in field_names
    assert "value" not in field_names


def test_situation_observed_at_must_be_aware_utc() -> None:
    scope = make_scope()
    with pytest.raises(ValueError, match="aware UTC"):
        Situation(
            situation_id="s-bad",
            scope=scope,
            origin_runtime_id="runtime-1",
            derived_facts=(),
            effective_state_ref="state-1",
            observed_at=datetime(2026, 8, 20, 11, 0),
            historical_context=None,
            persona_id=None,
            relationship_ids=(),
            evidence_refs=(),
        )


def test_situation_is_immutable() -> None:
    situation = make_situation()
    with pytest.raises(FrozenInstanceError):
        situation.derived_facts = ()  # type: ignore[misc]


def test_situation_effective_state_ref_non_empty() -> None:
    scope = make_scope()
    with pytest.raises(ValueError, match="non-empty"):
        Situation(
            situation_id="s-bad",
            scope=scope,
            origin_runtime_id="runtime-1",
            derived_facts=(),
            effective_state_ref="",
            observed_at=NOW,
            historical_context=None,
            persona_id=None,
            relationship_ids=(),
            evidence_refs=(),
        )


def test_derived_fact_keys_and_values_must_be_non_empty() -> None:
    scope = make_scope()
    with pytest.raises(ValueError, match="non-empty"):
        Situation(
            situation_id="s-bad",
            scope=scope,
            origin_runtime_id="runtime-1",
            derived_facts=(("", "value"),),
            effective_state_ref="state-1",
            observed_at=NOW,
            historical_context=None,
            persona_id=None,
            relationship_ids=(),
            evidence_refs=(),
        )
