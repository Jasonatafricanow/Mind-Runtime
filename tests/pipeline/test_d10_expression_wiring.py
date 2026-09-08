"""Canonical D10 expression wiring: one path, receipts, Policy/Intent/commit boundaries."""

from datetime import UTC, datetime
from typing import Any, cast

import pytest

from mind_runtime.contracts import (
    ActionDecision,
    ActionPermission,
    ActionPolicyInput,
    ActionPolicyResult,
    DeliveryStatus,
    ExpressionDisposition,
    IntentStatus,
    Interaction,
    InteractionStatus,
    PreviousExpression,
    Scope,
)
from mind_runtime.expression import (
    DecisionContextCompiler,
    DecisionContextConfig,
    DeterministicContextRenderer,
    DeterministicExpressionCoordinator,
    DeterministicExpressionGuardChain,
    ExpressionCoordinatorConfig,
    ExpressionGuardConfig,
    FixedPreviousExpressionPort,
)
from mind_runtime.expression.history import NullPreviousExpressionPort
from mind_runtime.intents.lifecycle import IntentLifecycleService
from mind_runtime.intents.persistence import InMemoryIntentBackend
from mind_runtime.pipeline.fake_agent import FakeAgent
from mind_runtime.pipeline.orchestrator import TurnOrchestrator
from mind_runtime.pipeline.ports import AgentFailure
from mind_runtime.pipeline.trace import TraceRecorder
from tests.golden.fixtures.common import make_evidence, make_scope
from tests.support.fake_clock import FakeClock

NOW = datetime(2026, 8, 23, 12, 0, tzinfo=UTC)
PRIOR = "今天真的很想和你聊聊"


def make_interaction() -> Interaction:
    return Interaction(
        interaction_id="interaction-1",
        scope=make_scope(),
        channel="chat",
        session_id="session-1",
        turn_id="turn-1",
        started_at=NOW,
        committed_at=None,
        status=InteractionStatus.OPEN,
    )


def make_compiler_config() -> DecisionContextConfig:
    return DecisionContextConfig(
        allowed_situation_facts=(),
        affect_rules=(),
        persona_style_constraints=(),
        allowed_history_kinds=(),
        max_history_items=1,
        max_prior_expression_chars=32,
        max_item_chars=160,
        max_items=16,
        max_render_chars=2048,
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


def make_prior(
    *,
    scope: Scope | None = None,
    action_type: str = "respond",
    text: str = PRIOR,
) -> PreviousExpression:
    return PreviousExpression(
        expression_id="previous-expression-1",
        scope=scope or make_scope(),
        origin_runtime_id="runtime-1",
        action_type=action_type,
        text=text,
        receipt_ref="receipt-1",
        delivery_status=DeliveryStatus.SENT,
        sent_at=NOW,
    )


def make_d10_orchestrator(
    *,
    prior: str | None = PRIOR,
    script: tuple[str | AgentFailure, ...] = ("你好呀",),
    max_rewrites: int = 2,
    backend: InMemoryIntentBackend | None = None,
) -> tuple[TurnOrchestrator, FakeAgent]:
    config = make_compiler_config()
    compiler = DecisionContextCompiler(config)
    agent = FakeAgent(list(script))
    coordinator = DeterministicExpressionCoordinator(
        compiler=compiler,
        renderer=DeterministicContextRenderer(config),
        agent=agent,
        guard=make_guard(),
        config=ExpressionCoordinatorConfig(max_rewrites=max_rewrites),
    )
    orchestrator = TurnOrchestrator(
        clock=FakeClock(NOW),
        trace=TraceRecorder(),
        agent=agent,
        previous_expression=(
            FixedPreviousExpressionPort(make_prior(text=prior))
            if prior is not None
            else NullPreviousExpressionPort()
        ),
        decision_context_compiler=compiler,
        expression_coordinator=coordinator,
        intent_lifecycle=(
            IntentLifecycleService(backend)
            if backend is not None
            else IntentLifecycleService(InMemoryIntentBackend())
        ),
    )
    return orchestrator, agent


def run_turn(orchestrator: TurnOrchestrator) -> None:
    orchestrator.begin_turn(make_interaction())
    orchestrator.ingest(make_evidence(text="hello"))
    orchestrator.run()


def test_real_d10_rewrites_duplicate_but_policy_stays_allowed() -> None:
    orchestrator, agent = make_d10_orchestrator(
        prior=PRIOR,
        script=("今天真的很想和你重复", "换个开头，最近还好吗？"),
    )
    run_turn(orchestrator)
    assert orchestrator.policy_result is not None
    assert orchestrator.policy_result.decision is ActionDecision.ALLOW
    assert orchestrator.expression_outcome is not None
    assert orchestrator.expression_outcome.final_disposition is ExpressionDisposition.ACCEPT
    assert agent.call_count == 2
    assert orchestrator.action_receipt is not None
    assert orchestrator.action_receipt.delivery_status is DeliveryStatus.SENT
    assert orchestrator.action_receipt.outcome == "换个开头，最近还好吗？"


def test_retry_exhaustion_is_unsent_but_affect_can_commit_explicitly() -> None:
    orchestrator, _agent = make_d10_orchestrator(
        prior=PRIOR,
        script=("今天真的很想和你一", "今天真的很想和你二", "今天真的很想和你三"),
    )
    run_turn(orchestrator)
    assert orchestrator.action_receipt is not None
    assert orchestrator.action_receipt.delivery_status is DeliveryStatus.UNSENT
    assert orchestrator.action_receipt.outcome is None
    assert orchestrator.policy_result is not None
    assert orchestrator.policy_result.decision is ActionDecision.ALLOW
    before = orchestrator.canonical
    orchestrator.commit_turn()
    assert orchestrator.canonical != before


def test_no_allowed_candidate_calls_no_d10_component() -> None:
    class DenyPolicy:
        def policy(self, policy_input: ActionPolicyInput) -> ActionPolicyResult:
            return ActionPolicyResult(
                policy_id="policy-deny",
                scope=policy_input.scope,
                origin_runtime_id=policy_input.intent.origin_runtime_id,
                intent_id=policy_input.intent.intent_id,
                decision=ActionDecision.DENY,
                permission=ActionPermission(
                    permission_id="permission-deny",
                    scope=policy_input.scope,
                    origin_runtime_id=policy_input.intent.origin_runtime_id,
                    action_type=policy_input.intent.kind,
                    allowed=False,
                    reasons=("deny",),
                    constraints=(),
                ),
                reason_codes=("deny",),
            )

    class CountingPreviousPort:
        def __init__(self) -> None:
            self.previous_calls = 0

        def previous(self, *, scope: Scope, action_type: str) -> PreviousExpression | None:
            self.previous_calls += 1
            return None

    class CountingCompiler:
        def __init__(self) -> None:
            self.compiler_calls = 0

        def compile(self, compiler_input: object) -> object:
            self.compiler_calls += 1
            raise AssertionError("compiler must not run without an allowed candidate")

        def retry(self, context: object, reason_codes: tuple[str, ...]) -> object:
            self.compiler_calls += 1
            raise AssertionError("compiler retry must not run without an allowed candidate")

    class CountingCoordinator:
        def __init__(self) -> None:
            self.coordinator_calls = 0

        def express(self, context: object) -> object:
            self.coordinator_calls += 1
            raise AssertionError("coordinator must not run without an allowed candidate")

    probes = CountingPreviousPort()
    compiler_probe = CountingCompiler()
    coordinator_probe = CountingCoordinator()
    orchestrator = TurnOrchestrator(
        clock=FakeClock(NOW),
        trace=TraceRecorder(),
        action_policy=DenyPolicy(),
        previous_expression=probes,
        decision_context_compiler=cast(Any, compiler_probe),
        expression_coordinator=cast(Any, coordinator_probe),
    )
    run_turn(orchestrator)
    assert probes.previous_calls == 0
    assert compiler_probe.compiler_calls == 0
    assert coordinator_probe.coordinator_calls == 0
    assert orchestrator.decision_context is None
    assert orchestrator.action_receipt is None
    assert orchestrator.expression_outcome is None


def test_previous_expression_query_uses_exact_scope_and_action_type() -> None:
    class RecordingPreviousPort:
        def __init__(self) -> None:
            self.calls: list[tuple[Scope, str]] = []

        def previous(self, *, scope: Scope, action_type: str) -> PreviousExpression | None:
            self.calls.append((scope, action_type))
            return None

    port = RecordingPreviousPort()
    orchestrator = TurnOrchestrator(
        clock=FakeClock(NOW),
        trace=TraceRecorder(),
        previous_expression=port,
        decision_context_compiler=cast(Any, make_compiler_probe()),
    )
    orchestrator.begin_turn(make_interaction())
    orchestrator.ingest(make_evidence(text="hello"))
    orchestrator.run()
    assert port.calls == [(make_scope(), "respond")]


def make_compiler_probe() -> object:
    config = make_compiler_config()
    return DecisionContextCompiler(config)


def test_cross_scope_prior_expression_fails_closed_without_receipt() -> None:
    class ContractViolatingPriorPort:
        """Returns a wrong-Scope item despite the port contract (bad double)."""

        def previous(self, *, scope: Scope, action_type: str) -> PreviousExpression:
            return make_prior(scope=make_scope(user_id="other-user"))

    orchestrator = TurnOrchestrator(
        clock=FakeClock(NOW),
        trace=TraceRecorder(),
        previous_expression=ContractViolatingPriorPort(),
        decision_context_compiler=DecisionContextCompiler(make_compiler_config()),
    )
    orchestrator.begin_turn(make_interaction())
    orchestrator.ingest(make_evidence(text="hello"))
    with pytest.raises(ValueError, match="scope"):
        orchestrator.run()
    assert orchestrator.action_receipt is None
    assert orchestrator.expression_outcome is None


def test_provider_failure_aborts_without_receipt_on_real_path() -> None:
    orchestrator, _agent = make_d10_orchestrator(
        prior=None,
        script=(AgentFailure("provider down"),),
    )
    orchestrator.begin_turn(make_interaction())
    orchestrator.ingest(make_evidence(text="hello"))
    with pytest.raises(AgentFailure, match="provider down"):
        orchestrator.run()
    assert orchestrator.state.value == "aborted"
    assert orchestrator.action_receipt is None


def test_accepted_expression_does_not_complete_intent_without_reconcile() -> None:
    backend = InMemoryIntentBackend()
    orchestrator, _agent = make_d10_orchestrator(
        prior=None,
        script=("你好呀",),
        backend=backend,
    )
    run_turn(orchestrator)
    assert orchestrator.action_receipt is not None
    assert orchestrator.action_receipt.delivery_status is DeliveryStatus.SENT
    current = backend.current(make_scope())
    assert len(current) == 1
    assert current[0].status is IntentStatus.ALLOWED


def test_expression_trace_records_context_compile_and_outcome_refs() -> None:
    orchestrator, _agent = make_d10_orchestrator(
        prior=PRIOR,
        script=("今天真的很想和你重复", "换个开头，最近还好吗？"),
    )
    run_turn(orchestrator)
    entries = orchestrator.trace.trace("interaction-1")
    stages = [entry.stage for entry in entries]
    assert "expression_context" in stages
    assert "expression_compile" in stages
    assert "expression" in stages
    context_entry = next(entry for entry in entries if entry.stage == "expression_context")
    assert orchestrator.decision_context is not None
    assert context_entry.ref == orchestrator.decision_context.context_id
    expression_entry = next(entry for entry in entries if entry.stage == "expression")
    assert orchestrator.expression_outcome is not None
    assert expression_entry.ref == orchestrator.expression_outcome.outcome_id
