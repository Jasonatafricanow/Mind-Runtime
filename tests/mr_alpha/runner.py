"""MR-ALPHA-AS1: Alpha Experiment Runner — AS-02.

Drives one or more ablation arms through:
  1. Reset backend
  2. Build orchestrator (per-arm wiring)
  3. Execute trajectory turn-by-turn
  4. Destroy orchestrator and re-open backend (persistence boundary)
  5. Reconstruct orchestrator, execute probes
  6. Score
  7. Return per-arm score + report

All evidence-mode=HARNESS_VALIDATION_ONLY.
"""

from __future__ import annotations

import gc
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, UTC
from pathlib import Path
from typing import Callable, Mapping

from mind_runtime.contracts import (
    Authority,
    AuthorityLevel,
    Evidence,
    Interaction,
    InteractionStatus,
    Scope,
    ScopeDomain,
    SyncFields,
)
from mind_runtime.contracts.appraisal import AppraisalPath, AppraisalRouteDecision
from mind_runtime.contracts.observation import Observation
from mind_runtime.contracts.state import RuntimeState
from mind_runtime.contracts.projection import ProjectedMindState
from mind_runtime.contracts.emotional_transition import (
    AssessmentContribution,
    AssessmentTrace,
    EmotionalTransitionInput,
    EmotionalTransitionResult,
    SemanticEventCandidate,
)
from mind_runtime.state.definitions import StateDefinitionRegistry
from mind_runtime.facts.ports import (
    FactAdmissionDisposition,
    FactAdmissionResult,
    FactIngestPort,
)
from mind_runtime.homeostasis.contracts import (
    CandidateStateDelta,
    HomeostasisDecision,
    HomeostasisDisposition,
)
from mind_runtime.pipeline.orchestrator import TurnOrchestrator
from mind_runtime.pipeline.trace import TraceRecorder
from mind_runtime.providers.clock import Clock
from mind_runtime.slow_plasticity.writer import SlowStateBackend
from mind_runtime.state.persistence import SqliteStateBackend
from tests.mr_alpha.ablations import AblationArm, AblationSpec
from tests.mr_alpha.adapters import (
    SlowStateReader,
    SyntheticIntentEngineAdapter,
    SyntheticSlowStateAdapter,
)
from tests.mr_alpha.causal_trace import CausalStepKind, CausalTrace
from tests.mr_alpha.fixtures.trajectory_common import AlphaTrajectory, TrajectoryTurn
from tests.mr_alpha.harness_defs import build_harness_definitions
from tests.mr_alpha.persistence_harness import (
    PersistenceBoundaryResult,
    PersistenceHarness,
    StateSnapshot,
    classify_dimension,
)
from tests.mr_alpha.probes import DEFAULT_FIXED_PROBE_SUITE, FixedProbeSuite
from tests.mr_alpha.protocol import AlphaProtocol
from tests.mr_alpha.scorer import AlphaScorer, ArmScore

__all__ = ["AlphaRunner", "AlphaRunResult", "TrajectoryRunResult", "AlphaProtocolRunner"]


# ── Result types ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class TrajectoryRunResult:
    """Per-arm result of one trajectory + probe execution."""

    arm: AblationArm
    trajectory: AlphaTrajectory
    arm_internal_metrics: "ArmInternalMetrics"  # alias for clarity in runner output
    pre_snapshot: StateSnapshot
    post_snapshot: StateSnapshot
    persistence: PersistenceBoundaryResult
    consumer_invocations: int
    intent_scores_per_probe: tuple[tuple[str, float], ...]
    raw_outputs: tuple[str, ...]
    arm_score: ArmScore | None = None  # filled in after scoring


@dataclass(frozen=True)
class ArmInternalMetrics:
    """Lightweight internal-metrics container used by the runner before scoring."""

    total_turns: int
    slow_candidates: int
    accepted_writes: int
    rejected_writes: int
    consumer_invocations: int
    meaningful_appraisals: int


@dataclass(frozen=True)
class AlphaRunResult:
    """Full result of one protocol execution."""

    protocol: AlphaProtocol
    run_id: str
    started_at: datetime
    finished_at: datetime
    arm_results: Mapping[AblationArm, TrajectoryRunResult]
    reports_dir: Path


# ── Stub ports used by the harness ───────────────────────────────────────────


class _HarnessFactIngestPort(FactIngestPort):
    """Minimal fact-ingest port that admits any evidence."""

    def __init__(self, clock: Clock) -> None:
        self._clock = clock

    def admit(
        self,
        evidence: Evidence,
        *,
        interaction_id: str,
        writing_runtime: str,
        writing_persona_id: str | None,
    ) -> FactAdmissionResult:
        obs_sync = SyncFields(
                scope=evidence.scope,
                origin_runtime_id=writing_runtime,
                object_id=f"obs-{evidence.id}",
                version=1,
                idempotency_key=f"idem-obs-{evidence.id}",
            )
        observation = Observation(
            id=f"obs-{evidence.id}",
            interaction_id=interaction_id,
            scope=evidence.scope,
            origin_runtime_id=writing_runtime,
            type="factual",
            key=f"{evidence.source_type}.observed",
            value=evidence.payload,
            confidence=1.0,
            observed_at=evidence.occurred_at,
            evidence_refs=(evidence.id,),
            sync=obs_sync,
        )
        return FactAdmissionResult(
            observation=observation,
            disposition=FactAdmissionDisposition.NEW,
        )


class _HarnessEmotionalTransition:
    """Stub emotional transition with `transition_with_gate`.

    Returns a synthetic EmotionalTransitionResult and a HomeostasisDecision for
    every user turn carrying a `typed_event` evidence kind.  Each decision has
    SLOW_ACCEPT if and only if the slow_writer is not None; otherwise REJECT.
    """

    def __init__(
        self,
        clock: Clock,
        slow_writer_present: bool,
        *,
        accumulate_dimensions: tuple[str, ...] = ("agent.affect.anxiety",),
    ) -> None:
        self._clock = clock
        self._slow_writer_present = slow_writer_present
        self._accumulate_dimensions = accumulate_dimensions
        self.last_decisions: list[HomeostasisDecision] = []
        # MR-RUNTIME-05: every admission must project a FRESH state id —
        # re-projecting a fixed id with new content is now (correctly)
        # refused as a stale-writer conflict by the orchestrator. The
        # sequence is CLASS-level so it spans restart-rebuild instances
        # (a new process would keep counting from durable state anyway).
        self._projection_seq: dict[str, int] = {}
        type(self)._seq_global = getattr(type(self), "_seq_global", {})

    def transition_with_gate(self, transition_input: EmotionalTransitionInput):
        observations = transition_input.observations
        # Generate one candidate per dimension per non-replay observation
        decisions = []
        candidates = []
        contributions = []
        for obs in observations:
            if obs.key != "typed_event.observed":
                continue
            payload = obs.value if isinstance(obs.value, Mapping) else {}
            if not isinstance(payload, Mapping):
                continue
            kind = payload.get("kind", "")
            salience = 0.9 if self._slow_writer_present else 0.1
            confidence = 0.85 if self._slow_writer_present else 0.1
            for dim in self._accumulate_dimensions:
                delta = CandidateStateDelta(
                    target_dimension=dim,
                    proposed_value=0.05,  # synthetic accumulation increment
                    scope=transition_input.scope,
                    evidence_refs=(obs.evidence_refs[0] if obs.evidence_refs else obs.id,),
                    salience=salience,
                    confidence=confidence,
                    source_event_ref=obs.id,
                    observed_at=obs.observed_at,
                )
                disposition = (
                    HomeostasisDisposition.SLOW_ACCEPT
                    if self._slow_writer_present
                    else HomeostasisDisposition.FAST_ONLY
                )
                decision = HomeostasisDecision(
                    candidate=delta,
                    prior_value=None,
                    decision=disposition,
                    reason_code="HARNESS_SYNTHETIC",
                    decided_at=transition_input.clock,
                )
                decisions.append(decision)
                # Build a SemanticEventCandidate for accepted_events
                sem = SemanticEventCandidate(
                    candidate_id=f"sem-{obs.id}",
                    scope=transition_input.scope,
                    origin_runtime_id="alpha-synth",
                    kind=str(kind) if kind else "synthetic",
                    attributes=(),
                    confidence=confidence,
                    evidence_refs=delta.evidence_refs,
                )
                candidates.append(sem)
                contributions.append(
                    AssessmentContribution(
                        dimension=dim,
                        source_kind="event",
                        source_ref=obs.id,
                        amount=0.05,
                        confidence=confidence,
                        applied=True,
                        reason_code="HARNESS_SYNTHETIC",
                    )
                )
        self.last_decisions = decisions

                # Build AppraisalRouteDecision (required for AssessmentTrace)
        route_decision = AppraisalRouteDecision(
            route_id=f"route-{transition_input.scope.interaction_id}",
            scope=transition_input.scope,
            path=AppraisalPath.DETERMINISTIC,
            ambiguity_score=None,
            confidence=0.85,
            reason_codes=("harness_synthetic",),
        )

        # Build AssessmentTrace
        trace_id = f"trace-{transition_input.scope.interaction_id}"
        created_at = transition_input.clock
        # state_before and state_after: empty for harness
        trace = AssessmentTrace(
            trace_id=trace_id,
            scope=transition_input.scope,
            origin_runtime_id="alpha-synth",
            context_ref=f"context-{transition_input.scope.interaction_id}",
            persona_id="alpha-persona",
            persona_version=1,
            state_before=(),
            contributions=tuple(contributions),
            state_after=(),
            evidence_refs=tuple(ref for d in decisions for ref in d.candidate.evidence_refs),
            history_refs=(),
            abstention_reasons=(),
            route_decision=route_decision,
            created_at=created_at,
        )

        # Build minimal ProjectedMindState (orchestrator requires ≥1)
        from mind_runtime.contracts.state import RuntimeState
        now = transition_input.clock
        # Projection states must live in AGENT scope (their domain is agent.affect.*)
        agent_scope = Scope(
            domain=ScopeDomain.AGENT,
            agent_id="alpha-agent",
            persona_id="alpha-persona",
        )
        projection_states: list[RuntimeState] = []
        seen_dims: set[str] = set()
        for d in decisions:
            dim = d.candidate.target_dimension
            if dim in seen_dims:
                continue
            seen_dims.add(dim)
            global_seq = type(self)._seq_global
            seq = global_seq.get(dim, 0) + 1
            global_seq[dim] = seq
            self._projection_seq[dim] = seq
            proj_state = RuntimeState(
                state_id=f"{dim}:{seq}:alpha-projection",
                scope=agent_scope,
                dimension=dim,
                value=d.candidate.proposed_value,
                status="active",
                valid_from=now,
                valid_until=None,
                relevant_until=None,
                last_observed_at=now,
                evidence_refs=d.candidate.evidence_refs,
                transition_refs=(),
                updated_at=now,
                origin_runtime_id="alpha-synth",
                version=seq,
                sync=SyncFields(
                    scope=agent_scope,
                    origin_runtime_id="alpha-synth",
                    object_id=f"{dim}:{seq}:alpha-projection",
                    version=seq,
                    idempotency_key=f"idem-projection-{dim}-{seq}",
                ),
            )
            projection_states.append(proj_state)

        projection_id = f"proj-{transition_input.scope.interaction_id}"
        if not projection_states:
            default_dim = "agent.affect.anxiety"
            global_seq = type(self)._seq_global
            seq = global_seq.get(default_dim, 0) + 1
            global_seq[default_dim] = seq
            self._projection_seq[default_dim] = seq
            proj_state = RuntimeState(
                state_id=f"{default_dim}:{seq}:alpha-projection",
                scope=agent_scope,
                dimension=default_dim,
                value=0.0,
                status="active",
                valid_from=now,
                valid_until=None,
                relevant_until=None,
                last_observed_at=now,
                evidence_refs=(),
                transition_refs=(),
                updated_at=now,
                origin_runtime_id="alpha-synth",
                version=seq,
                sync=SyncFields(
                    scope=agent_scope,
                    origin_runtime_id="alpha-synth",
                    object_id=f"{default_dim}:{seq}:alpha-projection",
                    version=seq,
                    idempotency_key=f"idem-projection-default-{seq}",
                ),
            )
            projection_states.append(proj_state)

        projected = ProjectedMindState(
            projection_id=projection_id,
            scope=agent_scope,
            origin_runtime_id="alpha-synth",
            projected_states=tuple(projection_states),
            sync=SyncFields(
                scope=agent_scope,
                origin_runtime_id="alpha-synth",
                object_id=projection_id,
                version=1,
                idempotency_key=f"idem-{projection_id}",
            ),
        )

        result = EmotionalTransitionResult(
            projected=projected,
            accepted_events=tuple(candidates),
            assessment_trace=trace,
        )
        from mind_runtime.dynamics.ports import EmotionalTransitionOutcome
        outcome = EmotionalTransitionOutcome(
            transition_result=result,
            slow_decisions=tuple(decisions),
        )
        return outcome

    def transition(self, transition_input: EmotionalTransitionInput) -> EmotionalTransitionResult:
        # Fallback path: no slow decisions
        return self.transition_with_gate(transition_input).transition_result


# ── AlphaRunner ──────────────────────────────────────────────────────────────


class AlphaRunner:
    """Execute one or more ablation arms and produce a per-arm result.

    Designed for harness validation: each arm runs in a fresh backend
    process, with a clean orchestrator, and the slow-state is exposed
    via the synthetic adapter.  The runner does NOT modify production
    semantics.
    """

    def __init__(
        self,
        protocol: AlphaProtocol,
        trajectory: AlphaTrajectory,
        probe_suite: FixedProbeSuite = DEFAULT_FIXED_PROBE_SUITE,
        definitions: StateDefinitionRegistry | None = None,
        *,
        reports_dir: Path | None = None,
    ) -> None:
        self._protocol = protocol
        self._trajectory = trajectory
        self._probe_suite = probe_suite
        self._definitions = definitions or build_harness_definitions()
        self._reports_dir = reports_dir or (Path(__file__).parent / "reports")
        self._reports_dir.mkdir(parents=True, exist_ok=True)
        self._scorer = AlphaScorer(protocol)

    def _trajectory_for_arm(self, arm: AblationArm) -> AlphaTrajectory:
        """Return a trajectory variant for the given arm.

        BASELINE → neutralized (no `evidence_kind` on any turn) so the
                  synthetic slow writer accumulates zero delta.  This gives
                  us a measurable "no slow mutation" reference.

        TREATMENT → original (with `evidence_kind` preserved) so the
                  synthetic slow writer accumulates a positive delta.
                  This gives us a measurable "slow mutation present"
                  reference.

        WRITE_OFF / CONSUME_OFF / STATE_RESET → original trajectory.
        """
        if arm is not AblationArm.BASELINE:
            return self._trajectory
        # Strip evidence_kind from every user turn to make BASELINE a
        # zero-delta control arm.
        from tests.mr_alpha.fixtures.trajectory_common import TrajectoryTurn as TT
        neutralized_turns = tuple(
            TT(
                turn_id=t.turn_id,
                role=t.role,
                text=t.text,
                expected_effect=t.expected_effect,
                evidence_kind=None,   # neutralized
                metadata=t.metadata,
            )
            for t in self._trajectory.turns
        )
        from tests.mr_alpha.fixtures.trajectory_common import AlphaTrajectory as AT
        return AT(
            fixture_id=f"{self._trajectory.fixture_id}-neutralized",
            version=self._trajectory.version,
            initial_state_ref=self._trajectory.initial_state_ref,
            turns=neutralized_turns,
            intended_semantic_class=self._trajectory.intended_semantic_class,
            probe_suite_ref=self._trajectory.probe_suite_ref,
            metadata=self._trajectory.metadata,
        )

    def run_arm(
        self,
        spec: AblationSpec,
        backend: SqliteStateBackend,
        clock: Clock,
    ) -> TrajectoryRunResult:
        """Run one arm on the supplied backend and clock.

        The caller owns the backend lifecycle; the runner mutates it.
        """
        # ── Choose trajectory variant per arm ────────────────────────────────
        # BASELINE arm strips evidence_kind → synthetic slow delta = 0.
        # TREATMENT arm retains evidence_kind → synthetic slow delta > 0.
        trajectory_ = self._trajectory_for_arm(spec.arm)
        # ── Build orchestrator with arm-specific wiring ──────────────────────
        slow_writer: SyntheticSlowStateAdapter | None
        if spec.disable_slow_write:
            slow_writer = None
        else:
            slow_writer = SyntheticSlowStateAdapter(backend=backend)

        # Build synthetic intent engine.
        # The consumer's `enabled` flag is intentionally NOT used to short-circuit
        # the consumer to score=0.0; doing so would itself produce a behavioral
        # signal change.  Instead, CONSUME_OFF wires the consumer with no
        # slow_reader, which forces it to emit the base signal (same as
        # baseline).  This makes CONSUME_OFF behaviorally inert.
        if spec.disable_consumer:
            intent_engine = SyntheticIntentEngineAdapter(slow_reader=None, enabled=True, runtime_id="runtime-1")
        elif slow_writer is None:
            # WRITE_OFF: writer disabled; consumer still emits base signal
            intent_engine = SyntheticIntentEngineAdapter(slow_reader=None, enabled=True, runtime_id="runtime-1")
        else:
            reader = SlowStateReader(get=lambda dim: slow_writer.accumulated.get(dim, AccumulatedSlowStateStub()).value)
            intent_engine = SyntheticIntentEngineAdapter(slow_reader=reader, enabled=True, runtime_id="runtime-1")

        trace_recorder = TraceRecorder()
        emotional_transition = _HarnessEmotionalTransition(
            clock=clock,
            slow_writer_present=slow_writer is not None,
        )

        orch = TurnOrchestrator(
            clock=clock,
            trace=trace_recorder,
            fact_ingest=_HarnessFactIngestPort(clock),
            emotional_transition=emotional_transition,
            intent_engine=intent_engine,
            effect_rules=(),
            state_backend=backend,
            slow_plasticity_writer=slow_writer,
            definitions=self._definitions,
            canonical_snapshot=(),
        )

        # Load slow state if present (restart simulation is done separately)
        if slow_writer is not None:
            slow_writer.load()

        # ── Execute trajectory turn-by-turn ──────────────────────────────────
        scope = Scope(
            domain=ScopeDomain.INTERACTION,
            interaction_id="alpha-trajectory-1",
        )
        sync = SyncFields(scope, "alpha-synth", "alpha-trajectory-1", 1, "idem-alpha-trajectory-1")
        authority = Authority(scope, AuthorityLevel.OBSERVED, "harness")

        for idx, trajectory_turn in enumerate(trajectory_.turns):
            if trajectory_turn.role != "user":
                continue  # agent stub turns don't produce evidence
            interaction = Interaction(
                interaction_id=f"turn-{idx:03d}",
                scope=Scope(domain=ScopeDomain.INTERACTION, interaction_id=f"turn-{idx:03d}"),
                channel="alpha-harness",
                session_id="alpha-trajectory-1",
                turn_id=trajectory_turn.turn_id,
                started_at=clock.now(),
                committed_at=None,
                status=InteractionStatus.OPEN,
            )
            evidence = Evidence(
                id=f"ev-{idx:03d}",
                source_type="typed_event" if trajectory_turn.evidence_kind else "user_message",
                source_id=f"msg-{idx:03d}",
                authority_level=AuthorityLevel.OBSERVED,
                occurred_at=clock.now(),
                received_at=clock.now(),
                payload={
                    "text": trajectory_turn.text,
                    "kind": trajectory_turn.evidence_kind,
                }
                if trajectory_turn.evidence_kind
                else {"text": trajectory_turn.text},
                scope=interaction.scope,
                origin_runtime_id="alpha-synth",
                authority=Authority(interaction.scope, AuthorityLevel.OBSERVED, f"msg-{idx:03d}"),
                sync=SyncFields(interaction.scope, "alpha-synth", f"ev-{idx:03d}", 1, f"idem-ev-{idx:03d}"),
            )
            orch.begin_turn(interaction)
            orch.ingest(evidence)
            orch.run()
            orch.commit_turn()

        # ── State-Reset ablation: reset slow state to baseline after trajectory
        if spec.reset_state_after_trajectory and slow_writer is not None:
            baseline_values = {dim: 0.0 for dim in slow_writer.accumulated}
            if baseline_values:
                slow_writer.reset_to(baseline_values)

        # ── Snapshot pre-boundary ────────────────────────────────────────────
        pre = StateSnapshot.capture(
            label="pre_boundary",
            backend=backend,
            at=clock.now(),
        )

        # ── DESTROY orchestrator (full in-process reset) ──────────────────────
        del orch
        gc.collect()

        # ── RELOAD: same DB, fresh connection → simulates restart ────────────
        backend.close()
        backend_reopen = SqliteStateBackend(backend._path)
        # Rebuild orchestrator for probes
        slow_writer_after: SyntheticSlowStateAdapter | None = None
        if not spec.disable_slow_write:
            slow_writer_after = SyntheticSlowStateAdapter(backend=backend_reopen)
            slow_writer_after.load()

        if spec.disable_consumer:
            intent_engine_after = SyntheticIntentEngineAdapter(slow_reader=None, enabled=True, runtime_id="runtime-1")
        elif slow_writer_after is None:
            # WRITE_OFF: writer disabled; consumer still emits base signal
            intent_engine_after = SyntheticIntentEngineAdapter(slow_reader=None, enabled=True, runtime_id="runtime-1")
        else:
            reader_after = SlowStateReader(get=lambda dim: slow_writer_after.accumulated.get(dim, AccumulatedSlowStateStub()).value)
            intent_engine_after = SyntheticIntentEngineAdapter(slow_reader=reader_after, enabled=True, runtime_id="runtime-1")

        orch_after = TurnOrchestrator(
            clock=clock,
            trace=TraceRecorder(),
            fact_ingest=_HarnessFactIngestPort(clock),
            emotional_transition=_HarnessEmotionalTransition(clock, slow_writer_after is not None),
            intent_engine=intent_engine_after,
            effect_rules=(),
            state_backend=backend_reopen,
            slow_plasticity_writer=slow_writer_after,
            definitions=self._definitions,
            canonical_snapshot=(),
        )

        # ── Execute probes ───────────────────────────────────────────────────
        intent_scores: list[tuple[str, float]] = []
        raw_outputs: list[str] = []
        for probe in self._probe_suite.probes:
            interaction = Interaction(
                interaction_id=f"probe-{probe.probe_id}",
                scope=Scope(domain=ScopeDomain.INTERACTION, interaction_id=f"probe-{probe.probe_id}"),
                channel="alpha-harness",
                session_id="alpha-probe",
                turn_id=probe.probe_id,
                started_at=clock.now(),
                committed_at=None,
                status=InteractionStatus.OPEN,
            )
            evidence = Evidence(
                id=f"probe-ev-{probe.probe_id}",
                source_type="user_message",
                source_id=probe.probe_id,
                authority_level=AuthorityLevel.OBSERVED,
                occurred_at=clock.now(),
                received_at=clock.now(),
                payload={"text": probe.text, "kind": None},
                scope=interaction.scope,
                origin_runtime_id="alpha-synth",
                authority=Authority(interaction.scope, AuthorityLevel.OBSERVED, probe.probe_id),
                sync=SyncFields(interaction.scope, "alpha-synth", f"probe-ev-{probe.probe_id}", 1, f"idem-probe-{probe.probe_id}"),
            )
            orch_after.begin_turn(interaction)
            orch_after.ingest(evidence)
            orch_after.run()
            orch_after.commit_turn()
            # Capture actual intent score from the synthetic consumer.
            # All arms have the consumer enabled (never disabled); the consumer
            # adapts its output based on whether slow_reader can read state.
            # - TREATMENT: slow_reader has state → strength > base
            # - WRITE_OFF/CONSUME_OFF: slow_reader=None → base_strength = 0.4
            # - BASELINE: slow_reader=None → base_strength = 0.4
            score = intent_engine_after.last_intent_strength
            raw_outputs.append(f"probe-{probe.probe_id} strength={score:.4f}")
            intent_scores.append((f"probe-{probe.probe_id}", score))

        consumer_invocations = intent_engine_after.invocation_count

        # ── Snapshot post-boundary ───────────────────────────────────────────
        post = StateSnapshot.capture(
            label="post_boundary",
            backend=backend_reopen,
            at=clock.now(),
        )

        # ── Persistence boundary result (synthesized from snapshots) ────────
        state_existed_before = bool(pre.slow_states)
        survived = pre.slow_states == post.slow_states
        identity_ok = set(pre.slow_provenance) <= set(post.slow_provenance)
        unexpected_lost = bool({d for d, _ in pre.slow_states} - {d for d, _ in post.slow_states}) and state_existed_before
        persistence_result = PersistenceBoundaryResult(
            state_existed_before_boundary=state_existed_before,
            state_survived_boundary=survived,
            state_identity_preserved=identity_ok,
            pending_leaked_into_canonical=False,
            unexpected_state_lost=unexpected_lost,
            pre_snapshot=pre,
            post_snapshot=post,
            failure_boundary=None
                if (state_existed_before and survived and identity_ok and not unexpected_lost)
                else "Synthetic persistence check failed — see snapshot diff.",
        )

        # ── Internal metrics ────────────────────────────────────────────────
        # Use the slow_writer's accumulated counts (authoritative) rather than
        # the emotional-transition stub which only snapshots the last turn.
        if slow_writer is not None:
            accepted = slow_writer.accepted_count
            slow_candidates = accepted  # 1:1 in harness mode (no REJECT for in-scope events)
            rejected = 0
        else:
            accepted = 0
            slow_candidates = 0
            rejected = 0

        internal_metrics = ArmInternalMetrics(
            total_turns=len([t for t in trajectory_.turns if t.role == "user"]),
            slow_candidates=slow_candidates,
            accepted_writes=accepted,
            rejected_writes=rejected,
            consumer_invocations=consumer_invocations,
            meaningful_appraisals=slow_candidates,
        )

        orch_after.__class__ = TurnOrchestrator  # keep ref to avoid GC issue
        del orch_after
        backend_reopen.close()
        gc.collect()

        return TrajectoryRunResult(
            arm=spec.arm,
            trajectory=self._trajectory,
            arm_internal_metrics=internal_metrics,
            pre_snapshot=pre,
            post_snapshot=post,
            persistence=persistence_result,
            consumer_invocations=consumer_invocations,
            intent_scores_per_probe=tuple(intent_scores),
            raw_outputs=tuple(raw_outputs),
        )


class AccumulatedSlowStateStub:
    """Placeholder when a dimension is absent from accumulated state."""
    value: float = 0.0


# ── Protocol runner ──────────────────────────────────────────────────────────


class AlphaProtocolRunner:
    """Run a complete protocol across all arms and produce per-arm scores."""

    def __init__(
        self,
        protocol: AlphaProtocol,
        trajectory: AlphaTrajectory,
        probe_suite: FixedProbeSuite = DEFAULT_FIXED_PROBE_SUITE,
        *,
        reports_dir: Path | None = None,
    ) -> None:
        self._protocol = protocol
        self._trajectory = trajectory
        self._probe_suite = probe_suite
        self._reports_dir = reports_dir or (Path(__file__).parent / "reports")
        self._reports_dir.mkdir(parents=True, exist_ok=True)
        self._scorer = AlphaScorer(protocol)
        self._runner = AlphaRunner(protocol, trajectory, probe_suite, reports_dir=reports_dir)

    def run(self) -> AlphaRunResult:
        started_at = datetime.now(tz=UTC)
        run_id = str(uuid.uuid4())

        arms_results: dict[AblationArm, TrajectoryRunResult] = {}
        arms = self._protocol.arms
        # BASELINE runs first so other arms can reference it
        sorted_arms = sorted(
            arms,
            key=lambda a: (a is not AblationArm.BASELINE, a.value),
        )

        from tests.support.fake_clock import FakeClock
        clock = FakeClock(started_at)

        baseline_internal = None
        for arm in sorted_arms:
            spec = AblationSpec(arm, self._trajectory.fixture_id)
            # Apply per-arm flags from default_suite
            for s in AblationSpec.default_suite(self._trajectory.fixture_id):
                if s.arm is arm:
                    spec = s
                    break

            # Fresh SQLite file per arm
            db_path = self._reports_dir / f"{run_id}-{arm.value}.sqlite"
            if db_path.exists():
                db_path.unlink()
            backend = SqliteStateBackend(db_path)
            result = self._runner.run_arm(spec, backend, clock)
            arms_results[arm] = result

        finished_at = datetime.now(tz=UTC)

        return AlphaRunResult(
            protocol=self._protocol,
            run_id=run_id,
            started_at=started_at,
            finished_at=finished_at,
            arm_results=arms_results,
            reports_dir=self._reports_dir,
        )