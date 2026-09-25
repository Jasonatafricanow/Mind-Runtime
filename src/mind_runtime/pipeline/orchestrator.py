"""Turn orchestrator: the D2S walking skeleton lifecycle."""

from __future__ import annotations

import os
import threading
import traceback
from contextlib import nullcontext
from dataclasses import dataclass
from dataclasses import replace as _replace
from datetime import datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Any

from mind_runtime.contracts import (
    ActionDecision,
    ActionPolicyInput,
    ActionPolicyResult,
    ActionReceipt,
    Authority,
    AuthorityLevel,
    DecisionContext,
    DeliveryStatus,
    EmotionalTransitionInput,
    EmotionalTransitionResult,
    Evidence,
    ExpressionContextKind,
    ExpressionDisposition,
    ExpressionGuardInput,
    ExpressionOutcome,
    Intent,
    IntentEngineInput,
    IntentScoreTrace,
    IntentStatus,
    Interaction,
    Observation,
    PolicyResources,
    ProjectedMindState,
    ProviderExpressionContext,
    RuntimeState,
    Scope,
    ScopeDomain,
    Situation,
    StateTransition,
    SyncFields,
    SurfaceProjectionPort,
    TurnCheckpoint,
    TurnProjection,
    TurnStage,
)
from mind_runtime.contracts.telemetry import TelemetrySinkProtocol, TelemetryStage
from mind_runtime.contracts.surface import SurfaceProjectionResult
from mind_runtime.surface import project_surface_for_cognition
from mind_runtime.contracts.late_projection import (
    ApplicationReceipt,
    ApplicationStatus,
    ProjectionStatus,
    application_identity,
    digest,
)
from mind_runtime.dynamics.persona import PersonaProfile
from mind_runtime.emotional_transition.effects import EventEffectRule
from mind_runtime.emotional_transition.factory import (
    create_semantic_provider,
)
from mind_runtime.emotional_transition.history import NullHistoricalContext
from mind_runtime.emotional_transition.semantic import (
    SemanticCandidateProvider,
    SemanticRouter,
)
from mind_runtime.expression.context import DecisionContextCompiler, DecisionContextCompilerInput
from mind_runtime.expression.history import NullPreviousExpressionPort
from mind_runtime.facts.ports import FactAdmissionDisposition, FactIngestPort
from mind_runtime.facts.service import FactIngestService
from mind_runtime.homeostasis.contracts import HomeostasisDecision
from mind_runtime.intents.lifecycle import IntentLifecycleService
from mind_runtime.intents.persistence import InMemoryIntentBackend
from mind_runtime.memory.pending import (
    PendingStatus,
    PendingWorkingEvidence,
    PendingWorkingOverlay,
)
from mind_runtime.pipeline.checkpoints import (
    CheckpointStore,
    RecoveryDecision,
    recovery_decision,
)
from mind_runtime.pipeline.ports import (
    ActionPolicyPort,
    AgentFailure,
    AgentPort,
    ContextRendererPort,
    EffectiveStatePort,
    EmotionalTransitionPort,
    ExpressionCoordinatorPort,
    ExpressionGuardPort,
    HistoricalContextPort,
    IntentEnginePort,
    PreviousExpressionPort,
    SituationPort,
)
from mind_runtime.pipeline.receipts import ReceiptOutcome, ReceiptRegistry
from mind_runtime.pipeline.stubs import (
    StubActionPolicy,
    StubContextRenderer,
    StubDecisionContextCompiler,
    StubEmotionalTransition,
    StubExpressionCoordinator,
    StubExpressionGuard,
    StubIntentEngine,
)
from mind_runtime.pipeline.trace import TraceRecorder
from mind_runtime.providers.clock import Clock
from mind_runtime.runtime_admission import AdmissionLease, RuntimeTurnAdmission
from mind_runtime.situation.builder import SituationBuilder
from mind_runtime.slow_plasticity.writer import SlowPlasticityWriter
from mind_runtime.state.definitions import StateDefinitionRegistry
from mind_runtime.state.intents import build_turn_commit_intent
from mind_runtime.state.persistence import (
    CommitMarkerStore,
    SqliteCommitMarkerStore,
    SqliteStateBackend,
    StateBackend,
    canonical_state_rows_equal,
)
from mind_runtime.state.ports import ResolverEffectiveStatePort
from mind_runtime.state.reconciler import FactualReconciler, interpret_observation
from mind_runtime.state.resolver import EffectiveStateResolver


class ShadowModeDisabled(RuntimeError):
    """Shadow mode is disabled (MIND_RUNTIME_SHADOW_ENABLED not set / false)."""


def resolve_shadow_enabled(explicit: bool | None, raw_env: str | None) -> bool:
    """Feature gate for D11L shadow validation (fail-closed).

    explicit  -- caller-provided override (highest priority)
    raw_env   -- value of MIND_RUNTIME_SHADOW_ENABLED
    Default (no explicit, no/empty/unknown env) => False.
    """
    if explicit is not None:
        return explicit
    if raw_env is None:
        return False
    return raw_env.strip().lower() in {"1", "true", "yes", "on"}


class TurnState(StrEnum):
    """Lifecycle state of one turn."""

    BEGIN = "begin"
    INGESTING = "ingesting"
    PROCESSING = "processing"
    DISPATCHING = "dispatching"
    AWAITING_COMMIT = "awaiting_commit"
    COMMITTED = "committed"
    ABORTED = "aborted"


class StaleProjectionError(RuntimeError):
    """The projection's base canonical version moved before commit (D5.3)."""


class CanonicalPersistenceError(RuntimeError):
    """An authority-bearing canonical write failed durably (MR-RUNTIME-05 §9).

    The admission fails loudly instead of continuing silently: no commit
    marker, no in-memory canonical advance, no receipt success. The turn
    stays open for the caller's abort/recovery path.
    """


def _current_states(states: tuple[RuntimeState, ...]) -> tuple[RuntimeState, ...]:
    """Keep one current canonical record per (scope, dimension).

    The durable ``states`` table is append-only; the current record of a
    dimension is the one with the highest version (D5.8 restart load).
    """
    by_key: dict[tuple[Scope, str], RuntimeState] = {}
    for state in states:
        key = (state.scope, state.dimension)
        current = by_key.get(key)
        if current is None or state.version > current.version:
            by_key[key] = state
    return tuple(by_key.values())


@dataclass
class _Turn:
    interaction: Interaction
    evidence_refs: tuple[str, ...]
    observations: tuple[Observation, ...]
    projected: ProjectedMindState | None
    transition_result: EmotionalTransitionResult | None
    slow_decisions: tuple[HomeostasisDecision, ...]
    intent: Intent | None
    policy_result: ActionPolicyResult | None
    policy_results: tuple[ActionPolicyResult, ...]
    admitted_intent_refs: tuple[str, ...]
    projection: TurnProjection | None
    situation: Situation | None
    decision_context: DecisionContext | None
    expression_outcome: ExpressionOutcome | None
    action_receipt: ActionReceipt | None
    surface: SurfaceProjectionResult | None = None
    surface_handoff_request_id: str | None = None
    surface_guard_accepted: bool = False
    intent_traces: tuple[IntentScoreTrace, ...] = ()


def _mr_thread_trace(phase: str, orchestrator, interaction_id: str = "") -> None:
    """MR THREAD TRACE — temporary diagnostic, IDs only, no behavior change."""
    import logging

    _logger = logging.getLogger("xiyue.mr.orchestrator")
    fact_ingest = getattr(orchestrator, "fact_ingest", None)
    fact_backend = getattr(fact_ingest, "_backend", None) or getattr(fact_ingest, "backend", None)
    state_backend = getattr(orchestrator, "_state_backend", None)
    markers = getattr(orchestrator, "commit_marker_store", None)
    _logger.warning(
        "MR THREAD TRACE pid=%s tid=%s orchestrator=%s fact_backend=%s state_backend=%s "
        "markers=%s phase=%s interaction=%s",
        os.getpid(),
        threading.get_ident(),
        hex(id(orchestrator)),
        hex(id(fact_backend)) if fact_backend is not None else "None",
        hex(id(state_backend)) if state_backend is not None else "None",
        hex(id(markers)) if markers is not None else "None",
        phase,
        interaction_id,
    )


class TurnOrchestrator:
    """Wires the full Product Slice lifecycle with injectable typed ports."""

    surface_projection_port: SurfaceProjectionPort | None = None

    def __init__(
        self,
        *,
        clock: Clock,
        trace: TraceRecorder,
        runtime_id: str = "runtime-1",
        fact_ingest: FactIngestPort | None = None,
        effective_state: EffectiveStatePort | None = None,
        situation: SituationPort | None = None,
        emotional_transition: EmotionalTransitionPort | None = None,
        intent_engine: IntentEnginePort | None = None,
        intent_lifecycle: IntentLifecycleService | None = None,
        action_policy: ActionPolicyPort | None = None,
        policy_resources: PolicyResources | None = None,
        agent: AgentPort | None = None,
        context_renderer: ContextRendererPort | None = None,
        expression_guard: ExpressionGuardPort | None = None,
        decision_context_compiler: DecisionContextCompiler | None = None,
        previous_expression: PreviousExpressionPort | None = None,
        expression_coordinator: ExpressionCoordinatorPort | None = None,
        canonical_snapshot: tuple[RuntimeState, ...] = (),
        definitions: StateDefinitionRegistry | None = None,
        checkpoints: CheckpointStore | None = None,
        receipts: ReceiptRegistry | None = None,
        persona: PersonaProfile | None = None,
        state_backend: StateBackend | None = None,
        commit_markers: CommitMarkerStore | None = None,
        historical_context: HistoricalContextPort | None = None,
        effect_rules: tuple[EventEffectRule, ...] = (),
        semantic_provider: SemanticCandidateProvider | None = None,
        shadow_enabled: bool | None = None,
        external_memory_authority: ExternalMemoryAuthority | None = None,
        external_memory_reference_store: MemoryReferenceStore | None = None,
        pending_overlay: PendingWorkingOverlay | None = None,
        slow_plasticity_writer: SlowPlasticityWriter | None = None,
        telemetry_sink: TelemetrySinkProtocol | None = None,
        turn_admission: RuntimeTurnAdmission | None = None,
        surface_projection_port: SurfaceProjectionPort | None = None,
        surface_delivery_backend: Any = None,
    ) -> None:
        self.surface_projection_port = surface_projection_port
        self._surface_delivery_backend = surface_delivery_backend
        self._clock = clock
        self._runtime_id = runtime_id
        self._trace = trace
        self._telemetry_sink = telemetry_sink
        # The D3 factual plane is the only ingest path: no direct Observation
        # construction may bypass authority/ownership/idempotency/provenance.
        self.fact_ingest = fact_ingest or FactIngestService(clock=clock)
        # C9-W1B: pre-admission pending overlay (non-canonical, non-durable).
        # When provided, ingest(..., defer_admission=True) routes evidence here
        # instead of directly to fact_ingest.admit().
        self._pending_overlay = pending_overlay
        self._persona = persona
        # D4.7: the default effective state comes from the authoritative
        # EffectiveStateResolver — raw status filtering by consumers is
        # forbidden.
        if effective_state is None:
            registry = definitions or StateDefinitionRegistry()
            effective_state = ResolverEffectiveStatePort(
                resolver=EffectiveStateResolver(definitions=registry), runtime_id=self._runtime_id
            )
        self.effective_state = effective_state
        self._definitions = definitions or StateDefinitionRegistry()
        self._checkpoints = checkpoints
        self._receipts = receipts
        self._situation_port = situation or SituationBuilder()
        # ADR-0004: the canonical path has one EmotionalTransition hop. With
        # a Persona, it is backed by the D7 algorithmic engine; without one,
        # the walking skeleton uses a deterministic stub.
        # J8-SP1: explicit semantic_provider wins over the factory. If the
        # caller did not inject one, ask the factory (which reads
        # MR_SEMANTIC_PROVIDER + GLM_API_KEY from the environment, default
        # OFF). The factory never writes state, loads memory, performs
        # routing, or invokes Appraisal — it only returns a provider.
        if semantic_provider is None:
            semantic_provider = create_semantic_provider()

        if emotional_transition is None and persona is not None:
            from mind_runtime.dynamics.engine import DynamicsEngine
            from mind_runtime.dynamics.ports import EngineEmotionalTransitionPort

            engine = DynamicsEngine(persona=persona)
            emotional_transition = EngineEmotionalTransitionPort(
                engine=engine,
                runtime_id=self._runtime_id,
                effect_rules=effect_rules,
                semantic_router=SemanticRouter(
                    provider=semantic_provider,
                    telemetry_sink=self._telemetry_sink,
                ),
                telemetry_sink=self._telemetry_sink,
            )
        self.emotional_transition = emotional_transition or StubEmotionalTransition(clock=clock)
        if self._telemetry_sink is not None:
            if getattr(self.emotional_transition, "_telemetry_sink", None) is None:
                try:
                    self.emotional_transition._telemetry_sink = self._telemetry_sink
                except Exception:
                    pass
            sr = getattr(self.emotional_transition, "_semantic_router", None)
            if sr is not None and getattr(sr, "_telemetry_sink", None) is None:
                try:
                    sr._telemetry_sink = self._telemetry_sink
                except Exception:
                    pass
        self.intent_engine = intent_engine or StubIntentEngine()
        self.intent_lifecycle = intent_lifecycle or IntentLifecycleService(InMemoryIntentBackend())
        self.historical_context = historical_context or NullHistoricalContext()
        self.action_policy = action_policy or StubActionPolicy()
        self.policy_resources = policy_resources or PolicyResources(("respond",))
        self.agent = agent or _DefaultAgent()
        self.context_renderer = context_renderer or StubContextRenderer()
        self.expression_guard = expression_guard or StubExpressionGuard()
        self.decision_context_compiler = decision_context_compiler or StubDecisionContextCompiler()
        self.previous_expression = previous_expression or NullPreviousExpressionPort()
        self._expression_coordinator_override = expression_coordinator
        # D5.8: the durable StateBackend is the canonical restart authority.
        # When provided, canonical state is loaded from it at startup (the
        # highest version per scope+dimension — the table is append-only)
        # and every ingest/turn_commit persists through it; a fresh
        # orchestrator on the same backend restores canonical after restart.
        # The in-memory snapshot is an alternative input, never both.
        if state_backend is not None and canonical_snapshot:
            raise ValueError("state_backend and canonical_snapshot cannot both be provided")
        self._state_backend = state_backend
        # MR-RUNTIME-05: process-local, per-namespace canonical admission
        # authority. When enrolled, the WHOLE turn lifecycle (begin →
        # commit/abort) holds the namespace's admission lease and the
        # canonical base is refreshed from the durable backend at admission
        # start — every admitted turn executes on the canonical outcome of
        # all prior admitted turns (no stale read-modify-write).
        self._turn_admission = turn_admission
        self._admission_lease: AdmissionLease | None = None
        # C10-B-W: the slow plasticity writer is the authoritative longitudinal
        # state writer. It is called at Seam B (per R3 §13.2) after the
        # emotional transition and before the commit marker. If provided,
        # it accumulates SLOW_ACCEPT decisions and writes to agent.slow.*
        # dimensions via the state backend.
        self._slow_writer = slow_plasticity_writer
        if slow_plasticity_writer is not None and state_backend is not None:
            # C10-B-W: rebuild the writer's in-memory window view from the
            # persisted ledger at startup (AGENT scope only — see helper).
            self._reload_slow_writer(slow_plasticity_writer)
        # C3.0 / ADR-0021: when a CommitMarkerStore is provided, every turn whose
        # projection is promoted records an implementation-neutral durable
        # marker so consumers answer committed-cognition from commit
        # semantics, never from projection-id naming.
        # ADR-0021: If commit_markers is a SqliteCommitMarkerStore targeting the same
        # SQLite database as state_backend, adopt the state_backend's connection so that
        # the entire cognitive turn commits on ONE connection in ONE atomic transaction.
        if (
            isinstance(state_backend, SqliteStateBackend)
            and isinstance(commit_markers, SqliteCommitMarkerStore)
        ):
            try:
                same_db = (
                    state_backend._path == commit_markers._path
                    or Path(state_backend._path).resolve() == Path(commit_markers._path).resolve()
                )
            except Exception:
                same_db = state_backend._path == commit_markers._path
            if same_db:
                if commit_markers._conn is state_backend.connection:
                    pass
                elif commit_markers._owns_conn:
                    commit_markers.close()
                    commit_markers._conn = state_backend.connection
                    commit_markers._owns_conn = False
                else:
                    # commit_markers is already a borrower on another connection.
                    # Create a separate store bound to THIS orchestrator's state_backend connection.
                    commit_markers = SqliteCommitMarkerStore(
                        state_backend._path,
                        connection=state_backend.connection,
                    )
        self.commit_marker_store = commit_markers
        if state_backend is not None:
            self._canonical = {
                state.state_id: state for state in _current_states(state_backend.load_states())
            }
        else:
            self._canonical = {state.state_id: state for state in canonical_snapshot}
        self._turn: _Turn | None = None
        self._overlay: tuple[RuntimeState, ...] = ()
        self._ingest_transitions: tuple[StateTransition, ...] = ()
        self._base_state_version = max(
            (state.version for state in self._canonical.values()), default=1
        )
        self.state: TurnState = TurnState.BEGIN
        self.factual_overlay: dict[str, object] = {}
        # D11L shadow gate: default OFF (fail-closed). Explicit param wins;
        # otherwise MIND_RUNTIME_SHADOW_ENABLED env, otherwise False.
        self._shadow_enabled = resolve_shadow_enabled(
            shadow_enabled, os.environ.get("MIND_RUNTIME_SHADOW_ENABLED")
        )
        # Forward-compatibility slot: retained so that a future ADR can re-open
        # this seam and restore external memory wiring without constructor
        # signature churn. Both default to None.
        self._em_authority: ExternalMemoryAuthority | None = external_memory_authority
        self._em_reference_store: MemoryReferenceStore | None = external_memory_reference_store

    @property
    def shadow_enabled(self) -> bool:
        return self._shadow_enabled

    @property
    def trace(self) -> TraceRecorder:
        return self._trace

    @property
    def observations(self) -> tuple[Observation, ...]:
        if self._turn is None:
            return ()
        return self._turn.observations

    @property
    def decision_context(self) -> DecisionContext | None:
        if self._turn is None:
            return None
        return self._turn.decision_context

    @property
    def expression_outcome(self) -> ExpressionOutcome | None:
        if self._turn is None:
            return None
        return self._turn.expression_outcome

    @property
    def expression_coordinator(self) -> ExpressionCoordinatorPort:
        """The bounded retry owner; defaults to the D2S single-attempt stub."""
        if self._expression_coordinator_override is not None:
            return self._expression_coordinator_override
        return StubExpressionCoordinator(
            renderer=self.context_renderer,
            agent=self.agent,
            guard=self.expression_guard,
        )

    @property
    def action_receipt(self) -> ActionReceipt | None:
        if self._turn is None:
            return None
        return self._turn.action_receipt

    def surface_handoff_request(self):
        """Read the committed C7 request for the active SURFACE_V1 turn."""
        turn = self._require_turn()
        request_id = turn.surface_handoff_request_id
        if request_id is None or self._surface_delivery_backend is None:
            return None
        from mind_runtime.delivery.surface_handoff import recover_admitted_surface_handoff

        return recover_admitted_surface_handoff(
            self._surface_delivery_backend, request_id,
            origin_runtime_id=self._runtime_id, scope=turn.interaction.scope,
        )

    def guard_surface_provider_prose(self, prose: str):
        """Guard Body prose after durable handoff and before external delivery."""
        from mind_runtime.delivery.state import DeliveryLifecycleState

        turn = self._require_turn()
        turn.surface_guard_accepted = False
        request = self.surface_handoff_request()
        if request is None or turn.decision_context is None or not isinstance(prose, str):
            raise ValueError("SURFACE_GUARD_UNAVAILABLE")
        context = turn.decision_context
        result = self.expression_guard.guard(ExpressionGuardInput(
            draft_id=f"draft-{context.context_id}",
            decision_context=context, expression=prose, attempt=context.attempt,
        ))
        if (
            result.scope != context.scope
            or result.origin_runtime_id != context.origin_runtime_id
            or result.expression != prose
        ):
            raise ValueError("SURFACE_GUARD_LINEAGE_MISMATCH")
        row = self._surface_delivery_backend.get_durable_request(request.request_id)
        if row.lifecycle_state is DeliveryLifecycleState.PENDING:
            self._surface_delivery_backend.set_lifecycle_state(
                request.request_id, DeliveryLifecycleState.IN_FLIGHT, at=self._clock.now()
            )
        elif row.lifecycle_state is not DeliveryLifecycleState.IN_FLIGHT:
            raise ValueError("SURFACE_GUARD_REQUEST_NOT_IN_FLIGHT")
        attempt = self._surface_delivery_backend.increment_attempt(
            request.request_id, at=self._clock.now()
        )
        self._surface_delivery_backend.record_attempt(
            attempt_id=f"{request.surface_handoff.logical_attempt_id}-physical-{attempt}",
            request_id=request.request_id,
            attempt=attempt, started_at=self._clock.now(), ended_at=self._clock.now(),
            outcome=(DeliveryLifecycleState.IN_FLIGHT
                     if result.disposition is ExpressionDisposition.ACCEPT
                     else DeliveryLifecycleState.REJECTED),
            provider_receipt_ref=None,
            reason_codes=("guard_accept",) if result.disposition is ExpressionDisposition.ACCEPT
            else tuple(result.violations),
        )
        turn.surface_guard_accepted = result.disposition is ExpressionDisposition.ACCEPT
        return result

    def acknowledge_surface_delivery(self) -> None:
        """Record operational acknowledgement; never create experiential evidence."""
        from mind_runtime.contracts import DeliveryReceipt
        from mind_runtime.delivery.state import DeliveryLifecycleState

        turn = self._require_turn()
        request = self.surface_handoff_request()
        if request is None:
            return
        if not turn.surface_guard_accepted:
            raise ValueError("SURFACE_GUARD_NOT_ACCEPTED")
        row = self._surface_delivery_backend.get_durable_request(request.request_id)
        if row.lifecycle_state is DeliveryLifecycleState.ACCEPTED:
            return
        if row.lifecycle_state is not DeliveryLifecycleState.IN_FLIGHT:
            raise ValueError("SURFACE_DELIVERY_NOT_IN_FLIGHT")
        now = self._clock.now()
        receipt_id = f"delivery-receipt-{request.request_id}"
        receipt = DeliveryReceipt(
            receipt_id=receipt_id, scope=request.scope,
            origin_runtime_id=request.origin_runtime_id, message_id=request.message_id,
            delivery_status=DeliveryStatus.SENT, delivered_at=now,
            sync=SyncFields(request.scope, request.origin_runtime_id, receipt_id, 1,
                            f"idem-{receipt_id}"),
        )
        self._surface_delivery_backend.record_receipt(
            receipt, request_id=request.request_id, provider_receipt_ref=None,
            provider_message_ref=None, attempt=row.attempt_count,
        )
        self._surface_delivery_backend.set_lifecycle_state(
            request.request_id, DeliveryLifecycleState.ACCEPTED, at=now
        )
        action_receipt_id = f"receipt-{turn.interaction.interaction_id}"
        turn.action_receipt = ActionReceipt(
            receipt_id=action_receipt_id, scope=turn.interaction.scope,
            origin_runtime_id=self._runtime_id,
            action_intent_id=turn.intent.intent_id,
            delivery_status=DeliveryStatus.SENT, outcome=None, received_at=now,
            sync=SyncFields(turn.interaction.scope, self._runtime_id,
                            action_receipt_id, 1, f"idem-{action_receipt_id}"),
        )
        if self._receipts is not None:
            self._receipts.record(turn.action_receipt)

    @property
    def projected(self) -> ProjectedMindState | None:
        if self._turn is None:
            return None
        return self._turn.projected

    @property
    def transition_result(self) -> EmotionalTransitionResult | None:
        if self._turn is None:
            return None
        return self._turn.transition_result

    @property
    def intent(self) -> Intent | None:
        if self._turn is None:
            return None
        return self._turn.intent

    @property
    def policy_results(self) -> tuple[ActionPolicyResult, ...]:
        if self._turn is None:
            return ()
        return self._turn.policy_results

    @property
    def policy_result(self) -> ActionPolicyResult | None:
        if self._turn is None:
            return None
        return self._turn.policy_result

    @property
    def intent_traces(self) -> tuple[IntentScoreTrace, ...]:
        if self._turn is None:
            return ()
        return self._turn.intent_traces

    @property
    def turn_projection(self) -> TurnProjection | None:
        """This turn's uncommitted TurnProjection (D5.2: Projection != Canonical)."""
        if self._turn is None:
            return None
        return self._turn.projection

    @property
    def situation(self) -> Situation | None:
        """This turn's built Situation (D6: derived facts aggregation)."""
        if self._turn is None:
            return None
        return self._turn.situation

    @property
    def canonical(self) -> tuple[RuntimeState, ...]:
        return tuple(self._canonical.values())

    @property
    def overlay(self) -> tuple[RuntimeState, ...]:
        """This turn's ingest-committed factual records (D5.3 read-your-writes)."""
        return self._overlay

    @property
    def ingest_transitions(self) -> tuple[StateTransition, ...]:
        """The reconcile transitions committed at ingest (facts, D5.3)."""
        return self._ingest_transitions

    def _require_turn(self) -> _Turn:
        if self._turn is None:
            raise RuntimeError("begin_turn must be called first")
        return self._turn

    def _derive_slow_scope(self, turn: _Turn) -> Scope:
        """Derive the scope for slow-state writes.

        Slow-state is always written in AGENT scope (matching the persona
        scope). If the projection scope is AGENT, use it directly; otherwise
        fall back to the persona scope; otherwise synthesize one.
        """
        projected = turn.projection
        if projected is not None:
            projected_scope = projected.projected_mind_state.scope
            if projected_scope.domain == ScopeDomain.AGENT:
                return projected_scope
        if self._persona is not None:
            return Scope(
                domain=ScopeDomain.AGENT,
                agent_id=self._persona.persona_id,
                persona_id=self._persona.persona_id,
            )
        return Scope(
            domain=ScopeDomain.AGENT,
            agent_id="default",
            persona_id="default",
        )

    # C10-C1: read authoritative agent.slow.* RuntimeState records from
    # SQLite at turn-runtime.  No in-memory cache, no shadow copy.  Only
    # dimensions registered with dynamics_policy="accumulator" (the
    # longitudinal target authority) are read.  When no state backend
    # or no definitions are configured, returns an empty tuple.
    #
    # Per ADR-0017 the slow-state writes are scoped to AGENT domain
    # (matching the persona scope).  We read at that scope only.
    def _read_slow_state_records(
        self, scope: Scope
    ) -> tuple[RuntimeState, ...]:
        if self._state_backend is None or self._definitions is None:
            return ()
        if scope.domain is not ScopeDomain.AGENT:
            return ()
        records: list[RuntimeState] = []
        for definition in self._definitions.all():
            if definition.dynamics_policy != "accumulator":
                continue
            try:
                states = self._state_backend.load_slow_states(scope, definition.key)
            except Exception:  # noqa: BLE001 — fail-closed: a missing dimension is not an error
                continue
            if not states:
                continue
            # Use the latest version per dimension (slow state is per-turn
            # overwrite; only the most recent write reflects the current
            # accumulated value).
            records.append(states[-1])
        return tuple(records)

    def _writing_persona_id_for(self, evidence: Evidence) -> str | None:
        if evidence.scope.domain not in {ScopeDomain.AGENT, ScopeDomain.RELATIONSHIP}:
            return None
        if self._persona is None:
            return None
        return self._persona.persona_id

    def _reload_slow_writer(self, writer: SlowPlasticityWriter) -> None:
        """Rebuild a slow-plasticity writer's window from the durable ledger.

        Pass the AGENT scope so the writer only loads slow-state dimension
        windows that belong to the agent (not user / world scopes).
        """
        from mind_runtime.contracts import Scope, ScopeDomain

        persona_id = self._persona.persona_id if self._persona is not None else "default"
        writer.load(
            Scope(domain=ScopeDomain.AGENT, agent_id=persona_id, persona_id=persona_id)
        )

    def _refresh_canonical_from_backend(self) -> None:
        """Reload canonical (and the slow window) from the durable backend.

        MR-RUNTIME-05: called at the START of an admitted turn, while the
        namespace's admission lease is held — no other writer can be
        mid-admission, so the durable read IS the authoritative canonical
        base. Prevents the stale read-modify-write the R1 probe exposed.
        """
        if self._state_backend is None:
            return
        self._canonical = {
            state.state_id: state
            for state in _current_states(self._state_backend.load_states())
        }
        if self._slow_writer is not None:
            self._reload_slow_writer(self._slow_writer)

    def _release_admission_lease(self) -> None:
        lease = self._admission_lease
        if lease is not None:
            self._admission_lease = None
            lease.release()

    def _persist_state_idempotent(self, state: RuntimeState) -> bool:
        """Persist one authority-bearing canonical state (MR-RUNTIME-05 §9).

        A duplicate insert is a CONFLICT only when the namespace already
        holds a DIFFERENT row with this id (a stale writer lost the race).
        An identical row is an idempotent no-op: the ingest phase may have
        admitted it earlier in the same turn, and an admitted-turn replay
        re-persists the same rows. Returns True when a NEW row was inserted,
        False for an idempotent duplicate (used to detect pure-replay
        admissions, which must not re-run the longitudinal slow-write seam).
        """
        if self._state_backend is None:
            return True
        if self._state_backend.save_state(state):
            return True
        for existing in self._state_backend.load_states():
            if existing.state_id != state.state_id:
                continue
            # Canonical meaning only: the sync envelope (idem key, versions
            # of the sync plane) is derived transport metadata, not part of
            # the canonical fact (governance boundary 18 spirit).
            if canonical_state_rows_equal(existing, state):
                return False
            break
        raise CanonicalPersistenceError(
            f"state {state.state_id} was not durably admitted: the namespace "
            "holds a DIFFERENT row with this id (stale-writer conflict); "
            "refusing to advance canonical memory or record a commit marker "
            "(MR-RUNTIME-05 §9)"
        )

    def _persist_transition_idempotent(self, transition: StateTransition) -> None:
        """Persist one authority-bearing canonical transition (§9)."""
        if self._state_backend is None:
            return
        if self._state_backend.save_transition(transition):
            return
        for existing in self._state_backend.load_transitions():
            if existing.transition_id != transition.transition_id:
                continue
            if (
                existing.from_state.state_id == transition.from_state.state_id
                and existing.to_state.state_id == transition.to_state.state_id
                and existing.origin_runtime_id == transition.origin_runtime_id
                and existing.intent_id == transition.intent_id
            ):
                return
            break
        raise CanonicalPersistenceError(
            f"transition {transition.transition_id} was not durably admitted: "
            "the namespace holds a DIFFERENT row with this id (stale-writer "
            "conflict) (MR-RUNTIME-05 §9)"
        )

    def begin_turn(self, interaction: Interaction) -> None:
        _mr_thread_trace("ORCH_BEGIN_ENTRY", self, interaction.interaction_id)
        # MR-RUNTIME-05: acquire the namespace admission lease for the WHOLE
        # turn lifecycle before touching any state. Overlapping turns from
        # other orchestrators on the same namespace block here until the
        # active admission completes.
        if self._turn_admission is not None:
            self._admission_lease = self._turn_admission.acquire(
                turn_context=f"turn:{interaction.interaction_id}"
            )
            try:
                self._refresh_canonical_from_backend()
            except Exception:
                self._release_admission_lease()
                raise
        self._turn = _Turn(
            interaction=interaction,
            evidence_refs=(),
            observations=(),
            projected=None,
            transition_result=None,
            slow_decisions=(),
            intent=None,
            policy_result=None,
            policy_results=(),
            admitted_intent_refs=(),
            projection=None,
            situation=None,
            decision_context=None,
            expression_outcome=None,
            action_receipt=None,
        )
        self.state = TurnState.BEGIN
        self._trace.record(
            interaction.interaction_id,
            "begin",
            ref=interaction.interaction_id,
            at=self._clock.now(),
        )

    def ingest(self, evidence: Evidence, *, defer_admission: bool = False) -> Observation | None:
        """Canonical or deferred evidence ingest.

        Canonical path (defer_admission=False):
          Delegates to the factual plane (D3.C1) for admission, authority,
          idempotency, and provenance. The returned Observation has already been
          reconciled into canonical state when run() is called.

        Deferred path (defer_admission=True):
          C9-W1B pre-admission path. Stores evidence in the pending overlay
          WITHOUT calling fact_ingest.admit(). Returns None — the caller must
          later call accept_pending() or reject_pending(). The compiler reads
          pending items via `pending_items` on DecisionContextCompilerInput.
          The overlay is cleared on abort_turn() or process restart.
        """
        turn = self._require_turn()
        self.state = TurnState.INGESTING
        # C9-W1B deferred admission path: hold in pending overlay, do not admit.
        if defer_admission:
            if self._pending_overlay is None:
                raise ValueError(
                    "defer_admission=True requires pending_overlay to be set on the orchestrator"
                )
            pending_id = f"pending-{evidence.id}"
            # Extract the original text from the evidence payload (which is a
            # FrozenMapping keyed dict like {"text": "..."} or a plain string).
            if isinstance(evidence.payload, dict):
                _raw_text = str(evidence.payload.get("text", ""))
            elif hasattr(evidence.payload, "__getitem__"):
                try:
                    _raw_text = str(evidence.payload["text"])
                except (KeyError, TypeError):
                    _raw_text = str(evidence.payload)
            else:
                _raw_text = str(evidence.payload)
            semantic_payload = (("fact.key", _raw_text),)
            pending = PendingWorkingEvidence(
                pending_id=pending_id,
                evidence_ref=evidence.id,
                source_turn_id=turn.interaction.interaction_id,
                scope=turn.interaction.scope,
                semantic_payload=semantic_payload,
                confidence=0.5,
                status=PendingStatus.PENDING,
                origin_runtime_id=self._runtime_id,
                source_text=_raw_text[:200],
                created_at=self._clock.now(),
            )
            self._pending_overlay.add(pending)
            self._trace.record(
                turn.interaction.interaction_id,
                "ingest",
                ref=evidence.id,
                outcome="fact_pending",
                at=self._clock.now(),
            )
            return None
        # Canonical ingest path (D3.C1): delegate to the factual plane so the
        # authority/ownership gates, append-only idempotent stores, and
        # provenance always run — stubs and second pipelines are forbidden.
        # ADR-0009: the factual plane decides the disposition; the turn
        # consumes NEW and REPAIRED Observations once, and records REPLAY as
        # a non-causal audit step without touching the turn inputs.
        result = self.fact_ingest.admit(
            evidence,
            interaction_id=turn.interaction.interaction_id,
            writing_runtime=self._runtime_id,
            writing_persona_id=self._writing_persona_id_for(evidence),
        )
        observation = result.observation
        if result.disposition is FactAdmissionDisposition.REPLAY:
            # The audit Interaction is retained and the turn continues, but
            # no Observation, evidence ref, or overlay entry enters this
            # turn: injected-Clock recovery, Intent lifecycle, Policy, and
            # other no-new-fact behavior still execute in run().
            self.state = TurnState.INGESTING
            self._trace.record(
                turn.interaction.interaction_id,
                "ingest",
                ref=evidence.id,
                outcome="fact_replay",
                at=self._clock.now(),
            )
            return observation
        turn.observations = turn.observations + (observation,)
        turn.evidence_refs = turn.evidence_refs + (evidence.id,)
        self.factual_overlay[f"{evidence.source_type}.observed"] = evidence.payload
        self.state = TurnState.INGESTING
        self._trace.record(
            turn.interaction.interaction_id,
            "ingest",
            ref=evidence.id,
            outcome=f"fact_{result.disposition.value}",
            at=self._clock.now(),
        )
        return observation

    def run_shadow(self) -> None:
        """D11L shadow-mode run: mirror a real turn for observation/learning.

        Fail-closed: refuses to run unless MIND_RUNTIME_SHADOW_ENABLED (or an
        explicit constructor override) enables the gate. Shadow semantics
        (observe-only, no outward expression) are enforced by the phase
        design (D11L field #4); here we only guarantee the gate.
        """
        if not self._shadow_enabled:
            raise ShadowModeDisabled("MIND_RUNTIME_SHADOW_ENABLED not enabled; shadow run refused")
        if self._turn is None:
            raise ValueError("run_shadow requires begin_turn() before running")
        self._trace.record(
            self._turn.interaction.interaction_id,
            "shadow.run",
            at=self._clock.now(),
        )
        self.run()

    def run(self) -> None:
        turn = self._require_turn()
        self.state = TurnState.PROCESSING
        now = self._clock.now()
        # D5.3 ingest-commit: facts already happened — this turn's
        # dimension-typed observations are reconciled into canonical state
        # immediately (durable facts, G13b: they survive a cognitive abort).
        # Derived mind transitions remain projections until commit_turn.
        self._ingest_commit(turn, now=now)
        # The projection bases on the post-ingest canonical version; commit
        # validates staleness against it (D5.3 optimistic commit).
        self._base_state_version = max(
            (state.version for state in self._canonical.values()), default=1
        )
        effective = self.effective_state.effective(
            interaction_id=turn.interaction.interaction_id,
            evidence_refs=turn.evidence_refs,
            canonical_snapshot=self.canonical,
            scope=turn.interaction.scope,
            clock=now,
        )
        # D6: the situation builder consumes the authoritative Effective
        # State view (never raw state) plus the interaction and the clock.
        view = EffectiveStateResolver(definitions=self._definitions).resolve(
            self.canonical, now=now
        )
        situation = self._situation_port.build(
            interaction=turn.interaction,
            effective_view=view,
            scope=turn.interaction.scope,
            clock=now,
        )
        if self._persona is not None:
            if situation.persona_id not in (None, self._persona.persona_id):
                raise ValueError("Situation Persona conflicts with turn Persona")
            situation = _replace(situation, persona_id=self._persona.persona_id)
        historical_context = self.historical_context.read(
            interaction_id=turn.interaction.interaction_id,
            context=situation,
            observations=turn.observations,
            scope=turn.interaction.scope,
            clock=now,
        )
        if historical_context is not None:
            situation = _replace(situation, historical_context=historical_context)
        turn.situation = situation
        # D7.7: the interaction scope (user) and the affect projection scope
        # (the persona's own agent scope) are separate. Agent-domain persona
        # dimensions project into Scope(AGENT, persona_id, persona_id);
        # user-domain personas keep the turn scope. The engine port fails
        # closed on any domain conflict.
        projection_scope: Scope | None = None
        if self._persona is not None and all(
            dimension.dimension.startswith("agent.") for dimension in self._persona.dimensions
        ):
            projection_scope = Scope(
                domain=ScopeDomain.AGENT,
                agent_id=self._persona.persona_id,
                persona_id=self._persona.persona_id,
            )
        persona_id = self._persona.persona_id if self._persona is not None else "stub-persona"
        persona_version = self._persona.version if self._persona is not None else 1
        persona_dimensions = self._persona.dimensions if self._persona is not None else ()
        persona_dimension_names = {dimension.dimension for dimension in persona_dimensions}
        current_affect = tuple(
            sorted(
                (
                    state
                    for state in self._canonical.values()
                    if state.dimension in persona_dimension_names
                    and state.scope == (projection_scope or turn.interaction.scope)
                    and isinstance(state.value, (int, float))
                    and not isinstance(state.value, bool)
                ),
                key=lambda state: state.dimension,
            )
        )
        elapsed = timedelta(0)
        if current_affect:
            latest_affect_update = max(state.updated_at for state in current_affect)
            if latest_affect_update > now:
                raise ValueError("current affect updated_at must not be in the future")
            elapsed = now - latest_affect_update
        # C10-B-W Seam B: attempt to invoke HomeostasisGate via transition_with_gate.
        # transition_with_gate is only available on EngineEmotionalTransitionPort
        # (not on StubEmotionalTransition). Backward compatibility: if not available,
        # fall back to plain transition().
        transition_input = EmotionalTransitionInput(
            interaction_id=turn.interaction.interaction_id,
            scope=turn.interaction.scope,
            origin_runtime_id=self._runtime_id,
            context=situation,
            current_affect=current_affect,
            elapsed=elapsed,
            persona_id=persona_id,
            persona_version=persona_version,
            persona=persona_dimensions,
            observations=turn.observations,
            semantic_candidates=(),
            history_context=situation.historical_context,
            clock=now,
            projection_scope=projection_scope,
        )
        if hasattr(self.emotional_transition, "transition_with_gate"):
            outcome = self.emotional_transition.transition_with_gate(transition_input)
            transition_result = outcome.transition_result
            turn.slow_decisions = outcome.slow_decisions
        else:
            transition_result = self.emotional_transition.transition(transition_input)
            turn.slow_decisions = ()
        projected = transition_result.projected
        turn.transition_result = transition_result
        turn.projected = projected
        surface_result = project_surface_for_cognition(
            surface_port=self.surface_projection_port,
            persona=self._persona,
            projected=projected,
            runtime_id=self._runtime_id,
            scope=projected.scope,
            interaction_or_tick_ref=f"interaction:{turn.interaction.interaction_id}",
        )
        turn.surface = surface_result
        intent_result = self.intent_engine.evaluate(
            IntentEngineInput(
                interaction_id=turn.interaction.interaction_id,
                scope=turn.interaction.scope,
                origin_runtime_id=self._runtime_id,
                context=situation,
                projected=projected,
                accepted_events=transition_result.accepted_events,
                clock=now,
                surface=surface_result,
                persona_version=self._persona.version if self._persona is not None else None,
                persona_content_digest=(
                    self._persona.persona_content_digest if self._persona is not None else None
                ),
            )
        )
        for candidate in intent_result.candidates:
            if candidate.scope != turn.interaction.scope:
                raise ValueError("candidate Intent scope must match interaction scope")
            if candidate.origin_runtime_id != self._runtime_id:
                raise ValueError("candidate Intent origin must match runtime")
            if not self.intent_lifecycle.is_initial_candidate(candidate):
                raise ValueError("intent engine must return version-one candidate Intents")
        turn.intent_traces = intent_result.traces
        for score_trace in intent_result.traces:
            if score_trace.scope != turn.interaction.scope:
                raise ValueError("Intent score trace scope must match interaction scope")
            if score_trace.surface_admission is not None and not score_trace.admitted:
                self._trace.record(
                    turn.interaction.interaction_id,
                    "initiative_gate_rejected",
                    ref=score_trace.intent_id,
                    outcome=score_trace.surface_admission.outcome,
                    at=now,
                )

        admitted = tuple(
            self.intent_lifecycle.admit(candidate) for candidate in intent_result.candidates
        )
        turn.admitted_intent_refs = tuple(candidate.intent_id for candidate in admitted)
        policy_results: list[ActionPolicyResult] = []
        selected: Intent | None = None
        for index, candidate in enumerate(admitted):
            if candidate.expires_at is not None and candidate.expires_at <= now:
                self.intent_lifecycle.transition(
                    candidate.scope,
                    candidate.intent_id,
                    IntentStatus.EXPIRED,
                    ("expired_before_policy",),
                    now,
                    f"orchestrator-expire-{candidate.intent_id}-v{candidate.sync.version}",
                )
                continue
            policy_result = self.action_policy.policy(
                ActionPolicyInput(
                    intent=candidate,
                    context=situation,
                    scope=turn.interaction.scope,
                    clock=now,
                    resources=self.policy_resources,
                )
            )
            if (
                policy_result.scope != turn.interaction.scope
                or policy_result.origin_runtime_id != self._runtime_id
                or policy_result.intent_id != candidate.intent_id
            ):
                raise ValueError("ActionPolicyResult must match candidate, scope, and runtime")
            policy_results.append(policy_result)
            if policy_result.decision is ActionDecision.DEFER:
                self.intent_lifecycle.transition(
                    candidate.scope,
                    candidate.intent_id,
                    IntentStatus.DEFERRED,
                    policy_result.reason_codes,
                    now,
                    f"policy-defer-{candidate.intent_id}-v{candidate.sync.version}",
                )
                continue
            if policy_result.decision is ActionDecision.DENY:
                self.intent_lifecycle.transition(
                    candidate.scope,
                    candidate.intent_id,
                    IntentStatus.BLOCKED,
                    policy_result.reason_codes,
                    now,
                    f"policy-block-{candidate.intent_id}-v{candidate.sync.version}",
                )
                continue
            selected = self.intent_lifecycle.transition(
                candidate.scope,
                candidate.intent_id,
                IntentStatus.ALLOWED,
                policy_result.reason_codes,
                now,
                f"policy-allow-{candidate.intent_id}-v{candidate.sync.version}",
            )
            for lower in admitted[index + 1 :]:
                self.intent_lifecycle.transition(
                    lower.scope,
                    lower.intent_id,
                    IntentStatus.SUPERSEDED,
                    ("lower_than_selected_candidate",),
                    now,
                    f"policy-supersede-{lower.intent_id}-v{lower.sync.version}",
                )
            break

        turn.policy_results = tuple(policy_results)
        turn.policy_result = policy_results[-1] if policy_results else None
        turn.intent = selected
        # D5.2: assemble the uncommitted TurnProjection. Projection is never
        # canonical: only commit_turn may promote it.
        turn.projection = self._build_projection(
            turn,
            effective_state_before=effective,
            situation_ref=situation.situation_id,
            assessment_trace_ref=transition_result.assessment_trace.trace_id,
            now=now,
        )
        self._trace.record(
            turn.interaction.interaction_id,
            "process",
            ref=situation.situation_id,
            at=now,
        )
        # D5.6 trace: the causal chain continues into the projection.
        self._trace.record(
            turn.interaction.interaction_id,
            "projection",
            ref=turn.projection.projection_id,
            at=now,
        )

        if selected is None:
            return

        selected_policy_result = turn.policy_result
        assert selected_policy_result is not None
        assert selected_policy_result.permission is not None
        permission = selected_policy_result.permission
        intent = selected
        previous = self.previous_expression.previous(
            scope=turn.interaction.scope,
            action_type=permission.action_type,
        )
        # C10-C1: read authoritative slow-state from SQLite.  Scope is the
        # AGENT scope (per ADR-0017 / _derive_slow_scope).  Empty tuple
        # when no registered slow dimensions are present (production D11S
        # config has zero agent.slow.* definitions).
        slow_scope = self._derive_slow_scope(turn)
        slow_state_records = self._read_slow_state_records(slow_scope)
        compiler_mode = "LEGACY"
        if hasattr(self.decision_context_compiler, "_config"):
            compiler_mode = getattr(self.decision_context_compiler._config, "mode", "LEGACY")
        compiler_input = DecisionContextCompilerInput(
            interaction_id=turn.interaction.interaction_id,
            scope=turn.interaction.scope,
            origin_runtime_id=self._runtime_id,
            situation=situation,
            effective_user_state=effective,
            projected_agent_state=projected,
            assessment_trace_ref=transition_result.assessment_trace.trace_id,
            intent=intent,
            policy_result=selected_policy_result,
            persona_ref=persona_id,
            prior_expression=previous,
            attempt=0,
            rewrite_reason_codes=(),
            slow_state_records=slow_state_records,
            state_definitions=self._definitions,
            accepted_appraisals=transition_result.accepted_appraisals,
            surface=getattr(turn, "surface", None),
            persona_version=self._persona.version if self._persona is not None else None,
            persona_content_digest=(
                self._persona.persona_content_digest if self._persona is not None else None
            ),
            mode=compiler_mode,
        )
        context, compile_trace = self.decision_context_compiler.compile(compiler_input)
        turn.decision_context = context
        self._trace.record(
            turn.interaction.interaction_id,
            "expression_context",
            ref=context.context_id,
            at=now,
        )
        self._trace.record(
            turn.interaction.interaction_id,
            "expression_compile",
            ref=compile_trace.trace_id,
            at=now,
        )

        if compiler_mode == "SURFACE_V1":
            import hashlib
            from mind_runtime.delivery import DeliveryRequest, SurfaceHandoffProvenance
            from mind_runtime.delivery.state import DeliveryLifecycleState
            from mind_runtime.expression.expression_map import (
                CANDIDATE_MAP_DIGEST, CANDIDATE_MAP_ID, CANDIDATE_MAP_VERSION,
            )

            if self._surface_delivery_backend is None or surface_result is None:
                raise ValueError("SURFACE_V1 requires durable C7 handoff and Surface")
            if not surface_result.is_available:
                raise ValueError("SURFACE_V1 cannot hand off unavailable Surface")
            rendered = self.context_renderer.render(context)
            guidance = tuple(sorted(
                (item.key, item.value) for item in context.expression_context
                if item.kind is ExpressionContextKind.SURFACE_GUIDANCE
            ))
            controls = surface_result.controls
            handoff_id = f"surface-handoff-{turn.interaction.interaction_id}"
            provenance = SurfaceHandoffProvenance(
                context_id=context.context_id,
                intent_id=intent.intent_id,
                action_type=permission.action_type,
                policy_id=selected_policy_result.policy_id,
                policy_constraints=tuple(permission.constraints),
                controls_id=controls["controls_id"],
                recipe_ref=(
                    f"{controls['recipe_id']}:{controls['recipe_version']}:{controls['recipe_digest']}"
                ),
                expression_map_ref=(
                    f"{CANDIDATE_MAP_ID}:{CANDIDATE_MAP_VERSION}:{CANDIDATE_MAP_DIGEST}"
                ),
                qualitative_guidance=guidance,
                intent_surface_use_ref=(
                    intent.surface_use.trace_id if intent.surface_use is not None else "none"
                ),
                render_id=rendered.render_id,
                logical_attempt_id=f"provider-attempt-{handoff_id}",
                envelope_digest=hashlib.sha256(rendered.text.encode("utf-8")).hexdigest(),
            )
            request = DeliveryRequest(
                request_id=handoff_id,
                message_id=handoff_id,
                scope=turn.interaction.scope,
                origin_runtime_id=self._runtime_id,
                channel="body_provider_context",
                target="body",
                action_type=permission.action_type,
                payload_bytes=rendered.text.encode("utf-8"),
                created_at=now,
                sync=SyncFields(
                    turn.interaction.scope, self._runtime_id, handoff_id, 1,
                    f"idem-{handoff_id}",
                ),
                surface_handoff=provenance,
            )
            self._surface_delivery_backend.record_request(
                request, lifecycle_state=DeliveryLifecycleState.PENDING
            )
            turn.surface_handoff_request_id = handoff_id
            self.state = TurnState.DISPATCHING
            return

        self.state = TurnState.DISPATCHING
        try:
            outcome = self.expression_coordinator.express(context)
        except AgentFailure:
            self.state = TurnState.ABORTED
            self._trace.record(
                turn.interaction.interaction_id,
                "abort",
                outcome="agent_failure",
                at=self._clock.now(),
            )
            raise
        turn.expression_outcome = outcome
        accepted = outcome.final_disposition is ExpressionDisposition.ACCEPT
        receipt = ActionReceipt(
            receipt_id=f"receipt-{turn.interaction.interaction_id}",
            scope=turn.interaction.scope,
            origin_runtime_id=self._runtime_id,
            action_intent_id=intent.intent_id,
            delivery_status=(DeliveryStatus.SENT if accepted else DeliveryStatus.UNSENT),
            outcome=outcome.accepted_expression if accepted else None,
            received_at=self._clock.now(),
            sync=SyncFields(
                turn.interaction.scope,
                self._runtime_id,
                f"receipt-{turn.interaction.interaction_id}",
                1,
                f"idem-receipt-{turn.interaction.interaction_id}",
            ),
        )
        turn.action_receipt = receipt
        # D5.5: record the receipt idempotently for later reconcile.
        if self._receipts is not None:
            self._receipts.record(receipt)
        # D5.4: checkpoint the dispatched stage for restart recovery.
        self._checkpoint(
            turn,
            stage=TurnStage.DISPATCHING,
            receipt=receipt,
            now=self._clock.now(),
        )
        self._trace.record(
            turn.interaction.interaction_id,
            "expression",
            ref=outcome.outcome_id,
            outcome=outcome.final_disposition.value,
            at=self._clock.now(),
        )
        self._trace.record(
            turn.interaction.interaction_id,
            "dispatch",
            ref=receipt.receipt_id,
            outcome=receipt.delivery_status.value,
            at=self._clock.now(),
        )

    def commit_turn(self) -> None:
        try:
            self._commit_turn_admitted()
        finally:
            # MR-RUNTIME-05: the namespace admission lease spans exactly the
            # turn lifecycle. Released on success AND on failure — a failed
            # admission must never wedge the namespace (the host adapter
            # aborts the turn; abort's release is idempotent).
            self._release_admission_lease()

    def _prepare_appraisal_receipts(
        self, turn: _Turn, slow_plans: tuple[Any, ...]
    ) -> tuple[ApplicationReceipt, ...]:
        transition = turn.transition_result
        if transition is None or not transition.accepted_appraisals:
            return ()
        journal = getattr(self.emotional_transition, "projection_journal", None)
        if journal is None:
            raise CanonicalPersistenceError("accepted appraisal has no derived journal")
        receipts: list[ApplicationReceipt] = []
        for acceptance, projection_ref in zip(
            transition.accepted_appraisals, transition.projection_refs, strict=True
        ):
            if (
                not acceptance.valid_lineage()
                or acceptance.interaction_id != turn.interaction.interaction_id
                or acceptance.candidate.scope != turn.interaction.scope
                or acceptance.candidate.origin_runtime_id != self._runtime_id
                or acceptance.projection_scope != transition.projected.scope
            ):
                raise CanonicalPersistenceError("cross-interaction appraisal application rejected")
            projection = journal.get_projection(projection_ref)
            if (
                projection is None
                or journal.get_acceptance(acceptance.acceptance_id) != acceptance
                or projection.source_appraisal_ref != acceptance.appraisal.appraisal_id
                or projection.source_candidate_ref != acceptance.candidate.candidate_id
            ):
                raise CanonicalPersistenceError(
                    "projection or accepted source is not journal-resolvable"
                )
            if projection.status is not ProjectionStatus.MAPPED:
                continue
            projector = getattr(self.emotional_transition, "_projector", None)
            if projector is None:
                raise CanonicalPersistenceError("one AppraisalProjector is required")
            projector.validate_materialized_result(projection, acceptance=acceptance)
            authorized_effects = tuple(
                effect for effect in projection.effects
                if effect.operation == "delta"
                or any(
                    decision.candidate.source_event_ref == effect.source_ref
                    and decision.candidate.target_dimension == effect.dimension
                    and decision.decision.value == "slow_accept"
                    for decision in turn.slow_decisions
                )
            )
            accepted_slow = tuple(
                decision for decision in turn.slow_decisions
                if decision.decision.value == "slow_accept"
                and any(
                    effect.operation == "proposed_value"
                    and decision.candidate.source_event_ref == effect.source_ref
                    and decision.candidate.target_dimension == effect.dimension
                    for effect in projection.effects
                )
            )
            if accepted_slow:
                if (
                    self._slow_writer is None
                    or getattr(self._slow_writer, "_backend", None) is not self._state_backend
                    or any(
                        not any(
                            plan.target_dimension == decision.candidate.target_dimension
                            and row["source_event_ref"] == decision.candidate.source_event_ref
                            for plan in slow_plans for row in plan.new_rows
                        )
                        for decision in accepted_slow
                    )
                ):
                    raise CanonicalPersistenceError(
                        "accepted appraisal Slow effect has no shared canonical flush plan"
                    )
            if not authorized_effects:
                continue
            if not isinstance(self._state_backend, SqliteStateBackend) or not (
                isinstance(self.commit_marker_store, SqliteCommitMarkerStore)
                and self.commit_marker_store._conn is self._state_backend.connection
            ):
                raise CanonicalPersistenceError(
                    "appraisal application requires shared canonical transaction and marker"
                )
            group_id = "group-" + digest((projection.admission_mode, authorized_effects))
            receipts.append(
                ApplicationReceipt(
                    application_id=application_identity(
                        self._runtime_id, acceptance.acceptance_id,
                        group_id, turn.interaction.interaction_id,
                    ),
                    projection_id=projection.projection_id,
                    acceptance_id=acceptance.acceptance_id,
                    interaction_id=turn.interaction.interaction_id,
                    effect_group_id=group_id,
                    runtime_id=self._runtime_id,
                    scope=transition.projected.scope,
                    status=ApplicationStatus.EVALUATED,
                    commit_ref=None,
                    transition_refs=(),
                )
            )
        return tuple(receipts)

    def _publish_committed_states(
        self, projected_states: tuple[RuntimeState, ...], slow_plans: tuple[Any, ...]
    ) -> None:
        for projected_state in projected_states:
            for old_id in [
                state_id for state_id, current in self._canonical.items()
                if current.scope == projected_state.scope
                and current.dimension == projected_state.dimension
            ]:
                del self._canonical[old_id]
            self._canonical[projected_state.state_id] = projected_state
        if slow_plans and hasattr(self._slow_writer, "apply_flush_plan"):
            slow_states = self._slow_writer.apply_flush_plan(slow_plans)
            for state in slow_states:
                for old_id in [
                    state_id for state_id, current in self._canonical.items()
                    if current.scope == state.scope and current.dimension == state.dimension
                ]:
                    del self._canonical[old_id]
                self._canonical[state.state_id] = state

    def _commit_turn_admitted(self) -> None:
        turn = self._require_turn()
        _mr_thread_trace("ORCH_COMMIT_ENTRY", self, turn.interaction.interaction_id)
        # D5.3 UnitOfWork commit: facts were already committed at ingest
        # (they survive abort); this commit promotes only the projected mind
        # transition to canonical. A commit without a successful run()
        # promotes nothing (fail-safe).
        if turn.projection is not None:
            # Optimistic staleness validation: the projection was computed
            # against the canonical version at run(); if canonical moved on
            # (e.g. another writer committed facts), the projection is
            # stale and must not be promoted silently.
            current_version = max((state.version for state in self._canonical.values()), default=1)
            if current_version != self._base_state_version:
                raise StaleProjectionError(
                    f"projection base version {self._base_state_version} is stale "
                    f"(canonical is at {current_version})"
                )
            # D5.4: mark awaiting_commit before promoting — a restart in
            # between must never treat the projection as committed.
            self._checkpoint(
                turn,
                stage=TurnStage.AWAITING_COMMIT,
                receipt=turn.action_receipt,
                now=self._clock.now(),
            )
            projected_states = turn.projection.projected_mind_state.projected_states
            # MR-RUNTIME-05 §10: a commit for an interaction that ALREADY has
            # an authoritative marker is an admitted-turn replay. The
            # longitudinal slow-write seam below is part of THE admission and
            # must run exactly once per interaction — replays re-derive
            # decisions from evolved accumulator state and would otherwise
            # double-write longitudinal state.
            interaction_replay = (
                self.commit_marker_store is not None
                and self.commit_marker_store.has_commit(
                    interaction_id=turn.interaction.interaction_id,
                    scope=turn.interaction.scope,
                )
            )
            if interaction_replay:
                self._drop_checkpoint(turn.interaction.interaction_id)
                self.state = TurnState.COMMITTED
                return

            slow_scope = None
            slow_plans: tuple[Any, ...] = ()
            accepted: list[Any] = []
            routable: list[Any] = []
            appraisal_receipts: tuple[ApplicationReceipt, ...] = ()

            try:
                # 1. Stage slow transient inputs
                if self._slow_writer is not None and turn.slow_decisions and not interaction_replay:
                    accepted = [
                        d for d in turn.slow_decisions
                        if d.decision.value == "slow_accept"
                    ]
                    slow_scope = self._derive_slow_scope(turn)
                    from mind_runtime.state.longitudinal import resolve_longitudinal_target

                    for decision in accepted:
                        try:
                            resolve_longitudinal_target(
                                self._definitions,
                                decision.candidate.target_dimension,
                            )
                            routable.append(decision)
                        except ValueError:
                            # BW-ONTO-2: fail closed — skip unregistered targets.
                            continue
                    for decision in routable:
                        self._slow_writer.accept(decision, target_scope=slow_scope)
                    if routable:
                        if hasattr(self._slow_writer, "prepare_flush"):
                            slow_plans = self._slow_writer.prepare_flush(slow_scope)
                        else:
                            slow_plans = ()

                appraisal_receipts = self._prepare_appraisal_receipts(turn, slow_plans)

                # 2. Atomic durable transaction
                tx_context = (
                    self._state_backend.transaction()
                    if self._state_backend is not None
                    and hasattr(self._state_backend, "transaction")
                    else nullcontext()
                )
                with tx_context:
                    if appraisal_receipts:
                        assert isinstance(self._state_backend, SqliteStateBackend)
                        for receipt in appraisal_receipts:
                            self._state_backend.stage_application_receipt(
                                _replace(receipt, status=ApplicationStatus.PENDING)
                            )
                    if self._state_backend is not None:
                        for projected_state in projected_states:
                            self._persist_state_idempotent(projected_state)
                        for intent in turn.projection.transition_intents:
                            transition_id = f"transition:{intent.proposed_after.state_id}"
                            self._state_backend.save_state(intent.before)
                            self._persist_transition_idempotent(
                                StateTransition(
                                    transition_id=transition_id,
                                    scope=intent.scope,
                                    origin_runtime_id=self._runtime_id,
                                    intent_id=intent.intent_id,
                                    from_state=intent.before,
                                    to_state=intent.proposed_after,
                                    committed_at=self._clock.now(),
                                    sync=SyncFields(
                                        intent.scope,
                                        self._runtime_id,
                                        transition_id,
                                        1,
                                        f"idem-{transition_id}",
                                    ),
                                )
                            )

                    # Execute slow plans inside transaction
                    if slow_plans:
                        for plan in slow_plans:
                            self._slow_writer.execute_flush_plan(plan)
                    elif routable and hasattr(self._slow_writer, "flush"):
                        self._slow_writer.flush(slow_scope)

                    # Record commit marker (LAST durable write)
                    if self.commit_marker_store is not None:
                        if not self.commit_marker_store.record_commit(
                            interaction_id=turn.interaction.interaction_id,
                            scope=turn.interaction.scope,
                            committed_at=self._clock.now(),
                            projected_state_ids=tuple(state.state_id for state in projected_states),
                            commit=False,
                        ) and not self.commit_marker_store.has_commit(
                            interaction_id=turn.interaction.interaction_id,
                            scope=turn.interaction.scope,
                        ):
                            raise CanonicalPersistenceError(
                                f"commit marker for {turn.interaction.interaction_id} "
                                "was not recorded (storage failure); refusing to "
                                "report a successful admission (MR-RUNTIME-05 §10)"
                            )
                    if appraisal_receipts:
                        assert isinstance(self._state_backend, SqliteStateBackend)
                        committed_refs = tuple(state.state_id for state in projected_states)
                        committed_refs += tuple(plan.state.state_id for plan in slow_plans)
                        for receipt in appraisal_receipts:
                            self._state_backend.commit_application_receipt(
                                _replace(
                                    receipt,
                                    status=ApplicationStatus.COMMITTED,
                                    commit_ref=f"commit:{turn.interaction.interaction_id}",
                                    transition_refs=committed_refs,
                                )
                            )

            except BaseException as exc:
                for receipt in appraisal_receipts:
                    aborted = _replace(receipt, status=ApplicationStatus.ABORTED)
                    self._trace.record(
                        turn.interaction.interaction_id,
                        "application_aborted",
                        ref=aborted.application_id,
                        at=self._clock.now(),
                    )
                if self._slow_writer is not None and slow_scope is not None:
                    if hasattr(self._slow_writer, "discard_pending"):
                        self._slow_writer.discard_pending(slow_scope)
                if not isinstance(exc, CanonicalPersistenceError):
                    raise CanonicalPersistenceError(
                        "atomic cognitive admission failed for "
                        f"{turn.interaction.interaction_id}: {exc}"
                    ) from exc
                raise

            # 3. Publish only after COMMIT. A publication failure cannot undo
            # the durable receipt; reload from the committed backend and expose
            # an explicit recovery event to the caller/audit trace.
            try:
                self._publish_committed_states(projected_states, slow_plans)
            except Exception as exc:
                self._refresh_canonical_from_backend()
                self.state = TurnState.COMMITTED
                self._trace.record(
                    turn.interaction.interaction_id,
                    "post_commit_publication_failed",
                    outcome="reloaded_from_canonical",
                    at=self._clock.now(),
                )
                raise CanonicalPersistenceError(
                    f"post-commit publication failed for {turn.interaction.interaction_id}; "
                    "canonical state reloaded from durable commit"
                ) from exc

            # Telemetry (best-effort, fail-open)
            if self._telemetry_sink is not None:
                try:
                    for intent in turn.projection.transition_intents:
                        before_val = (
                            float(intent.before.value)
                            if isinstance(intent.before.value, (int, float))
                            else 0.0
                        )
                        after_val = (
                            float(intent.proposed_after.value)
                            if isinstance(intent.proposed_after.value, (int, float))
                            else 0.0
                        )
                        delta = round(after_val - before_val, 4)
                        self._telemetry_sink.record(
                            interaction_id=turn.interaction.interaction_id,
                            stage=TelemetryStage.STATE_TRANSITION,
                            status="COMMITTED",
                            occurred_at=self._clock.now(),
                            payload={
                                "dimension": intent.proposed_after.dimension,
                                "before": before_val,
                                "after": after_val,
                                "delta": delta,
                                "version": intent.proposed_after.version,
                                "from_state_id": intent.before.state_id,
                                "to_state_id": intent.proposed_after.state_id,
                                "evidence_refs": list(intent.proposed_after.evidence_refs),
                            },
                            source_refs=intent.proposed_after.evidence_refs,
                        )
                except Exception:
                    pass

                if routable:
                    try:
                        for decision in routable:
                            self._telemetry_sink.record(
                                interaction_id=turn.interaction.interaction_id,
                                stage=TelemetryStage.SLOW_WRITE,
                                status="COMMITTED",
                                occurred_at=self._clock.now(),
                                payload={
                                    "target_dimension": decision.candidate.target_dimension,
                                    "target_scope": str(slow_scope),
                                    "window_size": getattr(
                                        self._slow_writer, "_window_size", None
                                    ),
                                    "flush_status": "flushed",
                                    "decision_id": decision.decision_id,
                                },
                                source_refs=tuple(decision.candidate.evidence_refs),
                            )
                    except Exception:
                        pass

            if self._slow_writer is not None and turn.slow_decisions and not interaction_replay:
                self._trace.record(
                    turn.interaction.interaction_id,
                    "slow_plasticity",
                    ref=f"slow-{turn.interaction.interaction_id}",
                    outcome=f"{len(accepted)}_slow_accept",
                    at=self._clock.now(),
                )
        self._drop_checkpoint(turn.interaction.interaction_id)
        self.state = TurnState.COMMITTED
        if self._telemetry_sink is not None:
            try:
                self._telemetry_sink.record(
                    interaction_id=turn.interaction.interaction_id,
                    stage=TelemetryStage.TURN_COMMIT,
                    status="COMMITTED",
                    occurred_at=self._clock.now(),
                    payload={"status": "committed"},
                    source_refs=(),
                )
            except Exception:
                pass
        self._trace.record(
            turn.interaction.interaction_id,
            "commit",
            at=self._clock.now(),
        )

    def abort_turn(self) -> None:
        try:
            self._abort_turn_admitted()
        finally:
            # MR-RUNTIME-05: release the namespace admission lease. Idempotent
            # with commit_turn's release (whichever terminal path runs first).
            self._release_admission_lease()

    def _abort_turn_admitted(self) -> None:
        turn = self._require_turn()
        _mr_thread_trace("ORCH_ABORT_ENTRY", self, turn.interaction.interaction_id)
        # D5.3 UnitOfWork abort: the projection is discarded; ingested facts
        # stay committed (G13b). The turn's derived state never touched
        # canonical before this point.
        self.factual_overlay = {}
        self._drop_checkpoint(turn.interaction.interaction_id)
        if self._slow_writer is not None:
            slow_scope = self._derive_slow_scope(turn)
            if hasattr(self._slow_writer, "discard_pending"):
                self._slow_writer.discard_pending(slow_scope)
        self.state = TurnState.ABORTED
        if self._telemetry_sink is not None:
            try:
                self._telemetry_sink.record(
                    interaction_id=turn.interaction.interaction_id,
                    stage=TelemetryStage.TURN_ABORT,
                    status="ABORTED",
                    occurred_at=self._clock.now(),
                    payload={"outcome": "aborted"},
                    source_refs=(),
                )
            except Exception:
                pass
        self._trace.record(
            turn.interaction.interaction_id,
            "abort",
            outcome="manual",
            at=self._clock.now(),
        )
        # C9-W1B: drop all pending items from the aborted turn.
        if self._pending_overlay is not None:
            cleared = self._pending_overlay.clear_on_turn_abort(
                turn.interaction.interaction_id
            )
            if cleared > 0:
                self._trace.record(
                    turn.interaction.interaction_id,
                    "abort.pending_clear",
                    outcome=f"{cleared} items dropped",
                    at=self._clock.now(),
                )

    def accept_pending(self, pending_id: str) -> Observation | None:
        """Promote a PENDING item to canonical via fact_ingest.admit().

        Creates a new Evidence from the pending item's stored source_text and
        calls fact_ingest.admit() (the canonical admission path). Removes the
        item from the pending overlay. Returns the resulting Observation, or
        None if the pending_id was not found.

        Raises ValueError if the item is not in PENDING status.
        """
        if self._pending_overlay is None:
            raise ValueError("pending_overlay is not set on this orchestrator")
        pending = self._pending_overlay.get_by_pending_id(pending_id)
        if pending is None:
            return None
        if pending.status is not PendingStatus.PENDING:
            raise ValueError(
                f"accept_pending requires PENDING status; got {pending.status.value}"
            )
        # Synthesize an Evidence from the pending item's stored source text.
        # Uses the pending item's scope; if the canonical path was not called
        # with a scope, we fall back to the orchestrator's writing persona.
        # The source_type is "user_message" because the pending item represents
        # a user utterance that has now been admitted; the authority boundary
        # is "user tells MR about their sister".
        evidence = Evidence(
            id=pending.evidence_ref,
            source_type="user_message",
            source_id=pending.pending_id,
            authority_level=AuthorityLevel.ASSERTED,
            occurred_at=pending.created_at,
            received_at=pending.created_at,
            payload=pending.source_text,
            scope=pending.scope,
            origin_runtime_id=pending.origin_runtime_id,
            authority=Authority(
                scope=pending.scope,
                level=AuthorityLevel.ASSERTED,
                source_id=pending.pending_id,
            ),
            sync=SyncFields(
                scope=pending.scope,
                origin_runtime_id=pending.origin_runtime_id,
                object_id=pending.evidence_ref,
                version=1,
                idempotency_key=f"pending:{pending.pending_id}",
            ),
        )
        result = self.fact_ingest.admit(
            evidence,
            interaction_id=pending.source_turn_id,
            writing_runtime=(
                pending.scope.agent_id
                if pending.scope.domain == ScopeDomain.AGENT
                else self._runtime_id
            ),
            writing_persona_id=pending.scope.persona_id,
        )
        # Remove from pending overlay (the ACCEPTED status is tracked by overlay accept())
        self._pending_overlay.accept(pending_id)
        return result.observation

    def reject_pending(self, pending_id: str) -> bool:
        """Reject a PENDING item without canonical promotion.

        Removes the item from the pending overlay. Returns True if the item
        was found, False if not.

        Raises ValueError if the item is not in PENDING status.
        """
        if self._pending_overlay is None:
            raise ValueError("pending_overlay is not set on this orchestrator")
        pending = self._pending_overlay.get_by_pending_id(pending_id)
        if pending is None:
            return False
        if pending.status is not PendingStatus.PENDING:
            raise ValueError(
                f"reject_pending requires PENDING status; got {pending.status.value}"
            )
        self._pending_overlay.reject(pending_id)
        return True

    def recover(self, interaction_id: str) -> RecoveryDecision:
        """Decide what a restart may do with a checkpointed turn (D5.4)."""
        checkpoint = (
            self._checkpoints.load(interaction_id) if self._checkpoints is not None else None
        )
        return recovery_decision(checkpoint)

    def reconcile(self, action_intent_id: str) -> ReceiptOutcome:
        """Reconcile the delivery state of one action intent (D5.5)."""
        if self._receipts is None:
            return ReceiptOutcome(
                action_intent_id=action_intent_id,
                delivery_status=DeliveryStatus.UNSENT,
                reconciled=False,
                reason="no_registry",
            )
        outcome = self._receipts.reconcile(action_intent_id)
        if outcome.reconciled and outcome.delivery_status is DeliveryStatus.SENT:
            current = next(
                (
                    intent
                    for intent in self.intent_lifecycle.backend.current(
                        self._require_turn().interaction.scope
                    )
                    if intent.intent_id == action_intent_id
                ),
                None,
            )
            if current is not None and self.intent_lifecycle.has_status(
                current, IntentStatus.ALLOWED
            ):
                self.intent_lifecycle.transition(
                    current.scope,
                    current.intent_id,
                    IntentStatus.COMPLETED,
                    ("delivery_reconciled_sent",),
                    self._clock.now(),
                    f"receipt-complete-{current.intent_id}-v{current.sync.version}",
                )
        return outcome

    def _checkpoint(
        self,
        turn: _Turn,
        *,
        stage: TurnStage,
        receipt: ActionReceipt | None,
        now: datetime,
    ) -> None:
        if self._checkpoints is None:
            return
        projection_ref = turn.projection.projection_id if turn.projection is not None else "none"
        checkpoint_id = f"checkpoint-{turn.interaction.interaction_id}"
        self._checkpoints.save(
            TurnCheckpoint(
                checkpoint_id=checkpoint_id,
                interaction_id=turn.interaction.interaction_id,
                scope=turn.interaction.scope,
                origin_runtime_id=self._runtime_id,
                stage=stage,
                base_state_version=max(
                    (state.version for state in self._canonical.values()), default=1
                ),
                projection_ref=projection_ref,
                action_id=receipt.action_intent_id if receipt is not None else None,
                delivery_status=(
                    receipt.delivery_status if receipt is not None else DeliveryStatus.UNSENT
                ),
                checkpointed_at=now,
                sync=SyncFields(
                    turn.interaction.scope,
                    self._runtime_id,
                    checkpoint_id,
                    1,
                    f"idem-{checkpoint_id}",
                ),
            )
        )

    def _drop_checkpoint(self, interaction_id: str) -> None:
        if self._checkpoints is not None:
            self._checkpoints.remove(interaction_id)

    def _ingest_commit(self, turn: _Turn, *, now: datetime) -> None:
        """Reconcile this turn's dimension-typed observations into canonical.

        Only observations that follow the typed convention
        (``<domain>.<name>.observed`` / ``.<terminal>``) produce state
        changes; source-typed observations (semantic extraction pending in
        D8) leave canonical untouched. The committed records are exposed as
        ``overlay`` for read-your-writes inspection.
        """
        intents = tuple(
            intent
            for observation in turn.observations
            if (intent := interpret_observation(observation)) is not None
        )
        if not intents:
            self._overlay = ()
            self._ingest_transitions = ()
            return
        reconciler = FactualReconciler(clock=self._clock, definitions=self._definitions)
        result = reconciler.apply(self.canonical, intents)
        base_ids = set(self._canonical)
        # D5.8: ingest-committed facts are durable immediately (they survive
        # a cognitive abort — G13b — and a restart). The durable table is
        # append-only history: every state a transition references is
        # persisted too (superseded intermediate records are not part of
        # the effective set) so load_transitions can resolve full chains.
        # MR-RUNTIME-05 §9: persist the ingest-committed states BEFORE
        # advancing memory; a persistence failure fails the turn loudly
        # instead of silently losing the write behind a success signal.
        if self._state_backend is not None:
            for state in result.effective:
                # MR-RUNTIME-05 §9: a NEW state (not in the pre-turn
                # canonical base) must durably insert — a conflicting
                # duplicate fails the turn loudly. An UNCHANGED state
                # carried through the reconciler's full-snapshot effective
                # set is an idempotent re-persist of an already-durable row.
                # (A validity-expiry rewrite of an existing row stays a
                # silent re-persist: pre-existing D4.2 behavior, unchanged.)
                if state.state_id in base_ids:
                    self._state_backend.save_state(state)
                else:
                    self._persist_state_idempotent(state)
            for transition in result.transitions:
                # Idempotent re-persists: from_state is the already-durable
                # prior record; to_state was saved with result.effective.
                self._state_backend.save_state(transition.from_state)
                self._state_backend.save_state(transition.to_state)
                self._persist_transition_idempotent(transition)
        for state in result.effective:
            # One current record per (scope, dimension): drop older versions.
            for old_id in [
                state_id
                for state_id, current in self._canonical.items()
                if current.scope == state.scope and current.dimension == state.dimension
            ]:
                del self._canonical[old_id]
            self._canonical[state.state_id] = state
        self._overlay = tuple(state for state in result.effective if state.state_id not in base_ids)
        self._ingest_transitions = result.transitions
        # D5.6 trace: the causal chain continues into canonical state records.
        for state in self._overlay:
            self._trace.record(
                turn.interaction.interaction_id,
                "state",
                ref=state.state_id,
                at=now,
            )

    def _build_projection(
        self,
        turn: _Turn,
        *,
        effective_state_before: RuntimeState,
        situation_ref: str,
        assessment_trace_ref: str,
        now: datetime,
    ) -> TurnProjection:
        """Assemble the uncommitted TurnProjection for this turn (D5.2).

        The projected mind transition carries a turn_commit-phase
        TransitionIntent only when the projection targets the same dimension
        as the effective state (a real before/after pair); stub projections
        that synthesize a fresh dimension carry no intent until real
        dynamics land (D7).
        """
        assert turn.projected is not None
        projected = turn.projected
        current_by_key = {
            (state.scope, state.dimension): state for state in self._canonical.values()
        }
        transition_intents = tuple(
            build_turn_commit_intent(
                interaction_id=turn.interaction.interaction_id,
                scope=projected_state.scope,
                origin_runtime_id=self._runtime_id,
                target_dimension=projected_state.dimension,
                before=current_by_key[(projected_state.scope, projected_state.dimension)],
                proposed_after=projected_state,
                cause_refs=tuple(observation.id for observation in turn.observations),
                confidence=1.0,
            )
            for projected_state in projected.projected_states
            if (projected_state.scope, projected_state.dimension) in current_by_key
        )
        projection_id = f"projection-{turn.interaction.interaction_id}"
        intent_refs = turn.admitted_intent_refs
        policy_result_ref = turn.policy_result.policy_id if turn.policy_result is not None else None
        return TurnProjection(
            projection_id=projection_id,
            interaction_id=turn.interaction.interaction_id,
            scope=turn.interaction.scope,
            origin_runtime_id=self._runtime_id,
            effective_state_before=effective_state_before,
            observations=turn.observations,
            situation=situation_ref,
            assessment_trace_ref=assessment_trace_ref,
            intent_refs=intent_refs,
            policy_result_ref=policy_result_ref,
            transition_intents=transition_intents,
            projected_mind_state=projected,
            created_at=now,
            sync=SyncFields(
                turn.interaction.scope,
                self._runtime_id,
                projection_id,
                1,
                f"idem-{projection_id}",
            ),
        )


class _DefaultAgent:
    """Fallback agent returning a fixed expression (never fails)."""

    def respond(self, provider_context: ProviderExpressionContext) -> str:
        return "stub response"
