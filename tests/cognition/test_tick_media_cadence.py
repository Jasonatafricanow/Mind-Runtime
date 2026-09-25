"""LR1-LR8: media photo cadence wiring on the proactive tick (C6B).

Closes legacy gap #6 (docs/legacy/kayla-rule-map.md image.quota_frequency)
READ/DERIVATION/CONTEXT half only:

    host-owned settled-action counter (read-only; no production writer yet)
      -> Situation derived fact media.photo_frequency_eligible
      -> DecisionContext generation hint
      -> generation may choose text or photo

NOT: a forced photo intent, NOT an ActionPolicy hard-allow, NOT
eligible == must send. A missing counter fails closed (fact "false"),
no Evidence is fabricated, and the ActionPolicy daily media budget
(media_limit) stays the separate hard authority. The cadence threshold
is deployment configuration on CognitiveTickConfig — ``None`` (the
generic runtime default) disables the feature entirely; no runtime
silently inherits one deployment's 1-per-3 rule (LR7a/b/c).
"""

# Helpers are kept above the fixture imports to mirror the historical seam.
# Ruff's E402 is irrelevant to this test-only organization.
# ruff: noqa: E402

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TypedDict

import pytest
from tests.support.fake_clock import FakeClock

from mind_runtime.cognition import build_cognitive_ticker
from mind_runtime.cognition.express import ProactiveExpressionArtifact
from mind_runtime.cognition.tick import (
    CognitiveTickConfig,
    CognitiveTicker,
    observation_fact_reader,
)
from mind_runtime.contracts import (
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
    WakeSignal,
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
    if (
        prep_result.status is not HostTurnStatus.PROCESSING
        or prep_result.outcome is not HostStatus.OK
    ):
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
from mind_runtime.pipeline.trace import TraceRecorder
from mind_runtime.state.persistence import SqliteStateBackend

BASE = datetime(2026, 8, 28, 12, 0, tzinfo=UTC)
CADENCE_COUNTER = "counter.proactive_prompts_since_photo"
DAILY_PHOTO_COUNTER = "counter.photo_count_today"
ELIGIBILITY_FACT = "media.photo_frequency_eligible"


class _Stack(TypedDict):
    orchestrator: TurnOrchestrator
    ticker: CognitiveTicker
    agent: FakeAgent
    fact_service: FactIngestService
    intent_backend: SqliteIntentBackend
    state_backend: SqliteStateBackend
    scope: Scope


def make_stack(
    tmp_path: Path,
    *,
    user_id: str = "user-a",
    persona_id: str = "synthetic-cadence",
    media_rule: bool = False,
    with_expression: bool = False,
    agent_script: tuple[str, ...] = ("今天下午想和你分享一首诗",),
    prior: PreviousExpression | None = None,
    photo_cadence_threshold: int | None = None,
) -> _Stack:
    """One durable production stack; media rule only when explicitly asked."""
    from mind_runtime.cognition.express import (
        ProactiveExpressionConfig,
        ProactiveExpressionPreparer,
    )
    from mind_runtime.contracts import AffectiveDimensionProfile

    persona = PersonaProfile(
        persona_id=persona_id,
        dimensions=(
            AffectiveDimensionProfile(
                dimension="agent.affect.missing",
                baseline=0.9,
                initial_value=0.6,
                sensitivity=1.0,
                recovery_rate=0.02,
                ceiling=1.0,
                floor=0.0,
                growth_profile=(),
                coupling_profile=(),
            ),
        ),
    )
    runtime_id = "runtime-1"
    scope = Scope(domain=ScopeDomain.USER, user_id=user_id)
    clock = FakeClock(BASE)
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
    # With the media rule the photo candidate must reach ActionPolicy (the
    # LR4 subject): keep its strength above reach_out's.
    reach_weight, reach_minimum = (0.5, 0.5) if media_rule else (1.0, 0.8)
    engine_rules: tuple[IntentRule, ...] = (
        IntentRule(
            rule_id="reach-out",
            kind="reach_out",
            base_strength=0.1,
            dimension_weights=(("agent.affect.missing", reach_weight),),
            event_kind=None,
            event_bonus=0.0,
            minimum_strength=reach_minimum,
            due_at_attribute=None,
            expires_after=None,
            reconsideration_policy=ReconsiderationPolicy.NEVER,
        ),
    )
    policy_rules: tuple[IntentPolicyRule, ...] = (
        IntentPolicyRule(
            intent_kind="reach_out",
            action_type="proactive_message",
            proactive=True,
            interrupts_active_conversation=False,
            media_counter_fact=None,
            media_limit=None,
            required_resource=None,
        ),
    )
    if media_rule:
        engine_rules += (
            IntentRule(
                rule_id="share-photo",
                kind="share_photo",
                base_strength=0.9,
                dimension_weights=(),
                event_kind=None,
                event_bonus=0.0,
                minimum_strength=0.5,
                due_at_attribute=None,
                expires_after=None,
                reconsideration_policy=ReconsiderationPolicy.NEVER,
            ),
        )
        policy_rules += (
            IntentPolicyRule(
                intent_kind="share_photo",
                action_type="send_photo",
                proactive=True,
                interrupts_active_conversation=False,
                media_counter_fact=DAILY_PHOTO_COUNTER,
                media_limit=8,
                required_resource=None,
            ),
        )
    expression = None
    if with_expression:
        compiler_config = DecisionContextConfig(
            allowed_situation_facts=("time.daypart", ELIGIBILITY_FACT),
            affect_rules=(
                AffectExpressionRule(
                    dimension="agent.affect.missing",
                    output_key="missing",
                    bands=(AffectBand(0.5, "low"), AffectBand(1.0, "high")),
                    priority=10,
                ),
            ),
            persona_style_constraints=(),
            allowed_history_kinds=(),
            max_history_items=4,
            max_prior_expression_chars=200,
            max_item_chars=200,
            max_items=24,
            max_render_chars=2000,
        )
        compiler = DecisionContextCompiler(config=compiler_config)
        coordinator = DeterministicExpressionCoordinator(
            compiler=compiler,
            renderer=DeterministicContextRenderer(config=compiler_config),
            agent=agent,
            guard=DeterministicExpressionGuardChain(
                config=ExpressionGuardConfig(
                    prefix_length=8,
                    transport_markers=(),
                    banned_openings=("刚忙完",),
                    temporal_rules=(),
                )
            ),
            config=ExpressionCoordinatorConfig(max_rewrites=2),
        )
        expression = ProactiveExpressionPreparer(
            orchestrator=orchestrator,
            compiler=compiler,
            coordinator=coordinator,
            previous_expression=(
                FixedPreviousExpressionPort(prior)
                if prior is not None
                else NullPreviousExpressionPort()
            ),
            config=ProactiveExpressionConfig(proactive_action_types=("proactive_message",)),
            runtime_id=runtime_id,
        )
    policy = DeterministicActionPolicy(
        ActionPolicyConfig(
            rules=policy_rules,
            proactive_cooldown=timedelta(minutes=30),
        ),
        runtime_id,
    )
    lifecycle = IntentLifecycleService(intent_backend)
    ticker = build_cognitive_ticker(
        orchestrator=orchestrator,
        persona=persona,
        intent_engine=DeterministicIntentEngine(engine_rules, runtime_id),
        action_policy=policy,
        policy_resources=PolicyResources(("proactive_message", "send_photo", "respond")),
        intent_lifecycle=lifecycle,
        runtime_id=runtime_id,
        fact_reader=observation_fact_reader(orchestrator),
        config=CognitiveTickConfig(photo_cadence_threshold=photo_cadence_threshold),
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
        "preparer": expression,
        "adapter": adapter,
    }


def seed_affect(stack: _Stack, *, value: float = 0.75, at: datetime = BASE) -> None:
    from mind_runtime.contracts import RuntimeState

    persona = stack["orchestrator"]._persona
    assert persona is not None
    projection_scope = Scope(
        domain=ScopeDomain.AGENT, agent_id=persona.persona_id, persona_id=persona.persona_id
    )
    state_id = "agent.affect.missing:1:seeded"
    stack["state_backend"].save_state(
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


def seed_counter(stack: _Stack, *, evidence_id: str, key: str, value: str) -> None:
    """Admit one counter observation through the REAL factual plane."""
    scope = stack["scope"]
    evidence = Evidence(
        id=evidence_id,
        scope=scope,
        origin_runtime_id="runtime-1",
        source_type="typed_event",
        source_id=f"source-{evidence_id}",
        authority_level=AuthorityLevel.ASSERTED,
        authority=Authority(scope, AuthorityLevel.ASSERTED, f"source-{evidence_id}"),
        occurred_at=BASE,
        received_at=BASE,
        payload={"key": key, "value": value},
        sync=SyncFields(scope, "runtime-1", evidence_id, 1, f"idem-{evidence_id}"),
    )
    stack["fact_service"].admit(
        evidence,
        interaction_id=f"tick-facts-{evidence_id}",
        writing_runtime="runtime-1",
        writing_persona_id=None,
    )


def tick_situation_facts(stack: _Stack, *, now: datetime = BASE) -> dict[str, str]:
    situation = stack["ticker"]._tick_situation(
        scope=stack["scope"], interaction_id="cognitive-tick-cadence", now=now
    )
    return dict(situation.derived_facts)


# ── LR1: counter below threshold -> not eligible ────────────────────────────


def test_lr1_counter_below_threshold_not_eligible(tmp_path: Path) -> None:
    stack = make_stack(tmp_path, photo_cadence_threshold=3)
    seed_counter(stack, evidence_id="ev-cad", key=CADENCE_COUNTER, value="2")

    facts = tick_situation_facts(stack)

    assert facts[ELIGIBILITY_FACT] == "false"


# ── LR2: threshold reached -> eligible, never a forced media action ─────────


def test_lr2_threshold_reached_eligible_but_no_forced_media(tmp_path: Path) -> None:
    """Cadence eligibility changes nothing in intent generation: the same
    rules produce the same candidates below and at the threshold."""

    def run(sub: str, count: str) -> dict[str, object]:
        (tmp_path / sub).mkdir()
        stack = make_stack(tmp_path / sub, media_rule=True, photo_cadence_threshold=3)
        seed_counter(stack, evidence_id="ev-cad", key=CADENCE_COUNTER, value=count)
        seed_affect(stack)
        report = stack["ticker"].tick(scope=stack["scope"], now=BASE + timedelta(hours=2))
        facts = tick_situation_facts(stack)
        current = stack["intent_backend"].current(stack["scope"])
        return {
            "eligible": facts[ELIGIBILITY_FACT],
            "generated": report.intent_candidates_generated,
            "admitted": report.candidates_admitted,
            "kinds": sorted(intent.kind for intent in current),
        }

    below = run("below", "2")
    at = run("at", "3")
    assert below["eligible"] == "false"
    assert at["eligible"] == "true"
    # Eligibility is only a generation hint: identical candidates either way.
    assert at["generated"] == below["generated"]
    assert at["admitted"] == below["admitted"]
    assert at["kinds"] == below["kinds"]


# ── LR3: missing counter -> fail-closed false, no fabricated facts ──────────


def test_lr3_missing_counter_fails_closed_without_fabrication(tmp_path: Path) -> None:
    stack = make_stack(tmp_path, photo_cadence_threshold=3)

    facts = tick_situation_facts(stack)
    assert facts[ELIGIBILITY_FACT] == "false"
    # The derivation admitted no Evidence: the factual plane stays empty.
    assert list(stack["fact_service"].observations.all()) == []


def test_lr3_garbage_counter_value_fails_closed(tmp_path: Path) -> None:
    stack = make_stack(tmp_path, photo_cadence_threshold=3)
    seed_counter(stack, evidence_id="ev-cad", key=CADENCE_COUNTER, value="many")

    facts = tick_situation_facts(stack)

    assert facts[ELIGIBILITY_FACT] == "false"


# ── LR4: daily cap exhausted + cadence eligible -> ActionPolicy still blocks ─


def test_lr4_daily_cap_beats_cadence_eligibility(tmp_path: Path) -> None:
    stack = make_stack(tmp_path, media_rule=True, photo_cadence_threshold=3)
    seed_counter(stack, evidence_id="ev-cad", key=CADENCE_COUNTER, value="3")
    seed_counter(stack, evidence_id="ev-photo", key=DAILY_PHOTO_COUNTER, value="8")
    seed_affect(stack)

    report = stack["ticker"].tick(scope=stack["scope"], now=BASE + timedelta(hours=2))

    facts = tick_situation_facts(stack)
    assert facts[ELIGIBILITY_FACT] == "true"  # cadence says optional
    current = {
        intent.kind: intent.status for intent in stack["intent_backend"].current(stack["scope"])
    }
    # ActionPolicy media_limit remains the separate hard authority.
    assert current["share_photo"] is IntentStatus.DEFERRED
    assert current["reach_out"] is IntentStatus.ALLOWED
    assert report.policy_deferred == 1


# ── LR5: eligibility reaches the provider-facing generation context ─────────


def test_lr5_eligibility_reaches_generation_context(tmp_path: Path) -> None:
    stack = make_stack(tmp_path, with_expression=True, photo_cadence_threshold=3)
    seed_counter(stack, evidence_id="ev-cad", key=CADENCE_COUNTER, value="3")
    seed_affect(stack)

    report = stack["ticker"].tick(scope=stack["scope"], now=BASE + timedelta(hours=2))
    assert report.wake_signal is not None
    turn_result = _run_test_proactive_turn(stack, report.wake_signal)

    artifact = turn_result.proactive_expression
    assert artifact is not None
    assert artifact.disposition is ExpressionDisposition.ACCEPT
    assert "media.photo_frequency_eligible: true" in stack["agent"].calls[0].text


# ── LR6: raw counters never leak into the provider-facing context ────────────


def test_lr6_raw_counters_do_not_leak_to_provider(tmp_path: Path) -> None:
    stack = make_stack(tmp_path, with_expression=True, photo_cadence_threshold=3)
    seed_counter(stack, evidence_id="ev-cad", key=CADENCE_COUNTER, value="3")
    seed_counter(stack, evidence_id="ev-photo", key=DAILY_PHOTO_COUNTER, value="2")
    seed_affect(stack)

    report = stack["ticker"].tick(scope=stack["scope"], now=BASE + timedelta(hours=2))
    assert report.wake_signal is not None
    turn_result = _run_test_proactive_turn(stack, report.wake_signal)

    artifact = turn_result.proactive_expression
    assert artifact is not None
    text = stack["agent"].calls[0].text
    assert artifact.disposition is ExpressionDisposition.ACCEPT
    assert CADENCE_COUNTER not in text
    assert DAILY_PHOTO_COUNTER not in text


# ── LR7a/b/c: the algorithm is generic; the numbers are configuration ────────


def test_lr7a_generic_runtime_without_config_never_activates_cadence(
    tmp_path: Path,
) -> None:
    """No configured threshold -> feature disabled: even counter=999 does
    not activate one deployment's 1-per-3 rule (Kayla numbers are not
    kernel law)."""
    (tmp_path / "g").mkdir()
    stack = make_stack(tmp_path / "g", photo_cadence_threshold=None)
    seed_counter(stack, evidence_id="ev-cad", key=CADENCE_COUNTER, value="999")

    assert tick_situation_facts(stack)[ELIGIBILITY_FACT] == "false"


def test_lr7b_configured_threshold_three(tmp_path: Path) -> None:
    def run(sub: str, count: str) -> str:
        (tmp_path / sub).mkdir()
        stack = make_stack(tmp_path / sub, photo_cadence_threshold=3)
        seed_counter(stack, evidence_id=f"ev-{sub}", key=CADENCE_COUNTER, value=count)
        return tick_situation_facts(stack)[ELIGIBILITY_FACT]

    assert run("two", "2") == "false"
    assert run("three", "3") == "true"


def test_lr7c_configured_threshold_five(tmp_path: Path) -> None:
    def run(sub: str, count: str) -> str:
        (tmp_path / sub).mkdir()
        stack = make_stack(tmp_path / sub, photo_cadence_threshold=5)
        seed_counter(stack, evidence_id=f"ev-{sub}", key=CADENCE_COUNTER, value=count)
        return tick_situation_facts(stack)[ELIGIBILITY_FACT]

    assert run("three", "3") == "false"
    assert run("five", "5") == "true"


# ── LR8: C5C angle-guard behavior unchanged with the cadence fact present ────


def test_lr8_expression_guard_behavior_unchanged(tmp_path: Path) -> None:
    """The prefix-duplicate rewrite path still works with the cadence fact
    in the provider-facing config: entry-angle authority is untouched."""
    prior = PreviousExpression(
        expression_id="prior-cad",
        scope=Scope(domain=ScopeDomain.USER, user_id="user-a"),
        origin_runtime_id="runtime-1",
        action_type="proactive_message",
        text="今天下午想和你分享一段话",
        receipt_ref="receipt-prior-cad",
        delivery_status=DeliveryStatus.SENT,
        sent_at=BASE - timedelta(hours=20),
    )
    stack = make_stack(
        tmp_path,
        with_expression=True,
        agent_script=("今天下午想和你分享一首诗", "下午想把一首短诗读给你听"),
        prior=prior,
        photo_cadence_threshold=3,
    )
    seed_counter(stack, evidence_id="ev-cad", key=CADENCE_COUNTER, value="3")
    seed_affect(stack)

    report = stack["ticker"].tick(scope=stack["scope"], now=BASE + timedelta(hours=2))
    assert report.wake_signal is not None
    turn_result = _run_test_proactive_turn(stack, report.wake_signal)

    artifact = turn_result.proactive_expression
    assert artifact is not None
    # First draft collided with the prior opening -> REWRITE -> ACCEPT.
    assert artifact.disposition is ExpressionDisposition.ACCEPT
    assert artifact.would_send == "下午想把一首短诗读给你听"
    assert artifact.attempt_count == 2
    assert stack["agent"].call_count == 2


# ── config construction fail-closed ──────────────────────────────────────────


def _cfg_intent_rules() -> tuple[IntentRule, ...]:
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


def _cfg_action_policy() -> ActionPolicyConfig:
    return ActionPolicyConfig(
        rules=(
            IntentPolicyRule(
                intent_kind="reach_out",
                action_type="proactive_message",
                proactive=True,
                interrupts_active_conversation=False,
                media_counter_fact=None,
                media_limit=None,
                required_resource=None,
            ),
        ),
        proactive_cooldown=timedelta(minutes=30),
    )


def test_cadence_config_construction_fails_closed(tmp_path: Path) -> None:
    """Invalid thresholds and wrong config types are refused (fail-closed).

    bool is rejected even though isinstance(True, int) is True (C6B bug).
    """
    assert CognitiveTickConfig().photo_cadence_threshold is None
    for bad in (0, -1, 3.5, "3", True, False):
        with pytest.raises(ValueError, match="positive integer or None"):
            CognitiveTickConfig(photo_cadence_threshold=bad)  # type: ignore[arg-type]

    # RuntimeBehaviorConfig.to_cognitive_tick_config also forwards the same
    # contract -- a bad threshold must fail closed. Different message wording
    # ("null" vs "None"); accept either.
    from mind_runtime.runtime_config import ProactiveRuntimeConfig

    with pytest.raises(ValueError, match=r"positive integer or (None|null)"):
        ProactiveRuntimeConfig(photo_cadence_threshold=True)

    # CognitiveTicker constructor must reject non-CognitiveTickConfig inputs
    # at runtime (not just mypy). Build minimal infra.
    from mind_runtime.contracts import AffectiveDimensionProfile
    from mind_runtime.facts.persistence import SqliteFactBackend
    from mind_runtime.facts.service import FactIngestService
    from mind_runtime.intents.persistence import SqliteIntentBackend
    from mind_runtime.pipeline.orchestrator import TurnOrchestrator
    from mind_runtime.pipeline.trace import TraceRecorder

    persona_min = PersonaProfile(
        persona_id="synthetic-cfg-fail",
        dimensions=(
            AffectiveDimensionProfile(
                dimension="agent.affect.missing",
                baseline=0.9,
                initial_value=0.6,
                sensitivity=1.0,
                recovery_rate=0.02,
                ceiling=1.0,
                floor=0.0,
                growth_profile=(),
                coupling_profile=(),
            ),
        ),
    )
    clock = FakeClock(BASE)
    fact_backend = SqliteFactBackend(tmp_path / "f.sqlite")
    orch_min = TurnOrchestrator(
        clock=clock,
        trace=TraceRecorder(),
        runtime_id="runtime-1",
        fact_ingest=FactIngestService(clock=clock, backend=fact_backend),
        persona=persona_min,
        state_backend=SqliteStateBackend(tmp_path / "s.sqlite"),
    )
    with pytest.raises(ValueError, match="CognitiveTickConfig"):
        CognitiveTicker(
            orchestrator=orch_min,
            persona=persona_min,
            intent_engine=DeterministicIntentEngine(_cfg_intent_rules(), "runtime-1"),
            action_policy=DeterministicActionPolicy(_cfg_action_policy(), "runtime-1"),
            policy_resources=PolicyResources(("proactive_message",)),
            intent_lifecycle=IntentLifecycleService(SqliteIntentBackend(tmp_path / "i.sqlite")),
            runtime_id="runtime-1",
            config=42,  # type: ignore[arg-type]
        )
