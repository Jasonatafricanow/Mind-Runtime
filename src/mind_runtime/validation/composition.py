"""Manifest-bound composition of the one production Product Slice pipeline."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from mind_runtime.contracts import (
    ActionPolicyResult,
    ActionReceipt,
    EmotionalTransitionResult,
    Evidence,
    HistoricalContextBundle,
    HistoricalContextQuery,
    Intent,
    IntentTransition,
    Interaction,
    Observation,
    PreviousExpression,
    RuntimeState,
    Scope,
    StateDefinition,
    StateTransition,
    TurnCheckpoint,
)
from mind_runtime.dynamics.engine import DynamicsEngine
from mind_runtime.dynamics.ports import EngineEmotionalTransitionPort
from mind_runtime.emotional_transition.appraisal import (
    ConfiguredSemanticAppraisalModel,
    ModelBackedSemanticAppraisalModel,
    SemanticAppraisalProducer,
)
from mind_runtime.emotional_transition.history import (
    BoundedHistoricalContextAdapter,
    HistoricalContextProvider,
    HistoryProviderUnavailable,
)
from mind_runtime.emotional_transition.provider import ChatTransport
from mind_runtime.emotional_transition.projection_journal import ProjectionJournal
from mind_runtime.emotional_transition.semantic import SemanticRouter
from mind_runtime.expression.context import DecisionContextCompiler
from mind_runtime.expression.coordinator import DeterministicExpressionCoordinator
from mind_runtime.expression.guards import DeterministicExpressionGuardChain
from mind_runtime.expression.history import FixedPreviousExpressionPort
from mind_runtime.expression.renderer import DeterministicContextRenderer
from mind_runtime.facts.coordinator import InteractionCoordinator
from mind_runtime.facts.persistence import SqliteFactBackend
from mind_runtime.facts.service import FactIngestService
from mind_runtime.homeostasis.policy import (
    FixedSalienceThresholdConfig,
    SalienceThresholdPolicy,
)
from mind_runtime.intents.engine import DeterministicIntentEngine
from mind_runtime.intents.lifecycle import IntentLifecycleService
from mind_runtime.intents.persistence import SqliteIntentBackend
from mind_runtime.intents.policy import DeterministicActionPolicy
from mind_runtime.intents.scheduler import IntentScheduler
from mind_runtime.pipeline.checkpoints import RecoveryDecision, SqliteCheckpointStore
from mind_runtime.pipeline.orchestrator import TurnOrchestrator
from mind_runtime.pipeline.ports import AgentPort
from mind_runtime.pipeline.receipts import ReceiptRegistry
from mind_runtime.pipeline.trace import TraceRecorder
from mind_runtime.slow_plasticity.writer import SlowPlasticityWriter
from mind_runtime.state.persistence import SqliteCommitMarkerStore, SqliteStateBackend
from mind_runtime.state.ports import ResolverEffectiveStatePort
from mind_runtime.state.resolver import EffectiveStateResolver
from mind_runtime.validation.contracts import (
    CertificationPlan,
    DecisionAuthoritySnapshot,
    DecodedRuntimeConfig,
    RuntimeConfigManifest,
    SimulationEvent,
    decode_horizon_template_bytes,
    decode_runtime_config_manifest_bytes,
    decode_runtime_manifest,
    verify_fixture_artifacts,
)
from mind_runtime.validation.digest import sha256_bytes
from mind_runtime.validation.schedule import SimulationClock

_EXPECTED_TABLES = {
    "facts": ("evidence", "interactions", "observations"),
    "state": (
        "slow_contribution_window",
        "sqlite_sequence",
        "state_definitions",
        "state_transitions",
        "states",
    ),
    "intents": ("intent_transitions", "intents"),
    "checkpoints": ("checkpoints",),
}
_W2_STATE_TABLES = tuple(
    sorted((*_EXPECTED_TABLES["state"], "commit_markers", "application_receipts"))
)


@dataclass(frozen=True, slots=True)
class DurablePaths:
    facts_db: Path
    state_db: Path
    intents_db: Path
    checkpoints_db: Path

    def __post_init__(self) -> None:
        paths = (self.facts_db, self.state_db, self.intents_db, self.checkpoints_db)
        if any(not isinstance(path, Path) for path in paths):
            raise ValueError("durable paths must be Path values")
        if len(set(paths)) != len(paths):
            raise ValueError("durable paths must be distinct")
        if any(path.name in {"receipts.sqlite", "memory.sqlite"} for path in paths):
            raise ValueError("ReceiptRegistry and Memory cannot be durable D11S planes")

    @classmethod
    def under(cls, root: Path) -> DurablePaths:
        return cls(
            facts_db=root / "facts.sqlite",
            state_db=root / "state.sqlite",
            intents_db=root / "intents.sqlite",
            checkpoints_db=root / "checkpoints.sqlite",
        )


@dataclass(frozen=True, slots=True)
class CertificationRuntimeConfig:
    repository_root: Path
    manifest_path: Path
    manifest_sha256: str
    durable_paths: DurablePaths
    clock: SimulationClock
    certification_id: str
    agent: AgentPort
    appraisal_transport: ChatTransport | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.repository_root, Path) or not isinstance(self.manifest_path, Path):
            raise ValueError("repository_root and manifest_path must be Path values")
        if len(self.manifest_sha256) != 64:
            raise ValueError("manifest_sha256 must be a SHA-256 hex digest")
        try:
            int(self.manifest_sha256, 16)
        except ValueError as error:
            raise ValueError("manifest_sha256 must be a SHA-256 hex digest") from error
        if not isinstance(self.durable_paths, DurablePaths):
            raise ValueError("durable_paths must be DurablePaths")
        if not isinstance(self.clock, SimulationClock):
            raise ValueError("clock must be a SimulationClock")
        if not isinstance(self.certification_id, str) or not self.certification_id.strip():
            raise ValueError("certification_id must be non-empty")
        if not isinstance(self.agent, AgentPort):
            raise ValueError("agent must implement AgentPort")
        if self.appraisal_transport is not None and not isinstance(
            self.appraisal_transport, ChatTransport
        ):
            raise ValueError("appraisal_transport must implement ChatTransport")


class _ScheduledHistoricalProvider(HistoricalContextProvider):
    """Expose only the immutable bundle already bound to the current event."""

    def __init__(self) -> None:
        self.current: HistoricalContextBundle | None = None

    def query(self, query: HistoricalContextQuery) -> HistoricalContextBundle:
        bundle = self.current
        if bundle is None:
            raise HistoryProviderUnavailable("scheduled event has no historical context")
        if bundle.scope != query.scope:
            raise ValueError("historical bundle scope must match certification scope")
        return bundle


@dataclass(frozen=True, slots=True)
class _DailyAuthorityRecords:
    """Full read-only authority captured for one semantic daily digest."""

    snapshot: DecisionAuthoritySnapshot
    state_definitions: tuple[StateDefinition, ...]
    canonical_states: tuple[RuntimeState, ...]
    state_transitions: tuple[StateTransition, ...]
    current_intents: tuple[Intent, ...]
    intent_history: tuple[Intent, ...]
    intent_transitions: tuple[IntentTransition, ...]
    transition_results: tuple[EmotionalTransitionResult, ...]
    policy_results: tuple[ActionPolicyResult, ...]
    interactions: tuple[Interaction, ...]
    evidence: tuple[tuple[Evidence, str], ...]
    observations: tuple[Observation, ...]
    receipts: tuple[ActionReceipt, ...]
    checkpoint: TurnCheckpoint | None
    recovery: RecoveryDecision


class CanonicalCertificationComposition:
    """Own one explicitly wired orchestrator and its four durable SQLite planes."""

    def __init__(
        self,
        *,
        config: CertificationRuntimeConfig,
        manifest: RuntimeConfigManifest,
        decoded: DecodedRuntimeConfig,
        fact_backend: SqliteFactBackend,
        state_backend: SqliteStateBackend,
        intent_backend: SqliteIntentBackend,
        checkpoint_store: SqliteCheckpointStore,
        interaction_coordinator: InteractionCoordinator,
        history_provider: _ScheduledHistoricalProvider,
        intent_scheduler: IntentScheduler,
        receipts: ReceiptRegistry,
        orchestrator: TurnOrchestrator,
        components: dict[str, object],
    ) -> None:
        self._config = config
        self._manifest = manifest
        self._decoded = decoded
        self._fact_backend = fact_backend
        self._state_backend = state_backend
        self._intent_backend = intent_backend
        self._checkpoint_store = checkpoint_store
        self._interaction_coordinator = interaction_coordinator
        self._history_provider = history_provider
        self._intent_scheduler = intent_scheduler
        self._receipts = receipts
        self.orchestrator = orchestrator
        self._components = dict(components)
        self._closed = False
        self._last_interaction_id: str | None = None
        self._reject_stub_components()

    def component_inventory(self) -> dict[str, str]:
        self._require_open()
        return {name: component.__class__.__name__ for name, component in self._components.items()}

    def table_inventory(self) -> dict[str, tuple[str, ...]]:
        self._require_open()
        return {
            "facts": self._fact_backend.table_names(),
            "state": self._state_backend.table_names(),
            "intents": self._intent_backend.table_names(),
            "checkpoints": self._checkpoint_store.table_names(),
        }

    def apply_event(self, event: SimulationEvent) -> None:
        self._apply_event(event, include_history=True)

    def _apply_event_without_history(self, event: SimulationEvent) -> None:
        """Apply the exact verified event while withholding its history input."""
        self._apply_event(event, include_history=False)

    def _apply_event(self, event: SimulationEvent, *, include_history: bool) -> None:
        self._require_open()
        if not isinstance(event, SimulationEvent):
            raise ValueError("event must be a SimulationEvent")
        scope = self._event_scope(event)
        interaction_id, session_id, turn_id = self._interaction_ids(event.event_id)
        interaction = self._interaction_coordinator.begin_interaction(
            interaction_id=interaction_id,
            scope=scope,
            channel=self._decoded.fact_ingest.certification_channel,
            session_id=session_id,
            turn_id=turn_id,
        )
        self._history_provider.current = event.historical_context if include_history else None
        self.orchestrator.begin_turn(interaction)
        try:
            for evidence in event.evidence:
                self.orchestrator.ingest(evidence)
            self._interaction_coordinator.processing(interaction)
            self.orchestrator.run()
            self.orchestrator.commit_turn()
            self._interaction_coordinator.commit_interaction(interaction)
        except Exception:
            self.orchestrator.abort_turn()
            self._interaction_coordinator.abort_interaction(interaction)
            raise
        self._last_interaction_id = interaction_id

    def tick(self) -> None:
        self._require_open()
        self._intent_scheduler.tick(
            self._decoded.fact_ingest.certification_scope,
            self._config.clock.now(),
        )

    def _verify_plan(
        self,
        plan: CertificationPlan,
        *,
        excluded_event_ids: frozenset[str] = frozenset(),
    ) -> None:
        """Bind the supplied plan to one verified checked-in horizon artifact.

        The no-duplicate control plan is verified with the named duplicate
        event excluded: the template bytes must still match the manifest and
        every other event must be the exact decoded object. The exclusion is
        only ever the template's ``idempotent_replay`` event (enforced by
        ``certify_horizon``); nothing else may be dropped or altered.
        """
        self._require_open()
        logical_path = f"certification/d11s/inputs/horizon-{plan.horizon_days}.json"
        artifact = next(
            item for item in self._manifest.fixture_artifacts if item.logical_path == logical_path
        )
        try:
            data = (self._config.repository_root / logical_path).read_bytes()
        except OSError as error:
            raise ValueError("verified horizon artifact is unavailable") from error
        if len(data) != artifact.byte_length or sha256_bytes(data) != artifact.bytes_sha256:
            raise ValueError("verified horizon artifact bytes do not match the manifest")
        template = decode_horizon_template_bytes(data)
        expected = CertificationPlan(
            certification_id=template.certification_id,
            source_head=_current_source_head(self._config.repository_root),
            persona_version=template.persona_version,
            runtime_config_manifest_sha256=self._config.manifest_sha256,
            horizon_days=template.horizon_days,
            started_at=template.started_at,
            events=tuple(
                event for event in template.events if event.event_id not in excluded_event_ids
            ),
            checkpoint_interval=template.checkpoint_interval,
        )
        if plan != expected or self._config.certification_id != plan.certification_id:
            raise ValueError("plan must exactly equal the verified horizon artifact")

    def capture_snapshot(self) -> DecisionAuthoritySnapshot:
        return self._capture_daily_records().snapshot

    def _capture_daily_records(self) -> _DailyAuthorityRecords:
        """Capture production records without adding another public decision path."""
        self._require_open()
        _require_unambiguous_current_states(self._state_backend.load_states())
        transition = self.orchestrator.transition_result
        scope = self._decoded.fact_ingest.certification_scope
        intents = tuple(sorted(self._intent_backend.current(scope), key=_intent_identity))
        intent_history = tuple(
            sorted(
                (
                    version
                    for intent in intents
                    for version in self._intent_backend.history(scope, intent.intent_id)
                ),
                key=_intent_identity,
            )
        )
        intent_transitions = tuple(
            sorted(
                (
                    item
                    for intent in intents
                    for item in self._intent_backend.transitions(scope, intent.intent_id)
                ),
                key=_intent_transition_identity,
            )
        )
        interaction_id = self._last_interaction_id or ""
        checkpoint = None if not interaction_id else self._checkpoint_store.load(interaction_id)
        recovery = self.orchestrator.recover(interaction_id)
        canonical_states = tuple(sorted(self.orchestrator.canonical, key=_state_identity))
        policy_results = tuple(sorted(self.orchestrator.policy_results, key=_policy_identity))
        snapshot = DecisionAuthoritySnapshot(
            accepted_event_refs=(
                ()
                if transition is None
                else tuple(sorted(event.candidate_id for event in transition.accepted_events))
            ),
            transition_refs=(() if transition is None else (transition.assessment_trace.trace_id,)),
            canonical_state_refs=tuple(state.state_id for state in canonical_states),
            candidate_intent_refs=tuple(intent.intent_id for intent in intents),
            selected_intent_ref=(
                None if self.orchestrator.intent is None else self.orchestrator.intent.intent_id
            ),
            policy_result_ref=(
                None
                if self.orchestrator.policy_result is None
                else self.orchestrator.policy_result.policy_id
            ),
            checkpoint_recovery=("no_interaction" if not interaction_id else recovery.action),
        )
        return _DailyAuthorityRecords(
            snapshot=snapshot,
            state_definitions=self._state_backend.load_definitions(),
            canonical_states=canonical_states,
            state_transitions=tuple(
                sorted(self._state_backend.load_transitions(), key=_state_transition_identity)
            ),
            current_intents=intents,
            intent_history=intent_history,
            intent_transitions=intent_transitions,
            transition_results=(() if transition is None else (transition,)),
            policy_results=policy_results,
            interactions=tuple(
                sorted(self._fact_backend.load_interactions(), key=lambda item: item.interaction_id)
            ),
            evidence=tuple(sorted(self._fact_backend.load_evidence(), key=lambda item: item[0].id)),
            observations=tuple(
                sorted(self._fact_backend.load_observations(), key=lambda item: item.id)
            ),
            receipts=tuple(sorted(self._receipts.all(), key=lambda item: item.receipt_id)),
            checkpoint=checkpoint,
            recovery=recovery,
        )

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        for owner in (
            self._checkpoint_store,
            self._intent_backend,
            self._state_backend,
            self._fact_backend,
        ):
            owner.close()

    def _event_scope(self, event: SimulationEvent) -> Scope:
        configured = self._decoded.fact_ingest.certification_scope
        supplied = tuple(evidence.scope for evidence in event.evidence)
        if supplied and any(scope != configured for scope in supplied):
            raise ValueError("event Evidence must match the manifest certification scope")
        if event.historical_context is not None and event.historical_context.scope != configured:
            raise ValueError("historical context must match the manifest certification scope")
        return supplied[0] if supplied else configured

    def _interaction_ids(self, event_id: str) -> tuple[str, str, str]:
        certification_id = self._config.certification_id
        base = f"d11s:{len(certification_id)}:{certification_id}:{len(event_id)}:{event_id}"
        return f"{base}:interaction", f"{base}:session", f"{base}:turn"

    def _reject_stub_components(self) -> None:
        stubs = tuple(
            component.__class__.__name__
            for component in self._components.values()
            if "Stub" in component.__class__.__name__
        )
        if stubs:
            raise ValueError(f"Stub components are forbidden: {', '.join(sorted(stubs))}")

    def _require_open(self) -> None:
        if self._closed:
            raise RuntimeError("canonical certification composition is closed")


def _scope_identity(scope: Scope) -> tuple[str, ...]:
    return (
        scope.domain.value,
        scope.user_id or "",
        scope.agent_id or "",
        scope.persona_id or "",
        scope.relationship_id or "",
        scope.world_id or "",
        scope.interaction_id or "",
    )


def _state_identity(state: RuntimeState) -> tuple[object, ...]:
    return (*_scope_identity(state.scope), state.dimension, state.state_id, state.version)


def _state_transition_identity(transition: StateTransition) -> tuple[object, ...]:
    return (
        *_scope_identity(transition.scope),
        transition.to_state.dimension,
        transition.transition_id,
        transition.sync.version,
    )


def _intent_identity(intent: Intent) -> tuple[object, ...]:
    return (*_scope_identity(intent.scope), intent.intent_id, intent.sync.version)


def _intent_transition_identity(transition: IntentTransition) -> tuple[object, ...]:
    return (
        *_scope_identity(transition.scope),
        transition.intent_id,
        transition.version,
        transition.transition_id,
    )


def _policy_identity(result: ActionPolicyResult) -> tuple[str, ...]:
    return (*_scope_identity(result.scope), result.intent_id, result.policy_id)


def _current_source_head(repository_root: Path) -> str:
    return subprocess.run(
        ["git", "rev-parse", "--verify", "HEAD"],
        cwd=repository_root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _require_table_inventory(plane: str, actual: tuple[str, ...]) -> None:
    # A prior certified run has the W2 receipt and existing shared marker
    # tables. Preserve the exact-table check for both fresh and restarted DBs.
    if plane == "state" and actual == _W2_STATE_TABLES:
        return
    if actual != _EXPECTED_TABLES[plane]:
        raise ValueError(f"{plane} SQLite table inventory must exactly match D11S/W2")


def _require_unambiguous_current_states(states: tuple[RuntimeState, ...]) -> None:
    grouped: dict[tuple[Scope, str], list[RuntimeState]] = {}
    for state in states:
        grouped.setdefault((state.scope, state.dimension), []).append(state)
    for records in grouped.values():
        maximum_version = max(state.version for state in records)
        if sum(state.version == maximum_version for state in records) > 1:
            raise ValueError("ambiguous current State at equal maximum version")


def build_composition(config: CertificationRuntimeConfig) -> CanonicalCertificationComposition:
    """Verify manifest bytes, then construct every canonical production component."""
    if not isinstance(config, CertificationRuntimeConfig):
        raise ValueError("config must be CertificationRuntimeConfig")
    try:
        manifest_bytes = config.manifest_path.read_bytes()
    except OSError as error:
        raise ValueError("runtime-config.json is unavailable") from error
    if sha256_bytes(manifest_bytes) != config.manifest_sha256:
        raise ValueError("runtime-config.json byte hash does not match the bound manifest hash")
    manifest = decode_runtime_config_manifest_bytes(manifest_bytes)
    verify_fixture_artifacts(manifest, config.repository_root)
    decoded = decode_runtime_manifest(manifest)

    for path in (
        config.durable_paths.facts_db,
        config.durable_paths.state_db,
        config.durable_paths.intents_db,
        config.durable_paths.checkpoints_db,
    ):
        path.parent.mkdir(parents=True, exist_ok=True)

    owners: list[object] = []
    try:
        fact_backend = SqliteFactBackend(config.durable_paths.facts_db)
        owners.append(fact_backend)
        _require_table_inventory("facts", fact_backend.table_names())
        state_backend = SqliteStateBackend(config.durable_paths.state_db)
        owners.append(state_backend)
        _require_table_inventory("state", state_backend.table_names())
        state_backend.enable_application_receipts()
        commit_markers = SqliteCommitMarkerStore(
            config.durable_paths.state_db, connection=state_backend.connection
        )
        intent_backend = SqliteIntentBackend(config.durable_paths.intents_db)
        owners.append(intent_backend)
        _require_table_inventory("intents", intent_backend.table_names())
        checkpoint_store = SqliteCheckpointStore(config.durable_paths.checkpoints_db)
        owners.append(checkpoint_store)
        _require_table_inventory("checkpoints", checkpoint_store.table_names())
        _require_unambiguous_current_states(state_backend.load_states())

        for definition in decoded.state_definitions.all():
            state_backend.save_definition(definition)

        fact_ingest = FactIngestService(clock=config.clock, backend=fact_backend)
        interaction_coordinator = InteractionCoordinator(clock=config.clock, backend=fact_backend)
        effective_state = ResolverEffectiveStatePort(
            resolver=EffectiveStateResolver(definitions=decoded.state_definitions)
        )
        situation = decoded.situation
        strategy_config = decoded.appraisal_producer_strategy
        if strategy_config.strategy == "model_backed":
            appraisal_model = ModelBackedSemanticAppraisalModel(
                endpoint_url=strategy_config.endpoint_url,
                model=strategy_config.model,
                api_key_env=strategy_config.api_key_env,
                timeout_s=strategy_config.timeout_s,
                allowed_hosts=strategy_config.allowed_hosts,
                transport=config.appraisal_transport,
            )
        elif strategy_config.strategy == "configured":
            appraisal_model = ConfiguredSemanticAppraisalModel()
        else:
            raise ValueError(
                f"unsupported appraisal strategy: {strategy_config.strategy}"
            )

        # Offline certification supplies no model transport. Its historical
        # candidate-only path is explicitly LEGACY_NO_APPRAISAL; a configured
        # or transport-backed producer must never fall back after rejection.
        appraisal_producer = (
            None
            if strategy_config.strategy == "model_backed"
            and config.appraisal_transport is None
            else SemanticAppraisalProducer(model=appraisal_model)
        )
        homeostasis_config = FixedSalienceThresholdConfig(
            salience_floor_fast_apply=decoded.homeostasis.salience_floor_fast_apply,
            salience_floor_slow_accept=decoded.homeostasis.salience_floor_slow_accept,
            confidence_floor_slow=decoded.homeostasis.confidence_floor_slow,
        )
        homeostasis_gate = SalienceThresholdPolicy(config=homeostasis_config)

        projection_journal = ProjectionJournal(
            config.durable_paths.state_db.with_name("appraisal_journal.sqlite")
        )
        owners.append(projection_journal)
        transition = EngineEmotionalTransitionPort(
            engine=DynamicsEngine(persona=decoded.persona_profile),
            runtime_id=decoded.intent_engine.runtime_id,
            effect_rules=decoded.emotional_effects,
            semantic_router=SemanticRouter(
                provider=None,
                minimum_confidence=decoded.semantic_provider.minimum_confidence,
                conflict_margin=decoded.semantic_provider.conflict_margin,
            ),
            homeostasis_gate=homeostasis_gate,
            appraisal_producer=appraisal_producer,
            projection_journal=projection_journal,
            state_definitions=decoded.state_definitions,
        )
        history_provider = _ScheduledHistoricalProvider()
        history = BoundedHistoricalContextAdapter(
            provider=history_provider,
            budget=decoded.historical_context.budget,
        )
        intent = DeterministicIntentEngine(
            decoded.intent_engine.rules,
            decoded.intent_engine.runtime_id,
        )
        intent_lifecycle = IntentLifecycleService(intent_backend)
        intent_scheduler = IntentScheduler(intent_lifecycle)
        policy = DeterministicActionPolicy(
            decoded.action_policy,
            decoded.intent_engine.runtime_id,
        )
        compiler = DecisionContextCompiler(
            decoded.decision_context,
            definitions=decoded.state_definitions,
            appraisal_journal=projection_journal,
        )
        renderer = DeterministicContextRenderer(decoded.decision_context)
        guard = DeterministicExpressionGuardChain(decoded.expression_guard)
        # The closed v1 decoder rejects fixed mode without an expression before
        # any durable store opens; the cast preserves that established contract.
        previous_value = cast(PreviousExpression, decoded.previous_expression.expression)
        previous_expression = FixedPreviousExpressionPort(previous_value)
        expression = DeterministicExpressionCoordinator(
            compiler=compiler,
            renderer=renderer,
            agent=config.agent,
            guard=guard,
            config=decoded.expression_coordinator,
        )
        receipts = ReceiptRegistry()
        # C10-B-W: the slow-plasticity writer is the single authoritative
        # longitudinal writer. window_size is configuration-owned (ADR-0017
        # Decision 2) and is passed through here. The writer loads its
        # rolling-window cache from the durable ledger at construction.
        slow_plasticity_writer = SlowPlasticityWriter(
            backend=state_backend,
            runtime_id=decoded.intent_engine.runtime_id,
            window_size=decoded.slow_plasticity.window_size,
        )
        orchestrator = TurnOrchestrator(
            clock=config.clock,
            trace=TraceRecorder(),
            runtime_id=decoded.intent_engine.runtime_id,
            fact_ingest=fact_ingest,
            effective_state=effective_state,
            situation=situation,
            emotional_transition=transition,
            intent_engine=intent,
            intent_lifecycle=intent_lifecycle,
            action_policy=policy,
            policy_resources=decoded.policy_resources,
            agent=config.agent,
            context_renderer=renderer,
            expression_guard=guard,
            decision_context_compiler=compiler,
            previous_expression=previous_expression,
            expression_coordinator=expression,
            canonical_snapshot=(),
            definitions=decoded.state_definitions,
            checkpoints=checkpoint_store,
            receipts=receipts,
            persona=decoded.persona_profile,
            state_backend=state_backend,
            commit_markers=commit_markers,
            historical_context=history,
            effect_rules=decoded.emotional_effects,
            semantic_provider=None,
            slow_plasticity_writer=slow_plasticity_writer,
        )
        components = {
            "effective_state": effective_state,
            "situation": situation,
            "transition": transition,
            "history": history,
            "intent": intent,
            "policy": policy,
            "compiler": compiler,
            "renderer": renderer,
            "guard": guard,
            "expression": expression,
            "previous_expression": previous_expression,
            "facts": fact_ingest,
            "intent_lifecycle": intent_lifecycle,
        }
        return CanonicalCertificationComposition(
            config=config,
            manifest=manifest,
            decoded=decoded,
            fact_backend=fact_backend,
            state_backend=state_backend,
            intent_backend=intent_backend,
            checkpoint_store=checkpoint_store,
            interaction_coordinator=interaction_coordinator,
            history_provider=history_provider,
            intent_scheduler=intent_scheduler,
            receipts=receipts,
            orchestrator=orchestrator,
            components=components,
        )
    except Exception:
        for owner in reversed(owners):
            owner.close()  # type: ignore[attr-defined]
        raise
