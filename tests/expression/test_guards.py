"""Deterministic expression guard chain stays registered, ordered, and fail-closed."""

from dataclasses import replace
from typing import Any, cast

import pytest

from mind_runtime.contracts import (
    DecisionContext,
    ExpressionContextItem,
    ExpressionContextKind,
    ExpressionDisposition,
    ExpressionGuardInput,
)
from mind_runtime.expression.guards import (
    DeterministicExpressionGuardChain,
    ExpressionGuardConfig,
    TemporalConflictRule,
    normalize_for_prefix,
)
from tests.golden.fixtures.common import make_scope


def make_item(
    kind: ExpressionContextKind,
    key: str,
    value: str,
    priority: int,
    *,
    item_id: str | None = None,
    source_refs: tuple[str, ...] = ("source-1",),
) -> ExpressionContextItem:
    return ExpressionContextItem(
        item_id=item_id or f"{kind.value}-{key}",
        kind=kind,
        key=key,
        value=value,
        source_refs=source_refs,
        priority=priority,
    )


def make_context(
    *,
    prior: str | None = None,
    daypart: str | None = None,
    extra_items: tuple[ExpressionContextItem, ...] = (),
    context_id: str = "context-1",
) -> DecisionContext:
    items: list[ExpressionContextItem] = [
        make_item(ExpressionContextKind.ACTION, "selected_action", "text_message", priority=0)
    ]
    if daypart is not None:
        items.append(make_item(ExpressionContextKind.FACT, "time.daypart", daypart, priority=10))
    if prior is not None:
        items.append(
            make_item(
                ExpressionContextKind.PRIOR_EXPRESSION,
                "previous_expression",
                prior,
                priority=30,
                source_refs=("previous-expression-1", "receipt-1"),
            )
        )
    items.extend(extra_items)
    return DecisionContext(
        context_id=context_id,
        scope=make_scope(),
        origin_runtime_id="runtime-1",
        interaction_ref="interaction-1",
        situation_ref="situation-1",
        effective_user_state_ref="state-user-1",
        projected_agent_state_ref="projection-1",
        relationship_state_refs=(),
        historical_context_ref=None,
        assessment_trace_ref="assessment-1",
        intent_ref="intent-1",
        policy_result_ref="policy-1",
        relevant_persona_ref="persona-1",
        goals_refs=(),
        selected_intent_kind="respond",
        selected_action_type="text_message",
        attempt=0,
        expression_context=tuple(items),
    )


def make_guard_input(
    *,
    prior: str | None = None,
    daypart: str | None = "evening",
    expression: str = "刚忙完，想起你了",
) -> ExpressionGuardInput:
    context = make_context(prior=prior, daypart=daypart)
    return ExpressionGuardInput(
        draft_id=f"draft-{context.context_id}",
        decision_context=context,
        expression=expression,
        attempt=0,
    )


def make_guard(**overrides: object) -> DeterministicExpressionGuardChain:
    config = ExpressionGuardConfig(
        prefix_length=8,
        transport_markers=("【助手】",),
        banned_openings=("刚忙完", "刚闲下来", "刚闲了", "忙完了没", "在干嘛"),
        temporal_rules=(
            TemporalConflictRule(
                rule_id="sunset_in_dawn",
                incompatible_dayparts=("dawn",),
                phrases=("晚霞", "夕阳", "落日"),
                temporal_fact_key="time.daypart",
            ),
        ),
    )
    return DeterministicExpressionGuardChain(replace(config, **cast(Any, overrides)))


def test_prefix_guard_uses_eight_unicode_code_points() -> None:
    guard = make_guard(prefix_length=8)
    result = guard.guard(
        make_guard_input(prior="今天真的很想和你聊聊", expression="今天真的很想和你换话题")
    )
    assert result.disposition is ExpressionDisposition.REWRITE
    assert result.violations == ("prefix_duplicate",)


def test_prefix_guard_accepts_different_prefix_sharing_fewer_code_points() -> None:
    guard = make_guard(prefix_length=8)
    result = guard.guard(
        make_guard_input(prior="今天真的很想和你聊聊", expression="今天真的很想换个话题")
    )
    assert result.disposition is ExpressionDisposition.ACCEPT


def test_prefix_guard_is_inactive_without_prior_expression() -> None:
    result = make_guard().guard(make_guard_input(prior=None, expression="今天真的很想和你聊聊"))
    assert result.disposition is ExpressionDisposition.ACCEPT


def test_banned_opening_is_inactive_without_prior_sent_expression() -> None:
    result = make_guard().guard(make_guard_input(prior=None, expression="刚忙完，想起你了"))
    assert result.disposition is ExpressionDisposition.ACCEPT


def test_banned_opening_is_active_with_prior_sent_expression() -> None:
    result = make_guard().guard(make_guard_input(prior="最近还好吗", expression="刚忙完，想起你了"))
    assert result.disposition is ExpressionDisposition.REWRITE
    assert result.violations == ("forbidden_opening",)


def test_blank_output_is_rejected_structurally() -> None:
    result = make_guard().guard(make_guard_input(prior=None, expression="   "))
    assert result.disposition is ExpressionDisposition.REJECT
    assert result.violations == ("invalid_expression",)


def test_normalization_strips_only_one_leading_marker_and_unicode_whitespace() -> None:
    normalized = normalize_for_prefix("  \u3000【助手】\t今天 很想你  ", ("【助手】",))
    assert normalized == "今天 很想你"
    kept = normalize_for_prefix("今天【助手】保留", ("【助手】",))
    assert kept == "今天【助手】保留"


def test_temporal_guard_rewrites_only_registered_conflict() -> None:
    result = make_guard().guard(make_guard_input(daypart="dawn", expression="晚霞看起来很好看"))
    assert result.disposition is ExpressionDisposition.REWRITE
    assert result.violations == ("temporal_conflict",)


def test_temporal_guard_does_not_claim_unknown_semantics() -> None:
    result = make_guard().guard(make_guard_input(daypart="dawn", expression="天色很特别"))
    assert result.disposition is ExpressionDisposition.ACCEPT


def test_temporal_guard_accepts_registered_phrase_in_compatible_daypart() -> None:
    result = make_guard().guard(make_guard_input(daypart="evening", expression="晚霞看起来很好看"))
    assert result.disposition is ExpressionDisposition.ACCEPT


def test_temporal_guard_missing_fact_fails_closed_when_enabled() -> None:
    result = make_guard().guard(make_guard_input(daypart=None, expression="晚霞看起来很好看"))
    assert result.disposition is ExpressionDisposition.REJECT
    assert result.violations == ("missing_temporal_fact",)


def test_temporal_guard_duplicate_fact_fails_closed() -> None:
    duplicate = make_item(
        ExpressionContextKind.FACT, "time.daypart", "dawn", priority=10, source_refs=("source-2",)
    )
    context = make_context(daypart="dawn", extra_items=(duplicate,))
    guard_input = ExpressionGuardInput(
        draft_id="draft-1", decision_context=context, expression="晚霞看起来很好看", attempt=0
    )
    result = make_guard().guard(guard_input)
    assert result.disposition is ExpressionDisposition.REJECT
    assert result.violations == ("malformed_temporal_fact",)


def test_structural_reject_precedes_content_rewrite() -> None:
    result = make_guard().guard(make_guard_input(daypart=None, expression="刚忙完，晚霞真美"))
    assert result.disposition is ExpressionDisposition.REJECT
    assert result.violations == ("missing_temporal_fact",)


def test_multiple_content_violations_accumulate_in_stable_order() -> None:
    result = make_guard().guard(
        make_guard_input(
            prior="刚忙完，今天真的很想和你聊聊",
            daypart="dawn",
            expression="刚忙完，今天真的很想和你换话题，晚霞真美",
        )
    )
    assert result.disposition is ExpressionDisposition.REWRITE
    assert result.violations == ("forbidden_opening", "prefix_duplicate", "temporal_conflict")


def test_config_rejects_invalid_markers_banned_openings_and_rules() -> None:
    with pytest.raises(ValueError, match="unique"):
        make_guard(transport_markers=("【助手】", "【助手】"))
    with pytest.raises(ValueError, match="prefix_length"):
        make_guard(prefix_length=0)
    with pytest.raises(ValueError, match="unique"):
        make_guard(banned_openings=("刚忙完", "刚忙完"))
    with pytest.raises(ValueError, match="phrases"):
        TemporalConflictRule(
            rule_id="empty",
            incompatible_dayparts=("dawn",),
            phrases=(),
            temporal_fact_key="time.daypart",
        )


def test_guard_rejects_non_guard_input() -> None:
    with pytest.raises(ValueError, match="guard_input"):
        make_guard().guard(object())  # type: ignore[arg-type]


def test_config_rejects_empty_dayparts_bad_rules_and_divergent_fact_keys() -> None:
    with pytest.raises(ValueError, match="incompatible_dayparts"):
        TemporalConflictRule(
            rule_id="no-dayparts",
            incompatible_dayparts=(),
            phrases=("晚霞",),
            temporal_fact_key="time.daypart",
        )
    with pytest.raises(ValueError, match="TemporalConflictRule"):
        make_guard(temporal_rules=(object(),))
    duplicate_rule = TemporalConflictRule(
        rule_id="sunset_in_dawn",
        incompatible_dayparts=("dawn",),
        phrases=("晚霞",),
        temporal_fact_key="time.daypart",
    )
    with pytest.raises(ValueError, match="rule ids"):
        make_guard(temporal_rules=(duplicate_rule, duplicate_rule))
    other_key_rule = TemporalConflictRule(
        rule_id="other_rule",
        incompatible_dayparts=("dawn",),
        phrases=("晚霞",),
        temporal_fact_key="time.other",
    )
    with pytest.raises(ValueError, match="one temporal fact key"):
        make_guard(temporal_rules=(duplicate_rule, other_key_rule))


def test_config_accepts_multiple_rules_sharing_one_fact_key() -> None:
    first = TemporalConflictRule(
        rule_id="sunrise_in_night",
        incompatible_dayparts=("night",),
        phrases=("朝霞",),
        temporal_fact_key="time.daypart",
    )
    second = TemporalConflictRule(
        rule_id="rain_in_dawn",
        incompatible_dayparts=("dawn",),
        phrases=("雷雨",),
        temporal_fact_key="time.daypart",
    )
    guard = make_guard(temporal_rules=(first, second))
    assert (
        guard.guard(make_guard_input(daypart="dawn", expression="雷雨交加")).disposition
        is ExpressionDisposition.REWRITE
    )


def test_guard_chain_rejects_non_config() -> None:
    with pytest.raises(ValueError, match="ExpressionGuardConfig"):
        DeterministicExpressionGuardChain(object())  # type: ignore[arg-type]
