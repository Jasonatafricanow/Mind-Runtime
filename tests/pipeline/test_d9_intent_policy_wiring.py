"""D9 Intent lifecycle, candidate fallback, and dispatch wiring."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from mind_runtime.contracts import (
    ActionDecision,
    ActionPermission,
    ActionPolicyInput,
    ActionPolicyResult,
    ActionReceipt,
    DeliveryStatus,
    EmotionalTransitionInput,
    EmotionalTransitionResult,
    ExpressionDisposition,
    ExpressionGuardInput,
    ExpressionGuardResult,
    Intent,
    IntentEngineInput,
    IntentEngineResult,
    IntentScoreContribution,
    IntentScoreTrace,
    IntentStatus,
    Interaction,
    InteractionStatus,
    PolicyResources,
    ReconsiderationPolicy,
    Scope,
    ScopeDomain,
    SyncFields,
)
from mind_runtime.intents.lifecycle import IntentLifecycleService
from mind_runtime.intents.persistence import InMemoryIntentBackend
from mind_runtime.pipeline.orchestrator import TurnOrchestrator, TurnState
from mind_runtime.pipeline.ports import ExpressionGuardPort
from mind_runtime.pipeline.receipts import ReceiptRegistry
from mind_runtime.pipeline.stubs import StubEmotionalTransition
from mind_runtime.pipeline.trace import TraceRecorder
from tests.golden.fixtures.common import make_scope
from tests.support.fake_clock import FakeClock

NOW = datetime(2026, 8, 22, 12, 0, tzinfo=UTC)
USER_SCOPE = make_scope()


def interaction() -> Interaction:
    return Interaction(
        interaction_id="interaction-1",
        scope=USER_SCOPE,
        channel="chat",
        session_id="session-1",
        turn_id="turn-1",
        started_at=NOW,
        committed_at=None,
        status=InteractionStatus.OPEN,
    )


def candidate(
    rule_id: str,
    kind: str,
    strength: float,
    *,
    scope: Scope = USER_SCOPE,
) -> Intent:
    intent_id = f"intent-interaction-1-{rule_id}"
    return Intent(
        intent_id=intent_id,
        scope=scope,
        origin_runtime_id="runtime-1",
        kind=kind,
        strength=strength,
        earliest_at=NOW,
        due_at=None,
        expires_at=NOW + timedelta(hours=1),
        reconsideration_policy=ReconsiderationPolicy.ON_CONTEXT_CHANGE,
        cause_refs=("situation-interaction-1",),
        state_refs=("projection-interaction-1",),
        status=IntentStatus.CANDIDATE,
        sync=SyncFields(scope, "runtime-1", intent_id, 1, f"idem-{intent_id}-v1"),
    )


def score_trace(value: Intent, rule_id: str) -> IntentScoreTrace:
    return IntentScoreTrace(
        trace_id=f"score-{rule_id}",
        scope=value.scope,
        rule_id=rule_id,
        intent_id=value.intent_id,
        contributions=(IntentScoreContribution("base", rule_id, value.strength),),
        unclamped_score=value.strength,
        final_strength=value.strength,
        admitted=True,
        reason_codes=("threshold_met",),
        created_at=NOW,
    )


def engine_result(values: tuple[Intent, ...]) -> IntentEngineResult:
    return IntentEngineResult(
        candidates=values,
        traces=tuple(score_trace(value, value.intent_id.rsplit("-", 1)[-1]) for value in values),
    )


class RecordingTransition:
    def __init__(self, clock: FakeClock) -> None:
        self.calls: list[EmotionalTransitionInput] = []
        self._delegate = StubEmotionalTransition(clock=clock)

    def transition(self, transition_input: EmotionalTransitionInput) -> EmotionalTransitionResult:
        self.calls.append(transition_input)
        return self._delegate.transition(transition_input)


class FixedEngine:
    def __init__(self, result: IntentEngineResult) -> None:
        self.result = result
        self.calls: list[IntentEngineInput] = []

    def evaluate(self, engine_input: IntentEngineInput) -> IntentEngineResult:
        self.calls.append(engine_input)
        return self.result


class PolicyByKind:
    def __init__(self, decisions: dict[str, ActionDecision]) -> None:
        self.decisions = decisions
        self.calls: list[ActionPolicyInput] = []

    def policy(self, policy_input: ActionPolicyInput) -> ActionPolicyResult:
        self.calls.append(policy_input)
        decision = self.decisions[policy_input.intent.kind]
        allowed = decision is ActionDecision.ALLOW
        reason = decision.value
        return ActionPolicyResult(
            policy_id=f"policy-{policy_input.intent.intent_id}",
            scope=policy_input.scope,
            origin_runtime_id="runtime-1",
            intent_id=policy_input.intent.intent_id,
            decision=decision,
            permission=ActionPermission(
                permission_id=f"permission-{policy_input.intent.intent_id}",
                scope=policy_input.scope,
                origin_runtime_id="runtime-1",
                action_type=policy_input.intent.kind,
                allowed=allowed,
                reasons=(reason,),
                constraints=() if allowed else (reason,),
            ),
            reason_codes=(reason,),
        )


class RecordingAgent:
    def __init__(self) -> None:
        self.calls: list[object] = []

    def respond(self, provider_context: object) -> str:
        self.calls.append(provider_context)
        return "hello"


class RejectingGuard:
    def guard(self, guard_input: ExpressionGuardInput) -> ExpressionGuardResult:
        return ExpressionGuardResult(
            guard_id="guard-rejected",
            scope=guard_input.decision_context.scope,
            origin_runtime_id=guard_input.decision_context.origin_runtime_id,
            expression=guard_input.expression,
            disposition=ExpressionDisposition.REJECT,
            violations=("blocked",),
        )


def make_runtime(
    values: tuple[Intent, ...],
    decisions: dict[str, ActionDecision],
    *,
    receipts: ReceiptRegistry | None = None,
    expression_guard: ExpressionGuardPort | None = None,
) -> tuple[
    TurnOrchestrator,
    RecordingTransition,
    FixedEngine,
    PolicyByKind,
    RecordingAgent,
    InMemoryIntentBackend,
]:
    clock = FakeClock(NOW)
    transition = RecordingTransition(clock)
    engine = FixedEngine(engine_result(values))
    policy = PolicyByKind(decisions)
    agent = RecordingAgent()
    backend = InMemoryIntentBackend()
    lifecycle = IntentLifecycleService(backend)
    orchestrator = TurnOrchestrator(
        clock=clock,
        trace=TraceRecorder(),
        emotional_transition=transition,
        intent_engine=engine,
        intent_lifecycle=lifecycle,
        action_policy=policy,
        policy_resources=PolicyResources(("text_message", "photo_message", "camera")),
        agent=agent,
        receipts=receipts,
        expression_guard=expression_guard,
    )
    return orchestrator, transition, engine, policy, agent, backend


def run(orchestrator: TurnOrchestrator) -> None:
    orchestrator.begin_turn(interaction())
    orchestrator.run()


def test_photo_defer_then_text_allow_selects_fallback_and_dispatches_once() -> None:
    photo = candidate("photo", "share_photo", 0.9)
    text = candidate("text", "respond", 0.7)
    orchestrator, transition, engine, policy, agent, backend = make_runtime(
        (photo, text),
        {"share_photo": ActionDecision.DEFER, "respond": ActionDecision.ALLOW},
    )

    run(orchestrator)

    assert len(transition.calls) == 1
    assert len(engine.calls) == 1
    assert [item.intent.kind for item in policy.calls] == ["share_photo", "respond"]
    assert all(
        item.resources == PolicyResources(("text_message", "photo_message", "camera"))
        for item in policy.calls
    )
    assert len(agent.calls) == 1
    assert orchestrator.intent is not None
    assert orchestrator.intent.intent_id == text.intent_id
    assert orchestrator.intent.status is IntentStatus.ALLOWED
    assert backend.current(USER_SCOPE)[0].status is IntentStatus.DEFERRED
    assert backend.current(USER_SCOPE)[1].status is IntentStatus.ALLOWED
    assert orchestrator.turn_projection is not None
    assert orchestrator.turn_projection.intent_refs == (photo.intent_id, text.intent_id)
    assert orchestrator.action_receipt is not None
    assert orchestrator.action_receipt.action_intent_id == text.intent_id


def test_all_defer_or_deny_skips_agent_context_and_receipt_but_projection_commits() -> None:
    photo = candidate("photo", "share_photo", 0.9)
    text = candidate("text", "respond", 0.7)
    registry = ReceiptRegistry()
    orchestrator, _transition, _engine, policy, agent, backend = make_runtime(
        (photo, text),
        {"share_photo": ActionDecision.DEFER, "respond": ActionDecision.DENY},
        receipts=registry,
    )

    run(orchestrator)

    assert [item.intent.kind for item in policy.calls] == ["share_photo", "respond"]
    assert agent.calls == []
    assert orchestrator.state is TurnState.PROCESSING
    assert orchestrator.intent is None
    assert orchestrator.decision_context is None
    assert orchestrator.action_receipt is None
    assert registry.count() == 0
    assert orchestrator.turn_projection is not None
    assert orchestrator.turn_projection.intent_refs == (photo.intent_id, text.intent_id)
    assert [item.status for item in backend.current(USER_SCOPE)] == [
        IntentStatus.DEFERRED,
        IntentStatus.BLOCKED,
    ]
    assert orchestrator.canonical == ()
    orchestrator.commit_turn()
    assert orchestrator.canonical != ()


def test_lower_candidates_supersede_only_after_first_allow() -> None:
    first = candidate("first", "share_photo", 0.9)
    selected = candidate("selected", "respond", 0.8)
    lower = candidate("lower", "contact_user", 0.7)
    orchestrator, _transition, _engine, policy, _agent, backend = make_runtime(
        (first, selected, lower),
        {
            "share_photo": ActionDecision.DEFER,
            "respond": ActionDecision.ALLOW,
            "contact_user": ActionDecision.ALLOW,
        },
    )

    run(orchestrator)

    assert [item.intent.kind for item in policy.calls] == ["share_photo", "respond"]
    assert orchestrator.intent is not None
    assert orchestrator.intent.intent_id == selected.intent_id
    current = {item.intent_id: item for item in backend.current(USER_SCOPE)}
    assert current[first.intent_id].status is IntentStatus.DEFERRED
    assert current[selected.intent_id].status is IntentStatus.ALLOWED
    assert current[lower.intent_id].status is IntentStatus.SUPERSEDED


def test_no_scored_candidates_is_a_no_dispatch_projection() -> None:
    orchestrator, _transition, engine, policy, agent, backend = make_runtime((), {})

    assert orchestrator.policy_results == ()
    run(orchestrator)

    assert len(engine.calls) == 1
    assert policy.calls == []
    assert agent.calls == []
    assert backend.current(USER_SCOPE) == ()
    assert orchestrator.turn_projection is not None
    assert orchestrator.turn_projection.intent_refs == ()
    assert orchestrator.turn_projection.policy_result_ref is None
    assert orchestrator.policy_results == ()


def test_wrong_scope_engine_output_fails_before_any_intent_is_persisted() -> None:
    other_scope = Scope(domain=ScopeDomain.USER, user_id="other-user")
    wrong = candidate("wrong", "respond", 0.7, scope=other_scope)
    orchestrator, _transition, _engine, _policy, _agent, backend = make_runtime(
        (wrong,), {"respond": ActionDecision.ALLOW}
    )
    orchestrator.begin_turn(interaction())

    with pytest.raises(ValueError, match="scope"):
        orchestrator.run()

    assert backend.current(USER_SCOPE) == ()
    assert backend.current(other_scope) == ()


@pytest.mark.parametrize(
    ("mutation", "message"),
    [("origin", "origin"), ("status", "version-one")],
)
def test_invalid_engine_candidate_origin_or_lifecycle_shape_fails_before_admission(
    mutation: str, message: str
) -> None:
    invalid = candidate(mutation, "respond", 0.7)
    if mutation == "origin":
        invalid = replace(
            invalid,
            origin_runtime_id="other-runtime",
            sync=replace(invalid.sync, origin_runtime_id="other-runtime"),
        )
    else:
        invalid = replace(invalid, status=IntentStatus.DEFERRED)
    orchestrator, _transition, _engine, _policy, _agent, backend = make_runtime(
        (invalid,), {"respond": ActionDecision.ALLOW}
    )
    orchestrator.begin_turn(interaction())

    with pytest.raises(ValueError, match=message):
        orchestrator.run()

    assert backend.current(USER_SCOPE) == ()


def test_rejected_score_trace_wrong_scope_fails_closed() -> None:
    other_scope = Scope(domain=ScopeDomain.USER, user_id="other-user")
    trace_source = candidate("trace", "respond", 0.7, scope=other_scope)
    rejected_trace = replace(
        score_trace(trace_source, "trace"),
        admitted=False,
        reason_codes=("below_minimum_strength",),
    )
    engine = FixedEngine(IntentEngineResult(candidates=(), traces=(rejected_trace,)))
    backend = InMemoryIntentBackend()
    orchestrator = TurnOrchestrator(
        clock=FakeClock(NOW),
        trace=TraceRecorder(),
        intent_engine=engine,
        intent_lifecycle=IntentLifecycleService(backend),
    )
    orchestrator.begin_turn(interaction())

    with pytest.raises(ValueError, match="score trace scope"):
        orchestrator.run()

    assert backend.current(USER_SCOPE) == ()


def test_expired_candidate_is_recorded_without_policy_or_dispatch() -> None:
    expired = replace(candidate("expired", "respond", 0.7), expires_at=NOW)
    orchestrator, _transition, _engine, policy, agent, backend = make_runtime(
        (expired,), {"respond": ActionDecision.ALLOW}
    )

    run(orchestrator)

    assert policy.calls == []
    assert agent.calls == []
    assert backend.current(USER_SCOPE)[0].status is IntentStatus.EXPIRED
    assert orchestrator.intent is None


def test_mismatched_policy_result_fails_before_lifecycle_decision() -> None:
    selected = candidate("selected", "respond", 0.7)

    class MismatchedPolicy(PolicyByKind):
        def policy(self, policy_input: ActionPolicyInput) -> ActionPolicyResult:
            valid = super().policy(policy_input)
            return replace(valid, intent_id="other-intent")

    backend = InMemoryIntentBackend()
    policy = MismatchedPolicy({"respond": ActionDecision.ALLOW})
    orchestrator = TurnOrchestrator(
        clock=FakeClock(NOW),
        trace=TraceRecorder(),
        intent_engine=FixedEngine(engine_result((selected,))),
        intent_lifecycle=IntentLifecycleService(backend),
        action_policy=policy,
    )
    orchestrator.begin_turn(interaction())

    with pytest.raises(ValueError, match="must match"):
        orchestrator.run()

    assert backend.current(USER_SCOPE)[0].status is IntentStatus.CANDIDATE


def test_old_emotional_transition_embedded_intent_shape_cannot_bypass_engine() -> None:
    clock = FakeClock(NOW)
    stub = StubEmotionalTransition(clock=clock)
    embedded = candidate("embedded", "respond", 0.7)

    class OldShapeTransition:
        def transition(self, transition_input: EmotionalTransitionInput) -> object:
            valid = stub.transition(transition_input)
            return SimpleNamespace(
                projected=valid.projected,
                intents=(embedded,),
                assessment_trace=valid.assessment_trace,
            )

    engine = FixedEngine(engine_result((embedded,)))
    backend = InMemoryIntentBackend()
    orchestrator = TurnOrchestrator(
        clock=clock,
        trace=TraceRecorder(),
        emotional_transition=OldShapeTransition(),  # type: ignore[arg-type]
        intent_engine=engine,
        intent_lifecycle=IntentLifecycleService(backend),
    )
    orchestrator.begin_turn(interaction())

    with pytest.raises(AttributeError, match="accepted_events"):
        orchestrator.run()

    assert engine.calls == []
    assert backend.current(USER_SCOPE) == ()


@pytest.mark.parametrize(
    ("guard_rejects", "add_unknown", "expected_status"),
    [
        (False, False, IntentStatus.COMPLETED),
        (True, False, IntentStatus.ALLOWED),
        (False, True, IntentStatus.ALLOWED),
    ],
)
def test_only_reconciled_sent_receipt_completes_selected_intent(
    guard_rejects: bool,
    add_unknown: bool,
    expected_status: IntentStatus,
) -> None:
    selected = candidate("selected", "respond", 0.8)
    registry = ReceiptRegistry()
    guard = RejectingGuard() if guard_rejects else None
    orchestrator, _transition, _engine, _policy, _agent, backend = make_runtime(
        (selected,),
        {"respond": ActionDecision.ALLOW},
        receipts=registry,
        expression_guard=guard,
    )
    run(orchestrator)
    if add_unknown:
        unknown_id = "receipt-unknown"
        registry.record(
            ActionReceipt(
                receipt_id=unknown_id,
                scope=USER_SCOPE,
                origin_runtime_id="runtime-1",
                action_intent_id=selected.intent_id,
                delivery_status=DeliveryStatus.UNKNOWN,
                outcome=None,
                received_at=NOW,
                sync=SyncFields(
                    USER_SCOPE,
                    "runtime-1",
                    unknown_id,
                    1,
                    "idem-receipt-unknown",
                ),
            )
        )

    orchestrator.reconcile(selected.intent_id)

    current = next(
        item for item in backend.current(USER_SCOPE) if item.intent_id == selected.intent_id
    )
    assert current.status is expected_status
    if expected_status is IntentStatus.COMPLETED:
        history_before = backend.history(USER_SCOPE, selected.intent_id)
        orchestrator.reconcile(selected.intent_id)
        assert backend.history(USER_SCOPE, selected.intent_id) == history_before


def test_reconciled_sent_receipt_for_unknown_intent_creates_no_lifecycle_record() -> None:
    registry = ReceiptRegistry()
    orchestrator, _transition, _engine, _policy, _agent, backend = make_runtime(
        (), {}, receipts=registry
    )
    run(orchestrator)
    receipt_id = "receipt-missing-intent"
    registry.record(
        ActionReceipt(
            receipt_id=receipt_id,
            scope=USER_SCOPE,
            origin_runtime_id="runtime-1",
            action_intent_id="missing-intent",
            delivery_status=DeliveryStatus.SENT,
            outcome="sent elsewhere",
            received_at=NOW,
            sync=SyncFields(
                USER_SCOPE,
                "runtime-1",
                receipt_id,
                1,
                "idem-receipt-missing-intent",
            ),
        )
    )

    outcome = orchestrator.reconcile("missing-intent")

    assert outcome.reconciled is True
    assert backend.current(USER_SCOPE) == ()
