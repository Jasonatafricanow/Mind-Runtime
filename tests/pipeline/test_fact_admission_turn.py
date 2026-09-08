"""ADR-0009 Phase 2 contract tests: canonical turn consumption of dispositions.

A replay retains the audit Interaction and lets the turn continue, but adds
no Observation to the turn, no evidence ref, no overlay entry, no semantic
candidate, no event impulse, and no replay/event-caused State. Registered
elapsed-time recovery still executes. REPAIRED is consumed once and is
causal once. The trace distinguishes fact_new / fact_repaired / fact_replay.
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from mind_runtime.contracts import (
    AffectiveDimensionProfile,
    Interaction,
    InteractionStatus,
    Observation,
    Scope,
    SemanticEventCandidate,
)
from mind_runtime.dynamics.engine import DynamicsEngine
from mind_runtime.dynamics.persona import PersonaProfile
from mind_runtime.dynamics.ports import EngineEmotionalTransitionPort
from mind_runtime.emotional_transition.effects import EventEffectRule
from mind_runtime.emotional_transition.semantic import SemanticRouter
from mind_runtime.facts.persistence import SqliteFactBackend
from mind_runtime.facts.service import FactIngestService
from mind_runtime.pipeline.orchestrator import TurnOrchestrator
from mind_runtime.pipeline.trace import TraceRecorder
from tests.golden.fixtures.common import make_evidence, make_scope
from tests.support.fake_clock import FakeClock

NOW = datetime(2026, 8, 23, 18, 0, tzinfo=UTC)


def make_interaction(interaction_id: str = "interaction-1") -> Interaction:
    return Interaction(
        interaction_id=interaction_id,
        scope=make_scope(),
        channel="chat",
        session_id="session-1",
        turn_id=f"turn-{interaction_id}",
        started_at=NOW,
        committed_at=None,
        status=InteractionStatus.OPEN,
    )


def make_orchestrator(service: FactIngestService, **kwargs: Any) -> TurnOrchestrator:
    return TurnOrchestrator(
        clock=FakeClock(NOW),
        trace=TraceRecorder(),
        fact_ingest=service,
        **kwargs,
    )


class ScriptedSemanticProvider:
    """Proposes one bounded candidate when observations are present."""

    def __init__(self) -> None:
        self.calls = 0

    def propose(
        self,
        *,
        observations: tuple[Observation, ...],
        context: object,
        scope: Scope,
    ) -> tuple[SemanticEventCandidate, ...]:
        self.calls += 1
        if not observations:
            return ()
        return (
            SemanticEventCandidate(
                candidate_id="semantic-plan-cancelled",
                scope=scope,
                origin_runtime_id="runtime-1",
                kind="plan_cancelled",
                attributes=(),
                confidence=0.9,
                evidence_refs=tuple(observation.id for observation in observations),
            ),
        )


def engine_orchestrator(
    service: FactIngestService, clock: FakeClock
) -> tuple[TurnOrchestrator, ScriptedSemanticProvider]:
    """Orchestrator with the real D7 engine and one event effect rule."""
    persona = PersonaProfile(
        persona_id="p1",
        dimensions=(
            AffectiveDimensionProfile(
                dimension="agent.affect.anxiety",
                baseline=0.2,
                initial_value=0.2,
                sensitivity=0.8,
                recovery_rate=0.5,
                ceiling=1.0,
                floor=0.0,
                growth_profile=(),
                coupling_profile=(),
            ),
        ),
    )
    provider = ScriptedSemanticProvider()
    port = EngineEmotionalTransitionPort(
        engine=DynamicsEngine(persona=persona),
        runtime_id="runtime-1",
        effect_rules=(
            EventEffectRule(
                event_kind="plan_cancelled",
                dimension="agent.affect.anxiety",
                base_amount=0.2,
                history_amount_per_match=0.0,
                history_amount_cap=0.0,
                minimum_history_confidence=0.0,
            ),
        ),
        semantic_router=SemanticRouter(provider=provider),
    )
    orchestrator = TurnOrchestrator(
        clock=clock,
        trace=TraceRecorder(),
        fact_ingest=service,
        persona=persona,
        emotional_transition=port,
    )
    return orchestrator, provider


def test_case1_replay_turn_retains_audit_interaction_and_runs() -> None:
    service = FactIngestService(clock=FakeClock(NOW))
    orchestrator = make_orchestrator(service)
    evidence = make_evidence(text="我刚睡醒")
    orchestrator.begin_turn(make_interaction("interaction-1"))
    first = orchestrator.ingest(evidence)
    assert orchestrator.observations == (first,)
    orchestrator.run()
    orchestrator.commit_turn()
    # Second Interaction with identical Evidence: retained for audit, the
    # turn still runs to completion.
    orchestrator.begin_turn(make_interaction("interaction-2"))
    replay = orchestrator.ingest(evidence)
    assert replay == first  # the existing authoritative Observation
    orchestrator.run()
    orchestrator.commit_turn()
    assert orchestrator.state.value == "committed"


def test_case2_replay_adds_nothing_to_turn_inputs() -> None:
    service = FactIngestService(clock=FakeClock(NOW))
    orchestrator = make_orchestrator(service)
    evidence = make_evidence(text="我刚睡醒")
    orchestrator.begin_turn(make_interaction("interaction-1"))
    orchestrator.ingest(evidence)
    orchestrator.run()
    orchestrator.commit_turn()
    turn1_overlay = dict(orchestrator.factual_overlay)
    orchestrator.begin_turn(make_interaction("interaction-2"))
    orchestrator.ingest(evidence)
    assert orchestrator.observations == ()
    assert orchestrator._turn is not None
    assert orchestrator._turn.evidence_refs == ()
    # The factual overlay is untouched by the replay (no new entry).
    assert orchestrator.factual_overlay == turn1_overlay


def test_case3_replay_produces_no_event_impulse_or_excitation() -> None:
    clock = FakeClock(NOW)
    service = FactIngestService(clock=clock)
    orchestrator, provider = engine_orchestrator(service, clock)
    evidence = make_evidence(text="我刚睡醒")
    # Turn 1: NEW evidence drives the event effect -> impulse.
    orchestrator.begin_turn(make_interaction("interaction-1"))
    orchestrator.ingest(evidence)
    orchestrator.run()
    first_trace = orchestrator.transition_result
    assert first_trace is not None
    assert any(
        c.source_kind == "event" and c.applied for c in first_trace.assessment_trace.contributions
    )
    assert provider.calls == 1
    orchestrator.commit_turn()
    # Turn 2: identical Evidence replays -> no observation enters the turn,
    # so no semantic candidate, no event impulse, no Evidence-linked
    # contribution, and no replay/event-caused state excitation.
    orchestrator.begin_turn(make_interaction("interaction-2"))
    orchestrator.ingest(evidence)
    assert orchestrator.observations == ()
    orchestrator.run()
    second_trace = orchestrator.transition_result
    assert second_trace is not None
    assert second_trace.assessment_trace.evidence_refs == ()
    assert not any(
        c.source_kind == "event" and c.applied for c in second_trace.assessment_trace.contributions
    )
    assert provider.calls == 1  # the provider was never re-invoked
    # The projection's transition intents carry no observation cause refs.
    assert orchestrator.turn_projection is not None
    assert all(
        intent.cause_refs == () for intent in orchestrator.turn_projection.transition_intents
    )
    orchestrator.commit_turn()
    anxiety = next(
        state for state in orchestrator.canonical if state.dimension == "agent.affect.anxiety"
    )
    # turn-1 event value (0.2 + 0.2*0.9 confidence * 0.8 sensitivity), not
    # re-excited by the replay turn.
    assert anxiety.value == pytest.approx(0.344)


def test_case4_registered_recovery_still_executes_in_replay_turn() -> None:
    clock = FakeClock(NOW)
    service = FactIngestService(clock=clock)
    orchestrator, provider = engine_orchestrator(service, clock)
    evidence = make_evidence(text="我刚睡醒")
    orchestrator.begin_turn(make_interaction("interaction-1"))
    orchestrator.ingest(evidence)
    orchestrator.run()
    orchestrator.commit_turn()
    # Advance the clock: the replay turn must still run the registered
    # recovery toward baseline even though no new fact is consumed.
    clock.advance(timedelta(hours=2))
    orchestrator.begin_turn(make_interaction("interaction-2"))
    orchestrator.ingest(evidence)
    assert orchestrator.observations == ()
    orchestrator.run()
    trace = orchestrator.transition_result
    assert trace is not None
    recovery = [
        c for c in trace.assessment_trace.contributions if c.source_kind == "recovery" and c.applied
    ]
    assert recovery, "registered recovery must still execute in the replay turn"
    assert all(c.amount < 0 for c in recovery)
    assert provider.calls == 1
    orchestrator.commit_turn()
    anxiety = next(
        state for state in orchestrator.canonical if state.dimension == "agent.affect.anxiety"
    )
    assert isinstance(anxiety.value, float)
    assert anxiety.value < 0.344  # recovery moved the value back toward baseline


def test_case5_repaired_observation_consumed_once_and_causal_once(tmp_path: Path) -> None:
    import sqlite3

    path = tmp_path / "facts.db"
    service = FactIngestService(clock=FakeClock(NOW), backend=SqliteFactBackend(path))
    orchestrator = make_orchestrator(service)
    evidence = make_evidence(text="我刚睡醒")
    orchestrator.begin_turn(make_interaction("interaction-1"))
    orchestrator.ingest(evidence)
    orchestrator.run()
    orchestrator.commit_turn()
    # Crash window: derived observation row removed.
    conn = sqlite3.connect(path)
    conn.execute("DELETE FROM observations")
    conn.commit()
    conn.close()
    restarted = FactIngestService(clock=FakeClock(NOW), backend=SqliteFactBackend(path))
    restarted_orchestrator = make_orchestrator(restarted)
    restarted_orchestrator.begin_turn(make_interaction("interaction-2"))
    repaired = restarted_orchestrator.ingest(evidence)
    assert repaired.interaction_id == "interaction-1"  # original provenance
    assert restarted_orchestrator.observations == (repaired,)
    assert restarted_orchestrator._turn is not None
    assert restarted_orchestrator._turn.evidence_refs == (evidence.id,)
    restarted_orchestrator.run()
    restarted_orchestrator.commit_turn()
    # The next identical Evidence is REPLAY: consumed zero further times.
    restarted_orchestrator.begin_turn(make_interaction("interaction-3"))
    replay = restarted_orchestrator.ingest(evidence)
    assert replay == repaired
    assert len(restarted_orchestrator.observations) == 0


def test_case6_new_consumption_still_works() -> None:
    service = FactIngestService(clock=FakeClock(NOW))
    orchestrator = make_orchestrator(service)
    evidence = make_evidence(text="我刚睡醒")
    orchestrator.begin_turn(make_interaction())
    observation = orchestrator.ingest(evidence)
    assert orchestrator.observations == (observation,)
    assert orchestrator._turn is not None
    assert orchestrator._turn.evidence_refs == (evidence.id,)
    assert orchestrator.factual_overlay["user_message.observed"] == {"text": "我刚睡醒"}
    orchestrator.run()
    orchestrator.commit_turn()


def test_case7_trace_distinguishes_dispositions(tmp_path: Path) -> None:
    import sqlite3

    backend_path = tmp_path / "facts.db"
    service = FactIngestService(clock=FakeClock(NOW), backend=SqliteFactBackend(backend_path))
    orchestrator = make_orchestrator(service)
    evidence = make_evidence(text="我刚睡醒")
    orchestrator.begin_turn(make_interaction("interaction-1"))
    orchestrator.ingest(evidence)
    outcomes = [entry.outcome for entry in orchestrator.trace.trace("interaction-1")]
    assert "fact_new" in outcomes
    orchestrator.run()
    orchestrator.commit_turn()
    # Replay leg: identical Evidence again -> fact_replay, not a new cause.
    orchestrator.begin_turn(make_interaction("interaction-2"))
    orchestrator.ingest(evidence)
    replay_outcomes = [entry.outcome for entry in orchestrator.trace.trace("interaction-2")]
    assert replay_outcomes[1] == "fact_replay"
    # Repair leg: crash window then repair -> fact_repaired.
    conn = sqlite3.connect(backend_path)
    conn.execute("DELETE FROM observations")
    conn.commit()
    conn.close()
    restarted = FactIngestService(clock=FakeClock(NOW), backend=SqliteFactBackend(backend_path))
    repaired_orchestrator = make_orchestrator(restarted)
    repaired_orchestrator.begin_turn(make_interaction("interaction-3"))
    repaired_orchestrator.ingest(evidence)
    repair_outcomes = [
        entry.outcome for entry in repaired_orchestrator.trace.trace("interaction-3")
    ]
    assert repair_outcomes[1] == "fact_repaired"
