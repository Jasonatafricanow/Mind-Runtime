"""MR-ASSEMBLY-B slow-write smoke: DynamicsEngine contribution → StateBackend → restart reload.

Assembly fact B2: DynamicsEngine produces RuntimeState contributions via
EngineEmotionalTransitionPort; TurnOrchestrator.commit_turn() promotes the
projection to canonical and writes it through the StateBackend; a fresh
orchestrator on the same backend restores the updated state.

This test exercises the complete slow-write path without any mocking of the
write path itself (only the factual admission is stubbed).
"""

from datetime import UTC, datetime, timedelta

from mind_runtime.contracts import (
    AffectiveDimensionProfile,
    Authority,
    AuthorityLevel,
    Evidence,
    Interaction,
    InteractionStatus,
    RuntimeState,
    Scope,
    ScopeDomain,
    SyncFields,
)
from mind_runtime.dynamics.engine import DynamicsEngine
from mind_runtime.dynamics.persona import PersonaProfile
from mind_runtime.dynamics.ports import EngineEmotionalTransitionPort
from mind_runtime.emotional_transition.effects import EventEffectRule
from mind_runtime.emotional_transition.semantic import SemanticRouter
from mind_runtime.facts.ports import FactAdmissionDisposition, FactAdmissionResult
from mind_runtime.facts.ports import FactIngestPort
from mind_runtime.pipeline.orchestrator import TurnOrchestrator
from mind_runtime.pipeline.trace import TraceRecorder
from mind_runtime.state.persistence import SqliteStateBackend
from tests.golden.fixtures.common import make_scope
from tests.support.fake_clock import FakeClock

NOW = datetime(2026, 9, 3, 14, 0, tzinfo=UTC)
AGENT_SCOPE = Scope(domain=ScopeDomain.AGENT, agent_id="assembly-b", persona_id="assembly-b")


def sync(scope: Scope, oid: str, version: int = 1) -> SyncFields:
    return SyncFields(scope, "runtime-assembly-b", oid, version, f"idem-{oid}")


class _NoOpFactPort(FactIngestPort):
    """Stub mirroring the real FactIngestService observation shape.

    The real service produces ``key=f"{evidence.source_type}.observed"`` —
    the SemanticRouter recognises ``typed_event.observed`` as a typed event
    and routes it to the EffectMapper. A naive stub with a different key
    would short-circuit the routing and starve the assessment trace.
    """

    def admit(
        self,
        evidence: Evidence,
        *,
        interaction_id: str,
        writing_runtime: str,
        writing_persona_id: str | None,
    ) -> FactAdmissionResult:
        from mind_runtime.contracts import Observation

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
            sync=sync(evidence.scope, f"obs-{evidence.id}"),
        )
        return FactAdmissionResult(observation, FactAdmissionDisposition.NEW)


def make_persona() -> PersonaProfile:
    """Three dimensions: anxiety (fast, sensitivity=1.0, recovery=0.9),
    pleasure (slow, sensitivity=0.2, recovery=0.1), calm (zero sensitivity)."""
    return PersonaProfile(
        persona_id="assembly-b",
        dimensions=(
            AffectiveDimensionProfile(
                dimension="agent.affect.anxiety",
                baseline=0.3,
                initial_value=0.3,
                sensitivity=1.0,
                recovery_rate=0.9,
                ceiling=1.0,
                floor=0.0,
                growth_profile=(),
                coupling_profile=(),
            ),
            AffectiveDimensionProfile(
                dimension="agent.affect.pleasure",
                baseline=0.6,
                initial_value=0.6,
                sensitivity=0.2,
                recovery_rate=0.1,
                ceiling=1.0,
                floor=0.0,
                growth_profile=(),
                coupling_profile=(),
            ),
            AffectiveDimensionProfile(
                dimension="agent.affect.calm",
                baseline=0.5,
                initial_value=0.5,
                sensitivity=0.0,
                recovery_rate=0.5,
                ceiling=1.0,
                floor=0.0,
                growth_profile=(),
                coupling_profile=(),
            ),
        ),
    )


def make_interaction() -> Interaction:
    return Interaction(
        interaction_id="turn-assembly-b-1",
        scope=make_scope(),
        channel="chat",
        session_id="session-assembly-b",
        turn_id="t-1",
        started_at=NOW,
        committed_at=None,
        status=InteractionStatus.OPEN,
    )


def make_typed_event_evidence() -> Evidence:
    """A typed_event that triggers the plan_cancelled effect rule."""
    scope = make_scope()
    return Evidence(
        id="ev-assembly-b-1",
        scope=scope,
        origin_runtime_id="runtime-assembly-b",
        source_type="typed_event",
        source_id="message-assembly-b",
        authority_level=AuthorityLevel.ASSERTED,
        authority=Authority(scope, AuthorityLevel.ASSERTED, "message-assembly-b"),
        occurred_at=NOW,
        received_at=NOW,
        payload={"kind": "plan_cancelled", "attributes": {"recurrence": "2"}},
        sync=sync(scope, "ev-assembly-b-1"),
    )


def _seed_canonical(backend: SqliteStateBackend) -> None:
    """Pre-populate the durable backend with v1 canonical state per persona dimension.

    The orchestrator's commit_turn promotes projection.projected_states, whose
    version is derived from the prior canonical record. Without an existing
    canonical v1, the engine would synthesize a v1 and a turn that just
    perturbs the value would still produce v1. Seeding v1 lets the projection
    advance to v2, which the smoke then asserts is persisted.
    """
    persona = make_persona()
    for profile in persona.dimensions:
        backend.save_state(
            RuntimeState(
                state_id=f"{profile.dimension}:1",
                scope=AGENT_SCOPE,
                origin_runtime_id="runtime-assembly-b",
                dimension=profile.dimension,
                value=profile.initial_value,
                status="active",
                valid_from=NOW,
                valid_until=None,
                relevant_until=None,
                last_observed_at=NOW,
                evidence_refs=(),
                transition_refs=(),
                updated_at=NOW,
                version=1,
                sync=sync(AGENT_SCOPE, f"{profile.dimension}:1"),
            )
        )


def test_dynamics_produces_contribution_on_typed_event(tmp_path) -> None:
    """B2a: DynamicsEngine emits a non-zero contribution for the anxiety dimension."""
    import tempfile
    from mind_runtime.state.persistence import SqliteStateBackend

    db_path = str(tmp_path / "assembly_b.db")
    backend = SqliteStateBackend(db_path)
    _seed_canonical(backend)
    persona = make_persona()
    engine = DynamicsEngine(persona=persona)
    em_transition = EngineEmotionalTransitionPort(
        engine=engine,
        runtime_id="runtime-assembly-b",
        effect_rules=(
            EventEffectRule(
                event_kind="plan_cancelled",
                dimension="agent.affect.anxiety",
                base_amount=0.2,
            ),
        ),
        semantic_router=SemanticRouter(),
    )
    orch = TurnOrchestrator(
        clock=FakeClock(NOW),
        trace=TraceRecorder(),
        runtime_id="runtime-assembly-b",
        persona=persona,
        emotional_transition=em_transition,
        fact_ingest=_NoOpFactPort(),
        state_backend=backend,
    )
    orch.begin_turn(make_interaction())
    orch.ingest(make_typed_event_evidence())
    orch.run()
    orch.commit_turn()

    # B2a: DynamicsEngine contributed an impulse to the assessment trace.
    assert orch.transition_result is not None
    trace = orch.transition_result.assessment_trace
    anxiety_contribs = [
        c for c in trace.contributions if c.dimension == "agent.affect.anxiety"
    ]
    assert len(anxiety_contribs) == 1, (
        f"Expected exactly one anxiety contribution; got {anxiety_contribs}"
    )
    assert anxiety_contribs[0].amount > 0, (
        f"Impulse should be positive; got {anxiety_contribs[0].amount}"
    )

    # B2a: the projected anxiety value reflects the contribution applied.
    projected_anxiety = next(
        s for s in orch.transition_result.projected.projected_states
        if s.dimension == "agent.affect.anxiety"
    )
    assert projected_anxiety.value > 0.3, (
        f"Anxiety should increase from 0.3; got {projected_anxiety.value}"
    )

    backend.close()


def test_commit_turn_persists_projections_to_state_backend(tmp_path) -> None:
    """B2b: commit_turn writes the projected states to the SQLite backend."""
    import tempfile
    from mind_runtime.state.persistence import SqliteStateBackend

    db_path = str(tmp_path / "assembly_b_persist.db")
    backend = SqliteStateBackend(db_path)
    _seed_canonical(backend)
    persona = make_persona()
    engine = DynamicsEngine(persona=persona)
    em_transition = EngineEmotionalTransitionPort(
        engine=engine,
        runtime_id="runtime-assembly-b",
        effect_rules=(
            EventEffectRule(
                event_kind="plan_cancelled",
                dimension="agent.affect.anxiety",
                base_amount=0.2,
            ),
        ),
        semantic_router=SemanticRouter(),
    )
    orch = TurnOrchestrator(
        clock=FakeClock(NOW),
        trace=TraceRecorder(),
        runtime_id="runtime-assembly-b",
        persona=persona,
        emotional_transition=em_transition,
        fact_ingest=_NoOpFactPort(),
        state_backend=backend,
    )
    orch.begin_turn(make_interaction())
    orch.ingest(make_typed_event_evidence())
    orch.run()
    orch.commit_turn()

    # B2b: SQLite contains the new version of the projected anxiety state.
    loaded = backend.load_states()
    anxiety_states = sorted(
        [s for s in loaded if s.dimension == "agent.affect.anxiety"],
        key=lambda s: s.version,
    )
    assert len(anxiety_states) >= 2, (
        f"Expected v1 and v2; got {[s.version for s in anxiety_states]}"
    )
    latest_anxiety = anxiety_states[-1]
    assert latest_anxiety.version == 2, (
        f"Latest anxiety version should be 2; got {latest_anxiety.version}"
    )
    assert latest_anxiety.value > 0.3, (
        f"Anxiety persisted value should reflect impulse; got {latest_anxiety.value}"
    )

    # B2b: at least one StateTransition record was persisted.
    transitions = backend.load_transitions()
    assert len(transitions) >= 1, (
        f"Expected at least one transition record; got {len(transitions)}"
    )

    backend.close()


def test_restart_reloads_updated_canonical_from_state_backend(tmp_path) -> None:
    """B2c: a fresh orchestrator on the same backend restores the updated state."""
    import tempfile
    from mind_runtime.state.persistence import SqliteStateBackend

    db_path = str(tmp_path / "assembly_b_restart.db")
    backend = SqliteStateBackend(db_path)
    _seed_canonical(backend)
    persona = make_persona()
    engine = DynamicsEngine(persona=persona)
    em_transition = EngineEmotionalTransitionPort(
        engine=engine,
        runtime_id="runtime-assembly-b",
        effect_rules=(
            EventEffectRule(
                event_kind="plan_cancelled",
                dimension="agent.affect.anxiety",
                base_amount=0.2,
            ),
        ),
        semantic_router=SemanticRouter(),
    )
    orch1 = TurnOrchestrator(
        clock=FakeClock(NOW),
        trace=TraceRecorder(),
        runtime_id="runtime-assembly-b",
        persona=persona,
        emotional_transition=em_transition,
        fact_ingest=_NoOpFactPort(),
        state_backend=backend,
    )
    orch1.begin_turn(make_interaction())
    orch1.ingest(make_typed_event_evidence())
    orch1.run()
    orch1.commit_turn()

    # B2c: canonical reflects the projected update (in-memory).
    canonical_pre = {s.dimension: s for s in orch1.canonical}
    anxiety_pre = canonical_pre["agent.affect.anxiety"]
    assert anxiety_pre.version == 2
    assert anxiety_pre.value > 0.3

    # B2c: fresh orchestrator on the same backend loads the updated canonical.
    orch2 = TurnOrchestrator(
        clock=FakeClock(NOW),
        trace=TraceRecorder(),
        runtime_id="runtime-assembly-b",
        persona=persona,
        state_backend=backend,
    )
    canonical_restored = {s.dimension: s for s in orch2.canonical}
    anxiety_restored = canonical_restored["agent.affect.anxiety"]
    assert anxiety_restored.version == 2, (
        f"Restart should load v2; got v{anxiety_restored.version}"
    )
    assert anxiety_restored.value == anxiety_pre.value, (
        f"Restart value mismatch: {anxiety_restored.value} != {anxiety_pre.value}"
    )

    # B2c: slow-dynamics dimensions (pleasure) that received no contribution
    # retain their previous values.
    pleasure_restored = canonical_restored.get("agent.affect.pleasure")
    assert pleasure_restored is not None, (
        "Pleasure dimension should be present after restart"
    )
    assert pleasure_restored.value == 0.6, (
        f"Pleasure should retain v1 value 0.6; got {pleasure_restored.value}"
    )

    backend.close()
