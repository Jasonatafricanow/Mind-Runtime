"""Decision-context compilation remains bounded, typed, and deterministic."""

from dataclasses import replace
from datetime import UTC, datetime
from typing import Any, cast

import pytest

from mind_runtime.contracts import (
    ActionDecision,
    ActionPermission,
    ActionPolicyResult,
    DeliveryStatus,
    HistoricalContextBundle,
    HistoricalContextItem,
    Intent,
    IntentStatus,
    PreviousExpression,
    ProjectedMindState,
    ReconsiderationPolicy,
    RuntimeState,
    Situation,
    SyncFields,
)
from mind_runtime.contracts.scope import Scope, ScopeDomain
from mind_runtime.expression.context import (
    AffectBand,
    AffectExpressionRule,
    DecisionContextCompiler,
    DecisionContextCompilerInput,
    DecisionContextConfig,
)
from mind_runtime.expression.history import FixedPreviousExpressionPort, NullPreviousExpressionPort
from tests.golden.fixtures.common import make_scope

NOW = datetime(2026, 8, 23, 12, 0, tzinfo=UTC)


def make_sync(scope: Scope, object_id: str) -> SyncFields:
    return SyncFields(scope, "runtime-1", object_id, 1, f"idem-{object_id}")


def make_situation(
    *,
    scope: Scope | None = None,
    origin_runtime_id: str = "runtime-1",
    derived_facts: tuple[tuple[str, str], ...] = (("time.daypart", "evening"),),
    historical_context: HistoricalContextBundle | None = None,
) -> Situation:
    active_scope = scope or make_scope()
    return Situation(
        situation_id="situation-1",
        scope=active_scope,
        origin_runtime_id=origin_runtime_id,
        derived_facts=derived_facts,
        effective_state_ref="state-user-1",
        observed_at=NOW,
        historical_context=historical_context,
        persona_id="persona-1",
        relationship_ids=("relationship-1",),
        evidence_refs=("evidence-1",),
    )


def make_effective_state(
    *, scope: Scope | None = None, origin_runtime_id: str = "runtime-1"
) -> RuntimeState:
    active_scope = scope or make_scope()
    return RuntimeState(
        state_id="state-user-1",
        scope=active_scope,
        dimension="user.context.phase",
        value="active",
        status="active",
        valid_from=NOW,
        valid_until=None,
        relevant_until=None,
        last_observed_at=NOW,
        evidence_refs=("evidence-1",),
        transition_refs=(),
        updated_at=NOW,
        origin_runtime_id=origin_runtime_id,
        version=1,
        sync=make_sync(active_scope, "state-user-1"),
    )


def make_projected_state(
    *,
    custom_value: float = 0.62,
    origin_runtime_id: str = "runtime-1",
) -> ProjectedMindState:
    agent_scope = Scope(domain=ScopeDomain.AGENT, agent_id="agent-1", persona_id="persona-1")
    state = RuntimeState(
        state_id="state-custom-trust-1",
        scope=agent_scope,
        dimension="agent.affect.custom_trust",
        value=custom_value,
        status="active",
        valid_from=NOW,
        valid_until=None,
        relevant_until=None,
        last_observed_at=NOW,
        evidence_refs=("assessment-1",),
        transition_refs=(),
        updated_at=NOW,
        origin_runtime_id=origin_runtime_id,
        version=1,
        sync=make_sync(agent_scope, "state-custom-trust-1"),
    )
    return ProjectedMindState(
        projection_id="projection-1",
        scope=agent_scope,
        origin_runtime_id=origin_runtime_id,
        projected_states=(state,),
        sync=make_sync(agent_scope, "projection-1"),
    )


def make_intent(*, scope: Scope | None = None, origin_runtime_id: str = "runtime-1") -> Intent:
    active_scope = scope or make_scope()
    return Intent(
        intent_id="intent-1",
        scope=active_scope,
        origin_runtime_id=origin_runtime_id,
        kind="respond",
        strength=0.8,
        earliest_at=None,
        due_at=None,
        expires_at=None,
        reconsideration_policy=ReconsiderationPolicy.ON_CONTEXT_CHANGE,
        cause_refs=("assessment-1",),
        state_refs=("projection-1",),
        status=IntentStatus.ALLOWED,
        sync=make_sync(active_scope, "intent-1"),
    )


def make_allowed_policy(
    *,
    scope: Scope | None = None,
    origin_runtime_id: str = "runtime-1",
    intent_id: str = "intent-1",
    action_type: str = "text_message",
    constraints: tuple[str, ...] = ("must_be_concise",),
) -> ActionPolicyResult:
    active_scope = scope or make_scope()
    return ActionPolicyResult(
        policy_id="policy-1",
        scope=active_scope,
        origin_runtime_id=origin_runtime_id,
        intent_id=intent_id,
        decision=ActionDecision.ALLOW,
        permission=ActionPermission(
            permission_id="permission-1",
            scope=active_scope,
            origin_runtime_id=origin_runtime_id,
            action_type=action_type,
            allowed=True,
            reasons=("allowed",),
            constraints=constraints,
        ),
        reason_codes=("allowed",),
    )


def make_previous_expression(
    *,
    scope: Scope | None = None,
    origin_runtime_id: str = "runtime-1",
    action_type: str = "text_message",
    delivery_status: DeliveryStatus = DeliveryStatus.SENT,
    text: str = "Previous sent expression.",
    receipt_ref: str = "receipt-1",
) -> PreviousExpression:
    return PreviousExpression(
        expression_id="previous-expression-1",
        scope=scope or make_scope(),
        origin_runtime_id=origin_runtime_id,
        action_type=action_type,
        text=text,
        receipt_ref=receipt_ref,
        delivery_status=delivery_status,
        sent_at=NOW,
    )


def make_compiler_input(
    *,
    scope: Scope | None = None,
    custom_value: float = 0.62,
    situation: Situation | None = None,
    effective_user_state: RuntimeState | None = None,
    projected_agent_state: ProjectedMindState | None = None,
    intent: Intent | None = None,
    policy_result: ActionPolicyResult | None = None,
    prior_expression: PreviousExpression | None = None,
    rewrite_reason_codes: tuple[str, ...] = (),
) -> DecisionContextCompilerInput:
    active_scope = scope or make_scope()
    return DecisionContextCompilerInput(
        interaction_id="interaction-1",
        scope=active_scope,
        origin_runtime_id="runtime-1",
        situation=situation or make_situation(scope=active_scope),
        effective_user_state=effective_user_state or make_effective_state(scope=active_scope),
        projected_agent_state=projected_agent_state
        or make_projected_state(custom_value=custom_value),
        assessment_trace_ref="assessment-1",
        intent=intent or make_intent(scope=active_scope),
        policy_result=policy_result or make_allowed_policy(scope=active_scope),
        persona_ref="persona-1",
        prior_expression=prior_expression,
        attempt=0,
        rewrite_reason_codes=rewrite_reason_codes,
    )


def make_compiler(**overrides: object) -> DecisionContextCompiler:
    config = DecisionContextConfig(
        allowed_situation_facts=("time.daypart",),
        affect_rules=(
            AffectExpressionRule(
                dimension="agent.affect.custom_trust",
                output_key="trust",
                bands=(AffectBand(0.3, "low"), AffectBand(0.7, "medium"), AffectBand(1.0, "high")),
                priority=20,
            ),
        ),
        persona_style_constraints=(("tone", "warm_concise"),),
        allowed_history_kinds=("episode",),
        max_history_items=2,
        max_prior_expression_chars=32,
        max_item_chars=160,
        max_items=16,
        max_render_chars=2048,
    )
    return DecisionContextCompiler(replace(config, **cast(Any, overrides)))


@pytest.mark.parametrize("value", [0, -1, True])
def test_config_rejects_non_positive_or_boolean_prior_expression_budget(value: int) -> None:
    with pytest.raises(ValueError, match="max_prior_expression_chars"):
        make_compiler(max_prior_expression_chars=value)


def test_config_accepts_positive_prior_expression_budget_below_eight() -> None:
    assert make_compiler(max_prior_expression_chars=1)


def test_config_rejects_invalid_bands_duplicate_keys_and_non_positive_budgets() -> None:
    with pytest.raises(ValueError, match="strictly increasing"):
        make_compiler(
            affect_rules=(
                AffectExpressionRule(
                    "agent.affect.custom_trust",
                    "trust",
                    (AffectBand(0.7, "medium"), AffectBand(0.7, "high")),
                    20,
                ),
            )
        )
    with pytest.raises(ValueError, match="unique"):
        make_compiler(allowed_situation_facts=("time.daypart", "time.daypart"))
    with pytest.raises(ValueError, match="unique"):
        make_compiler(persona_style_constraints=(("tone", "warm"), ("tone", "brief")))
    with pytest.raises(ValueError, match="max_items"):
        make_compiler(max_items=0)


def test_config_rejects_non_finite_band_and_duplicate_rule_dimension_or_output() -> None:
    with pytest.raises(ValueError, match="finite"):
        AffectBand(float("inf"), "unbounded")
    duplicate_dimension = AffectExpressionRule(
        "agent.affect.custom_trust", "other_trust", (AffectBand(1.0, "high"),), 1
    )
    with pytest.raises(ValueError, match="unique"):
        make_compiler(
            affect_rules=(
                AffectExpressionRule(
                    "agent.affect.custom_trust", "trust", (AffectBand(1.0, "high"),), 1
                ),
                duplicate_dimension,
            )
        )


def test_custom_affect_dimension_maps_to_qualitative_band_without_raw_number() -> None:
    context, trace = make_compiler().compile(make_compiler_input(custom_value=0.62))
    trust = next(item for item in context.expression_context if item.key == "trust")
    assert trust.value == "medium"
    assert "0.62" not in tuple(item.value for item in context.expression_context)
    assert trace.context_id == context.context_id


def test_compiler_uses_stable_section_order_ids_and_policy_constraints() -> None:
    first, first_trace = make_compiler().compile(make_compiler_input())
    second, second_trace = make_compiler().compile(make_compiler_input())
    assert first == second
    assert first_trace == second_trace
    assert first.context_id == "context-interaction-1-a0"
    assert [item.item_id for item in first.expression_context] == [
        "action-selected_action",
        "fact-time.daypart",
        "internal_state-trust",
        "policy_constraint-must_be_concise",
        "persona_style-tone",
    ]


def test_compiler_rejects_wrong_scope_origin_intent_or_policy_relation() -> None:
    wrong_scope = make_scope(user_id="other-user")
    with pytest.raises(ValueError, match="Situation scope"):
        make_compiler().compile(make_compiler_input(situation=make_situation(scope=wrong_scope)))
    with pytest.raises(ValueError, match="origin"):
        make_compiler().compile(
            make_compiler_input(intent=make_intent(origin_runtime_id="other-runtime"))
        )
    with pytest.raises(ValueError, match="intent"):
        make_compiler().compile(
            make_compiler_input(policy_result=make_allowed_policy(intent_id="other-intent"))
        )


def test_history_is_bounded_ordered_by_relevance_and_source_referenced() -> None:
    scope = make_scope()
    low = HistoricalContextItem(
        "history-low", scope, "external-low", "episode", "Low relevance.", ("src-low",), None, 0.2
    )
    high = HistoricalContextItem(
        "history-high",
        scope,
        "external-high",
        "episode",
        "High relevance.",
        ("src-high",),
        None,
        0.9,
    )
    bundle = HistoricalContextBundle(
        "history-1", scope, "runtime-1", (low, high), (), (), (), ("bundle-src",), "provider-1"
    )
    context, _trace = make_compiler(max_history_items=1).compile(
        make_compiler_input(situation=make_situation(scope=scope, historical_context=bundle))
    )
    history = [item for item in context.expression_context if item.kind.value == "history"]
    assert [(item.item_id, item.value, item.source_refs) for item in history] == [
        ("history-history-high", "High relevance.", ("src-high",)),
    ]
    assert bundle.episodes == (low, high)


def test_history_items_of_one_kind_with_shared_source_keep_distinct_identities() -> None:
    scope = make_scope()
    first = HistoricalContextItem(
        "history-first", scope, "external-1", "episode", "First.", ("shared-src",), None, 0.8
    )
    second = HistoricalContextItem(
        "history-second", scope, "external-2", "episode", "Second.", ("shared-src",), None, 0.7
    )
    bundle = HistoricalContextBundle(
        "history-1", scope, "runtime-1", (second, first), (), (), (), ("bundle-src",), "provider-1"
    )
    context, _trace = make_compiler(max_history_items=2).compile(
        make_compiler_input(situation=make_situation(scope=scope, historical_context=bundle))
    )
    history = [item.item_id for item in context.expression_context if item.kind.value == "history"]
    assert history == ["history-history-first", "history-history-second"]


def test_history_items_outside_allowed_kinds_are_skipped() -> None:
    scope = make_scope()
    skipped = HistoricalContextItem(
        "history-stable", scope, "external-1", "stable_fact", "Stable.", ("src-1",), None, 0.8
    )
    included = HistoricalContextItem(
        "history-episode", scope, "external-2", "episode", "Episode.", ("src-2",), None, 0.8
    )
    bundle = HistoricalContextBundle(
        "history-1", scope, "runtime-1", (included,), (skipped,), (), (), ("src",), "provider-1"
    )
    context, _trace = make_compiler().compile(
        make_compiler_input(situation=make_situation(scope=scope, historical_context=bundle))
    )
    history = [item.item_id for item in context.expression_context if item.kind.value == "history"]
    assert history == ["history-history-episode"]


def test_previous_expression_must_match_scope_origin_and_action() -> None:
    prior = make_previous_expression(action_type="photo_message")
    with pytest.raises(ValueError, match="action type"):
        make_compiler().compile(make_compiler_input(prior_expression=prior))
    with pytest.raises(ValueError, match="scope"):
        make_compiler().compile(
            make_compiler_input(
                prior_expression=make_previous_expression(scope=make_scope(user_id="other-user"))
            )
        )
    with pytest.raises(ValueError, match="origin"):
        make_compiler().compile(
            make_compiler_input(
                prior_expression=make_previous_expression(origin_runtime_id="other")
            )
        )


def test_previous_expression_contract_rejects_unsent_or_unknown() -> None:
    with pytest.raises(ValueError, match="SENT"):
        make_previous_expression(delivery_status=DeliveryStatus.UNSENT)
    with pytest.raises(ValueError, match="SENT"):
        make_previous_expression(delivery_status=DeliveryStatus.UNKNOWN)


def test_previous_expression_is_bounded_and_read_only_ports_are_exact() -> None:
    prior = make_previous_expression(text="x" * 40)
    context, _trace = make_compiler(max_prior_expression_chars=8).compile(
        make_compiler_input(prior_expression=prior)
    )
    previous = next(
        item for item in context.expression_context if item.kind.value == "prior_expression"
    )
    assert previous.value == "x" * 8
    port = FixedPreviousExpressionPort(prior)
    assert port.previous(scope=make_scope(), action_type="text_message") == prior
    assert port.previous(scope=make_scope(user_id="other-user"), action_type="text_message") is None
    assert port.previous(scope=make_scope(), action_type="photo_message") is None
    assert not hasattr(port, "save")


def test_null_previous_expression_port_has_no_write_surface() -> None:
    port = NullPreviousExpressionPort()
    assert port.previous(scope=make_scope(), action_type="text_message") is None
    assert not hasattr(port, "save")


def test_retry_preserves_non_guidance_and_replaces_guidance_deterministically() -> None:
    compiler = make_compiler()
    first, _trace = compiler.compile(make_compiler_input())
    retried, trace = compiler.retry(first, ("prefix_duplicate", "forbidden_opening"))
    assert retried.context_id == "context-interaction-1-a1"
    assert retried.attempt == 1
    assert (
        tuple(item for item in retried.expression_context if item.kind.value != "rewrite_guidance")
        == first.expression_context
    )
    assert [(item.key, item.value) for item in retried.expression_context[-2:]] == [
        ("forbidden_opening", "Use a different opening."),
        ("prefix_duplicate", "Start with a distinct first phrase."),
    ]
    assert trace.reason_codes == ("forbidden_opening", "prefix_duplicate")


def test_retry_rejects_unknown_reason_codes() -> None:
    context, _trace = make_compiler().compile(make_compiler_input())
    with pytest.raises(ValueError, match="unknown rewrite"):
        make_compiler().retry(context, ("unregistered",))


def test_compiler_input_rejects_negative_attempt_and_blank_persona_or_codes() -> None:
    with pytest.raises(ValueError, match="attempt"):
        replace(make_compiler_input(), attempt=-1)
    with pytest.raises(ValueError, match="persona_ref"):
        replace(make_compiler_input(), persona_ref="")
    with pytest.raises(ValueError, match="rewrite_reason_codes"):
        make_compiler_input(rewrite_reason_codes=("",))


def test_affect_band_and_rule_reject_invalid_bounds_entries_and_coverage() -> None:
    with pytest.raises(ValueError, match="finite"):
        AffectBand("0.5", "low")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="bands"):
        AffectExpressionRule("d", "k", (), 1)
    with pytest.raises(ValueError, match="AffectBand"):
        AffectExpressionRule("d", "k", (object(),), 1)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="final band"):
        AffectExpressionRule("d", "k", (AffectBand(0.5, "low"),), 1)
    with pytest.raises(ValueError, match="priority"):
        AffectExpressionRule("d", "k", (AffectBand(1.0, "high"),), -1)


def test_config_rejects_bad_rule_entries_and_style_pairs() -> None:
    with pytest.raises(ValueError, match="AffectExpressionRule"):
        make_compiler(affect_rules=(object(),))
    with pytest.raises(ValueError, match="key/value"):
        make_compiler(persona_style_constraints=(("tone",),))


def test_compiler_rejects_wrong_effective_intent_policy_or_projected_relations() -> None:
    wrong_scope = make_scope(user_id="other-user")
    with pytest.raises(ValueError, match="effective user state scope"):
        make_compiler().compile(
            make_compiler_input(effective_user_state=make_effective_state(scope=wrong_scope))
        )
    with pytest.raises(ValueError, match="Intent and Policy scope"):
        make_compiler().compile(make_compiler_input(intent=make_intent(scope=wrong_scope)))
    with pytest.raises(ValueError, match="projected agent state scope"):
        other_scope = Scope(domain=ScopeDomain.USER, user_id="other-user")
        other_state = replace(
            make_projected_state().projected_states[0],
            scope=other_scope,
            dimension="user.affect.stub",
            state_id="state-other",
            sync=make_sync(other_scope, "state-other"),
        )
        make_compiler().compile(
            make_compiler_input(
                projected_agent_state=replace(
                    make_projected_state(),
                    scope=other_scope,
                    projection_id="projection-other",
                    projected_states=(other_state,),
                    sync=make_sync(other_scope, "projection-other"),
                )
            )
        )
    with pytest.raises(ValueError, match="origin"):
        make_compiler().compile(
            make_compiler_input(situation=make_situation(origin_runtime_id="other-runtime"))
        )
    denied = ActionPolicyResult(
        policy_id="policy-denied",
        scope=make_scope(),
        origin_runtime_id="runtime-1",
        intent_id="intent-1",
        decision=ActionDecision.DENY,
        permission=ActionPermission(
            permission_id="permission-denied",
            scope=make_scope(),
            origin_runtime_id="runtime-1",
            action_type="text_message",
            allowed=False,
            reasons=("deny",),
            constraints=(),
        ),
        reason_codes=("deny",),
    )
    with pytest.raises(ValueError, match="ALLOW"):
        make_compiler().compile(make_compiler_input(policy_result=denied))


def test_compiler_rejects_duplicate_constraints_and_situation_facts() -> None:
    with pytest.raises(ValueError, match="constraints"):
        make_compiler().compile(
            make_compiler_input(policy_result=make_allowed_policy(constraints=("a", "a")))
        )
    with pytest.raises(ValueError, match="duplicate"):
        make_compiler().compile(
            make_compiler_input(
                situation=make_situation(
                    derived_facts=(("time.daypart", "evening"), ("time.daypart", "dawn"))
                )
            )
        )


def test_compiler_skips_dimension_without_rule_and_persona_without_style() -> None:
    compiler = make_compiler(
        affect_rules=(
            AffectExpressionRule(
                "agent.affect.unmapped", "unmapped", (AffectBand(1.0, "high"),), 20
            ),
        )
    )
    context, trace = compiler.compile(make_compiler_input())
    assert not any(item.key == "unmapped" for item in context.expression_context)
    assert not any(item.kind.value == "internal_state" for item in context.expression_context)
    assert not trace.omitted_item_refs
    no_persona, _trace = make_compiler().compile(replace(make_compiler_input(), persona_ref=None))
    assert not any(item.kind.value == "persona_style" for item in no_persona.expression_context)


def test_compiler_fails_closed_on_malformed_affect_values() -> None:
    with pytest.raises(ValueError, match="finite number"):
        make_compiler().compile(make_compiler_input(custom_value="not-a-number"))  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="outside configured bands"):
        make_compiler().compile(make_compiler_input(custom_value=1.5))


def test_compiler_rejects_bad_history_bundle_items_and_missing_refs() -> None:
    scope = make_scope()
    with pytest.raises(ValueError, match="HistoricalContextBundle"):
        make_compiler().compile(
            make_compiler_input(situation=make_situation(historical_context=object()))  # type: ignore[arg-type]
        )
    wrong_scope_bundle = HistoricalContextBundle(
        "history-wrong",
        make_scope(user_id="other-user"),
        "runtime-1",
        (),
        (),
        (),
        (),
        ("src",),
        "provider-1",
    )
    with pytest.raises(ValueError, match="scope and origin"):
        make_compiler().compile(
            make_compiler_input(
                situation=make_situation(scope=scope, historical_context=wrong_scope_bundle)
            )
        )
    wrong_item_scope = HistoricalContextItem(
        "history-item",
        make_scope(user_id="other-user"),
        "external-1",
        "episode",
        "Wrong scope.",
        ("src-1",),
        None,
        0.8,
    )
    bundle = HistoricalContextBundle(
        "history-1", scope, "runtime-1", (wrong_item_scope,), (), (), (), ("src",), "provider-1"
    )
    with pytest.raises(ValueError, match="item scope"):
        make_compiler().compile(
            make_compiler_input(situation=make_situation(scope=scope, historical_context=bundle))
        )
    no_refs_item = HistoricalContextItem(
        "history-norefs",
        scope,
        "external-2",
        "episode",
        "No refs.",
        (),
        None,
        0.8,
    )
    no_refs_bundle = HistoricalContextBundle(
        "history-2", scope, "runtime-1", (no_refs_item,), (), (), (), ("src",), "provider-1"
    )
    with pytest.raises(ValueError, match="source refs"):
        make_compiler().compile(
            make_compiler_input(
                situation=make_situation(scope=scope, historical_context=no_refs_bundle)
            )
        )


def test_compiler_rejects_bad_prior_and_duplicate_reason_codes() -> None:
    with pytest.raises(ValueError, match="PreviousExpression"):
        make_compiler().compile(make_compiler_input(prior_expression=object()))  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="unique"):
        make_compiler().compile(
            make_compiler_input(rewrite_reason_codes=("prefix_duplicate", "prefix_duplicate"))
        )


def test_compiler_budget_omits_optional_items_and_fails_on_essential_overflow() -> None:
    scope = make_scope()
    long_history = HistoricalContextItem(
        "history-long", scope, "external-1", "episode", "x" * 500, ("src-1",), None, 0.8
    )
    bundle = HistoricalContextBundle(
        "history-1", scope, "runtime-1", (long_history,), (), (), (), ("src",), "provider-1"
    )
    context, trace = make_compiler(max_item_chars=20).compile(
        make_compiler_input(situation=make_situation(scope=scope, historical_context=bundle))
    )
    assert "history-history-long" in trace.omitted_item_refs
    assert not any(item.key == "history-long" for item in context.expression_context)
    with pytest.raises(ValueError, match="max_item_chars"):
        make_compiler(max_item_chars=1).compile(make_compiler_input())


def test_compiler_render_budget_omits_and_essential_exceeding_budget_fails() -> None:
    compiler = make_compiler(
        allowed_situation_facts=(),
        affect_rules=(),
        persona_style_constraints=(("tone", "w" * 100),),
        max_render_chars=30,
    )
    context, trace = compiler.compile(make_compiler_input())
    assert "persona_style-tone" in trace.omitted_item_refs
    assert any(item.key == "selected_action" for item in context.expression_context)
    with pytest.raises(ValueError, match="configured budget"):
        make_compiler(max_render_chars=5).compile(make_compiler_input())


def test_retry_exceeding_budgets_fails_closed() -> None:
    first, _trace = make_compiler().compile(make_compiler_input())
    with pytest.raises(ValueError, match="max_items"):
        make_compiler(max_items=1).retry(first, ("prefix_duplicate",))
    with pytest.raises(ValueError, match="max_render_chars"):
        make_compiler(max_render_chars=16).retry(first, ("prefix_duplicate",))


def test_compiler_and_input_reject_wrong_types() -> None:
    with pytest.raises(ValueError, match="DecisionContextConfig"):
        DecisionContextCompiler(object())  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="compiler_input"):
        make_compiler().compile(object())  # type: ignore[arg-type]
    context, _trace = make_compiler().compile(make_compiler_input())
    with pytest.raises(ValueError, match="DecisionContext"):
        make_compiler().retry(object(), ("prefix_duplicate",))  # type: ignore[arg-type]


def test_fixed_previous_port_rejects_non_expression_at_construction() -> None:
    with pytest.raises(ValueError, match="PreviousExpression"):
        FixedPreviousExpressionPort(object())  # type: ignore[arg-type]
