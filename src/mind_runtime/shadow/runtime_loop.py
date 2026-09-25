"""Production live-source processing loop (C2.10, ADR-0012).

Scheduling boundary between source acquisition and canonical cognition:

    Hermes --(sync/backfill, OWN cursor)--> shadow_events
        ↓
    process_pending(): select PENDING rows (frozen store order)
        ↓
    HermesProductionBridge (LIVE mode)  ->  TurnOrchestrator commit/abort

This module owns ONLY the production step. It never touches the Hermes
acquisition cursor and never writes shadow source rows.

Processing state is derived, not duplicated:

    PROCESSED       the durable factual plane already holds the admission
                    pair for ``hermes:<id>`` under the USER scope — the
                    authoritative marker, transactional with admission;
    BLOCKED         recorded once in a dedicated minimal state store
                    (authority-refused sources, e.g. assistant messages —
                    never retried forever);
    RETRYABLE/PEND  everything else: implicitly retried on later passes,
                    including Crash-Window-A rows (persisted but unprocessed).

Failure layers are isolated by contract: an exception while processing one
record marks nothing, skips nothing durably, and never prevents later
records in the same pass; legacy derived metrics are NOT invoked here at
all. Logs/stats carry counts and ids only — never message bodies.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path

from mind_runtime.binding_registry import BindingRegistryReader
from mind_runtime.cognition import (
    CognitiveTickConfig,
    CognitiveTicker,
    CognitiveTickReport,
)
from mind_runtime.contracts import Scope
from mind_runtime.contracts.surface import SurfaceProjectionPort
from mind_runtime.contracts.telemetry import TelemetrySinkProtocol
from mind_runtime.dynamics.engine import DynamicsEngine
from mind_runtime.dynamics.persona import PersonaProfile
from mind_runtime.dynamics.ports import EngineEmotionalTransitionPort
from mind_runtime.emotional_transition.appraisal import SemanticAppraisalProducer
from mind_runtime.emotional_transition.effects import EventEffectRule
from mind_runtime.emotional_transition.projection_journal import ProjectionJournal
from mind_runtime.emotional_transition.semantic import (
    SemanticCandidateProvider,
    SemanticRouter,
)
from mind_runtime.expression.context import DecisionContextCompiler, DecisionContextConfig
from mind_runtime.expression.renderer import DeterministicContextRenderer
from mind_runtime.facts.persistence import SqliteFactBackend
from mind_runtime.facts.service import FactIngestService
from mind_runtime.homeostasis.contracts import HomeostasisGate
from mind_runtime.intents.engine import DeterministicIntentEngine, IntentRule
from mind_runtime.intents.lifecycle import IntentLifecycleService
from mind_runtime.intents.persistence import SqliteIntentBackend
from mind_runtime.intents.policy import (
    ActionPolicyConfig,
    DeterministicActionPolicy,
    IntentPolicyRule,
)
from mind_runtime.persona_publication import PersonaConfigPublicationRepository, PersonaRevisionRef
from mind_runtime.pipeline.orchestrator import TurnOrchestrator
from mind_runtime.pipeline.ports import ExpressionGuardPort, HistoricalContextPort
from mind_runtime.pipeline.trace import TraceRecorder
from mind_runtime.providers.clock import Clock
from mind_runtime.reality import RealityInputService, build_reality_input
from mind_runtime.runtime_admission import NamespaceAdmissionAuthority
from mind_runtime.runtime_binding import RuntimeBinding, RuntimeEnvironment, resolve_storage_paths
from mind_runtime.shadow.production_wiring import ProductionShadowTap, ShadowTapReport
from mind_runtime.shadow.source_bridge import (
    SOURCE_NAME,
    AdmissionMode,
    BridgeOutcome,
    HermesProductionBridge,
    SourceRecord,
)
from mind_runtime.situation.builder import SituationBuilder
from mind_runtime.slow_plasticity.writer import SlowPlasticityWriter
from mind_runtime.state.definitions import StateDefinitionRegistry
from mind_runtime.state.persistence import (
    CommitMarkerStore,
    SqliteCommitMarkerStore,
    SqliteStateBackend,
)

_ROW_LIMIT_DEFAULT = 2000

# C5B (STEP 1): fail-closed proactive-tick gate. With it off, the loop's
# behavior is byte-for-byte the pre-C5B flow.
PROACTIVE_TICK_ENV = "MIND_RUNTIME_PROACTIVE_TICK"


def proactive_tick_enabled() -> bool:
    """Return whether the host-level cognitive tick may run (fail-closed)."""

    raw = os.environ.get(PROACTIVE_TICK_ENV)
    return raw is not None and raw.strip().lower() in {"1", "true", "yes", "on"}


class _UtcClock:
    """Minimal process clock for long-running entrypoints."""

    def now(self) -> datetime:
        return datetime.now(UTC)


class SourceProcessingState(StrEnum):
    """Durable per-record outcome vocabulary for loop bookkeeping.

    Maps onto C2 dispositions: PROCESSED covers NEW/REPAIRED admissions,
    plus already-admitted ids detected before turn construction; BLOCKED
    covers authority refusals; RETRYABLE is everything not yet decided.
    """

    PENDING = "pending"
    PROCESSED = "processed"
    BLOCKED = "blocked"
    RETRYABLE = "retryable"


@dataclass
class RuntimePassReport:
    """One pass over pending source rows (operability counters only)."""

    considered: int = 0
    processed: int = 0
    replayed: int = 0
    blocked: int = 0
    failed: int = 0
    already_blocked_skipped: int = 0
    fallback_time_rows: int = 0
    # C8C-B: optional audit-only shadow counters; remain zero when no
    # ProductionShadowTap is wired into the loop.
    shadow_invoked: int = 0
    shadow_completed: int = 0
    shadow_failed: int = 0
    reason_codes: tuple[str, ...] = field(default_factory=tuple)

    def as_dict(self) -> dict[str, int]:
        return {
            "considered": self.considered,
            "processed": self.processed,
            "replayed": self.replayed,
            "blocked": self.blocked,
            "failed": self.failed,
            "already_blocked_skipped": self.already_blocked_skipped,
            "fallback_time_rows": self.fallback_time_rows,
        }


class BlockedSourceStore:
    """Minimal durable BLOCKED ledger (ADR-0012 Decision 1).

    Operational state only — never contains Evidence, message bodies, or
    anything authoritative. One row per authority-refused source record so
    a poisoned record cannot wedge every future pass.
    """

    def __init__(self, path: str | Path) -> None:
        self._path = str(path)
        with sqlite3.connect(self._path) as con:
            con.execute(
                "CREATE TABLE IF NOT EXISTS blocked_records ("
                "source_record_id TEXT PRIMARY KEY,"
                " reason TEXT NOT NULL,"
                " decided_at TEXT NOT NULL)"
            )
            con.commit()

    def mark(self, source_record_id: str, *, reason: str, at: datetime) -> None:
        with sqlite3.connect(self._path) as con:
            con.execute(
                "INSERT INTO blocked_records (source_record_id, reason, decided_at) "
                "VALUES (?,?,?) ON CONFLICT(source_record_id) DO NOTHING",
                (source_record_id, reason, at.isoformat(timespec="seconds")),
            )
            con.commit()

    def is_blocked(self, source_record_id: str) -> bool:
        with sqlite3.connect(self._path) as con:
            row = con.execute(
                "SELECT 1 FROM blocked_records WHERE source_record_id=?",
                (source_record_id,),
            ).fetchone()
        return row is not None


def _admitted_observation_id(evidence_id: str) -> str:
    return f"observation-{evidence_id}"


def _has_authoritative_commit(
    markers: CommitMarkerStore | None, *, interaction_id: str, scope: Scope
) -> bool:
    """Authoritative committed-cognition probe via the marker store."""
    if markers is None:
        return False
    return markers.has_commit(interaction_id=interaction_id, scope=scope)


def _canonical_fingerprint(orchestrator: TurnOrchestrator) -> tuple[tuple[str, int], ...]:
    """Order-insensitive canonical identity: (state_id, version) multiset."""
    return tuple(sorted((state.state_id, state.version) for state in orchestrator.canonical))


def build_runtime_stack(
    *,
    clock: Clock,
    facts_db: str | Path,
    state_db: str | Path,
    origin_runtime_id: str,
    user_id: str,
    persona: PersonaProfile | None = None,
    semantic_provider: SemanticCandidateProvider | None = None,
    intent_rules: tuple[IntentRule, ...] | None = None,
    action_policy_config: ActionPolicyConfig | None = None,
    policy_resources: tuple[str, ...] | None = None,
    intent_db: str | Path | None = None,
    cognitive_tick_config: CognitiveTickConfig | None = None,
    memory_enabled: bool = False,
    memory_binding: RuntimeBinding | None = None,
    lce_enabled: bool = False,
    historical_context: HistoricalContextPort | None = None,
    slow_plasticity_window_size: int | None = None,
    definitions: StateDefinitionRegistry | None = None,
    situation: SituationBuilder | None = None,
    decision_context_config: DecisionContextConfig | None = None,
    effect_rules: tuple[EventEffectRule, ...] = (),
    appraisal_producer: SemanticAppraisalProducer | None = None,
    homeostasis_gate: HomeostasisGate | None = None,
    telemetry_sink: TelemetrySinkProtocol | None = None,
    reality_input: RealityInputService | None = None,
    persona_publication: PersonaConfigPublicationRepository | None = None,
    persona_revision_ref: PersonaRevisionRef | None = None,
    surface_binding_registry: BindingRegistryReader | None = None,
    surface_binding_id: str | None = None,
    surface_binding_environment: RuntimeEnvironment | None = None,
    surface_projection_port: SurfaceProjectionPort | None = None,
    delivery_db: str | Path | None = None,
    expression_guard: ExpressionGuardPort | None = None,
) -> tuple[TurnOrchestrator, HermesProductionBridge]:
    """Assemble ONE durable production stack bound to SQLite backends.

    The orchestrator records authoritative commit markers in the shared
    state DB (C3.0); ``process_pending`` reads them instead of any
    projection-id naming. ``persona``/``semantic_provider`` optionally
    activate the real engine transition path with a guarded LLM provider.

    C5B additions (used only by the proactive tick, never by the turn path):
    ``intent_rules``/``action_policy_config``/``policy_resources``/``intent_db``
    wire the REAL deterministic Intent scoring and permission authorities so
    ``build_cognitive_ticker`` can run on this stack without repurposing the
    orchestrator's stub turn ports.
    """
    surface_mode = (
        decision_context_config is not None and decision_context_config.mode == "SURFACE_V1"
    )
    if surface_mode:
        if (
            persona_publication is None
            or surface_binding_registry is None
            or surface_binding_id is None
            or surface_binding_environment is None
        ):
            raise ValueError("SURFACE_V1 requires durable binding and published Persona authority")
        bound_runtime = surface_binding_registry.resolve_binding(
            surface_binding_id, environment=surface_binding_environment
        )
        if bound_runtime.runtime_id != origin_runtime_id:
            raise ValueError("SURFACE_V1 runtime differs from durable binding")
        pinned_ref = surface_binding_registry.resolve_persona_revision(
            surface_binding_id, environment=surface_binding_environment
        )
        if pinned_ref.persona_id != bound_runtime.persona_id:
            raise ValueError("SURFACE_V1 Persona differs from durable binding")
        if persona_revision_ref is not None and persona_revision_ref != pinned_ref:
            raise ValueError("SURFACE_V1 Persona reference differs from pinned revision")
        persona_revision_ref = pinned_ref
        resolved_persona = persona_publication.resolve(persona_revision_ref).profile
        if persona is not None and persona != resolved_persona:
            raise ValueError("SURFACE_V1 Persona differs from published revision")
        persona = resolved_persona
        if surface_projection_port is not None:
            raise ValueError("production Surface projection is composed once by runtime root")
        from mind_runtime.surface.projector import DeterministicSurfaceProjector

        surface_projection_port = DeterministicSurfaceProjector()
        if (
            intent_rules is None
            or intent_db is None
            or action_policy_config is None
            or policy_resources is None
            or delivery_db is None
            or expression_guard is None
        ):
            raise ValueError("SURFACE_V1 requires durable Intent, Policy, C7 handoff and Guard")
    elif surface_projection_port is not None:
        raise ValueError("Surface port requires SURFACE_V1 composition")
    if type(memory_enabled) is not bool:
        raise ValueError("memory_enabled must be bool")
    if type(lce_enabled) is not bool:
        raise ValueError("lce_enabled must be bool")
    thread_updates = None
    if memory_enabled:
        from mind_runtime.memory.composition import (
            build_bound_fact_service,
            build_bound_thread_updates,
        )

        if memory_binding is None:
            raise ValueError("enabled Memory requires a Runtime binding")
        paths = resolve_storage_paths(memory_binding)
        if (
            Path(facts_db).resolve() != paths.facts_db.resolve()
            or Path(state_db).resolve() != paths.state_db.resolve()
            or origin_runtime_id != memory_binding.runtime_id
        ):
            raise ValueError("Memory binding must match the factual/state runtime namespace")
        fact_service = build_bound_fact_service(memory_binding, clock=clock, enabled=True)
        thread_projection_compiler = None
        if lce_enabled:
            from mind_runtime.integrations.lce import LceThreadProjectionCompiler

            thread_projection_compiler = LceThreadProjectionCompiler(
                binding=memory_binding,
                enabled=True,
            )
        thread_updates = build_bound_thread_updates(
            memory_binding,
            enabled=True,
            projection_compiler=thread_projection_compiler,
        )
    else:
        fact_service = FactIngestService(clock=clock, backend=SqliteFactBackend(facts_db))
    state_backend = SqliteStateBackend(state_db)
    if appraisal_producer is not None:
        state_backend.enable_application_receipts()
    marker_store = SqliteCommitMarkerStore(state_db, connection=state_backend.connection)
    if situation is None:
        bound_situation = SituationBuilder(runtime_id=origin_runtime_id)
    else:
        bound_situation = SituationBuilder(
            runtime_id=origin_runtime_id,
            recently_awake_window=situation._awake_window,
            conversation_idle_window=situation._idle_window,
            interaction_recent_window=situation._recent_window,
        )
    # Reuse ONE state backend instance for both the orchestrator canonical
    # state and the slow-plasticity writer, so slow-state commits are
    # transactional with canonical state (ADR-0017 "one transaction").
    slow_plasticity_writer = None
    if slow_plasticity_window_size is not None and slow_plasticity_window_size > 0:
        slow_plasticity_writer = SlowPlasticityWriter(
            backend=state_backend,
            runtime_id=origin_runtime_id,
            window_size=int(slow_plasticity_window_size),
        )
    # C10/D4 authority: persist the manifest-bound state definitions so the
    # host runtime does not run on an empty registry. The certified registry
    # includes the agent.longitudinal.* accumulators (e.g.
    # agent.longitudinal.relationship_security, dynamics_policy=accumulator).
    if definitions is not None:
        for definition in definitions.all():
            state_backend.save_definition(definition)
    projection_journal = (
        ProjectionJournal(Path(state_db).with_name("appraisal_journal.sqlite"))
        if appraisal_producer is not None
        else None
    )
    decision_context_compiler = None
    context_renderer = None
    if decision_context_config is not None:
        decision_context_compiler = DecisionContextCompiler(
            config=decision_context_config,
            definitions=definitions,
            appraisal_journal=projection_journal,
        )
        context_renderer = DeterministicContextRenderer(decision_context_config)
    # Emotional-composition wiring: when a persona is supplied together with
    # appraisal / homeostasis authorities (configuration-driven, wired by the
    # host), construct the production EngineEmotionalTransitionPort directly so
    # appraisal + homeostasis-gate + slow(path) composition is active. Without
    # these authorities, keep the orchestrator's internal persona branch
    # (unchanged pre-composition behavior), which cannot reach the gate.
    emotional_transition = None
    if persona is not None and (appraisal_producer is not None or homeostasis_gate is not None):
        emotional_transition = EngineEmotionalTransitionPort(
            engine=DynamicsEngine(persona=persona),
            runtime_id=origin_runtime_id,
            effect_rules=effect_rules,
            semantic_router=SemanticRouter(provider=semantic_provider),
            homeostasis_gate=homeostasis_gate,
            appraisal_producer=appraisal_producer,
            projection_journal=projection_journal,
            state_definitions=definitions,
            telemetry_sink=telemetry_sink,
        )
    turn_intent_engine = None
    turn_intent_lifecycle = None
    turn_action_policy = None
    turn_policy_resources = None
    surface_delivery_backend = None
    if surface_mode:
        from mind_runtime.contracts import PolicyResources
        from mind_runtime.delivery.persistence import SqliteDeliveryBackend

        if (
            intent_rules is None
            or intent_db is None
            or action_policy_config is None
            or policy_resources is None
            or delivery_db is None
        ):
            raise ValueError("SURFACE_V1 requires durable Intent, Policy and C7 handoff")
        turn_intent_engine = DeterministicIntentEngine(intent_rules, origin_runtime_id)
        turn_intent_lifecycle = IntentLifecycleService(SqliteIntentBackend(intent_db))
        turn_action_policy = DeterministicActionPolicy(action_policy_config, origin_runtime_id)
        turn_policy_resources = PolicyResources(tuple(policy_resources))
        surface_delivery_backend = SqliteDeliveryBackend(delivery_db)
    orchestrator = TurnOrchestrator(
        clock=clock,
        trace=TraceRecorder(),
        runtime_id=origin_runtime_id,
        fact_ingest=fact_service,
        persona=persona,
        emotional_transition=emotional_transition,
        effect_rules=effect_rules,
        definitions=definitions,
        situation=bound_situation,
        decision_context_compiler=decision_context_compiler,
        context_renderer=context_renderer,
        state_backend=state_backend,
        commit_markers=marker_store,
        semantic_provider=semantic_provider,
        historical_context=historical_context,
        slow_plasticity_writer=slow_plasticity_writer,
        telemetry_sink=telemetry_sink,
        reality_input=reality_input if reality_input is not None else build_reality_input(),
        surface_projection_port=surface_projection_port,
        surface_delivery_backend=surface_delivery_backend,
        intent_engine=turn_intent_engine,
        intent_lifecycle=turn_intent_lifecycle,
        action_policy=turn_action_policy,
        policy_resources=turn_policy_resources,
        expression_guard=expression_guard,
        thread_updates=thread_updates,
        # MR-RUNTIME-05: enroll the stack in the process-local, per-namespace
        # canonical admission authority — whole turns on this namespace are
        # serialized and each admitted turn refreshes from the durable base.
        turn_admission=NamespaceAdmissionAuthority.for_state_db(state_db),
    )
    bridge = HermesProductionBridge(
        orchestrator,
        clock=clock,
        origin_runtime_id=origin_runtime_id,
        user_id=user_id,
    )
    if intent_rules is not None:
        orchestrator.cognitive_tick_components = build_cognitive_components(  # type: ignore[attr-defined]
            orchestrator=orchestrator,
            origin_runtime_id=origin_runtime_id,
            intent_rules=intent_rules,
            action_policy_config=action_policy_config,
            policy_resources=policy_resources,
            intent_db=intent_db,
            cognitive_tick_config=cognitive_tick_config,
        )
    return orchestrator, bridge


def build_cognitive_components(
    *,
    orchestrator: TurnOrchestrator,
    origin_runtime_id: str,
    intent_rules: tuple[IntentRule, ...],
    action_policy_config: ActionPolicyConfig | None,
    policy_resources: tuple[str, ...] | None,
    intent_db: str | Path | None,
    cognitive_tick_config: CognitiveTickConfig | None = None,
) -> dict[str, object]:
    """Wire the real Intent/Policy authorities for the cognitive tick.

    Fail-closed: a missing durable intent backend refuses to build — an
    autonomous tick over an in-memory lifecycle would silently lose its
    decisions on restart.
    """
    if intent_db is None:
        raise ValueError("cognitive tick requires a durable intent_db")
    if action_policy_config is None:
        raise ValueError("cognitive tick requires an explicit action policy config")
    if policy_resources is None:
        raise ValueError("cognitive tick requires explicit policy resources")
    intent_backend = SqliteIntentBackend(intent_db)
    lifecycle = IntentLifecycleService(intent_backend)
    engine = DeterministicIntentEngine(intent_rules, origin_runtime_id)
    policy = DeterministicActionPolicy(action_policy_config, origin_runtime_id)
    from mind_runtime.contracts import PolicyResources

    resources = PolicyResources(tuple(policy_resources))
    persona = orchestrator._persona
    if persona is None:
        raise ValueError("cognitive tick requires a Persona-backed orchestrator")
    from mind_runtime.cognition import build_cognitive_ticker

    ticker = build_cognitive_ticker(
        orchestrator=orchestrator,
        persona=persona,
        intent_engine=engine,
        action_policy=policy,
        policy_resources=resources,
        intent_lifecycle=lifecycle,
        runtime_id=origin_runtime_id,
        config=cognitive_tick_config,
    )
    return {
        "ticker": ticker,
        "lifecycle": lifecycle,
        "intent_backend": intent_backend,
        "engine": engine,
        "policy": policy,
        "resources": resources,
    }


def run_cognitive_tick(
    orchestrator: TurnOrchestrator,
    *,
    scope: Scope,
    now: datetime,
) -> CognitiveTickReport:
    """Run one host-level cognitive tick on a wired production stack."""

    components = getattr(orchestrator, "cognitive_tick_components", None)
    if not isinstance(components, dict) or "ticker" not in components:
        raise ValueError(
            "cognitive tick is not wired on this stack: rebuild via "
            "build_runtime_stack(intent_rules=...)"
        )
    ticker = components["ticker"]
    if not isinstance(ticker, CognitiveTicker):
        raise TypeError("wired ticker must be a CognitiveTicker")
    result = ticker.tick(scope=scope, now=now)
    assert isinstance(result, CognitiveTickReport)
    return result


def process_pending(
    orchestrator: TurnOrchestrator,
    bridge: HermesProductionBridge,
    *,
    shadow_db: str | Path,
    blocked_store_path: str | Path,
    limit: int = _ROW_LIMIT_DEFAULT,
    production_shadow_tap: ProductionShadowTap | None = None,
) -> RuntimePassReport:
    """Process PENDING shadow source rows through production cognition.

    Always AdmissionMode.LIVE (ADR-0012 Decision 4). Caller owns durability:
    the orchestrator must have been built on Sqlite backends
    (build_runtime_stack), otherwise Progress-by-fact-store would silently
    degrade to memory-only.

    C8C-B: When ``production_shadow_tap`` is provided and enabled, a
    shadow observation is run for each successfully committed production
    turn. The tap is audit-only: it never blocks, retries, or influences
    production. All shadow counters in the report remain zero when the
    tap is None.
    """
    service = orchestrator.fact_ingest
    if not isinstance(service, FactIngestService):
        raise TypeError("production loop requires FactIngestService admission")
    scope = bridge.scope

    blocked_store = BlockedSourceStore(blocked_store_path)
    report = RuntimePassReport()
    reasons: list[str] = []

    rows = _select_pending_rows(shadow_db, limit=limit)
    now = datetime.now(UTC)

    for content_id, sender, text, event_ts_raw, persisted_raw, channel, session_hash in rows:
        record, fallback = _row_to_record(
            content_id=content_id,
            sender=sender,
            text=text,
            event_ts_raw=event_ts_raw,
            persisted_raw=persisted_raw,
            channel=channel,
            session_hash=session_hash,
        )
        if fallback:
            report.fallback_time_rows += 1
            reasons.append(f"occurred_fallback_persisted:{record.source_record_id}")
        evidence_id = bridge.evidence_id_for(record)

        # PROCESSED? Derived from DURABLE commit semantics (C3.0): the
        # authoritative probe is the CommitMarkerStore written by
        # orchestrator.commit_turn — projection-id naming is never parsed.
        # The legacy projected-<interaction> read below only serves state
        # DBs created before markers existed (pre-C3.0 instances).
        already_admitted = (
            service.observations.get(scope, _admitted_observation_id(evidence_id)) is not None
        )
        interaction_id = f"{SOURCE_NAME}-{record.source_record_id}"
        markers: CommitMarkerStore | None = getattr(orchestrator, "commit_marker_store", None)
        already_committed = already_admitted and (
            _has_authoritative_commit(markers, interaction_id=interaction_id, scope=scope)
            or any(
                state.state_id == f"projected-{interaction_id}" for state in orchestrator.canonical
            )
        )
        if already_committed:
            report.replayed += 1  # Crash-Window-B / repeat-pass convergence
            continue

        # BLOCKED previously? Skip without retry pressure.
        if blocked_store.is_blocked(record.source_record_id):
            report.already_blocked_skipped += 1
            continue

        report.considered += 1
        # Mode follows the identity state (ADR-0012 §4/§9): first-time
        # processing is LIVE; reprocessing an already-admitted identity is
        # REPLAY regardless of which store it came from.
        mode = AdmissionMode.REPLAY if already_admitted else AdmissionMode.LIVE
        before_fingerprint = _canonical_fingerprint(orchestrator)
        try:
            outcome = bridge.process(record, mode=mode)
        except Exception:
            # RETRYABLE: leave untouched for the next pass (ADR-0012 §8).
            report.failed += 1
            reasons.append(f"failed:{record.source_record_id}")
            continue

        # Cognitive outcome truth: did the durable canonical plane change?
        # (A REPLAY admission that completes a previously aborted
        # projection IS real processing; a no-op audit no-op is not.)
        cognitive_effect = (
            outcome.stage != "blocked"
            and _canonical_fingerprint(orchestrator) != before_fingerprint
        )
        _fold_outcome(report, outcome, cognitive_effect=cognitive_effect)
        if outcome.stage == "blocked":
            blocked_store.mark(
                record.source_record_id,
                reason=outcome.blocked_reason or "authority_refused",
                at=now,
            )
            reasons.append(f"blocked:{record.source_record_id}")
            continue

        # C8C-B: post-commit shadow tap (audit-only). Only runs after a
        # successful production commit (skipped on REPLAY audit turns and
        # on BLOCKED). Failures are isolated; the per-pass counters
        # record invocation outcome without affecting production.
        if production_shadow_tap is not None:
            shadow_interaction = bridge.interaction_for(record)
            tap_report = ShadowTapReport()
            production_shadow_tap.tap(
                shadow_interaction,
                report=tap_report,
            )
            report.shadow_invoked += tap_report.shadow_invoked
            report.shadow_completed += tap_report.shadow_completed
            report.shadow_failed += tap_report.shadow_failed

    report.reason_codes = tuple(reasons[-16:])
    return report


def _fold_outcome(
    report: RuntimePassReport, outcome: BridgeOutcome, *, cognitive_effect: bool
) -> None:
    """Fold one BridgeOutcome into pass counters.

    Counters track COGNITIVE outcomes: ``cognitive_effect`` means the
    durable canonical plane changed during this record's lifecycle (either
    a first commit or a REPLAY convergence completing a missing
    projection); a blocked refusal or a pure audit no-op does not count as
    processing.
    """
    if outcome.stage == "blocked":
        report.blocked += 1
    elif cognitive_effect:
        report.processed += 1
    else:
        report.replayed += 1


# ── internals ──────────────────────────────────────────────────────────────


def _select_pending_rows(
    shadow_db: str | Path, *, limit: int
) -> list[tuple[int, str, str, str | None, str, str, str]]:
    """Frozen deterministic order: (ts ASC, content_id ASC) per ADR-0012 §3."""
    con = sqlite3.connect(str(shadow_db))
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute(
            "SELECT content_id, sender, redacted_text, event_ts, ts, channel, session_hash "
            "FROM shadow_events WHERE sender IN ('user','agent') "
            "ORDER BY ts ASC, content_id ASC LIMIT ?",
            (limit,),
        ).fetchall()
    finally:
        con.close()
    return [
        (
            int(r["content_id"]),
            str(r["sender"]),
            str(r["redacted_text"] or ""),
            r["event_ts"] if r["event_ts"] is None else str(r["event_ts"]),
            str(r["ts"] or ""),
            str(r["channel"] or "unknown"),
            str(r["session_hash"] or "unknown"),
        )
        for r in rows
    ]


def _parse_iso(value: object) -> datetime | None:
    raw = value if isinstance(value, str) else None
    if raw is None or not raw.strip():
        return None
    return datetime.fromisoformat(raw)


def _row_to_record(
    *,
    content_id: int,
    sender: str,
    text: str,
    event_ts_raw: str | None,
    persisted_raw: str,
    channel: str,
    session_hash: str,
) -> tuple[SourceRecord, bool]:
    """Build the adapter record from one raw shadow row (ADR-0012 §2)."""
    persisted_ts = _parse_iso(persisted_raw) or datetime.now(UTC)
    record, fallback = SourceRecord.from_shadow_row(
        content_id=content_id,
        sender=sender,
        text=text,
        event_ts=_parse_iso(event_ts_raw),
        persisted_ts=persisted_ts,
        channel=channel,
        session_hash=session_hash,
    )
    return record, fallback


# ── entrypoint ─────────────────────────────────────────────────────────────

DEFAULT_RUNTIME_DIR = Path.home() / ".hermes" / "profiles" / "xiyue" / "runtime"
_DEFAULT_SHADOW_DB = Path.home() / ".hermes" / "profiles" / "xiyue" / "shadow.db"


def main(argv: list[str] | None = None) -> int:
    """Daemon-facing entrypoint (fail-closed gate, ADR-0012 §6).

    DB locations come from flags or env counterparts so each plane can be
    relocated independently; output carries counters/ids only.
    """
    import argparse
    import json
    import os

    parser = argparse.ArgumentParser(description="C2.10 production source loop")
    parser.add_argument("--shadow-db", default=str(_DEFAULT_SHADOW_DB))
    parser.add_argument("--facts-db", default=None)
    parser.add_argument("--cognition-db", default=None)
    parser.add_argument("--blocked-db", default=None)
    parser.add_argument("--user-id", default=os.environ.get("MIND_RUNTIME_PRODUCTION_USER", "user"))
    parser.add_argument(
        "--origin-runtime-id",
        default=os.environ.get("MIND_RUNTIME_ORIGIN_RUNTIME_ID", "kayla"),
    )
    parser.add_argument("--limit", type=int, default=_ROW_LIMIT_DEFAULT)
    parser.add_argument(
        "--semantic-recorded",
        default=None,
        help=(
            "C3: path to a RECORDED validated-candidates JSON batch; the "
            "only sanctioned way to attach semantic behavior to this loop "
            "today (fail-closed default: no provider)."
        ),
    )
    parser.add_argument(
        "--proactive-tick",
        action="store_true",
        help=(
            "C5B: run one host-level cognitive tick after source processing. "
            "Requires MIND_RUNTIME_PROACTIVE_TICK and the C5B config flags; "
            "fail-closed default OFF."
        ),
    )
    parser.add_argument(
        "--persona-json",
        default=None,
        help=(
            "C5B: persona profile path for the cognitive tick (required when the tick gate is ON)."
        ),
    )
    parser.add_argument(
        "--intent-db",
        default=None,
        help="C5B: durable Intent backend path for the cognitive tick.",
    )
    parser.add_argument(
        "--intent-rules-json",
        default=None,
        help=(
            'C5B: path to a JSON file {"rules": [...], "policy": {...}, '
            '"resources": [...]} configuring the tick\'s real Intent/Policy '
            "authorities (STEP 3: Kayla numbers live here, never in kernel)."
        ),
    )
    parser.add_argument(
        "--runtime-behavior-json",
        default=None,
        help=(
            'C6B: path to a runtime behavior JSON file {"proactive": '
            '{"photo_cadence_threshold": N}} configuring deployment-specific '
            "proactive behavior (e.g. cadence threshold). Defaults to the "
            "repo's configs/runtime/kayla.json when the tick gate is ON; "
            "not required unless the tick gate is ON."
        ),
    )
    args = parser.parse_args(argv)

    raw_gate = os.environ.get("MIND_RUNTIME_PRODUCTION_INGEST")
    enabled = raw_gate is not None and raw_gate.strip().lower() in {"1", "true", "yes", "on"}
    if not enabled:
        print(json.dumps({"gate": "off"}))
        return 0

    runtime_dir = DEFAULT_RUNTIME_DIR
    runtime_dir.mkdir(parents=True, exist_ok=True)
    facts_db = args.facts_db or str(runtime_dir / "facts.sqlite")
    cognition_db = args.cognition_db or str(runtime_dir / "cognition_state.sqlite")
    blocked_db = args.blocked_db or str(runtime_dir / "blocked.sqlite3")

    provider = None
    if args.semantic_recorded:
        # fail-closed by construction: only RECORDED validated artifacts are
        # attachable from the entrypoint; no live generation, no network.
        from mind_runtime.emotional_transition.provider import RecordedSemanticProvider

        with open(args.semantic_recorded, encoding="utf-8") as handle:
            recorded_batch = json.load(handle)
        provider = RecordedSemanticProvider([list(recorded_batch)])

    # C5B addendum: the tick flag alone changes nothing. Components and the
    # persona are wired ONLY when both the flag and the env gate are ON —
    # with the gate OFF the stack is byte-for-byte the pre-C5B reactive one.
    tick_requested = args.proactive_tick and proactive_tick_enabled()
    persona = None
    cognitive_tick_config = None
    if tick_requested:
        if args.persona_json is None:
            raise ValueError("--proactive-tick (gate ON) requires --persona-json")
        from mind_runtime.persona_config import load_persona_profile

        persona = load_persona_profile(args.persona_json).profile
        # C6B: load deployment runtime behavior config (default: repo Kayla).
        from mind_runtime.runtime_config import default_runtime_behavior_path, load_runtime_behavior

        behavior = load_runtime_behavior(
            args.runtime_behavior_json or default_runtime_behavior_path()
        )
        cognitive_tick_config = behavior.to_cognitive_tick_config()

    orchestrator, bridge = build_runtime_stack(
        clock=_UtcClock(),
        facts_db=facts_db,
        state_db=cognition_db,
        origin_runtime_id=args.origin_runtime_id,
        user_id=args.user_id,
        persona=persona,
        semantic_provider=provider,
        intent_rules=tick_config_rules(args) if tick_requested else None,
        action_policy_config=tick_config_policy(args) if tick_requested else None,
        policy_resources=tick_config_resources(args) if tick_requested else None,
        intent_db=(
            args.intent_db
            if args.intent_db is not None
            else (str(Path(str(facts_db)).with_suffix("")) + "-intents.sqlite")
            if tick_requested
            else None
        ),
        cognitive_tick_config=cognitive_tick_config,
    )
    report = process_pending(
        orchestrator,
        bridge,
        shadow_db=args.shadow_db,
        blocked_store_path=blocked_db,
        limit=args.limit,
    )
    payload: dict[str, object] = {
        "runtime": report.as_dict(),
        "reasons": list(report.reason_codes),
    }
    if args.proactive_tick:
        if not proactive_tick_enabled():
            payload["proactive_tick"] = {"gate": "off"}
        else:
            from mind_runtime.contracts import ScopeDomain

            tick_scope = Scope(
                domain=ScopeDomain.USER,
                user_id=args.user_id,
            )
            tick_report = run_cognitive_tick(
                orchestrator,
                scope=tick_scope,
                now=datetime.now(UTC),
            )
            payload["proactive_tick"] = tick_report.as_dict()
    print(json.dumps(payload))
    return 0


def tick_config_rules(args: argparse.Namespace) -> tuple[IntentRule, ...]:
    """Load the tick's IntentRule tuples from the C5B JSON config file."""

    import json

    from mind_runtime.contracts import ReconsiderationPolicy
    from mind_runtime.intents.engine import IntentRule

    if args.intent_rules_json is None:
        raise ValueError("--proactive-tick requires --intent-rules-json")
    with open(args.intent_rules_json, encoding="utf-8") as handle:
        raw = json.load(handle)
    rules: list[IntentRule] = []
    for entry in raw.get("rules", []):
        rules.append(
            IntentRule(
                rule_id=entry["rule_id"],
                kind=entry["kind"],
                base_strength=entry["base_strength"],
                dimension_weights=tuple(
                    (item["dimension"], item["weight"]) for item in entry["dimension_weights"]
                ),
                event_kind=entry.get("event_kind"),
                event_bonus=entry.get("event_bonus", 0.0),
                minimum_strength=entry["minimum_strength"],
                due_at_attribute=entry.get("due_at_attribute"),
                expires_after=(
                    timedelta(seconds=entry["expires_after_seconds"])
                    if entry.get("expires_after_seconds") is not None
                    else None
                ),
                reconsideration_policy=ReconsiderationPolicy(
                    entry.get("reconsideration_policy", "never")
                ),
            )
        )
    return tuple(rules)


def tick_config_policy(args: argparse.Namespace) -> ActionPolicyConfig:
    """Load the tick's ActionPolicyConfig from the C5B JSON config file."""

    import json

    if args.intent_rules_json is None:
        raise ValueError("--proactive-tick requires --intent-rules-json")
    with open(args.intent_rules_json, encoding="utf-8") as handle:
        raw = json.load(handle)
    policy = raw.get("policy", {})
    rules: list[IntentPolicyRule] = []
    for entry in policy.get("rules", []):
        rules.append(
            IntentPolicyRule(
                intent_kind=entry["intent_kind"],
                action_type=entry["action_type"],
                proactive=entry.get("proactive", False),
                interrupts_active_conversation=entry.get("interrupts_active_conversation", False),
                media_counter_fact=entry.get("media_counter_fact"),
                media_limit=entry.get("media_limit"),
                required_resource=entry.get("required_resource"),
            )
        )
    cooldown_seconds = policy.get("proactive_cooldown_seconds", 0)
    return ActionPolicyConfig(
        rules=tuple(rules),
        proactive_cooldown=timedelta(seconds=cooldown_seconds),
    )


def tick_config_resources(args: argparse.Namespace) -> tuple[str, ...]:
    """Load the tick's PolicyResources from the C5B JSON config file."""

    import json

    if args.intent_rules_json is None:
        raise ValueError("--proactive-tick requires --intent-rules-json")
    with open(args.intent_rules_json, encoding="utf-8") as handle:
        raw = json.load(handle)
    return tuple(raw.get("resources", []))


if __name__ == "__main__":
    raise SystemExit(main())
