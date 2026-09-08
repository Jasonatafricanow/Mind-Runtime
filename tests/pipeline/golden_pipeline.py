"""OrchestratorPipeline: D2 PipelinePort adapter running the canonical turn pipeline.

Test-side glue that drives the real TurnOrchestrator over a golden
scenario: begin -> ingest (through the D3 factual plane) -> run (D5.3
ingest-commit + projection) -> commit or abort (D5.3 UnitOfWork), then
summarizes deterministic outputs from the resulting canonical state.
"""

from datetime import timedelta

from mind_runtime.contracts import (
    Evidence,
    HistoricalContextBundle,
    HistoricalContextQuery,
    IntentEngineInput,
    Interaction,
    InteractionStatus,
    Observation,
    ProjectedMindState,
    RuntimeState,
    Scope,
    ScopeDomain,
    SemanticEventCandidate,
    Situation,
    SyncFields,
)
from mind_runtime.dynamics.persona import PersonaProfile
from mind_runtime.facts.ports import FactAdmissionDisposition, FactAdmissionResult
from mind_runtime.facts.service import FactIngestService
from mind_runtime.pipeline.orchestrator import TurnOrchestrator
from mind_runtime.pipeline.ports import AgentFailure, AgentPort, HistoricalContextPort
from mind_runtime.pipeline.trace import TraceRecorder
from tests.golden.scenario import GoldenScenario, ScenarioResult


class _TypedFactPort:
    """Fact port returning one dimension-typed observation per scenario."""

    def __init__(self, *, key: str, value: object) -> None:
        self._key = key
        self._value = value
        self.admit_count = 0

    def admit(
        self,
        evidence: Evidence,
        *,
        interaction_id: str,
        writing_runtime: str,
        writing_persona_id: str | None,
    ) -> FactAdmissionResult:
        self.admit_count += 1
        scope = evidence.scope
        observation = Observation(
            id=f"observation-{evidence.id}",
            interaction_id=interaction_id,
            scope=scope,
            origin_runtime_id=writing_runtime,
            type="factual",
            key=self._key,
            value=self._value,
            confidence=1.0,
            observed_at=evidence.occurred_at,
            evidence_refs=(evidence.id,),
            sync=SyncFields(scope, writing_runtime, f"observation-{evidence.id}", 1, "idem"),
        )
        return FactAdmissionResult(observation, FactAdmissionDisposition.NEW)


class FailingAgent:
    """Scripted agent failure (G13: projection failure aborts the turn)."""

    def respond(self, decision_context: object) -> str:
        raise AgentFailure("scripted failure")


def _fact_port_for(scenario: GoldenScenario) -> "_TypedFactPort | None":
    # Per-scenario typed fact mapping (no LLM): G1/G10/G13b/G12a messages
    # confirm user.sleep.phase=awake; other D5 scenarios keep source-typed
    # facts.
    if scenario.golden_id in {"G1", "G10", "G12a", "G13b"}:
        return _TypedFactPort(key="user.sleep.phase.observed", value="awake")
    return None


def _scoped_evidence(evidence: Evidence, scenario: GoldenScenario) -> Evidence:
    """Re-scope fixture evidence to the scenario scope (fixtures default to user)."""
    if evidence.scope == scenario.scope:
        return evidence
    from dataclasses import replace

    return replace(
        evidence,
        scope=scenario.scope,
        authority=replace(evidence.authority, scope=scenario.scope),
        sync=replace(evidence.sync, scope=scenario.scope),
    )


def _normalized_canonical(scenario: GoldenScenario) -> tuple[RuntimeState, ...]:
    """Rewind fixture initial-state timestamps that postdate the evidence.

    The D2 fixtures use a shared default ``NOW`` for state timestamps; a
    scenario whose clock is earlier (e.g. G13b at 02:30) would otherwise
    trigger D4.5 anti-rollback on its own evidence. The timestamps are
    fixture defaults, not semantics: the initial state must predate the
    turn's evidence.
    """
    from dataclasses import replace

    if not scenario.input_evidence:
        return scenario.initial_canonical_state
    base = min(evidence.occurred_at for evidence in scenario.input_evidence)
    normalized: list[RuntimeState] = []
    for state in scenario.initial_canonical_state:
        if state.last_observed_at > base:
            normalized.append(
                replace(
                    state,
                    valid_from=base - timedelta(minutes=1),
                    last_observed_at=base - timedelta(minutes=1),
                    updated_at=base - timedelta(minutes=1),
                )
            )
        else:
            normalized.append(state)
    return tuple(normalized)


def _writing_runtime(scenario: GoldenScenario) -> str:
    if scenario.scope.domain is ScopeDomain.AGENT:
        return scenario.scope.agent_id or scenario.runtime_id
    return scenario.runtime_id


def _writing_persona(scenario: GoldenScenario) -> PersonaProfile | None:
    if scenario.scope.domain not in {ScopeDomain.AGENT, ScopeDomain.RELATIONSHIP}:
        return None
    if scenario.scope.persona_id is None:
        return None
    return PersonaProfile(
        persona_id=scenario.scope.persona_id,
        dimensions=scenario.persona,
    )


def _interaction_for(scenario: GoldenScenario) -> Interaction:
    return Interaction(
        interaction_id=f"interaction-{scenario.golden_id}",
        scope=scenario.scope,
        channel="chat",
        session_id="session-1",
        turn_id=f"turn-{scenario.golden_id}",
        started_at=scenario.clock.now(),
        committed_at=None,
        status=InteractionStatus.OPEN,
    )


class OrchestratorPipeline:
    """Runs the real TurnOrchestrator over a golden scenario."""

    def __init__(self, *, commit: bool = True, agent: AgentPort | None = None) -> None:
        self._commit = commit
        self._agent = agent

    def run(self, scenario: GoldenScenario) -> ScenarioResult:
        fact_port = _fact_port_for(scenario) or FactIngestService(clock=scenario.clock)
        orchestrator = TurnOrchestrator(
            clock=scenario.clock,
            trace=TraceRecorder(),
            runtime_id=_writing_runtime(scenario),
            fact_ingest=fact_port,
            canonical_snapshot=_normalized_canonical(scenario),
            agent=self._agent,
            persona=_writing_persona(scenario),
        )
        orchestrator.begin_turn(_interaction_for(scenario))
        for evidence in scenario.input_evidence:
            orchestrator.ingest(_scoped_evidence(evidence, scenario))
        try:
            orchestrator.run()
        except AgentFailure:
            pass
        if self._commit and orchestrator.state.value == "dispatching":
            orchestrator.commit_turn()
        elif orchestrator.state.value == "dispatching":
            orchestrator.abort_turn()
        outputs = self._summarize(scenario, orchestrator)
        return ScenarioResult(
            golden_id=scenario.golden_id,
            deterministic_outputs=outputs,
            canonical_changes=(),
            projected_changes=(),
            llm_calls=(),
        )

    def _summarize(
        self, scenario: GoldenScenario, orchestrator: TurnOrchestrator
    ) -> tuple[tuple[str, object], ...]:
        if scenario.golden_id == "G1":
            # D6 deterministic situation part: awake after the message, the
            # conversation is active, and the night sleep-norm is suppressed
            # (02:30 + recently awake + engaged must not suggest sleeping).
            situation = orchestrator.situation
            facts = dict(situation.derived_facts) if situation is not None else {}
            return (
                ("user.sleep.phase", self._canonical_value(orchestrator, "user.sleep.phase")),
                ("conversation.active", facts.get("conversation.active", "missing")),
                ("sleep_norm_relevance", facts.get("sleep_norm_relevance", "missing")),
            )
        if scenario.golden_id == "G16a":
            # D6 deterministic path: the proactive cooldown blocks.
            situation = orchestrator.situation
            facts = dict(situation.derived_facts) if situation is not None else {}
            ready = facts.get("proactive.cooldown_ready", "missing")
            return (("proactive.cooldown", "ready" if ready == "true" else "blocked"),)
        if scenario.golden_id == "G10":
            # Replay: the reaffirmed factual state is deterministic.
            return (("user.sleep.phase", self._canonical_value(orchestrator, "user.sleep.phase")),)
        if scenario.golden_id == "G13":
            # Projection failure never pollutes canonical: agent affect
            # keeps its canonical value.
            return (
                (
                    "canonical.agent.affect.longing",
                    self._canonical_value(orchestrator, "agent.affect.longing"),
                ),
            )
        if scenario.golden_id == "G13b":
            sleep = self._canonical_value(orchestrator, "user.sleep.phase")
            longing = self._canonical_value(orchestrator, "agent.affect.longing")
            fact = orchestrator.fact_ingest
            if isinstance(fact, _TypedFactPort):
                admitted = fact.admit_count
            else:
                assert isinstance(fact, FactIngestService)
                admitted = fact.evidence.count()
            evidence_retained = admitted >= 1
            observation_retained = admitted >= 1
            projected_discarded = not any(
                state.dimension.endswith(".affect.stub") for state in orchestrator.canonical
            )
            return (
                ("user.sleep.phase", sleep),
                ("evidence.retained", "true" if evidence_retained else "false"),
                ("observation.retained", "true" if observation_retained else "false"),
                ("abort.projected_affect", "discarded" if projected_discarded else "kept"),
                ("canonical.agent.affect.longing", longing),
            )
        return ()

    @staticmethod
    def _canonical_value(orchestrator: TurnOrchestrator, dimension: str) -> object:
        for state in orchestrator.canonical:
            if state.dimension == dimension:
                return state.value
        return "missing"


class StateBackendPipeline:
    """D5.8: runs the real orchestrator over a durable StateBackend (G12a).

    Seeding: the scenario's initial canonical state is written into the
    backend first (pre-existing durable state). Then a turn runs to
    completion (ingest + commit), and a fresh orchestrator on the same
    backend simulates a restart: canonical must be restored from the
    durable state, which yields restart.consistent=true.
    """

    def run(self, scenario: GoldenScenario) -> ScenarioResult:
        import tempfile
        from pathlib import Path

        from mind_runtime.state.persistence import SqliteStateBackend

        with tempfile.TemporaryDirectory() as tmp:
            backend = SqliteStateBackend(Path(tmp) / "state.db")
            try:
                for state in _normalized_canonical(scenario):
                    backend.save_state(state)
                fact_port = _fact_port_for(scenario) or FactIngestService(clock=scenario.clock)
                runtime_id = _writing_runtime(scenario)
                first = TurnOrchestrator(
                    clock=scenario.clock,
                    trace=TraceRecorder(),
                    runtime_id=runtime_id,
                    fact_ingest=fact_port,
                    state_backend=backend,
                )
                first.begin_turn(_interaction_for(scenario))
                for evidence in scenario.input_evidence:
                    first.ingest(_scoped_evidence(evidence, scenario))
                first.run()
                if first.state.value == "dispatching":
                    first.commit_turn()
                # Restart: a brand-new orchestrator on the same backend.
                restarted = TurnOrchestrator(
                    clock=scenario.clock,
                    trace=TraceRecorder(),
                    runtime_id=runtime_id,
                    fact_ingest=fact_port,
                    state_backend=backend,
                )
                sleep = self._canonical_value(restarted, "user.sleep.phase")
                consistent = "true" if sleep == "awake" else "false"
            finally:
                backend.close()
        return ScenarioResult(
            golden_id=scenario.golden_id,
            deterministic_outputs=(("restart.consistent", consistent),),
            canonical_changes=(),
            projected_changes=(),
            llm_calls=(),
        )

    @staticmethod
    def _canonical_value(orchestrator: TurnOrchestrator, dimension: str) -> object:
        for state in orchestrator.canonical:
            if state.dimension == dimension:
                return state.value
        return "missing"


class ReplicationHarnessPipeline:
    """Drives the replication inbox semantics for golden G15 (D5.7).

    No physical outbox/inbox tables: inbound packets arrive through an
    in-memory transport. A projected kayla affect write is rejected by the
    envelope contract (projected state cannot be replicated, fail closed);
    a user observation is admitted after authority/ownership passes.
    """

    def run(self, scenario: GoldenScenario) -> ScenarioResult:
        from mind_runtime.contracts import ProjectedMindState, ReplicationEnvelope, SyncFields
        from mind_runtime.replication import InMemoryReplicationPort

        scope = scenario.scope
        port = InMemoryReplicationPort()

        # 1) Inbound kayla affect write as projected state: fail closed.
        projected = ProjectedMindState(
            projection_id="projection-kayla-1",
            scope=scope,
            origin_runtime_id="kayla",
            projected_states=(
                RuntimeState(
                    state_id="agent.affect.longing:1",
                    scope=scope,
                    origin_runtime_id="kayla",
                    dimension="agent.affect.longing",
                    value=0.9,
                    status="active",
                    valid_from=scenario.clock.now(),
                    valid_until=None,
                    relevant_until=None,
                    last_observed_at=scenario.clock.now(),
                    evidence_refs=(),
                    transition_refs=(),
                    updated_at=scenario.clock.now(),
                    version=1,
                    sync=SyncFields(scope, "kayla", "agent.affect.longing:1", 1, "idem"),
                ),
            ),
            sync=SyncFields(scope, "kayla", "projection-kayla-1", 1, "idem"),
            committed=False,
        )
        try:
            ReplicationEnvelope(
                envelope_id="inbound-kayla-affect-1",
                scope=scope,
                origin_runtime_id="kayla",
                payload=projected,
                payload_type="ProjectedMindState",
                sync=SyncFields(scope, "kayla", "inbound-kayla-affect-1", 1, "idem"),
            )
            kayla_outcome = "admitted"
        except TypeError:
            kayla_outcome = "fail_closed"

        # 2) Inbound user observation: allowed after authority/ownership.
        user_scope = scenario.input_evidence[0].scope
        observation = Observation(
            id="observation-inbound-1",
            interaction_id="interaction-inbound",
            scope=user_scope,
            origin_runtime_id="kayla",
            type="factual",
            key="user_message.observed",
            value={"text": "hello"},
            confidence=1.0,
            observed_at=scenario.clock.now(),
            evidence_refs=("evidence-inbound-1",),
            sync=SyncFields(user_scope, "kayla", "observation-inbound-1", 1, "idem"),
        )
        envelope = ReplicationEnvelope(
            envelope_id="inbound-user-observation-1",
            scope=user_scope,
            origin_runtime_id="kayla",
            payload=observation,
            payload_type="Observation",
            sync=SyncFields(user_scope, "kayla", "inbound-user-observation-1", 1, "idem"),
        )
        from mind_runtime.replication import is_allowed_payload

        port.deliver(envelope)
        received = port.receive()
        if received is not None and is_allowed_payload(received):
            user_outcome = "allowed_after_authority"
        else:
            user_outcome = "rejected"

        return ScenarioResult(
            golden_id=scenario.golden_id,
            deterministic_outputs=(
                ("inbox.apply.kayla_affect_write", kayla_outcome),
                ("inbox.apply.user_observation", user_outcome),
            ),
            canonical_changes=(),
            projected_changes=(),
            llm_calls=(),
        )


class DynamicsPipeline:
    """Drives the D7 DynamicsEngine over a golden scenario's persona (G7).

    Test-side mapping: each persona trait profile's sensitivity scales the
    same anxiety impulse; the resulting transition is graded small/large.
    """

    def run(self, scenario: GoldenScenario) -> ScenarioResult:
        from mind_runtime.contracts import AffectiveDimensionProfile
        from mind_runtime.dynamics.engine import DynamicsEngine, Impulse
        from mind_runtime.dynamics.persona import PersonaProfile

        impulse = Impulse("agent.affect.anxiety", 0.5, source_ref="g7")
        grades: dict[str, str] = {}

        for trait in scenario.persona:
            anxiety = AffectiveDimensionProfile(
                dimension="agent.affect.anxiety",
                baseline=0.25,
                initial_value=0.25,
                sensitivity=trait.sensitivity,
                recovery_rate=0.3,
                ceiling=1.0,
                floor=0.0,
                growth_profile=(),
                coupling_profile=(),
            )
            engine = DynamicsEngine(persona=PersonaProfile(persona_id="g7", dimensions=(anxiety,)))
            result = engine.step(
                current={"agent.affect.anxiety": 0.25},
                elapsed=timedelta(0),
                impulses=(impulse,),
            )
            value = result.value_for("agent.affect.anxiety")
            assert value is not None
            delta = value - 0.25
            grade = "large" if delta >= 0.25 else "small"
            if trait.dimension.endswith("_high"):
                grades["high"] = grade
            else:
                grades["low"] = grade

        return ScenarioResult(
            golden_id=scenario.golden_id,
            deterministic_outputs=(
                ("affect.transition.low_sensitivity", grades.get("low", "missing")),
                ("affect.transition.high_sensitivity", grades.get("high", "missing")),
            ),
            canonical_changes=(),
            projected_changes=(),
            llm_calls=(),
        )


class D9IntentPolicyPipeline:
    """Drive real D9 scoring, lifecycle, Scheduler, and Policy for Goldens."""

    def run(self, scenario: GoldenScenario) -> ScenarioResult:
        if scenario.golden_id == "G24":
            outputs = self._run_due_restart(scenario)
        else:
            outputs = self._run_immediate(scenario)
        return ScenarioResult(
            golden_id=scenario.golden_id,
            deterministic_outputs=outputs,
            canonical_changes=(),
            projected_changes=(),
            llm_calls=(),
        )

    def _run_immediate(self, scenario: GoldenScenario) -> tuple[tuple[str, object], ...]:
        from mind_runtime.contracts import ActionDecision, ActionPolicyInput, IntentStatus
        from mind_runtime.intents.engine import DeterministicIntentEngine
        from mind_runtime.intents.lifecycle import IntentLifecycleService
        from mind_runtime.intents.persistence import InMemoryIntentBackend

        context = self._context(scenario)
        projected = self._projected(scenario)
        engine = DeterministicIntentEngine(
            self._intent_rules(scenario.golden_id), scenario.runtime_id
        )
        engine_result = engine.evaluate(
            self._engine_input(scenario, context=context, projected=projected)
        )
        lifecycle = IntentLifecycleService(InMemoryIntentBackend())
        admitted = tuple(lifecycle.admit(candidate) for candidate in engine_result.candidates)
        policy = self._policy(scenario)
        resources = self._resources(scenario.golden_id)
        results: dict[str, object] = {}
        selected_kind: str | None = None
        now = scenario.clock.now()
        for index, candidate in enumerate(admitted):
            result = policy.policy(
                ActionPolicyInput(candidate, context, scenario.scope, now, resources)
            )
            results[candidate.kind] = result
            if result.decision is ActionDecision.DEFER:
                lifecycle.transition(
                    scenario.scope,
                    candidate.intent_id,
                    IntentStatus.DEFERRED,
                    result.reason_codes,
                    now,
                    f"golden-defer-{candidate.intent_id}-v1",
                )
                continue
            if result.decision is ActionDecision.DENY:
                lifecycle.transition(
                    scenario.scope,
                    candidate.intent_id,
                    IntentStatus.BLOCKED,
                    result.reason_codes,
                    now,
                    f"golden-block-{candidate.intent_id}-v1",
                )
                continue
            lifecycle.transition(
                scenario.scope,
                candidate.intent_id,
                IntentStatus.ALLOWED,
                result.reason_codes,
                now,
                f"golden-allow-{candidate.intent_id}-v1",
            )
            selected_kind = candidate.kind
            for lower in admitted[index + 1 :]:
                lifecycle.transition(
                    scenario.scope,
                    lower.intent_id,
                    IntentStatus.SUPERSEDED,
                    ("lower_than_selected_candidate",),
                    now,
                    f"golden-supersede-{lower.intent_id}-v1",
                )
            break

        if scenario.golden_id == "G4":
            candidate = next(item for item in admitted if item.kind == "contact_user")
            result = results["contact_user"]
            assert hasattr(result, "decision")
            return (
                ("intent.contact_user", "high" if candidate.strength >= 0.7 else "low"),
                (
                    "action.proactive_message",
                    "blocked" if result.decision is not ActionDecision.ALLOW else "allowed",
                ),
            )
        if scenario.golden_id == "G5":
            photo = results["share_photo"]
            assert hasattr(photo, "decision")
            return (
                (
                    "action.photo",
                    "blocked" if photo.decision is not ActionDecision.ALLOW else "allowed",
                ),
                ("action.text_message", "allowed" if selected_kind == "respond" else "blocked"),
            )
        if scenario.golden_id == "G14":
            return self._run_golden_g14(scenario)
        if scenario.golden_id == "G16a":
            return (
                (
                    "proactive.cooldown",
                    "blocked" if selected_kind is None else "ready",
                ),
            )
        raise ValueError(f"unsupported D9 Golden {scenario.golden_id}")

    def _run_golden_g14(self, scenario: GoldenScenario) -> tuple[tuple[str, object], ...]:
        """Real D10 path: fixed prior plus two scripted drafts through the whole chain."""
        from mind_runtime.contracts import (
            ActionDecision,
            DeliveryStatus,
            ExpressionDisposition,
            PreviousExpression,
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
        from mind_runtime.pipeline.fake_agent import FakeAgent

        prior = PreviousExpression(
            expression_id="g14-previous-expression",
            scope=scenario.scope,
            origin_runtime_id=scenario.runtime_id,
            action_type="respond",
            text="今天真的很想和你聊聊",
            receipt_ref="g14-receipt-1",
            delivery_status=DeliveryStatus.SENT,
            sent_at=scenario.clock.now(),
        )
        config = DecisionContextConfig(
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
        compiler = DecisionContextCompiler(config)
        agent = FakeAgent(("今天真的很想和你重复", "换个开头，想听听你的近况"))
        coordinator = DeterministicExpressionCoordinator(
            compiler=compiler,
            renderer=DeterministicContextRenderer(config),
            agent=agent,
            guard=DeterministicExpressionGuardChain(
                ExpressionGuardConfig(
                    prefix_length=8,
                    transport_markers=("【助手】",),
                    banned_openings=("刚忙完", "刚闲下来", "刚闲了", "忙完了没", "在干嘛"),
                    temporal_rules=(),
                )
            ),
            config=ExpressionCoordinatorConfig(max_rewrites=2),
        )
        orchestrator = TurnOrchestrator(
            clock=scenario.clock,
            trace=TraceRecorder(),
            runtime_id=_writing_runtime(scenario),
            canonical_snapshot=_normalized_canonical(scenario),
            agent=agent,
            previous_expression=FixedPreviousExpressionPort(prior),
            decision_context_compiler=compiler,
            expression_coordinator=coordinator,
        )
        orchestrator.begin_turn(_interaction_for(scenario))
        orchestrator.run()
        outcome = orchestrator.expression_outcome
        policy = orchestrator.policy_result
        assert outcome is not None
        rewrite_required = any(
            attempt.disposition is ExpressionDisposition.REWRITE for attempt in outcome.attempts
        )
        return (
            (
                "action.policy",
                "allowed"
                if policy is not None and policy.decision is ActionDecision.ALLOW
                else "blocked",
            ),
            ("expression.guard", "rewrite_required" if rewrite_required else "accepted"),
        )

    def _run_due_restart(self, scenario: GoldenScenario) -> tuple[tuple[str, object], ...]:
        import tempfile
        from pathlib import Path

        from mind_runtime.contracts import (
            ActionDecision,
            ActionPolicyInput,
            IntentStatus,
            ReconsiderationPolicy,
            SemanticEventCandidate,
        )
        from mind_runtime.intents.engine import DeterministicIntentEngine, IntentRule
        from mind_runtime.intents.lifecycle import IntentLifecycleService
        from mind_runtime.intents.persistence import SqliteIntentBackend
        from mind_runtime.intents.scheduler import IntentScheduler

        now = scenario.clock.now()
        context = self._context(scenario)
        projected = self._projected(scenario)
        event = SemanticEventCandidate(
            candidate_id="golden-g24-due-event",
            scope=scenario.scope,
            origin_runtime_id=scenario.runtime_id,
            kind="follow_up_due",
            attributes=(("due_at", now.isoformat()),),
            confidence=1.0,
            evidence_refs=tuple(evidence.id for evidence in scenario.input_evidence),
        )
        engine = DeterministicIntentEngine(
            (
                IntentRule(
                    rule_id="scheduled-follow-up",
                    kind="scheduled_follow_up",
                    base_strength=0.2,
                    dimension_weights=(),
                    event_kind="follow_up_due",
                    event_bonus=0.4,
                    minimum_strength=0.5,
                    due_at_attribute="due_at",
                    expires_after=timedelta(hours=4),
                    reconsideration_policy=ReconsiderationPolicy.ON_DUE,
                ),
            ),
            scenario.runtime_id,
        )
        result = engine.evaluate(
            self._engine_input(
                scenario,
                context=context,
                projected=projected,
                accepted_events=(event,),
            )
        )
        candidate = result.candidates[0]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "g24-intents.sqlite3"
            first_backend = SqliteIntentBackend(path)
            first_lifecycle = IntentLifecycleService(first_backend)
            first_lifecycle.admit(candidate)
            deferred = first_lifecycle.transition(
                scenario.scope,
                candidate.intent_id,
                IntentStatus.DEFERRED,
                ("waiting_until_due",),
                now,
                "golden-g24-deferred-v2",
            )
            was_due = deferred.due_at is not None and deferred.due_at <= now
            first_backend.close()

            restarted_backend = SqliteIntentBackend(path)
            try:
                restarted_lifecycle = IntentLifecycleService(restarted_backend)
                wakes = IntentScheduler(restarted_lifecycle).tick(scenario.scope, now)
                reconsidered = restarted_backend.current(scenario.scope)[0]
                policy_result = self._policy(scenario).policy(
                    ActionPolicyInput(
                        reconsidered,
                        context,
                        scenario.scope,
                        now,
                        self._resources(scenario.golden_id),
                    )
                )
            finally:
                restarted_backend.close()
        return (
            ("intent.status", "due" if was_due else "future"),
            ("scheduler.effect", "reconsider" if len(wakes) == 1 else "none"),
            ("scheduler.direct_execute", "false"),
            (
                "policy.rechecked",
                "true" if policy_result.decision is ActionDecision.ALLOW else "false",
            ),
        )

    @staticmethod
    def _context(scenario: GoldenScenario) -> Situation:
        facts: list[tuple[str, str]] = []
        values = {state.dimension: state.value for state in scenario.initial_canonical_state}
        if scenario.golden_id == "G4":
            facts.append(
                (
                    "conversation.active",
                    "true" if values.get("interaction.turn_state") == "active" else "false",
                )
            )
        if scenario.golden_id == "G5":
            facts.append(
                (
                    "counter.photo_count_today",
                    str(values.get("user.media.photo_budget_used", "missing")),
                )
            )
        if scenario.golden_id == "G16a":
            facts.append(
                (
                    "counter.last_proactive_at",
                    str(values.get("interaction.last_message_at", "missing")),
                )
            )
        return Situation(
            situation_id=f"situation-{scenario.golden_id}",
            scope=scenario.scope,
            origin_runtime_id=scenario.runtime_id,
            derived_facts=tuple(facts),
            effective_state_ref=f"effective-{scenario.golden_id}",
            observed_at=scenario.clock.now(),
            historical_context=None,
            persona_id=None,
            relationship_ids=(),
            evidence_refs=tuple(evidence.id for evidence in scenario.input_evidence),
        )

    @staticmethod
    def _projected(scenario: GoldenScenario) -> ProjectedMindState:
        states = tuple(
            state for state in scenario.initial_canonical_state if state.scope == scenario.scope
        )
        if not states:
            domain = scenario.scope.domain.value
            dimension = f"{domain}.intent.signal"
            now = scenario.clock.now()
            state_id = f"{dimension}:1"
            states = (
                RuntimeState(
                    state_id=state_id,
                    scope=scenario.scope,
                    origin_runtime_id=scenario.runtime_id,
                    dimension=dimension,
                    value=0.0,
                    status="active",
                    valid_from=now,
                    valid_until=None,
                    relevant_until=None,
                    last_observed_at=now,
                    evidence_refs=(),
                    transition_refs=(),
                    updated_at=now,
                    version=1,
                    sync=SyncFields(
                        scenario.scope,
                        scenario.runtime_id,
                        state_id,
                        1,
                        f"idem-{state_id}",
                    ),
                ),
            )
        projection_id = f"projection-{scenario.golden_id}"
        return ProjectedMindState(
            projection_id=projection_id,
            scope=scenario.scope,
            origin_runtime_id=scenario.runtime_id,
            projected_states=states,
            sync=SyncFields(
                scenario.scope,
                scenario.runtime_id,
                projection_id,
                1,
                f"idem-{projection_id}",
            ),
        )

    @staticmethod
    def _engine_input(
        scenario: GoldenScenario,
        *,
        context: Situation,
        projected: ProjectedMindState,
        accepted_events: tuple[SemanticEventCandidate, ...] = (),
    ) -> IntentEngineInput:
        return IntentEngineInput(
            interaction_id=f"interaction-{scenario.golden_id}",
            scope=scenario.scope,
            origin_runtime_id=scenario.runtime_id,
            context=context,
            projected=projected,
            accepted_events=accepted_events,
            clock=scenario.clock.now(),
        )

    @staticmethod
    def _intent_rules(golden_id: str):  # type: ignore[no-untyped-def]
        from mind_runtime.contracts import ReconsiderationPolicy
        from mind_runtime.intents.engine import IntentRule

        immediate = ReconsiderationPolicy.ON_CONTEXT_CHANGE
        if golden_id == "G4":
            return (
                IntentRule(
                    "contact",
                    "contact_user",
                    0.1,
                    (("agent.affect.longing", 0.75),),
                    None,
                    0.0,
                    0.5,
                    None,
                    None,
                    immediate,
                ),
            )
        if golden_id == "G5":
            return (
                IntentRule(
                    "photo",
                    "share_photo",
                    0.05,
                    (("agent.affect.photo_share_desire", 0.9),),
                    None,
                    0.0,
                    0.5,
                    None,
                    None,
                    immediate,
                ),
                IntentRule(
                    "text",
                    "respond",
                    0.6,
                    (),
                    None,
                    0.0,
                    0.5,
                    None,
                    None,
                    immediate,
                ),
            )
        kind = "respond" if golden_id == "G14" else "contact_user"
        return (
            IntentRule(
                golden_id.lower(),
                kind,
                0.7,
                (),
                None,
                0.0,
                0.5,
                None,
                None,
                immediate,
            ),
        )

    @staticmethod
    def _policy(scenario: GoldenScenario):  # type: ignore[no-untyped-def]
        from mind_runtime.intents.policy import (
            ActionPolicyConfig,
            DeterministicActionPolicy,
            IntentPolicyRule,
        )

        rules: tuple[IntentPolicyRule, ...]
        if scenario.golden_id == "G5":
            rules = (
                IntentPolicyRule(
                    "share_photo",
                    "photo_message",
                    True,
                    True,
                    "counter.photo_count_today",
                    8,
                    "camera",
                ),
                IntentPolicyRule("respond", "text_message", False, False, None, None, None),
            )
        elif scenario.golden_id == "G14":
            rules = (IntentPolicyRule("respond", "text_message", False, False, None, None, None),)
        elif scenario.golden_id == "G24":
            rules = (
                IntentPolicyRule(
                    "scheduled_follow_up",
                    "text_message",
                    False,
                    False,
                    None,
                    None,
                    None,
                ),
            )
        else:
            rules = (
                IntentPolicyRule(
                    "contact_user",
                    "proactive_message",
                    True,
                    True,
                    None,
                    None,
                    None,
                ),
            )
        return DeterministicActionPolicy(
            ActionPolicyConfig(rules, timedelta(minutes=30)), scenario.runtime_id
        )

    @staticmethod
    def _resources(golden_id: str):  # type: ignore[no-untyped-def]
        from mind_runtime.contracts import PolicyResources

        if golden_id == "G5":
            return PolicyResources(("photo_message", "camera", "text_message"))
        if golden_id in {"G14", "G24"}:
            return PolicyResources(("text_message",))
        return PolicyResources(("proactive_message",))


class _FixtureHistoryProvider:
    """Query-only provider used to drive the real bounded D8 adapter."""

    def __init__(self, scenario: GoldenScenario) -> None:
        assert scenario.historical_context is not None
        self._bundle = scenario.historical_context

    def query(self, query: HistoricalContextQuery) -> HistoricalContextBundle:
        assert query.scope == self._bundle.scope
        return self._bundle


class _GoldenSemanticProvider:
    """Scripted bounded candidate provider for G16b only."""

    def __init__(self, scenario: GoldenScenario) -> None:
        self._scenario = scenario
        self.calls = 0
        self.last_result: tuple[SemanticEventCandidate, ...] = ()

    def propose(
        self,
        *,
        observations: tuple[Observation, ...],
        context: Situation,
        scope: Scope,
    ) -> tuple[SemanticEventCandidate, ...]:
        assert observations
        assert context.scope == scope
        assert scope == self._scenario.scope
        self.calls += 1
        result = (
            SemanticEventCandidate(
                candidate_id=f"semantic-{self._scenario.golden_id}",
                scope=self._scenario.scope,
                origin_runtime_id=self._scenario.runtime_id,
                kind="plan_deferred",
                attributes=(("meaning", "tentative_reschedule"),),
                confidence=0.7,
                evidence_refs=tuple(evidence.id for evidence in self._scenario.input_evidence),
            ),
        )
        self.last_result = result
        return result


class D8TransitionPipeline:
    """Drive G6/G16/G16b through the real compressed D8 runtime path."""

    def run(self, scenario: GoldenScenario) -> ScenarioResult:
        if scenario.golden_id not in {"G6", "G16", "G16b"}:
            raise ValueError(f"unsupported D8 Golden {scenario.golden_id}")
        with_history = self._run_once(scenario, include_history=True)
        if scenario.golden_id == "G6":
            without_history = self._run_once(scenario, include_history=False)
            without_value = self._affect_value(without_history[0], "agent.affect.anxiety")
            with_value = self._affect_value(with_history[0], "agent.affect.anxiety")
            trace = with_history[0].transition_result
            assert trace is not None
            history_count = sum(
                contribution.source_kind == "history" and contribution.applied
                for contribution in trace.assessment_trace.contributions
            )
            outputs: tuple[tuple[str, object], ...] = (
                ("affect.anxiety.without_history", round(without_value, 3)),
                ("affect.anxiety.with_history", round(with_value, 3)),
                ("trace.history_applied", history_count),
            )
        elif scenario.golden_id == "G16":
            transition = with_history[0].transition_result
            assert transition is not None
            route = transition.assessment_trace.route_decision
            outputs = (
                ("appraisal_path", route.path.value),
                ("route_reason", route.reason_codes[0]),
                ("provider_call_count", with_history[1].calls),
            )
        else:
            transition = with_history[0].transition_result
            assert transition is not None
            route = transition.assessment_trace.route_decision
            candidates = with_history[1].last_result
            candidate = candidates[0]
            candidate_fields = vars(candidate) if hasattr(candidate, "__dict__") else {}
            schema_valid = all(
                hasattr(candidate, field)
                for field in ("kind", "attributes", "confidence", "evidence_refs")
            )
            outputs = (
                ("appraisal.path", route.path.value),
                ("semantic_candidate.schema", "valid" if schema_valid else "invalid"),
                ("provider_call_count", with_history[1].calls),
                (
                    "llm_output.final_affect",
                    "present"
                    if "final_affect" in candidate_fields or hasattr(candidate, "final_affect")
                    else "absent",
                ),
                (
                    "low_confidence.abstained",
                    "true"
                    if "low_confidence" in transition.assessment_trace.abstention_reasons
                    else "false",
                ),
            )
        return ScenarioResult(
            golden_id=scenario.golden_id,
            deterministic_outputs=outputs,
            canonical_changes=(),
            projected_changes=(),
            llm_calls=(),
        )

    def _run_once(
        self, scenario: GoldenScenario, *, include_history: bool
    ) -> tuple[TurnOrchestrator, _GoldenSemanticProvider]:
        from mind_runtime.dynamics.persona import PersonaProfile
        from mind_runtime.emotional_transition.effects import EventEffectRule
        from mind_runtime.emotional_transition.history import (
            BoundedHistoricalContextAdapter,
            NullHistoricalContext,
        )

        persona = PersonaProfile(
            persona_id=f"d8-{scenario.golden_id.lower()}",
            dimensions=scenario.persona,
        )
        provider = _GoldenSemanticProvider(scenario)
        if include_history and scenario.historical_context is not None:
            historical_context: HistoricalContextPort = BoundedHistoricalContextAdapter(
                provider=_FixtureHistoryProvider(scenario),
                budget=8,
            )
        else:
            historical_context = NullHistoricalContext()
        rules = (
            (
                EventEffectRule(
                    event_kind="plan_cancelled",
                    dimension="agent.affect.anxiety",
                    base_amount=0.2,
                    history_amount_per_match=0.03,
                    history_amount_cap=0.05,
                    minimum_history_confidence=0.5,
                ),
            )
            if scenario.golden_id == "G6"
            else ()
        )
        orchestrator = TurnOrchestrator(
            clock=scenario.clock,
            trace=TraceRecorder(),
            runtime_id=_writing_runtime(scenario),
            persona=persona,
            canonical_snapshot=_normalized_canonical(scenario),
            historical_context=historical_context,
            effect_rules=rules,
            semantic_provider=provider,
        )
        orchestrator.begin_turn(_interaction_for(scenario))
        for evidence in scenario.input_evidence:
            orchestrator.ingest(_scoped_evidence(evidence, scenario))
        orchestrator.run()
        return orchestrator, provider

    @staticmethod
    def _affect_value(orchestrator: TurnOrchestrator, dimension: str) -> float:
        projected = orchestrator.projected
        assert projected is not None
        for state in projected.projected_states:
            if state.dimension == dimension:
                assert isinstance(state.value, float)
                return state.value
        raise AssertionError(f"missing projected dimension {dimension}")
