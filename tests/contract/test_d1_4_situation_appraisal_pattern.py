"""D1.4 Situation / Appraisal / Pattern contract tests."""

from dataclasses import FrozenInstanceError, fields, replace
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


@pytest.mark.parametrize(
    ("overrides", "message"),
    (
        ({"ambiguity_score": 1.5}, "ambiguity_score"),
        ({"path": "nonsense"}, "path"),
        ({"confidence": 1.1}, "confidence"),
        ({"reason_codes": ("",)}, "non-empty"),
    ),
)
def test_route_rejects_invalid_fields(
    overrides: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        replace(make_route(), **overrides)

    assert make_route().ambiguity_score is None


@pytest.mark.parametrize(
    ("kwargs", "message"),
    (
        ({"ambiguous": True, "score": 0.6, "reasons": (" ",)}, "non-empty"),
        ({"ambiguous": "yes", "score": 0.6, "reasons": ()}, "ambiguous"),
        ({"ambiguous": True, "score": 2.0, "reasons": ("conflict",)}, "score"),
    ),
)
def test_ambiguity_assessment_rejects_invalid_fields(
    kwargs: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        AmbiguityAssessment(**kwargs)  # type: ignore[arg-type]

    valid = AmbiguityAssessment(ambiguous=True, score=0.6, reasons=("conflict",))
    assert valid.ambiguous is True


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


@pytest.mark.parametrize(
    ("overrides", "message"),
    (
        ({"signature": ""}, "non-empty"),
        ({"signature": "  "}, "non-empty"),
        ({"time_window": ""}, "non-empty"),
        ({"time_window": "  "}, "non-empty"),
        ({"filters": (("", "value"),)}, "non-empty"),
        ({"filters": (("key", ""),)}, "non-empty"),
    ),
)
def test_pattern_query_rejects_invalid_fields(
    overrides: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        replace(make_pattern_query(), **overrides)


@pytest.mark.parametrize(
    ("overrides", "message"),
    (
        ({"matched_refs": ("",)}, "non-empty"),
        ({"first_seen_at": datetime(2026, 8, 20, 11, 0)}, "aware UTC"),
        ({"match_count": -1}, "match_count"),
        ({"confidence": 1.5}, "confidence"),
    ),
)
def test_pattern_summary_rejects_invalid_fields(
    overrides: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        replace(make_pattern_summary(), **overrides)


def test_pattern_summary_accepts_null_timestamps() -> None:
    summary = replace(
        make_pattern_summary(),
        match_count=0,
        first_seen_at=None,
        last_seen_at=None,
        matched_refs=(),
        confidence=0.0,
    )
    assert summary.first_seen_at is None
    assert summary.last_seen_at is None


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


@pytest.mark.parametrize(
    ("overrides", "message"),
    (
        ({"situation_hint": "   "}, "non-empty"),
        ({"situation_hint": None, "query_text": ""}, "non-empty"),
        ({"budget": -1}, "budget"),
    ),
)
def test_history_query_rejects_invalid_fields(
    overrides: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        replace(make_history_query(), **overrides)


@pytest.mark.parametrize(
    ("overrides", "message"),
    (
        ({"confidence": 1.5}, "confidence"),
        ({"confidence": None, "relevance_hint": -0.5}, "relevance_hint"),
    ),
)
def test_history_item_rejects_out_of_range_scores(
    overrides: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        replace(make_history_item(), **overrides)


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


@pytest.mark.parametrize(
    ("overrides", "message"),
    (
        ({"observed_at": datetime(2026, 8, 20, 11, 0)}, "aware UTC"),
        ({"effective_state_ref": ""}, "non-empty"),
        ({"derived_facts": (("", "value"),)}, "non-empty"),
    ),
)
def test_situation_rejects_invalid_fields(
    overrides: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        replace(make_situation(), **overrides)


def test_situation_is_immutable() -> None:
    situation = make_situation()
    with pytest.raises(FrozenInstanceError):
        situation.derived_facts = ()  # type: ignore[misc]

