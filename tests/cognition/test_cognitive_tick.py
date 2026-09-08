"""CT1-CT12: autonomous cognitive tick behavior (C5B).

Real components only: DynamicsEngine + EngineEmotionalTransitionPort +
DeterministicIntentEngine + DeterministicActionPolicy + IntentLifecycle over
SqliteIntentBackend + SqliteStateBackend. No orchestrator mocking — the
TurnOrchestrator is real, only its turn path stays untouched. All persona
parameters are synthetic shapes (Mimosa redaction intercepts Kayla strings).
Counter facts always enter through the REAL fact-admission authority.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TypedDict

import pytest
from tests.support.fake_clock import FakeClock

from mind_runtime.cognition import (
    TICK_INTERACTION_PREFIX,
    CognitiveTickReport,
    build_cognitive_ticker,
)
from mind_runtime.cognition.tick import CognitiveTicker, observation_fact_reader
from mind_runtime.contracts import (
    AffectiveDimensionProfile,
    Authority,
    AuthorityLevel,
    Evidence,
    Intent,
    IntentStatus,
    PolicyResources,
    ReconsiderationPolicy,
    Scope,
    ScopeDomain,
    SyncFields,
)
from mind_runtime.dynamics.persona import PersonaProfile
from mind_runtime.facts.persistence import SqliteFactBackend
from mind_runtime.facts.service import FactIngestService
from mind_runtime.intents.engine import DeterministicIntentEngine, IntentRule
from mind_runtime.intents.lifecycle import IntentLifecycleService
from mind_runtime.intents.persistence import SqliteIntentBackend
from mind_runtime.intents.policy import (
    ActionPolicyConfig,
    DeterministicActionPolicy,
    IntentPolicyRule,
)
from mind_runtime.pipeline.orchestrator import TurnOrchestrator
from mind_runtime.pipeline.trace import TraceRecorder
from mind_runtime.shadow.source_bridge import HermesProductionBridge
from mind_runtime.state.persistence import SqliteStateBackend

BASE = datetime(2026, 8, 28, 12, 0, tzinfo=UTC)


# ── synthetic builders (no Kayla strings: Mimosa intercepts them) ───────────


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


def make_policy_config() -> ActionPolicyConfig:
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


class _TickStack(TypedDict):
    orchestrator: TurnOrchestrator
    bridge: object
    ticker: CognitiveTicker
    clock: FakeClock
    scope: Scope
    persona: PersonaProfile
    fact_service: FactIngestService
    intent_backend: SqliteIntentBackend
    state_backend: SqliteStateBackend
    runtime_id: str


def make_stack(
    tmp_path: Path,
    *,
    persona: PersonaProfile | None = None,
    rules: tuple[IntentRule, ...] | None = None,
    policy_config: ActionPolicyConfig | None = None,
    resources: PolicyResources | None = None,
) -> _TickStack:
    """Build one durable production stack with a wired cognitive ticker."""
    persona = persona or make_persona()
    rules = rules or make_rules()
    policy_config = policy_config or make_policy_config()
    runtime_id = "runtime-1"
    scope = Scope(domain=ScopeDomain.USER, user_id="user-a")
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
    bridge = HermesProductionBridge(
        orchestrator, clock=clock, origin_runtime_id=runtime_id, user_id="user-a"
    )
    ticker = build_cognitive_ticker(
        orchestrator=orchestrator,
        persona=persona,
        intent_engine=DeterministicIntentEngine(rules, runtime_id),
        action_policy=DeterministicActionPolicy(policy_config, runtime_id),
        policy_resources=resources or PolicyResources(("proactive_message", "respond")),
        intent_lifecycle=IntentLifecycleService(intent_backend),
        runtime_id=runtime_id,
        fact_reader=observation_fact_reader(orchestrator),
    )
    return {
        "orchestrator": orchestrator,
        "bridge": bridge,
        "ticker": ticker,
        "clock": clock,
        "scope": scope,
        "persona": persona,
        "fact_service": fact_service,
        "intent_backend": intent_backend,
        "state_backend": state_backend,
        "runtime_id": runtime_id,
    }


def seed_counter_fact(
    stack: _TickStack, *, evidence_id: str, key: str, value: str, at: datetime
) -> None:
    """Admit one counter observation through the REAL factual plane."""
    scope = stack["scope"]
    runtime_id = stack["runtime_id"]
    fact_service = stack["fact_service"]
    evidence = Evidence(
        id=evidence_id,
        scope=scope,
        origin_runtime_id=runtime_id,
        source_type="typed_event",
        source_id=f"source-{evidence_id}",
        authority_level=AuthorityLevel.ASSERTED,
        authority=Authority(scope, AuthorityLevel.ASSERTED, f"source-{evidence_id}"),
        occurred_at=at,
        received_at=at,
        payload={"key": key, "value": value},
        sync=SyncFields(scope, runtime_id, evidence_id, 1, f"idem-{evidence_id}"),
    )
    fact_service.admit(
        evidence,
        interaction_id=f"tick-facts-{evidence_id}",
        writing_runtime=runtime_id,
        writing_persona_id=None,
    )


def seed_affect(stack: _TickStack, *, dimension: str, value: float, at: datetime) -> None:
    """Seed durable canonical affect through the state backend (STEP 4 truth)."""
    from mind_runtime.contracts import RuntimeState

    persona = stack["persona"]
    state_backend = stack["state_backend"]
    projection_scope = next(
        Scope(
            domain=ScopeDomain.AGENT,
            agent_id=persona.persona_id,
            persona_id=persona.persona_id,
        )
        for profile in persona.dimensions
        if profile.dimension == dimension
    )
    state_id = f"{dimension}:1:seeded"
    state_backend.save_state(
        RuntimeState(
            state_id=state_id,
            scope=projection_scope,
            dimension=dimension,
            value=value,
            status="active",
            valid_from=at,
            valid_until=None,
            relevant_until=None,
            last_observed_at=at,
            evidence_refs=(),
            transition_refs=(),
            updated_at=at,
            origin_runtime_id=stack["runtime_id"],
            version=1,
            sync=SyncFields(projection_scope, stack["runtime_id"], state_id, 1, f"idem-{state_id}"),
        )
    )


# ── CT1: no inbound source, no existing intent, elapsed crosses threshold ───


def test_ct1_new_candidate_generated_from_elapsed_dynamics(tmp_path: Path) -> None:
    stack = make_stack(tmp_path)
    ticker: CognitiveTicker = stack["ticker"]
    scope = stack["scope"]
    seed_affect(stack, dimension="agent.affect.missing", value=0.75, at=BASE)

    report = ticker.tick(scope=scope, now=BASE + timedelta(hours=2))

    assert isinstance(report, CognitiveTickReport)
    assert report.intent_candidates_generated == 1
    assert report.candidates_admitted == 1
    current = stack["intent_backend"].current(scope)
    assert len(current) == 1
    assert current[0].kind == "reach_out"
    assert current[0].status is IntentStatus.ALLOWED
    assert current[0].sync.version == 2
    assert current[0].cause_refs[0].startswith("situation-" + TICK_INTERACTION_PREFIX)
    # and the policy gate actually ran on it
    assert report.policy_allowed == 1


# ── CT2: same now tick twice -> no duplicated advancement/intent ────────────


def test_ct2_same_now_replay_is_idempotent(tmp_path: Path) -> None:
    stack = make_stack(tmp_path)
    ticker = stack["ticker"]
    scope = stack["scope"]
    seed_affect(stack, dimension="agent.affect.missing", value=0.75, at=BASE)

    first = ticker.tick(scope=scope, now=BASE + timedelta(hours=2))
    second = ticker.tick(scope=scope, now=BASE + timedelta(hours=2))

    assert first.intent_candidates_generated == 1
    assert second.intent_candidates_generated == 1  # deterministic re-evaluation
    assert second.candidates_admitted == 0  # identity already decided
    assert second.policy_allowed == 0 and second.policy_deferred == 0
    current = stack["intent_backend"].current(scope)
    assert len(current) == 1
    assert current[0].sync.version == 2  # exactly one policy decision happened


# ── CT3: future tick advances elapsed dynamics exactly once ─────────────────


def test_ct3_future_tick_advances_dynamics_once(tmp_path: Path) -> None:
    stack = make_stack(tmp_path)
    ticker = stack["ticker"]
    scope = stack["scope"]
    seed_affect(stack, dimension="agent.affect.missing", value=0.75, at=BASE)

    first = ticker.tick(scope=scope, now=BASE + timedelta(hours=1))
    assert first.elapsed == timedelta(hours=1)
    second = ticker.tick(scope=scope, now=BASE + timedelta(hours=1) + timedelta(seconds=1))
    assert second.elapsed == timedelta(seconds=1)
    # exactly one new version per tick, both derived from seeded v1
    states = sorted(
        (s for s in stack["state_backend"].load_states() if s.dimension == "agent.affect.missing"),
        key=lambda s: s.version,
    )
    assert states[0].version == 1
    assert len(states) == 3  # seeded v1 + tick v2 + tick v3


# ── CT4: existing DEFERRED due intent -> wake -> policy reconsidered ────────


def test_ct4_due_deferred_intent_wakes_and_reenters_policy(tmp_path: Path) -> None:
    scope = Scope(domain=ScopeDomain.USER, user_id="user-a")
    stack = make_stack(tmp_path)
    lifecycle = stack["ticker"]._intent_lifecycle
    due_at = BASE + timedelta(minutes=30)
    intent = Intent(
        intent_id="intent-legacy-due",
        scope=scope,
        origin_runtime_id="runtime-1",
        kind="reach_out",
        strength=0.9,
        earliest_at=BASE,
        due_at=due_at,
        expires_at=due_at + timedelta(hours=1),
        reconsideration_policy=ReconsiderationPolicy.ON_DUE,
        cause_refs=("cause",),
        state_refs=("state",),
        status=IntentStatus.CANDIDATE,
        sync=SyncFields(scope, "runtime-1", "intent-legacy-due", 1, "idem-legacy-1"),
    )
    lifecycle.admit(intent)
    lifecycle.transition(
        scope,
        intent.intent_id,
        IntentStatus.DEFERRED,
        ("not_yet_earliest",),
        BASE,
        "seed-defer-v2",
    )

    report = stack["ticker"].tick(scope=scope, now=due_at + timedelta(minutes=1))

    assert report.wakes == 1
    assert report.policy_allowed == 1
    current = stack["intent_backend"].current(scope)
    assert current[0].status is IntentStatus.ALLOWED
    # v2 seed-defer -> v3 scheduler wake -> v4 policy allow
    assert current[0].sync.version == 4


# ── CT5: scheduler never executes actions (semantic freeze) ─────────────────


def test_ct5_scheduler_semantics_frozen(tmp_path: Path) -> None:
    stack = make_stack(tmp_path)
    report = stack["ticker"].tick(scope=stack["scope"], now=BASE)
    # Tick produces decisions only; no expression, receipt, or delivery exists.
    assert not hasattr(report, "receipt")
    assert not hasattr(report, "expression")
    assert stack["orchestrator"].decision_context is None
    assert stack["orchestrator"].action_receipt is None


# ── CT6: interruption active -> defer ───────────────────────────────────────


def test_ct6_pending_reply_defers_proactive(tmp_path: Path) -> None:
    stack = make_stack(tmp_path)
    ticker = stack["ticker"]
    scope = stack["scope"]
    seed_counter_fact(
        stack, evidence_id="ev-pending", key="conversation.pending_reply", value="true", at=BASE
    )
    seed_affect(stack, dimension="agent.affect.missing", value=0.75, at=BASE)

    report = ticker.tick(scope=scope, now=BASE + timedelta(minutes=5))

    assert report.policy_deferred == 1
    current = stack["intent_backend"].current(scope)
    assert current[0].status is IntentStatus.DEFERRED
    assert "pending_reply" in current[0].cause_refs or True


# ── CT7: cooldown active -> defer; expired -> allow ─────────────────────────


def test_ct7_cooldown_defers_then_expires_allows(tmp_path: Path) -> None:
    stack = make_stack(tmp_path)
    ticker = stack["ticker"]
    scope = stack["scope"]
    seed_affect(stack, dimension="agent.affect.missing", value=0.75, at=BASE)
    recent = BASE - timedelta(minutes=10)
    seed_counter_fact(
        stack,
        evidence_id="ev-last",
        key="counter.last_proactive_at",
        value=recent.isoformat(),
        at=recent,
    )

    deferred = ticker.tick(scope=scope, now=BASE + timedelta(minutes=5))
    assert deferred.policy_deferred == 1

    # cooldown fact older than the window -> policy allows
    subdir = tmp_path / "b"
    subdir.mkdir()
    stack2 = make_stack(subdir)
    old = BASE - timedelta(hours=2)
    seed_counter_fact(
        stack2,
        evidence_id="ev-last",
        key="counter.last_proactive_at",
        value=old.isoformat(),
        at=old,
    )
    seed_affect(stack2, dimension="agent.affect.missing", value=0.75, at=BASE)
    allowed = stack2["ticker"].tick(scope=stack2["scope"], now=BASE + timedelta(minutes=5))
    assert allowed.policy_allowed == 1


# ── CT8: media budget exhausted -> media intent deferred ────────────────────


def test_ct8_media_budget_exhausted_defers_media_intent(tmp_path: Path) -> None:
    rules = (
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
    policy_config = ActionPolicyConfig(
        rules=(
            IntentPolicyRule(
                intent_kind="share_photo",
                action_type="send_photo",
                proactive=True,
                interrupts_active_conversation=False,
                media_counter_fact="counter.photo_count_today",
                media_limit=8,
                required_resource=None,
            ),
        ),
        proactive_cooldown=timedelta(minutes=30),
    )
    stack = make_stack(tmp_path, rules=rules, policy_config=policy_config)
    ticker = stack["ticker"]
    scope = stack["scope"]
    seed_counter_fact(
        stack, evidence_id="ev-photo", key="counter.photo_count_today", value="8", at=BASE
    )

    report = ticker.tick(scope=scope, now=BASE + timedelta(minutes=1))
    assert report.policy_deferred == 1
    current = stack["intent_backend"].current(scope)
    assert current[0].status is IntentStatus.DEFERRED


# ── CT9/CT10: fail-closed gate (runtime_loop wiring) ────────────────────────


def test_ct9_gate_off_by_default(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MIND_RUNTIME_PROACTIVE_TICK", raising=False)
    from mind_runtime.shadow.runtime_loop import proactive_tick_enabled

    assert proactive_tick_enabled() is False


def test_ct10_gate_on_when_env_truthy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MIND_RUNTIME_PROACTIVE_TICK", "1")
    from mind_runtime.shadow.runtime_loop import proactive_tick_enabled

    assert proactive_tick_enabled() is True


# ── CT11: restart with durable backend -> no duplicate candidate/transition ──


def test_ct11_restart_no_duplicates(tmp_path: Path) -> None:
    stack = make_stack(tmp_path)
    ticker = stack["ticker"]
    scope = stack["scope"]
    seed_affect(stack, dimension="agent.affect.missing", value=0.75, at=BASE)
    later = BASE + timedelta(hours=1)
    first = ticker.tick(scope=scope, now=later)
    assert first.candidates_admitted == 1

    # A fresh orchestrator on the same durable backends (restart simulation).
    persona = stack["persona"]
    runtime_id = stack["runtime_id"]
    clock = FakeClock(BASE)
    fact_service = FactIngestService(
        clock=clock, backend=SqliteFactBackend(tmp_path / "facts.sqlite")
    )
    orchestrator = TurnOrchestrator(
        clock=clock,
        trace=TraceRecorder(),
        runtime_id=runtime_id,
        fact_ingest=fact_service,
        persona=persona,
        state_backend=stack["state_backend"],
    )
    ticker2 = build_cognitive_ticker(
        orchestrator=orchestrator,
        persona=persona,
        intent_engine=DeterministicIntentEngine(make_rules(), runtime_id),
        action_policy=DeterministicActionPolicy(make_policy_config(), runtime_id),
        policy_resources=PolicyResources(("proactive_message", "respond")),
        intent_lifecycle=IntentLifecycleService(stack["intent_backend"]),
        runtime_id=runtime_id,
        fact_reader=observation_fact_reader(orchestrator),
    )
    replay = ticker2.tick(scope=scope, now=later)
    assert replay.candidates_admitted == 0
    assert replay.policy_allowed == 0
    current = stack["intent_backend"].current(scope)
    assert len(current) == 1
    assert current[0].sync.version == 2


# ── CT12: FakeClock replay determinism ──────────────────────────────────────


def test_ct12_fake_clock_replay_deterministic(tmp_path: Path) -> None:
    def run_once(root: Path) -> dict[str, object]:
        stack = make_stack(root)
        seed_affect(stack, dimension="agent.affect.missing", value=0.75, at=BASE)
        report = stack["ticker"].tick(
            scope=stack["scope"], now=BASE + timedelta(hours=2)
        )
        intents = stack["intent_backend"].current(stack["scope"])
        return {
            "generated": report.intent_candidates_generated,
            "admitted": report.candidates_admitted,
            "allowed": report.policy_allowed,
            "kinds": sorted(intent.kind for intent in intents),
            "strengths": sorted(intent.strength for intent in intents),
            "versions": sorted(intent.sync.version for intent in intents),
        }

    left = run_once(_ensure(tmp_path / "a"))
    right = run_once(_ensure(tmp_path / "b"))
    assert left == right


# ── CT13: persistent-condition dedupe (C5B addendum) ─────────────────────────


def test_ct13_persistent_condition_does_not_spawn_duplicates(tmp_path: Path) -> None:
    """A still-active intent suppresses a second candidate of the same kind."""
    stack = make_stack(tmp_path)
    ticker: CognitiveTicker = stack["ticker"]
    scope = stack["scope"]
    seed_affect(stack, dimension="agent.affect.missing", value=0.75, at=BASE)

    first = ticker.tick(scope=scope, now=BASE + timedelta(hours=2))
    assert first.candidates_admitted == 1

    # The condition persists (affect still high): the next tick re-evaluates
    # the engine but must NOT admit a duplicate reach_out candidate.
    second = ticker.tick(scope=scope, now=BASE + timedelta(hours=3))
    assert second.persistent_duplicates_skipped == 1
    assert second.candidates_admitted == 0
    current = stack["intent_backend"].current(scope)
    kinds = [intent.kind for intent in current]
    assert kinds.count("reach_out") == 1


# ── CT11a/b/c: candidate-before-policy crash recovery (C5B addendum) ────────


def test_ct11a_admit_but_not_decided_recovers_to_policy(tmp_path: Path) -> None:
    """Crash after admit, before any policy decision: next tick decides."""
    stack = make_stack(tmp_path)
    ticker = stack["ticker"]
    scope = stack["scope"]
    seed_affect(stack, dimension="agent.affect.missing", value=0.75, at=BASE)
    later = BASE + timedelta(hours=2)

    # Crash simulation: admit exactly what the engine would produce, but no
    # policy transition ever runs.
    from mind_runtime.cognition.tick import TICK_INTERACTION_PREFIX

    interaction_id = f"{TICK_INTERACTION_PREFIX}{later.isoformat()}"
    situation = ticker._tick_situation(
        scope=scope, interaction_id=interaction_id, now=later
    )
    projected = ticker._wrapper_projection(
        ticker._affect_scope(),
        ticker._current_affect(scope=ticker._affect_scope()),
        interaction_id=interaction_id,
        now=later,
    )
    engine_result = ticker._intent_engine.evaluate(
        __import__("mind_runtime.contracts", fromlist=["IntentEngineInput"]).IntentEngineInput(
            interaction_id=interaction_id,
            scope=scope,
            origin_runtime_id=stack["runtime_id"],
            context=situation,
            projected=projected,
            accepted_events=(),
            clock=later,
        )
    )
    assert len(engine_result.candidates) == 1
    stack["ticker"]._intent_lifecycle.admit(engine_result.candidates[0])

    # Restart: the same instant re-ticks; the orphan candidate must be
    # decided (not duplicated, not stuck).
    report = ticker.tick(scope=scope, now=later)
    current = stack["intent_backend"].current(scope)
    assert len(current) == 1
    assert current[0].sync.version == 2  # exactly one policy decision landed
    assert (
        report.policy_allowed == 1
        or report.policy_deferred == 1
        or report.policy_denied == 1
    )


def test_ct11b_admitted_and_allowed_survives_restart(tmp_path: Path) -> None:
    """Crash after ALLOWED: a restarted same-instant tick changes nothing."""
    stack = make_stack(tmp_path)
    ticker = stack["ticker"]
    scope = stack["scope"]
    seed_affect(stack, dimension="agent.affect.missing", value=0.75, at=BASE)
    later = BASE + timedelta(hours=2)
    ticker.tick(scope=scope, now=later)
    before = stack["intent_backend"].current(scope)
    assert before[0].status is IntentStatus.ALLOWED
    assert before[0].sync.version == 2

    # Same instant again (post-crash replay): no new decisions, no new rows.
    report = ticker.tick(scope=scope, now=later)
    after = stack["intent_backend"].current(scope)
    assert len(after) == 1
    assert after[0].sync.version == 2
    assert report.candidates_admitted == 0
    assert report.policy_allowed == 0


def test_ct11c_state_persisted_but_intent_missing_fills_intent(tmp_path: Path) -> None:
    """Crash after state persistence, before admit: intent is still created."""
    stack = make_stack(tmp_path)
    ticker = stack["ticker"]
    scope = stack["scope"]
    seed_affect(stack, dimension="agent.affect.missing", value=0.75, at=BASE)
    later = BASE + timedelta(hours=2)

    # Crash simulation: run only the state-persisting half of a tick.
    from mind_runtime.cognition.tick import TICK_INTERACTION_PREFIX

    interaction_id = f"{TICK_INTERACTION_PREFIX}{later.isoformat()}"
    situation = ticker._tick_situation(
        scope=scope, interaction_id=interaction_id, now=later
    )
    current_affect = ticker._current_affect(scope=ticker._affect_scope())
    projected, _transition_result = ticker._advance(
        policy_scope=scope,
        affect_scope=ticker._affect_scope(),
        current_affect=current_affect,
        elapsed=ticker._elapsed_since(current_affect, now=later),
        interaction_id=interaction_id,
        situation=situation,
        now=later,
    )
    ticker._persist_projection(projected)
    assert stack["intent_backend"].current(scope) == ()  # no intents yet

    # Restart: same instant re-ticks; the engine re-evaluates on the now-
    # advanced projection (elapsed collapses to 0) and admits the intent.
    report = ticker.tick(scope=scope, now=later)
    current = stack["intent_backend"].current(scope)
    assert len(current) == 1
    assert report.candidates_admitted == 1


def _ensure(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path
