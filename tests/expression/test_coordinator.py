"""Bounded rewrite coordination stays capped, traced, and fail-closed."""

from typing import Any, cast

import pytest

from mind_runtime.contracts import (
    DecisionContext,
    ExpressionContextItem,
    ExpressionContextKind,
    ExpressionDisposition,
    ExpressionGuardInput,
    ExpressionGuardResult,
    ProviderExpressionContext,
)
from mind_runtime.expression.context import DecisionContextCompiler, DecisionContextConfig
from mind_runtime.expression.coordinator import (
    DeterministicExpressionCoordinator,
    ExpressionCoordinatorConfig,
)
from mind_runtime.expression.guards import DeterministicExpressionGuardChain, ExpressionGuardConfig
from mind_runtime.expression.renderer import DeterministicContextRenderer
from mind_runtime.pipeline.fake_agent import FakeAgent
from mind_runtime.pipeline.ports import AgentFailure
from tests.golden.fixtures.common import make_scope

PRIOR = "今天真的很想和你聊聊"


def make_item(
    kind: ExpressionContextKind,
    key: str,
    value: str,
    priority: int,
    *,
    source_refs: tuple[str, ...] = ("source-1",),
) -> ExpressionContextItem:
    return ExpressionContextItem(
        item_id=f"{kind.value}-{key}",
        kind=kind,
        key=key,
        value=value,
        source_refs=source_refs,
        priority=priority,
    )


def make_context(*, prior: str | None = PRIOR) -> DecisionContext:
    items: list[ExpressionContextItem] = [
        make_item(ExpressionContextKind.ACTION, "selected_action", "text_message", priority=0)
    ]
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
    return DecisionContext(
        context_id="context-interaction-1-a0",
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


def make_config() -> DecisionContextConfig:
    return DecisionContextConfig(
        allowed_situation_facts=(),
        affect_rules=(),
        persona_style_constraints=(),
        allowed_history_kinds=(),
        max_history_items=1,
        max_prior_expression_chars=8,
        max_item_chars=160,
        max_items=16,
        max_render_chars=2048,
    )


def make_coordinator(
    *,
    agent: object,
    guard: object | None = None,
    max_rewrites: int = 2,
) -> DeterministicExpressionCoordinator:
    config = make_config()
    return DeterministicExpressionCoordinator(
        compiler=DecisionContextCompiler(config),
        renderer=DeterministicContextRenderer(config),
        agent=cast(Any, agent),
        guard=cast(Any, guard) if guard is not None else make_guard(),
        config=ExpressionCoordinatorConfig(max_rewrites=max_rewrites),
    )


def make_guard() -> DeterministicExpressionGuardChain:
    return DeterministicExpressionGuardChain(
        ExpressionGuardConfig(
            prefix_length=8,
            transport_markers=("【助手】",),
            banned_openings=("刚忙完", "刚闲下来", "刚闲了", "忙完了没", "在干嘛"),
            temporal_rules=(),
        )
    )


class ExplodingGuard:
    def guard(self, guard_input: ExpressionGuardInput) -> ExpressionGuardResult:
        raise RuntimeError("guard exploded")


class WrongScopeGuard:
    def guard(self, guard_input: ExpressionGuardInput) -> ExpressionGuardResult:
        return ExpressionGuardResult(
            guard_id="wrong-scope-guard",
            scope=make_scope(user_id="other-user"),
            origin_runtime_id=guard_input.decision_context.origin_runtime_id,
            expression=guard_input.expression,
            disposition=ExpressionDisposition.ACCEPT,
            violations=(),
        )


class WrongOriginGuard:
    def guard(self, guard_input: ExpressionGuardInput) -> ExpressionGuardResult:
        return ExpressionGuardResult(
            guard_id="wrong-origin-guard",
            scope=guard_input.decision_context.scope,
            origin_runtime_id="other-runtime",
            expression=guard_input.expression,
            disposition=ExpressionDisposition.ACCEPT,
            violations=(),
        )


class AlteredExpressionGuard:
    def guard(self, guard_input: ExpressionGuardInput) -> ExpressionGuardResult:
        return ExpressionGuardResult(
            guard_id="altered-expression-guard",
            scope=guard_input.decision_context.scope,
            origin_runtime_id=guard_input.decision_context.origin_runtime_id,
            expression="different expression",
            disposition=ExpressionDisposition.ACCEPT,
            violations=(),
        )


class NonStringAgent:
    def respond(self, provider_context: ProviderExpressionContext) -> str:
        return 42  # type: ignore[return-value]


def test_clean_first_draft_is_accepted() -> None:
    outcome = make_coordinator(agent=FakeAgent(["你好呀"])).express(make_context(prior=None))
    assert outcome.final_disposition is ExpressionDisposition.ACCEPT
    assert outcome.accepted_expression == "你好呀"
    assert tuple(attempt.attempt for attempt in outcome.attempts) == (0,)
    assert outcome.attempts[0].reason_codes == ()


def test_one_rewrite_preserves_authority_and_accepts_second_draft() -> None:
    agent = FakeAgent(["今天真的很想和你重复", "换个开头，想听听你的近况"])
    outcome = make_coordinator(agent=agent, max_rewrites=2).express(make_context())
    assert outcome.final_disposition is ExpressionDisposition.ACCEPT
    assert outcome.accepted_expression == "换个开头，想听听你的近况"
    assert tuple(attempt.attempt for attempt in outcome.attempts) == (0, 1)
    assert agent.call_count == 2
    assert agent.calls[0].context_id != agent.calls[1].context_id
    assert agent.calls[1].context_id == "context-interaction-1-a1"


def test_zero_rewrite_cap_rejects_first_duplicate_draft() -> None:
    agent = FakeAgent(["今天真的很想和你重复"])
    outcome = make_coordinator(agent=agent, max_rewrites=0).express(make_context())
    assert outcome.final_disposition is ExpressionDisposition.REJECT
    assert outcome.accepted_expression is None
    assert outcome.attempts[-1].reason_codes == ("prefix_duplicate", "retry_exhausted")
    assert agent.call_count == 1


def test_retry_exhaustion_is_reject_and_never_returns_text() -> None:
    agent = FakeAgent(["今天真的很想和你一", "今天真的很想和你二", "今天真的很想和你三"])
    outcome = make_coordinator(agent=agent, max_rewrites=2).express(make_context())
    assert outcome.final_disposition is ExpressionDisposition.REJECT
    assert outcome.accepted_expression is None
    assert outcome.attempts[-1].reason_codes == ("prefix_duplicate", "retry_exhausted")
    assert agent.call_count == 3


def test_structural_reject_does_not_retry() -> None:
    agent = FakeAgent(["   "])
    outcome = make_coordinator(agent=agent, max_rewrites=2).express(make_context())
    assert outcome.final_disposition is ExpressionDisposition.REJECT
    assert outcome.accepted_expression is None
    assert outcome.attempts[-1].reason_codes == ("invalid_expression",)
    assert agent.call_count == 1


def test_provider_failure_propagates_without_fabricated_attempt_result() -> None:
    agent = FakeAgent([AgentFailure("provider down")])
    with pytest.raises(AgentFailure, match="provider down"):
        make_coordinator(agent=agent).express(make_context())


def test_guard_exception_fails_closed_without_sending() -> None:
    outcome = make_coordinator(agent=FakeAgent(["你好呀"]), guard=ExplodingGuard()).express(
        make_context()
    )
    assert outcome.final_disposition is ExpressionDisposition.REJECT
    assert outcome.accepted_expression is None
    assert outcome.attempts[-1].reason_codes == ("guard_failure",)


def test_wrong_scope_guard_output_fails_closed() -> None:
    outcome = make_coordinator(agent=FakeAgent(["你好呀"]), guard=WrongScopeGuard()).express(
        make_context()
    )
    assert outcome.final_disposition is ExpressionDisposition.REJECT
    assert outcome.accepted_expression is None
    assert outcome.attempts[-1].reason_codes == ("scope_mismatch",)


def test_wrong_origin_guard_output_fails_closed() -> None:
    outcome = make_coordinator(agent=FakeAgent(["你好呀"]), guard=WrongOriginGuard()).express(
        make_context()
    )
    assert outcome.final_disposition is ExpressionDisposition.REJECT
    assert outcome.accepted_expression is None
    assert outcome.attempts[-1].reason_codes == ("origin_mismatch",)


def test_altered_expression_guard_output_fails_closed() -> None:
    outcome = make_coordinator(agent=FakeAgent(["你好呀"]), guard=AlteredExpressionGuard()).express(
        make_context()
    )
    assert outcome.final_disposition is ExpressionDisposition.REJECT
    assert outcome.accepted_expression is None
    assert outcome.attempts[-1].reason_codes == ("invalid_expression",)


def test_one_rewrite_cap_exhausts_on_second_duplicate_draft() -> None:
    agent = FakeAgent(["今天真的很想和你重复", "今天真的很想和你再聊"])
    outcome = make_coordinator(agent=agent, max_rewrites=1).express(make_context())
    assert outcome.final_disposition is ExpressionDisposition.REJECT
    assert outcome.accepted_expression is None
    assert outcome.attempts[-1].reason_codes == ("prefix_duplicate", "retry_exhausted")
    assert agent.call_count == 2


def test_non_string_provider_output_is_rejected_before_guard_input() -> None:
    outcome = make_coordinator(agent=NonStringAgent()).express(make_context())
    assert outcome.final_disposition is ExpressionDisposition.REJECT
    assert outcome.accepted_expression is None
    assert outcome.attempts[-1].reason_codes == ("invalid_expression",)


def test_retry_guidance_reaches_provider_and_authority_refs_survive() -> None:
    agent = FakeAgent(["今天真的很想和你重复", "换个开头，想听听你的近况"])
    make_coordinator(agent=agent, max_rewrites=2).express(make_context())
    assert "Start with a distinct first phrase." in agent.calls[1].text
    assert agent.calls[0].scope == agent.calls[1].scope
    assert agent.calls[0].origin_runtime_id == agent.calls[1].origin_runtime_id


def test_attempt_trace_ids_are_distinct_per_attempt() -> None:
    agent = FakeAgent(["今天真的很想和你重复", "换个开头，想听听你的近况"])
    outcome = make_coordinator(agent=agent, max_rewrites=2).express(make_context())
    first, second = outcome.attempts
    assert first.attempt_id == "attempt-context-interaction-1-a0"
    assert first.context_id == "context-interaction-1-a0"
    assert first.render_id == "render-context-interaction-1-a0"
    assert first.draft_id == "draft-context-interaction-1-a0"
    assert second.context_id == "context-interaction-1-a1"
    assert len({first.attempt_id, second.attempt_id}) == 2
    assert len({first.context_id, second.context_id}) == 2
    assert len({first.render_id, second.render_id}) == 2
    assert len({first.draft_id, second.draft_id}) == 2


def test_config_rejects_boolean_or_negative_rewrite_counts() -> None:
    with pytest.raises(ValueError, match="max_rewrites"):
        ExpressionCoordinatorConfig(max_rewrites=True)
    with pytest.raises(ValueError, match="max_rewrites"):
        ExpressionCoordinatorConfig(max_rewrites=-1)


def test_express_rejects_non_context() -> None:
    with pytest.raises(ValueError, match="DecisionContext"):
        make_coordinator(agent=FakeAgent(["你好呀"])).express(object())  # type: ignore[arg-type]


def test_coordinator_rejects_bad_compiler_or_config() -> None:
    config = make_config()
    with pytest.raises(ValueError, match="compiler"):
        DeterministicExpressionCoordinator(
            compiler=object(),  # type: ignore[arg-type]
            renderer=DeterministicContextRenderer(config),
            agent=FakeAgent(["你好呀"]),
            guard=make_guard(),
            config=ExpressionCoordinatorConfig(max_rewrites=2),
        )
    with pytest.raises(ValueError, match="config"):
        DeterministicExpressionCoordinator(
            compiler=DecisionContextCompiler(config),
            renderer=DeterministicContextRenderer(config),
            agent=FakeAgent(["你好呀"]),
            guard=make_guard(),
            config=object(),  # type: ignore[arg-type]
        )
