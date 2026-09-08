"""D2S.3 FakeAgent + ActionReceipt skeleton tests."""

from datetime import UTC, datetime

import pytest

from mind_runtime.contracts import (
    DeliveryStatus,
    ExpressionDisposition,
    ExpressionGuardInput,
    ExpressionGuardResult,
    Interaction,
    InteractionStatus,
    ProviderExpressionContext,
    Scope,
    ScopeDomain,
)
from mind_runtime.pipeline.fake_agent import FakeAgent
from mind_runtime.pipeline.orchestrator import TurnOrchestrator
from mind_runtime.pipeline.ports import AgentFailure
from mind_runtime.pipeline.trace import TraceRecorder
from tests.golden.fixtures.common import make_evidence, make_scope
from tests.support.fake_clock import FakeClock

NOW = datetime(2026, 8, 20, 17, 0, tzinfo=UTC)


def make_interaction() -> Interaction:
    scope = make_scope()
    return Interaction(
        interaction_id="interaction-1",
        scope=scope,
        channel="chat",
        session_id="session-1",
        turn_id="turn-1",
        started_at=NOW,
        committed_at=None,
        status=InteractionStatus.OPEN,
    )


def make_orchestrator(agent: FakeAgent) -> TurnOrchestrator:
    return TurnOrchestrator(
        clock=FakeClock(NOW),
        trace=TraceRecorder(),
        agent=agent,
    )


def make_provider_context() -> ProviderExpressionContext:
    return ProviderExpressionContext(
        "render-1", "context-1", make_scope(), "runtime-1", "selected_action=text_message", (), ()
    )


def test_fake_agent_returns_scripted_responses_in_order() -> None:
    agent = FakeAgent(["first", "second"])
    context = make_provider_context()
    assert agent.respond(context) == "first"
    assert agent.respond(context) == "second"
    # Last scripted response repeats (idempotent tail).
    assert agent.respond(context) == "second"
    assert agent.call_count == 3
    assert len(agent.calls) == 3


def test_fake_agent_raises_scripted_failure() -> None:
    agent = FakeAgent(["ok", AgentFailure("boom")])
    context = make_provider_context()
    assert agent.respond(context) == "ok"
    with pytest.raises(AgentFailure, match="boom"):
        agent.respond(context)
    assert agent.call_count == 2


def test_fake_agent_rejects_empty_script() -> None:
    with pytest.raises(ValueError, match="empty"):
        FakeAgent([])


def test_dispatch_receipt_transitions_unsent_to_sent() -> None:
    agent = FakeAgent(["晚上好"])
    orchestrator = make_orchestrator(agent)
    orchestrator.begin_turn(make_interaction())
    orchestrator.ingest(make_evidence(text="hello"))
    # Before run: no receipt yet.
    assert orchestrator.action_receipt is None
    orchestrator.run()
    assert orchestrator.state.value == "dispatching"
    assert orchestrator.action_receipt is not None
    assert orchestrator.action_receipt.delivery_status is DeliveryStatus.SENT
    assert orchestrator.action_receipt.outcome == "晚上好"
    assert agent.call_count == 1
    assert orchestrator.trace.trace("interaction-1")[-1].stage == "dispatch"


def test_agent_failure_leaves_receipt_absent_and_state_aborted() -> None:
    agent = FakeAgent([AgentFailure("boom")])
    orchestrator = make_orchestrator(agent)
    orchestrator.begin_turn(make_interaction())
    orchestrator.ingest(make_evidence(text="hello"))
    with pytest.raises(AgentFailure):
        orchestrator.run()
    assert orchestrator.state.value == "aborted"
    assert orchestrator.action_receipt is None
    assert orchestrator.canonical == ()


def test_guard_rejection_leaves_receipt_unsent() -> None:
    class RejectingGuard:
        def guard(self, guard_input: ExpressionGuardInput) -> ExpressionGuardResult:
            return ExpressionGuardResult(
                guard_id="guard-reject",
                scope=guard_input.decision_context.scope,
                origin_runtime_id=guard_input.decision_context.origin_runtime_id,
                expression=guard_input.expression,
                disposition=ExpressionDisposition.REWRITE,
                violations=("forbidden_opening",),
            )

    agent = FakeAgent(["早上好"])
    orchestrator = make_orchestrator(agent)
    orchestrator.expression_guard = RejectingGuard()
    orchestrator.begin_turn(make_interaction())
    orchestrator.ingest(make_evidence(text="hello"))
    orchestrator.run()
    assert orchestrator.action_receipt is not None
    assert orchestrator.action_receipt.delivery_status is DeliveryStatus.UNSENT
    assert orchestrator.action_receipt.outcome is None


def test_mismatched_guard_scope_cannot_create_a_sent_receipt() -> None:
    class MismatchedScopeGuard:
        def guard(self, guard_input: ExpressionGuardInput) -> ExpressionGuardResult:
            return ExpressionGuardResult(
                guard_id="guard-wrong-scope",
                scope=Scope(domain=ScopeDomain.USER, user_id="other-user"),
                origin_runtime_id=guard_input.decision_context.origin_runtime_id,
                expression=guard_input.expression,
                disposition=ExpressionDisposition.ACCEPT,
                violations=(),
            )

    agent = FakeAgent(["hello"])
    orchestrator = make_orchestrator(agent)
    orchestrator.expression_guard = MismatchedScopeGuard()
    orchestrator.begin_turn(make_interaction())
    orchestrator.ingest(make_evidence(text="hello"))
    orchestrator.run()

    assert orchestrator.expression_outcome is not None
    assert orchestrator.expression_outcome.final_disposition is ExpressionDisposition.REJECT
    assert orchestrator.action_receipt is not None
    assert orchestrator.action_receipt.delivery_status is DeliveryStatus.UNSENT
    assert orchestrator.action_receipt.outcome is None


def test_mismatched_guard_origin_cannot_create_a_sent_receipt() -> None:
    class MismatchedOriginGuard:
        def guard(self, guard_input: ExpressionGuardInput) -> ExpressionGuardResult:
            return ExpressionGuardResult(
                guard_id="guard-wrong-origin",
                scope=guard_input.decision_context.scope,
                origin_runtime_id="other-runtime",
                expression=guard_input.expression,
                disposition=ExpressionDisposition.ACCEPT,
                violations=(),
            )

    agent = FakeAgent(["hello"])
    orchestrator = make_orchestrator(agent)
    orchestrator.expression_guard = MismatchedOriginGuard()
    orchestrator.begin_turn(make_interaction())
    orchestrator.ingest(make_evidence(text="hello"))
    orchestrator.run()

    assert orchestrator.expression_outcome is not None
    assert orchestrator.expression_outcome.final_disposition is ExpressionDisposition.REJECT
    assert orchestrator.action_receipt is not None
    assert orchestrator.action_receipt.delivery_status is DeliveryStatus.UNSENT
    assert orchestrator.action_receipt.outcome is None


def test_mismatched_guard_expression_cannot_create_a_sent_receipt() -> None:
    class MismatchedExpressionGuard:
        def guard(self, guard_input: ExpressionGuardInput) -> ExpressionGuardResult:
            return ExpressionGuardResult(
                guard_id="guard-wrong-expression",
                scope=guard_input.decision_context.scope,
                origin_runtime_id=guard_input.decision_context.origin_runtime_id,
                expression="different expression",
                disposition=ExpressionDisposition.ACCEPT,
                violations=(),
            )

    agent = FakeAgent(["hello"])
    orchestrator = make_orchestrator(agent)
    orchestrator.expression_guard = MismatchedExpressionGuard()
    orchestrator.begin_turn(make_interaction())
    orchestrator.ingest(make_evidence(text="hello"))
    orchestrator.run()

    assert orchestrator.expression_outcome is not None
    assert orchestrator.expression_outcome.final_disposition is ExpressionDisposition.REJECT
    assert orchestrator.action_receipt is not None
    assert orchestrator.action_receipt.delivery_status is DeliveryStatus.UNSENT
    assert orchestrator.action_receipt.outcome is None
