"""CE1-CE8: proactive would-send expression preparation (C5C).

The tick's ALLOWED proactive intent feeds the frozen D10 expression
authorities (DecisionContextCompiler -> DeterministicContextRenderer ->
agent -> DeterministicExpressionGuardChain, driven by the one
DeterministicExpressionCoordinator). C5C stops at the would-send artifact:
no outbound, no receipt, no delivery, and counter facts stay READ-ONLY
inputs — preparation never admits Evidence and never writes facts;
authoritative counter updates belong to later settled delivery outcomes.
Entry-angle repetition stays a seam: the injected read-only
PreviousExpressionPort is the future backing point for durable
would-send/sent history (C7/C8), not a new rule.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TypedDict

import pytest
from tests.support.fake_clock import FakeClock

from mind_runtime.cognition import build_cognitive_ticker
from mind_runtime.cognition.express import ProactiveExpressionArtifact
from mind_runtime.cognition.tick import CognitiveTicker, observation_fact_reader
from mind_runtime.contracts import (
    AffectiveDimensionProfile,
    Authority,
    AuthorityLevel,
    DeliveryStatus,
    Evidence,
    ExpressionDisposition,
    HostStatus,
    HostTurnStatus,
    IntentStatus,
    PolicyResources,
    PreviousExpression,
    ReconsiderationPolicy,
    Scope,
    ScopeDomain,
    SyncFields,
)
from mind_runtime.contracts.host import HostProactiveTurnResult


@dataclass
class _TestTurnResult:
    result: HostProactiveTurnResult
    proactive_expression: ProactiveExpressionArtifact | None

    @property
    def status(self) -> HostTurnStatus:
        return self.result.status

    @property
    def outcome(self) -> HostStatus:
        return self.result.outcome

    @property
    def bounded_context(self):
        return self.result.bounded_context

    @property
    def debug_ref(self):
        return self.result.debug_ref

    @property
    def decision_context_ref(self):
        return self.result.decision_context_ref

    @property
    def expression_ref(self):
        return self.result.expression_ref


def _run_test_proactive_turn(stack: _Stack, wake: WakeSignal) -> _TestTurnResult:
    adapter = stack["adapter"]
    prep_result = adapter.begin_proactive_turn(wake)
    if prep_result.status is not HostTurnStatus.PROCESSING or prep_result.outcome is not HostStatus.OK:
        return _TestTurnResult(prep_result, None)

    preparer = stack["preparer"]
    exec_ctx = adapter._pending_exec_contexts.get(wake.wake_id)
    if preparer is None or exec_ctx is None:
        return _TestTurnResult(prep_result, None)

    now = wake.woken_at
    tick_ctx = adapter._pending_wake_contexts.get(wake.wake_id) or {}
    if tick_ctx.get("transition_result") is None:
        artifact = ProactiveExpressionArtifact(
            interaction_id=wake.interaction_id,
            intent_id=wake.intent_id,
            action_type=wake.action_type,
            context_id=exec_ctx.context.context_id,
            skip_reason="no_transition",
        )
        fail_res = HostProactiveTurnResult(
            wake_id=wake.wake_id,
            interaction_id=wake.interaction_id,
            status=HostTurnStatus.ABORTED,
            outcome=HostStatus.FAILED,
            decision_context_ref=exec_ctx.context.context_id,
            expression_ref=None,
            debug_ref=f"debug-{wake.interaction_id}",
            bounded_context=prep_result.bounded_context,
            reason_codes=("no_transition",),
        )
        return _TestTurnResult(fail_res, artifact)

    try:
        artifact = preparer.realize_after_wake(exec_ctx, now=now)
    except Exception as exc:
        artifact = ProactiveExpressionArtifact(
            interaction_id=wake.interaction_id,
            intent_id=wake.intent_id,
            action_type=wake.action_type,
            context_id=exec_ctx.context.context_id,
            skip_reason="agent_failure",
        )
        fail_res = HostProactiveTurnResult(
            wake_id=wake.wake_id,
            interaction_id=wake.interaction_id,
            status=HostTurnStatus.ABORTED,
            outcome=HostStatus.FAILED,
            decision_context_ref=exec_ctx.context.context_id,
            expression_ref=None,
            debug_ref=f"debug-{wake.interaction_id}",
            bounded_context=prep_result.bounded_context,
            reason_codes=("agent_failure", str(exc)),
        )
        return _TestTurnResult(fail_res, artifact)

    if artifact.disposition is ExpressionDisposition.ACCEPT:
        guard_res = adapter.guard_proactive_prose(wake.wake_id, artifact.would_send or "")
        return _TestTurnResult(guard_res, artifact)
    else:
        fail_res = HostProactiveTurnResult(
            wake_id=wake.wake_id,
            interaction_id=wake.interaction_id,
            status=HostTurnStatus.ABORTED,
            outcome=HostStatus.FAILED,
            decision_context_ref=artifact.context_id,
            expression_ref=None,
            debug_ref=f"debug-{wake.interaction_id}",
            bounded_context=prep_result.bounded_context,
            disposition=artifact.disposition,
            would_send=artifact.would_send,
            reason_codes=(artifact.skip_reason,) if artifact.skip_reason else (),
        )
        return _TestTurnResult(fail_res, artifact)
from mind_runtime.dynamics.persona import PersonaProfile
from mind_runtime.expression import (
    AffectBand,
    AffectExpressionRule,
    DecisionContextCompiler,
    DecisionContextConfig,
    DeterministicContextRenderer,
    DeterministicExpressionCoordinator,
    DeterministicExpressionGuardChain,
    ExpressionCoordinatorConfig,
    ExpressionGuardConfig,
    FixedPreviousExpressionPort,
    TemporalConflictRule,
)
from mind_runtime.expression.history import NullPreviousExpressionPort
from mind_runtime.facts.persistence import SqliteFactBackend
from mind_runtime.facts.service import FactIngestService
from mind_runtime.host import MindRuntimeHostAdapter
from mind_runtime.intents.engine import DeterministicIntentEngine, IntentRule
from mind_runtime.intents.lifecycle import IntentLifecycleService
from mind_runtime.intents.persistence import SqliteIntentBackend
from mind_runtime.intents.policy import (
    ActionPolicyConfig,
    DeterministicActionPolicy,
    IntentPolicyRule,
)
from mind_runtime.pipeline.fake_agent import FakeAgent
from mind_runtime.pipeline.orchestrator import TurnOrchestrator
from mind_runtime.pipeline.ports import AgentFailure, PreviousExpressionPort
from mind_runtime.pipeline.trace import TraceRecorder
from mind_runtime.state.persistence import SqliteStateBackend

BASE = datetime(2026, 8, 28, 12, 0, tzinfo=UTC)  # afternoon
NIGHT = datetime(2026, 8, 28, 3, 0, tzinfo=UTC)
WILL_SEND = "今天下午想和你分享一首诗"
PREFIX_TWIN = "今天下午想和你分享一段话"


class _Stack(TypedDict):
    orchestrator: TurnOrchestrator
    ticker: CognitiveTicker
    agent: FakeAgent
    fact_service: FactIngestService
    intent_backend: SqliteIntentBackend
    state_backend: SqliteStateBackend
    scope: Scope
    persona: PersonaProfile
    adapter: MindRuntimeHostAdapter
    preparer: object


def _dimension(name: str, *, baseline: float, recovery: float) -> AffectiveDimensionProfile:
    return AffectiveDimensionProfile(
        dimension=name,
        baseline=baseline,
        initial_value=baseline - 0.3,
        sensitivity=1.0,
        recovery_rate=recovery,
        ceiling=1.0,
        floor=0.0,
        growth_profile=(),
        coupling_profile=(),
    )


def make_persona() -> PersonaProfile:
    return PersonaProfile(
        persona_id="synthetic-tick",
        dimensions=(
            _dimension("agent.affect.missing", baseline=0.9, recovery=0.02),
            _dimension("agent.affect.quiet", baseline=0.2, recovery=0.05),
        ),
    )


def make_rules() -> tuple[IntentRule, ...]:
    return (
        IntentRule(
            rule_id="reach-out",
            kind="reach_out",
            base_strength=0.1,
            dimension_weights=(("agent.affect.missing", 1.0),),
            event_kind=None,
            event_bonus=0.0,
            minimum_strength=0.8,
            due_at_attribute=None,
            expires_after=None,
            reconsideration_policy=ReconsiderationPolicy.NEVER,
        ),
    )


def make_policy_config(*, action_type: str = "proactive_message") -> ActionPolicyConfig:
    return ActionPolicyConfig(
        rules=(
            IntentPolicyRule(
                intent_kind="reach_out",
                action_type=action_type,
                proactive=action_type == "proactive_message",
                interrupts_active_conversation=False,
                media_counter_fact=None,
                media_limit=None,
                required_resource=None,
            ),
        ),
        proactive_cooldown=timedelta(minutes=30),
    )


def make_compiler_config() -> DecisionContextConfig:
    return DecisionContextConfig(
        allowed_situation_facts=("time.daypart",),
        affect_rules=(
            AffectExpressionRule(
                dimension="agent.affect.missing",
                output_key="missing",
                bands=(AffectBand(upper_bound=0.5, label="low"), AffectBand(1.0, "high")),
                priority=10,
            ),
        ),
        persona_style_constraints=(("tone", "steady"),),
        allowed_history_kinds=(),
        max_history_items=4,
        max_prior_expression_chars=200,
        max_item_chars=200,
        max_items=24,
        max_render_chars=2000,
    )


def make_guard_config() -> ExpressionGuardConfig:
    return ExpressionGuardConfig(
        prefix_length=8,
        transport_markers=(),
        banned_openings=("刚忙完",),
        temporal_rules=(
            TemporalConflictRule(
                rule_id="night-waking",
                incompatible_dayparts=("night",),
                phrases=("起床了吗", "吃早饭"),
                temporal_fact_key="time.daypart",
            ),
        ),
    )


def make_previous(prior: PreviousExpression | None, scope: Scope) -> PreviousExpressionPort:
    if prior is None:
        return NullPreviousExpressionPort()
    return FixedPreviousExpressionPort(prior)


def make_stack(
    tmp_path: Path,
    *,
    agent_script: tuple[str | AgentFailure, ...] = (WILL_SEND,),
    prior: PreviousExpression | None = None,
    action_type: str = "proactive_message",
    proactive_action_types: tuple[str, ...] = ("proactive_message",),
    with_expression: bool = True,
    base: datetime = BASE,
) -> _Stack:
    """One durable production stack with the C5C expression seam wired."""
    persona = make_persona()
    runtime_id = "runtime-1"
    scope = Scope(domain=ScopeDomain.USER, user_id="user-a")
    clock = FakeClock(base)

    fact_service = FactIngestService(
        clock=clock, backend=SqliteFactBackend(tmp_path / "facts.sqlite")
    )
    state_backend = SqliteStateBackend(tmp_path / "state.sqlite")
    intent_backend = SqliteIntentBackend(tmp_path / "intents.sqlite")
    orchestrator = TurnOrchestrator(
        clock=clock,
        trace=TraceRecorder(),
        runtime_id=runtime_id,
        fact_ingest=fact_service,
        persona=persona,
        state_backend=state_backend,
    )
    agent = FakeAgent(list(agent_script))
    expression = None
    if with_expression:
        from mind_runtime.cognition.express import (
            ProactiveExpressionConfig,
            ProactiveExpressionPreparer,
        )

        compiler_config = make_compiler_config()
        compiler = DecisionContextCompiler(config=compiler_config)
        coordinator = DeterministicExpressionCoordinator(
            compiler=compiler,
            renderer=DeterministicContextRenderer(config=compiler_config),
            agent=agent,
            guard=DeterministicExpressionGuardChain(config=make_guard_config()),
            config=ExpressionCoordinatorConfig(max_rewrites=2),
        )
        expression = ProactiveExpressionPreparer(
            orchestrator=orchestrator,
            compiler=compiler,
            coordinator=coordinator,
            previous_expression=make_previous(prior, scope),
            config=ProactiveExpressionConfig(proactive_action_types=proactive_action_types),
            runtime_id=runtime_id,
        )
    policy = DeterministicActionPolicy(
        make_policy_config(action_type=action_type), runtime_id
    )
    lifecycle = IntentLifecycleService(intent_backend)
    ticker = build_cognitive_ticker(
        orchestrator=orchestrator,
        persona=persona,
        intent_engine=DeterministicIntentEngine(make_rules(), runtime_id),
        action_policy=policy,
        policy_resources=PolicyResources(("proactive_message", "respond")),
        intent_lifecycle=lifecycle,
        runtime_id=runtime_id,
        fact_reader=observation_fact_reader(orchestrator),
    )
    orchestrator.cognitive_tick_components = {
        "ticker": ticker,
        "lifecycle": lifecycle,
        "policy": policy,
        "expression_preparer": expression,
    }
    adapter = MindRuntimeHostAdapter(orchestrator=orchestrator)
    return {
        "orchestrator": orchestrator,
        "ticker": ticker,
        "agent": agent,
        "fact_service": fact_service,
        "intent_backend": intent_backend,
        "state_backend": state_backend,
        "scope": scope,
        "persona": persona,
        "adapter": adapter,
        "preparer": expression,
    }


def seed_affect(stack: _Stack, *, value: float, at: datetime) -> None:
    """Seed durable canonical agent-scope affect through the state backend."""
    from mind_runtime.contracts import RuntimeState

    persona = stack["persona"]
    state_backend = stack["state_backend"]
    projection_scope = Scope(
        domain=ScopeDomain.AGENT, agent_id=persona.persona_id, persona_id=persona.persona_id
    )
    state_id = "agent.affect.missing:1:seeded"
    state_backend.save_state(
        RuntimeState(
            state_id=state_id,
            scope=projection_scope,
            dimension="agent.affect.missing",
            value=value,
            status="active",
            valid_from=at,
            valid_until=None,
            relevant_until=None,
            last_observed_at=at,
            evidence_refs=(),
            transition_refs=(),
            updated_at=at,
            origin_runtime_id="runtime-1",
            version=1,
            sync=SyncFields(projection_scope, "runtime-1", state_id, 1, f"idem-{state_id}"),
        )
    )


def seed_counter_fact(
    stack: _Stack, *, evidence_id: str, key: str, value: str, at: datetime
) -> None:
    """Admit one counter observation through the REAL factual plane."""
    scope = stack["scope"]
    fact_service = stack["fact_service"]
    evidence = Evidence(
        id=evidence_id,
        scope=scope,
        origin_runtime_id="runtime-1",
        source_type="typed_event",
        source_id=f"source-{evidence_id}",
        authority_level=AuthorityLevel.ASSERTED,
        authority=Authority(scope, AuthorityLevel.ASSERTED, f"source-{evidence_id}"),
        occurred_at=at,
        received_at=at,
        payload={"key": key, "value": value},
        sync=SyncFields(scope, "runtime-1", evidence_id, 1, f"idem-{evidence_id}"),
    )
    fact_service.admit(
        evidence,
        interaction_id=f"tick-facts-{evidence_id}",
        writing_runtime="runtime-1",
        writing_persona_id=None,
    )


def make_prior(scope: Scope, *, text: str) -> PreviousExpression:
    return PreviousExpression(
        expression_id="prior-1",
        scope=scope,
        origin_runtime_id="runtime-1",
        action_type="proactive_message",
        text=text,
        receipt_ref="receipt-prior-1",
        delivery_status=DeliveryStatus.SENT,
        sent_at=BASE - timedelta(hours=20),
    )


# ── CE1: ALLOWED proactive intent -> would-send artifact, nothing outbound ──


def test_ce1_allowed_intent_prepares_would_send(tmp_path: Path) -> None:
    stack = make_stack(tmp_path)
    seed_affect(stack, value=0.75, at=BASE)

    report = stack["ticker"].tick(scope=stack["scope"], now=BASE + timedelta(hours=2))

    assert report.policy_allowed == 1
    assert report.wake_signal is not None
    assert report.proactive_expression is None
    assert stack["agent"].call_count == 0

    turn_result = _run_test_proactive_turn(stack, report.wake_signal)
    assert turn_result.status is HostTurnStatus.PROCESSING
    artifact = turn_result.proactive_expression
    assert artifact is not None
    assert artifact.disposition is ExpressionDisposition.ACCEPT
    assert artifact.would_send == WILL_SEND
    assert artifact.context_id is not None and artifact.outcome_id is not None
    assert artifact.intent_id.startswith("intent-cognitive-tick-")
    assert artifact.action_type == "proactive_message"
    assert artifact.skip_reason is None
    # The guard verdict never completes the Intent: it stays ALLOWED v2.
    current = stack["intent_backend"].current(stack["scope"])
    assert current[0].status is IntentStatus.ALLOWED
    assert current[0].sync.version == 2
    # No delivery surface exists on the tick path.
    assert stack["orchestrator"].action_receipt is None
    # Proactive expression trace is recorded on the tick interaction.
    stages = {entry.stage for entry in stack["orchestrator"].trace.trace(report.interaction_id)}
    assert "proactive_body_entry" in stages
    assert "provider_realization" in stages
    assert "expression_guard" in stages

    commit_res = stack["adapter"].commit_proactive_turn(report.wake_signal.wake_id)
    assert commit_res.status is HostTurnStatus.COMMITTED
    current_after = stack["intent_backend"].current(stack["scope"])
    assert current_after[0].status is IntentStatus.COMPLETED


def test_ce1b_provider_view_is_bounded_and_counter_free(tmp_path: Path) -> None:
    stack = make_stack(tmp_path)
    seed_affect(stack, value=0.75, at=BASE)

    report = stack["ticker"].tick(scope=stack["scope"], now=BASE + timedelta(hours=2))
    assert report.wake_signal is not None
    turn_result = _run_test_proactive_turn(stack, report.wake_signal)

    artifact = turn_result.proactive_expression
    assert artifact is not None and artifact.would_send is not None
    calls = stack["agent"].calls
    assert len(calls) == 1
    text = calls[0].text
    # Only the allowed daypart fact crosses the provider boundary; counter
    # facts never do (read-only inputs, and only allow-listed keys render).
    assert "time.daypart: afternoon" in text
    assert "counter." not in text
    assert "INTERNAL_STATE" in text
    # The would-send text is never serialized into operability reports.
    assert WILL_SEND not in json.dumps(report.as_dict())


# ── CE2: prefix duplicate against prior -> REJECT, intent stays ALLOWED ─────


def test_ce2_prefix_duplicate_rejects_and_intent_survives(tmp_path: Path) -> None:
    prior = make_prior(stack_scope(), text=PREFIX_TWIN)
    stack = make_stack(tmp_path, agent_script=(WILL_SEND,), prior=prior)
    seed_affect(stack, value=0.75, at=BASE)

    report = stack["ticker"].tick(scope=stack["scope"], now=BASE + timedelta(hours=2))
    assert report.wake_signal is not None
    turn_result = _run_test_proactive_turn(stack, report.wake_signal)

    assert turn_result.status is HostTurnStatus.ABORTED
    artifact = turn_result.proactive_expression
    assert artifact is not None
    assert artifact.disposition is ExpressionDisposition.REJECT
    assert artifact.would_send is None
    assert artifact.attempt_count == 3  # initial + max_rewrites=2, then exhausted
    # Guard outcomes never complete or demote the Intent.
    current = stack["intent_backend"].current(stack["scope"])
    assert current[0].status is IntentStatus.ALLOWED
    assert current[0].sync.version == 2
    # The failed preparation leaves exactly the C5B durable footprint: the
    # same state rows and the same lifecycle versions as an unwired stack.
    baseline_dir = tmp_path / "baseline"
    baseline_dir.mkdir()
    baseline = make_stack(baseline_dir, with_expression=False)
    seed_affect(baseline, value=0.75, at=BASE)
    baseline["ticker"].tick(scope=baseline["scope"], now=BASE + timedelta(hours=2))
    assert len(stack["state_backend"].load_states()) == len(
        baseline["state_backend"].load_states()
    )
    assert len(stack["intent_backend"].current(stack["scope"])) == len(
        baseline["intent_backend"].current(baseline["scope"])
    )


def stack_scope() -> Scope:
    return Scope(domain=ScopeDomain.USER, user_id="user-a")


# ── CE3: rewrite loop succeeds within budget (prefix and temporal) ──────────


def test_ce3_prefix_rewrite_succeeds(tmp_path: Path) -> None:
    prior = make_prior(stack_scope(), text=PREFIX_TWIN)
    stack = make_stack(
        tmp_path, agent_script=(WILL_SEND, "下午想把一首短诗读给你听"), prior=prior
    )
    seed_affect(stack, value=0.75, at=BASE)

    report = stack["ticker"].tick(scope=stack["scope"], now=BASE + timedelta(hours=2))
    assert report.wake_signal is not None
    turn_result = _run_test_proactive_turn(stack, report.wake_signal)

    assert turn_result.status is HostTurnStatus.PROCESSING
    artifact = turn_result.proactive_expression
    assert artifact is not None
    assert artifact.disposition is ExpressionDisposition.ACCEPT
    assert artifact.would_send == "下午想把一首短诗读给你听"
    assert artifact.attempt_count == 2


def test_ce3b_temporal_conflict_rewrites_for_night(tmp_path: Path) -> None:
    stack = make_stack(
        tmp_path,
        base=NIGHT,
        agent_script=("起床了吗？想吃早饭吗", "晚上好，想和你分享一首诗"),
    )
    seed_affect(stack, value=0.75, at=NIGHT - timedelta(hours=2))

    report = stack["ticker"].tick(scope=stack["scope"], now=NIGHT)
    assert report.wake_signal is not None
    turn_result = _run_test_proactive_turn(stack, report.wake_signal)

    assert turn_result.status is HostTurnStatus.PROCESSING
    artifact = turn_result.proactive_expression
    assert artifact is not None
    assert artifact.disposition is ExpressionDisposition.ACCEPT
    assert artifact.would_send == "晚上好，想和你分享一首诗"
    assert artifact.attempt_count == 2
    assert "time.daypart: night" in stack["agent"].calls[0].text


# ── CE4: counter facts are read-only during preparation ──────────────────────


def test_ce4_counter_facts_never_mutated_by_preparation(tmp_path: Path) -> None:
    stack = make_stack(tmp_path)
    # Two counter facts that do NOT gate the policy: the photo count only
    # matters to media intents, and the last proactive timestamp is outside
    # the cooldown window. They must be visible to nothing but the reader.
    seed_counter_fact(
        stack,
        evidence_id="ev-photo",
        key="counter.photo_count_today",
        value="3",
        at=BASE,
    )
    seed_counter_fact(
        stack,
        evidence_id="ev-last",
        key="counter.last_proactive_at",
        value=(BASE - timedelta(hours=2)).isoformat(),
        at=BASE - timedelta(hours=2),
    )
    seed_affect(stack, value=0.75, at=BASE)

    def snapshot() -> list[tuple[object, ...]]:
        return sorted(
            (o.id, o.observed_at, str(o.scope), repr(o.value))
            for o in stack["fact_service"].observations.all()
        )

    before = snapshot()
    report = stack["ticker"].tick(scope=stack["scope"], now=BASE + timedelta(hours=2))
    assert report.wake_signal is not None
    turn_result = _run_test_proactive_turn(stack, report.wake_signal)
    after = snapshot()

    assert turn_result.proactive_expression is not None
    assert turn_result.proactive_expression.disposition is ExpressionDisposition.ACCEPT
    # Preparation produced no Evidence and mutated no admitted fact.
    assert after == before
    assert len(after) == 2


# ── CE5: non-proactive ALLOW never prepares expression ───────────────────────


def test_ce5_non_proactive_allow_skips_preparation(tmp_path: Path) -> None:
    stack = make_stack(tmp_path, action_type="respond")
    seed_affect(stack, value=0.75, at=BASE)

    report = stack["ticker"].tick(scope=stack["scope"], now=BASE + timedelta(hours=2))

    assert report.policy_allowed == 1
    assert report.wake_signal is None
    assert report.proactive_expression is None
    assert stack["agent"].call_count == 0


# ── CE6: no real transition this pass -> fail-closed skip, no generation ────


def test_ce6_elapsed_zero_pass_skips_preparation(tmp_path: Path) -> None:
    stack = make_stack(tmp_path)
    seed_affect(stack, value=0.75, at=BASE)

    # Same-instant affect: elapsed collapses to 0, no EmotionalTransition runs.
    report = stack["ticker"].tick(scope=stack["scope"], now=BASE)

    assert report.policy_allowed == 1
    assert report.proactive_expression is None
    assert stack["agent"].call_count == 0
    assert report.wake_signal is not None
    turn_result = _run_test_proactive_turn(stack, report.wake_signal)
    artifact = turn_result.proactive_expression
    assert artifact is not None
    assert artifact.disposition is None
    assert artifact.skip_reason == "no_transition"
    assert artifact.would_send == None
    assert stack["agent"].call_count == 0


# ── CE7: agent failure survives the tick without state corruption ───────────


def test_ce7_agent_failure_never_breaks_the_tick(tmp_path: Path) -> None:
    stack = make_stack(tmp_path, agent_script=(AgentFailure("provider down"),))
    seed_affect(stack, value=0.75, at=BASE)

    report = stack["ticker"].tick(scope=stack["scope"], now=BASE + timedelta(hours=2))

    assert report.policy_allowed == 1
    assert report.wake_signal is not None
    assert report.proactive_expression is None
    turn_result = _run_test_proactive_turn(stack, report.wake_signal)
    assert turn_result.status is HostTurnStatus.ABORTED

    artifact = turn_result.proactive_expression
    assert artifact is not None
    assert artifact.disposition is None
    assert artifact.skip_reason == "agent_failure"
    assert stack["agent"].call_count == 1
    # Intent and affect truth are untouched by the failed preparation.
    current = stack["intent_backend"].current(stack["scope"])
    assert current[0].status is IntentStatus.ALLOWED
    assert current[0].sync.version == 2


# ── CE8: expression seam unwired -> byte-for-byte C5B behavior ───────────────


def test_ce8_unwired_expression_keeps_c5b_behavior(tmp_path: Path) -> None:
    stack = make_stack(tmp_path, with_expression=False)
    seed_affect(stack, value=0.75, at=BASE)

    report = stack["ticker"].tick(scope=stack["scope"], now=BASE + timedelta(hours=2))

    assert report.policy_allowed == 1
    assert report.wake_signal is not None
    assert report.proactive_expression is None
    assert stack["agent"].call_count == 0
    current = stack["intent_backend"].current(stack["scope"])
    assert current[0].status is IntentStatus.ALLOWED


# ── construction fail-closed ─────────────────────────────────────────────────


def test_preparer_construction_fails_closed(tmp_path: Path) -> None:
    from mind_runtime.cognition.express import (
        ProactiveExpressionConfig,
        ProactiveExpressionPreparer,
    )

    stack = make_stack(tmp_path, with_expression=False)
    compiler_config = make_compiler_config()
    compiler = DecisionContextCompiler(config=compiler_config)
    coordinator = DeterministicExpressionCoordinator(
        compiler=compiler,
        renderer=DeterministicContextRenderer(config=compiler_config),
        agent=FakeAgent([WILL_SEND]),
        guard=DeterministicExpressionGuardChain(config=make_guard_config()),
        config=ExpressionCoordinatorConfig(max_rewrites=2),
    )
    with pytest.raises(ValueError, match="DecisionContextCompiler"):
        ProactiveExpressionPreparer(
            orchestrator=stack["orchestrator"],
            compiler=coordinator,  # type: ignore[arg-type]
            coordinator=coordinator,
            previous_expression=NullPreviousExpressionPort(),
            config=ProactiveExpressionConfig(proactive_action_types=("proactive_message",)),
            runtime_id="runtime-1",
        )
    with pytest.raises(ValueError, match="DeterministicExpressionCoordinator"):
        ProactiveExpressionPreparer(
            orchestrator=stack["orchestrator"],
            compiler=compiler,
            coordinator=compiler,  # type: ignore[arg-type]
            previous_expression=NullPreviousExpressionPort(),
            config=ProactiveExpressionConfig(proactive_action_types=("proactive_message",)),
            runtime_id="runtime-1",
        )
    with pytest.raises(ValueError, match="runtime_id"):
        ProactiveExpressionPreparer(
            orchestrator=stack["orchestrator"],
            compiler=compiler,
            coordinator=coordinator,
            previous_expression=NullPreviousExpressionPort(),
            config=ProactiveExpressionConfig(proactive_action_types=("proactive_message",)),
            runtime_id="",
        )
    with pytest.raises(ValueError, match="proactive_action_types"):
        ProactiveExpressionConfig(proactive_action_types=())
    with pytest.raises(ValueError, match="proactive_action_types"):
        ProactiveExpressionConfig(proactive_action_types=("", "proactive_message"))
    with pytest.raises(ValueError, match="unique"):
        ProactiveExpressionConfig(proactive_action_types=("a", "a"))


def test_ticker_rejects_wrong_expression_type(tmp_path: Path) -> None:
    """The ticker's own constructor refuses an expression seam (TypeError)."""
    stack = make_stack(tmp_path, with_expression=False)
    with pytest.raises(TypeError, match="unexpected keyword argument 'expression'"):
        build_cognitive_ticker(
            orchestrator=stack["orchestrator"],
            persona=stack["persona"],
            intent_engine=DeterministicIntentEngine(make_rules(), "runtime-1"),
            action_policy=DeterministicActionPolicy(make_policy_config(), "runtime-1"),
            policy_resources=PolicyResources(("proactive_message", "respond")),
            intent_lifecycle=IntentLifecycleService(
                SqliteIntentBackend(tmp_path / "i.sqlite")
            ),
            runtime_id="runtime-1",
            expression=object(),  # type: ignore[call-arg]
        )


def test_preparer_direct_prepare_skips_defense_paths(tmp_path: Path) -> None:
    """Direct prepare() callers get the same fail-closed skips the tick gate
    enforces via handles(): non-ALLOW and non-proactive never prepare."""
    from mind_runtime.cognition.express import (
        ProactiveExpressionArtifact,
        ProactiveExpressionConfig,
        ProactiveExpressionPreparer,
    )
    from mind_runtime.contracts import (
        ActionDecision,
        ActionPermission,
        ActionPolicyResult,
        Intent,
    )

    stack = make_stack(tmp_path)
    compiler_config = make_compiler_config()
    compiler = DecisionContextCompiler(config=compiler_config)
    coordinator = DeterministicExpressionCoordinator(
        compiler=compiler,
        renderer=DeterministicContextRenderer(config=compiler_config),
        agent=stack["agent"],
        guard=DeterministicExpressionGuardChain(config=make_guard_config()),
        config=ExpressionCoordinatorConfig(max_rewrites=2),
    )
    preparer = ProactiveExpressionPreparer(
        orchestrator=stack["orchestrator"],
        compiler=compiler,
        coordinator=coordinator,
        previous_expression=NullPreviousExpressionPort(),
        config=ProactiveExpressionConfig(proactive_action_types=("proactive_message",)),
        runtime_id="runtime-1",
    )
    scope = stack["scope"]
    intent = Intent(
        intent_id="intent-direct-1",
        scope=scope,
        origin_runtime_id="runtime-1",
        kind="reach_out",
        strength=0.9,
        earliest_at=BASE,
        due_at=None,
        expires_at=None,
        reconsideration_policy=ReconsiderationPolicy.NEVER,
        cause_refs=("cause",),
        state_refs=("state",),
        status=IntentStatus.CANDIDATE,
        sync=SyncFields(scope, "runtime-1", "intent-direct-1", 1, "idem-direct-1"),
    )
    situation = stack["ticker"]._tick_situation(
        scope=scope, interaction_id="cognitive-tick-direct", now=BASE
    )
    projected = stack["ticker"]._wrapper_projection(
        stack["ticker"]._affect_scope(), (), interaction_id="cognitive-tick-direct", now=BASE
    )

    def prepare(policy_result: ActionPolicyResult) -> ProactiveExpressionArtifact:
        return preparer.prepare(
            interaction_id="cognitive-tick-direct",
            intent=intent,
            policy_result=policy_result,
            situation=situation,
            projected=projected,
            assessment_trace_ref="trace-direct",
            state_rows=(),
            persona_ref=None,
            now=BASE,
        )

    denied = ActionPolicyResult(
        policy_id="policy-1",
        scope=scope,
        origin_runtime_id="runtime-1",
        intent_id=intent.intent_id,
        decision=ActionDecision.DENY,
        permission=ActionPermission(
            permission_id="perm-denied",
            scope=scope,
            origin_runtime_id="runtime-1",
            action_type="proactive_message",
            allowed=False,
            reasons=("cooldown",),
            constraints=(),
        ),
        reason_codes=("cooldown",),
    )
    assert prepare(denied).skip_reason == "not_allowed"

    unlisted = ActionPolicyResult(
        policy_id="policy-2",
        scope=scope,
        origin_runtime_id="runtime-1",
        intent_id=intent.intent_id,
        decision=ActionDecision.ALLOW,
        permission=ActionPermission(
            permission_id="perm-1",
            scope=scope,
            origin_runtime_id="runtime-1",
            action_type="respond",
            allowed=True,
            reasons=("ok",),
            constraints=(),
        ),
        reason_codes=("ok",),
    )
    assert prepare(unlisted).skip_reason == "not_proactive"
