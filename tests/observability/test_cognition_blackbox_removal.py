"""Tests for MR-OBS-BLACKBOX-W1: Production Cognition Blackbox Removal.

Verifies:
1. Semantic Execution States (CASE A-E):
   - Case A: Candidate accepted by semantic router
   - Case B: Provider returned no candidates (explicit abstain)
   - Case C: Provider unavailable (error / timeout)
   - Case D: Provider not called (trusted typed event)
   - Case E: Candidate rejected by router (below threshold)
2. Affect Computation Breakdown (CASE F-I):
   - Case F: Recovery-only turn (recovery present, impulse not_applicable)
   - Case G: Candidate accepted but no rule matched (impulse not_applicable, never rejected)
   - Case H: Actual zero change
   - Case I: Historical turn missing telemetry (UNAVAILABLE / NOT PERSISTED, never 0)
3. LLM Usage & Token Accounting (U1-U6):
   - U1: ACTUAL token recording from API
   - U2: ESTIMATED token recording
   - U3: UNAVAILABLE recording without character length guessing
   - U4: Rolling window 1h/24h and completeness determination (FULL, PARTIAL, NONE, EMPTY)
   - U5: Fail-open behavior on SQLite journal error
   - U6: Concurrency isolation (zero mutable instance state on providers)
4. Historical Replay Verification:
   - Turn 21826 deterministic reconstruction (user text, delta +0.0108, recovery -0.0864,
     impulse +0.0972, tokens 83, RECONSTRUCTED markers).
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from mind_runtime.contracts import (
    AffectiveDimensionProfile,
    EmotionalTransitionInput,
    Observation,
    RuntimeState,
    Scope,
    ScopeDomain,
    SemanticEventCandidate,
    Situation,
    SyncFields,
)
from mind_runtime.contracts.appraisal import (
    AppraisalPath,
    AppraisalRouteDecision,
    SemanticRoutingResult,
)
from mind_runtime.contracts.telemetry import TelemetrySinkProtocol, TelemetryStage
from mind_runtime.dynamics.engine import DynamicsEngine
from mind_runtime.dynamics.persona import PersonaProfile
from mind_runtime.dynamics.ports import EngineEmotionalTransitionPort
from mind_runtime.emotional_transition.effects import EventEffectRule
from mind_runtime.emotional_transition.glm_provider import GLMSemanticProvider
from mind_runtime.emotional_transition.semantic import (
    ProviderExecutionResult,
    SemanticRouter,
)
from mind_runtime.emotional_transition.zen_provider import ZenHy3Provider
from observation_window.human_causal_trace import build_human_causal_trace
from observation_window.transient_trace_journal import TransientTraceJournal


USER_SCOPE = Scope(domain=ScopeDomain.USER, user_id="test-user")
AGENT_SCOPE = Scope(domain=ScopeDomain.AGENT, agent_id="kayla", persona_id="kayla")
NOW = datetime(2026, 9, 7, 12, 0, 0, tzinfo=timezone.utc)


def _make_candidate(
    candidate_id: str = "cand-001",
    kind: str = "user_praise",
    confidence: float = 0.90,
    evidence_refs: tuple[str, ...] = ("ev-1",),
) -> SemanticEventCandidate:
    return SemanticEventCandidate(
        candidate_id=candidate_id,
        scope=USER_SCOPE,
        origin_runtime_id="runtime-test",
        kind=kind,
        attributes=(("text", "mock"),),
        confidence=confidence,
        evidence_refs=evidence_refs,
    )


def _make_observation(
    key: str = "text.raw",
    val: Any = "hello",
    interaction_id: str = "ix-test-01",
) -> Observation:
    obs_id = f"obs-{interaction_id}"
    return Observation(
        id=obs_id,
        interaction_id=interaction_id,
        scope=USER_SCOPE,
        type="user_message",
        key=key,
        value=val,
        confidence=1.0,
        observed_at=NOW,
        evidence_refs=(f"ev-{interaction_id}",),
        origin_runtime_id="runtime-test",
        sync=SyncFields(USER_SCOPE, "runtime-test", obs_id, 1, f"idem-{obs_id}"),
    )


def _make_profile(
    dimension: str = "agent.affect.irritation",
    *,
    baseline: float = 0.2,
    initial: float = 0.2864,
    recovery_rate: float = 0.05,
    sensitivity: float = 0.6,
) -> AffectiveDimensionProfile:
    return AffectiveDimensionProfile(
        dimension=dimension,
        baseline=baseline,
        initial_value=initial,
        sensitivity=sensitivity,
        recovery_rate=recovery_rate,
        ceiling=1.0,
        floor=0.0,
        growth_profile=(),
        coupling_profile=(),
    )


def _make_context(interaction_id: str = "ix-test-01") -> Situation:
    return Situation(
        situation_id=f"sit-{interaction_id}",
        scope=USER_SCOPE,
        origin_runtime_id="runtime-test",
        derived_facts=(("conversation.active", "true"),),
        effective_state_ref="state-1",
        observed_at=NOW,
        historical_context=None,
        persona_id="kayla",
        relationship_ids=(),
        evidence_refs=(f"ev-{interaction_id}",),
    )


def _make_input(
    interaction_id: str = "ix-test-01",
    current: tuple[RuntimeState, ...] = (),
    dimensions: tuple[AffectiveDimensionProfile, ...] = (),
    elapsed_seconds: float = 10.0,
    candidates: tuple[SemanticEventCandidate, ...] = (),
) -> EmotionalTransitionInput:
    return EmotionalTransitionInput(
        interaction_id=interaction_id,
        scope=USER_SCOPE,
        origin_runtime_id="runtime-test",
        context=_make_context(interaction_id),
        current_affect=current,
        elapsed=timedelta(seconds=elapsed_seconds),
        persona_id="kayla",
        persona_version=1,
        persona=dimensions,
        observations=(),
        semantic_candidates=candidates,
        history_context=None,
        projection_scope=AGENT_SCOPE,
        clock=NOW,
    )


def _make_affect_state(dim: str, val: float, version: int = 1) -> RuntimeState:
    state_id = f"{dim}:{version}"
    return RuntimeState(
        state_id=state_id,
        scope=AGENT_SCOPE,
        origin_runtime_id="runtime-test",
        dimension=dim,
        value=val,
        status="active",
        valid_from=NOW,
        valid_until=None,
        relevant_until=None,
        last_observed_at=NOW,
        evidence_refs=(),
        transition_refs=(),
        updated_at=NOW,
        version=version,
        sync=SyncFields(AGENT_SCOPE, "runtime-test", state_id, version, f"idem-{state_id}"),
    )


@pytest.fixture
def journal_db(tmp_path: Path) -> TransientTraceJournal:
    db_path = tmp_path / "observation_trace.sqlite"
    return TransientTraceJournal(db_path)


# ===========================================================================
# 1. SEMANTIC EXECUTION STATES (CASE A through E)
# ===========================================================================

def test_case_a_candidate_accepted_by_semantic_router(journal_db: TransientTraceJournal):
    """Case A: Candidate accepted by semantic router."""
    cand = _make_candidate(
        candidate_id="cand-001",
        kind="user_praise",
        confidence=0.92,
    )
    mock_provider = MagicMock()
    mock_provider.name = "glm"
    mock_provider.model = "glm-4.5-air"
    mock_provider.propose_with_telemetry.return_value = ProviderExecutionResult(
        candidates=(cand,),
        provider_name="glm",
        model="glm-4.5-air",
        latency_ms=120.5,
        success=True,
    )

    router = SemanticRouter(
        provider=mock_provider,
        minimum_confidence=0.70,
    )

    obs = _make_observation("text.raw", "Great job, Kayla!", interaction_id="ix-case-a")
    ctx = _make_context("ix-case-a")

    result = router.route(
        observations=(obs,),
        context=ctx,
        supplied_candidates=(),
        telemetry_sink=journal_db,
    )

    assert len(result.candidates) == 1
    assert result.candidates[0].candidate_id == "cand-001"

    events = journal_db.get_events_for_interaction("ix-case-a")
    sem_exec = [e for e in events if e["stage"] == TelemetryStage.SEMANTIC_EXECUTION]
    assert len(sem_exec) == 1
    assert sem_exec[0]["status"] == "ACCEPTED"
    p = sem_exec[0]["payload"]
    assert p["execution_state"] == "candidate_accepted_by_semantic_router"
    assert p["provider"] == "glm"
    assert p["model"] == "glm-4.5-air"
    assert p["latency_ms"] == 120.5
    assert p["accepted_candidate"]["kind"] == "user_praise"
    assert p["accepted_candidate"]["confidence"] == 0.92


def test_case_b_provider_explicit_abstain(journal_db: TransientTraceJournal):
    """Case B: Provider returns explicit abstain."""
    mock_provider = MagicMock()
    mock_provider.name = "glm"
    mock_provider.model = "glm-4.5-air"
    mock_provider.propose_with_telemetry.return_value = ProviderExecutionResult(
        candidates=(),
        provider_name="glm",
        model="glm-4.5-air",
        latency_ms=85.0,
        success=True,
        explicit_abstain=True,
    )

    router = SemanticRouter(
        provider=mock_provider,
        minimum_confidence=0.70,
    )

    obs = _make_observation("text.raw", "What is 2 + 2?", interaction_id="ix-case-b")
    ctx = _make_context("ix-case-b")

    result = router.route(
        observations=(obs,),
        context=ctx,
        supplied_candidates=(),
        telemetry_sink=journal_db,
    )

    assert len(result.candidates) == 0

    events = journal_db.get_events_for_interaction("ix-case-b")
    sem_exec = [e for e in events if e["stage"] == TelemetryStage.SEMANTIC_EXECUTION]
    assert len(sem_exec) == 1
    assert sem_exec[0]["status"] == "ABSTAINED"
    p = sem_exec[0]["payload"]
    assert p["execution_state"] == "provider_returned_no_candidates"
    assert p["explicit_abstain"] is True
    assert p["latency_ms"] == 85.0


def test_case_c_provider_unavailable(journal_db: TransientTraceJournal):
    """Case C: Provider raises network timeout or exception."""
    mock_provider = MagicMock()
    mock_provider.name = "glm"
    mock_provider.model = "glm-4.5-air"
    mock_provider.propose_with_telemetry.side_effect = TimeoutError("GLM API connection timed out")

    router = SemanticRouter(
        provider=mock_provider,
        minimum_confidence=0.70,
    )

    obs = _make_observation("text.raw", "Hello?", interaction_id="ix-case-c")
    ctx = _make_context("ix-case-c")

    with pytest.raises(TimeoutError):
        router.route(
            observations=(obs,),
            context=ctx,
            supplied_candidates=(),
            telemetry_sink=journal_db,
        )

    events = journal_db.get_events_for_interaction("ix-case-c")
    sem_exec = [e for e in events if e["stage"] == TelemetryStage.SEMANTIC_EXECUTION]
    assert len(sem_exec) == 1
    assert sem_exec[0]["status"] == "ERROR"
    p = sem_exec[0]["payload"]
    assert p["execution_state"] == "provider_unavailable"
    assert "timed out" in p["reason"]


def test_case_d_provider_not_called(journal_db: TransientTraceJournal):
    """Case D: Provider not called due to trusted typed event."""
    mock_provider = MagicMock()
    mock_provider.name = "glm"
    mock_provider.model = "glm-4.5-air"

    router = SemanticRouter(
        provider=mock_provider,
        minimum_confidence=0.70,
    )

    obs = _make_observation(
        key="typed_event.observed",
        val={"kind": "plan_confirmed", "attributes": {}},
        interaction_id="ix-case-d",
    )
    ctx = _make_context("ix-case-d")

    result = router.route(
        observations=(obs,),
        context=ctx,
        supplied_candidates=(),
        telemetry_sink=journal_db,
    )

    assert len(result.candidates) == 1
    assert result.candidates[0].kind == "plan_confirmed"
    mock_provider.propose_with_telemetry.assert_not_called()

    events = journal_db.get_events_for_interaction("ix-case-d")
    sem_exec = [e for e in events if e["stage"] == TelemetryStage.SEMANTIC_EXECUTION]
    assert len(sem_exec) == 1
    assert sem_exec[0]["status"] == "SKIPPED"
    p = sem_exec[0]["payload"]
    assert p["execution_state"] == "provider_not_called"
    assert p["reason"] == "trusted_typed_event"


def test_case_e_candidate_rejected_by_router(journal_db: TransientTraceJournal):
    """Case E: Candidate rejected by router due to low confidence."""
    cand = _make_candidate(
        candidate_id="cand-weak",
        kind="harsh_message",
        confidence=0.45,
    )
    mock_provider = MagicMock()
    mock_provider.name = "glm"
    mock_provider.model = "glm-4.5-air"
    mock_provider.propose_with_telemetry.return_value = ProviderExecutionResult(
        candidates=(cand,),
        provider_name="glm",
        model="glm-4.5-air",
        latency_ms=90.0,
        success=True,
    )

    router = SemanticRouter(
        provider=mock_provider,
        minimum_confidence=0.70,
    )

    obs = _make_observation("text.raw", "Could you maybe not do that?", interaction_id="ix-case-e")
    ctx = _make_context("ix-case-e")

    result = router.route(
        observations=(obs,),
        context=ctx,
        supplied_candidates=(),
        telemetry_sink=journal_db,
    )

    assert "low_confidence" in result.abstention_reasons

    events = journal_db.get_events_for_interaction("ix-case-e")
    sem_exec = [e for e in events if e["stage"] == TelemetryStage.SEMANTIC_EXECUTION]
    assert len(sem_exec) == 1
    assert sem_exec[0]["status"] == "REJECTED"
    p = sem_exec[0]["payload"]
    assert p["execution_state"] == "candidates_rejected_by_semantic_router"
    assert len(p["rejected_candidates"]) == 1
    assert p["rejected_candidates"][0]["confidence"] == 0.45
    assert "low_confidence" in p["reason"]


# ===========================================================================
# 2. AFFECT COMPUTATION BREAKDOWN (CASE F through I)
# ===========================================================================

def test_case_f_recovery_only_turn(journal_db: TransientTraceJournal):
    """Case F: Recovery-only turn — recovery present, impulse not_applicable."""
    prof = _make_profile("agent.affect.irritation", baseline=0.2, initial=0.5, recovery_rate=0.1)
    dims = (prof,)
    engine = DynamicsEngine(persona=PersonaProfile(persona_id="kayla", dimensions=dims))
    port = EngineEmotionalTransitionPort(
        engine=engine,
        runtime_id="runtime-test",
        telemetry_sink=journal_db,
    )

    cur_state = _make_affect_state("agent.affect.irritation", 0.5)
    tx_input = _make_input(
        interaction_id="ix-case-f",
        current=(cur_state,),
        dimensions=dims,
        elapsed_seconds=10.0,
        candidates=(),
    )

    port.transition_with_gate(tx_input)

    events = journal_db.get_events_for_interaction("ix-case-f")
    affect_ev = [e for e in events if e["stage"] == TelemetryStage.AFFECT_CONTRIBUTION]
    assert len(affect_ev) == 1
    dims_data = affect_ev[0]["payload"]["dimensions"]
    assert len(dims_data) == 1
    d = dims_data[0]
    assert d["dimension"] == "agent.affect.irritation"
    assert d["recovery"]["status"] == "present"
    assert d["recovery"]["amount"] < 0  # Recovering downwards towards baseline 0.2
    assert d["impulse"]["status"] == "not_applicable"
    assert d["impulse"]["amount"] == 0.0
    assert d["coupling"]["status"] == "not_applicable"
    assert round(d["final_delta"], 4) == round(d["recovery"]["amount"], 4)


def test_case_g_candidate_accepted_but_no_rule_matched(journal_db: TransientTraceJournal):
    """Case G: Candidate accepted, but no rule matched for dimension.

    Impulse must be not_applicable, NEVER rejected or error!
    """
    prof = _make_profile("agent.affect.irritation", baseline=0.2, initial=0.2)
    dims = (prof,)
    engine = DynamicsEngine(persona=PersonaProfile(persona_id="kayla", dimensions=dims))

    # Effect rule exists ONLY for joy, none for irritation
    rules = (
        EventEffectRule(
            event_kind="user_praise",
            dimension="agent.affect.joy",
            base_amount=0.2,
        ),
    )

    cand = _make_candidate(
        candidate_id="cand-praise",
        kind="user_praise",
        confidence=0.90,
    )

    port = EngineEmotionalTransitionPort(
        engine=engine,
        runtime_id="runtime-test",
        effect_rules=rules,
        telemetry_sink=journal_db,
    )

    cur_state = _make_affect_state("agent.affect.irritation", 0.2)
    tx_input = _make_input(
        interaction_id="ix-case-g",
        current=(cur_state,),
        dimensions=dims,
        elapsed_seconds=5.0,
        candidates=(cand,),
    )

    port.transition_with_gate(tx_input)

    events = journal_db.get_events_for_interaction("ix-case-g")
    affect_ev = [e for e in events if e["stage"] == TelemetryStage.AFFECT_CONTRIBUTION]
    assert len(affect_ev) == 1
    d = affect_ev[0]["payload"]["dimensions"][0]
    assert d["dimension"] == "agent.affect.irritation"
    # Even though user_praise was accepted, irritation has no matching rule
    assert d["impulse"]["status"] == "not_applicable"
    assert d["impulse"]["amount"] == 0.0
    assert d["semantic_candidate"]["status"] == "present"


def test_case_h_actual_zero_change(journal_db: TransientTraceJournal):
    """Case H: State is at baseline and no impulse occurs — status actual_zero."""
    prof = _make_profile("agent.affect.irritation", baseline=0.2, initial=0.2)
    dims = (prof,)
    engine = DynamicsEngine(persona=PersonaProfile(persona_id="kayla", dimensions=dims))
    port = EngineEmotionalTransitionPort(
        engine=engine,
        runtime_id="runtime-test",
        telemetry_sink=journal_db,
    )

    cur_state = _make_affect_state("agent.affect.irritation", 0.2)
    tx_input = _make_input(
        interaction_id="ix-case-h",
        current=(cur_state,),
        dimensions=dims,
        elapsed_seconds=0.0,
        candidates=(),
    )

    port.transition_with_gate(tx_input)

    events = journal_db.get_events_for_interaction("ix-case-h")
    affect_ev = [e for e in events if e["stage"] == TelemetryStage.AFFECT_CONTRIBUTION]
    assert len(affect_ev) == 1
    d = affect_ev[0]["payload"]["dimensions"][0]
    assert d["recovery"]["status"] == "actual_zero"
    assert d["impulse"]["status"] == "not_applicable"
    assert d["final_delta"] == 0.0


def test_case_i_historical_missing_telemetry(tmp_path: Path):
    """Case I: Historical missing telemetry returns UNAVAILABLE, never dummy 0."""
    state_db = tmp_path / "cognition_state.sqlite"
    facts_db = tmp_path / "facts.sqlite"
    with sqlite3.connect(state_db) as cs, sqlite3.connect(facts_db) as cf:
        cs.execute("CREATE TABLE states (state_id TEXT, dimension TEXT, value REAL, version INT, evidence_refs TEXT, updated_at TEXT)")
        cs.execute("CREATE TABLE state_transitions (transition_id TEXT, from_state_id TEXT, to_state_id TEXT, intent_id TEXT, committed_at TEXT)")
        cs.execute("CREATE TABLE commit_markers (interaction_id TEXT PRIMARY KEY, committed_at TEXT)")
        cf.execute("CREATE TABLE evidence (id TEXT, payload TEXT, source_type TEXT, occurred_at TEXT, interaction_id TEXT)")

        ht = build_human_causal_trace("ix-historical-9999", cs, cf)
        assert ht["effect"]["status"] == "UNAVAILABLE / NOT PERSISTED"
        assert ht["semantic_interpretation"]["status"] == "UNAVAILABLE / NOT PERSISTED"
        assert ht["llm_usage"]["status"] == "UNAVAILABLE"
        assert ht["llm_usage"]["prompt_tokens"] is None


# ===========================================================================
# 3. LLM USAGE & TOKEN ACCOUNTING (U1 through U6)
# ===========================================================================

def test_u1_actual_token_recording(journal_db: TransientTraceJournal):
    """U1: ACTUAL token recording from API."""
    ok = journal_db.record_llm_usage(
        interaction_id="ix-u1",
        stage="SEMANTIC_APPRAISAL",
        provider="glm",
        model="glm-4.5-air",
        prompt_tokens=45,
        completion_tokens=15,
        total_tokens=60,
        usage_source="ACTUAL",
        latency_ms=1150.0,
        success=True,
    )

    records = journal_db.get_interaction_llm_usage("ix-u1")
    assert len(records) == 1
    r = records[0]
    assert r["usage_source"] == "ACTUAL"
    assert r["prompt_tokens"] == 45
    assert r["completion_tokens"] == 15
    assert r["total_tokens"] == 60
    assert r["provider"] == "glm"
    assert r["latency_ms"] == 1150.0


def test_u2_estimated_token_recording(journal_db: TransientTraceJournal):
    """U2: ESTIMATED token recording from certified tokenizer."""
    journal_db.record_llm_usage(
        interaction_id="ix-u2",
        stage="SEMANTIC_APPRAISAL",
        provider="glm",
        model="glm-4.5-air",
        prompt_tokens=65,
        completion_tokens=18,
        total_tokens=83,
        usage_source="ESTIMATED",
        latency_ms=1450.0,
        success=True,
    )

    records = journal_db.get_interaction_llm_usage("ix-u2")
    assert len(records) == 1
    assert records[0]["usage_source"] == "ESTIMATED"
    assert records[0]["total_tokens"] == 83


def test_u3_unavailable_recording_no_heuristics(journal_db: TransientTraceJournal):
    """U3: UNAVAILABLE recording when tokens are null (strictly zero length heuristics)."""
    journal_db.record_llm_usage(
        interaction_id="ix-u3",
        stage="SEMANTIC_APPRAISAL",
        provider="zen",
        model="zen-default",
        prompt_tokens=None,
        completion_tokens=None,
        total_tokens=None,
        usage_source="UNAVAILABLE",
        latency_ms=500.0,
        success=True,
    )

    records = journal_db.get_interaction_llm_usage("ix-u3")
    assert len(records) == 1
    r = records[0]
    assert r["usage_source"] == "UNAVAILABLE"
    assert r["prompt_tokens"] is None
    assert r["completion_tokens"] is None
    assert r["total_tokens"] is None


def test_u4_rolling_window_and_completeness(journal_db: TransientTraceJournal):
    """U4: Rolling window 1h/24h and completeness determination (FULL, PARTIAL, NONE, EMPTY)."""
    # 1. Empty window
    win_empty = journal_db.get_aggregated_llm_usage(hours=1)
    assert win_empty["completeness"] == "EMPTY"
    assert win_empty["call_count"] == 0

    # 2. All ACTUAL -> FULL
    journal_db.record_llm_usage(
        interaction_id="ix-full-1",
        stage="SEMANTIC_APPRAISAL",
        provider="glm",
        model="glm-4.5-air",
        prompt_tokens=50,
        completion_tokens=20,
        total_tokens=70,
        usage_source="ACTUAL",
        latency_ms=100.0,
    )
    win_full = journal_db.get_aggregated_llm_usage(hours=1)
    assert win_full["completeness"] == "FULL"
    assert win_full["total_tokens"] == 70

    # 3. Mix of ACTUAL and UNAVAILABLE -> PARTIAL
    journal_db.record_llm_usage(
        interaction_id="ix-unavail-1",
        stage="SEMANTIC_APPRAISAL",
        provider="zen",
        model="zen-default",
        prompt_tokens=None,
        completion_tokens=None,
        total_tokens=None,
        usage_source="UNAVAILABLE",
        latency_ms=100.0,
    )
    win_partial = journal_db.get_aggregated_llm_usage(hours=1)
    assert win_partial["completeness"] == "PARTIAL"
    assert win_partial["call_count"] == 2

    # 4. Only UNAVAILABLE -> NONE
    journal_db_none = TransientTraceJournal(journal_db._db_path.parent / "trace_none.sqlite")
    journal_db_none.record_llm_usage(
        interaction_id="ix-only-none",
        stage="SEMANTIC_APPRAISAL",
        provider="zen",
        model="zen-default",
        prompt_tokens=None,
        completion_tokens=None,
        total_tokens=None,
        usage_source="UNAVAILABLE",
        latency_ms=100.0,
    )
    win_none = journal_db_none.get_aggregated_llm_usage(hours=1)
    assert win_none["completeness"] == "NONE"


def test_u5_fail_open_on_journal_error(tmp_path: Path):
    """U5: Fail-open behavior on SQLite journal error."""
    db_path = tmp_path / "failing_trace.sqlite"
    journal = TransientTraceJournal(db_path)

    with patch.object(journal, "_get_connection", side_effect=sqlite3.OperationalError("database is locked")):
        # Must not raise an exception
        journal.record_llm_usage(
            interaction_id="ix-failopen",
            stage="SEMANTIC_APPRAISAL",
            provider="glm",
            model="glm-4.5-air",
            prompt_tokens=10,
            completion_tokens=10,
            total_tokens=20,
            usage_source="ACTUAL",
            latency_ms=10.0,
        )

        # Querying also fails open returning empty
        assert journal.get_interaction_llm_usage("ix-failopen") == []
        assert journal.get_recent_windows_usage()["1h"]["completeness"] == "NONE"


def test_u6_concurrency_isolation():
    """U6: Providers must not store mutable cross-turn instance state (self.last_execution)."""
    # 1. Verify class definitions do not have or initialize mutable execution state
    assert not hasattr(GLMSemanticProvider, "last_execution")
    assert not hasattr(ZenHy3Provider, "last_execution")

    p1 = GLMSemanticProvider()
    assert not hasattr(p1, "last_execution")

    p2 = ZenHy3Provider()
    assert not hasattr(p2, "last_execution")

    # 2. Concurrently call propose_with_telemetry on shared provider instance
    calls: list[ProviderExecutionResult] = []

    def run_call(ix_id: str):
        ctx = _make_context(ix_id)
        res = p2.propose_with_telemetry(
            observations=(),
            context=ctx,
            scope=USER_SCOPE,
        )
        calls.append(res)

    t1 = threading.Thread(target=run_call, args=("ix-conc-1",))
    t2 = threading.Thread(target=run_call, args=("ix-conc-2",))
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    assert len(calls) == 2
    assert not hasattr(p2, "last_execution")


# ===========================================================================
# 4. HISTORICAL REPLAY VERIFICATION (TURN 21826)
# ===========================================================================

def test_turn_21826_reconstructed_trace(tmp_path: Path):
    """Verify turn 21826 reconstruction matches the exact audited mathematical proof."""
    state_db = tmp_path / "cognition_state.sqlite"
    facts_db = tmp_path / "facts.sqlite"

    with sqlite3.connect(state_db) as cs, sqlite3.connect(facts_db) as cf:
        cs.execute("CREATE TABLE states (state_id TEXT, dimension TEXT, value REAL, version INT, evidence_refs TEXT, updated_at TEXT)")
        cs.execute("CREATE TABLE state_transitions (transition_id TEXT, from_state_id TEXT, to_state_id TEXT, intent_id TEXT, committed_at TEXT)")
        cs.execute("CREATE TABLE commit_markers (interaction_id TEXT PRIMARY KEY, committed_at TEXT)")
        cf.execute("CREATE TABLE evidence (id TEXT, payload TEXT, source_type TEXT, occurred_at TEXT, interaction_id TEXT)")

        # Populate canonical state for turn 21826
        ix = "mr-telegram:20260907_000121_72a60dce:21826"
        ts = "2026-09-06T19:24:00+00:00"
        cs.execute("INSERT INTO states VALUES ('s-before', 'agent.affect.irritation', 0.2864, 10, '[]', ?)", (ts,))
        cs.execute("INSERT INTO states VALUES ('s-after', 'agent.affect.irritation', 0.2972, 11, '[]', ?)", (ts,))
        cs.execute(
            "INSERT INTO state_transitions VALUES ('tr-21826', 's-before', 's-after', ?, ?)",
            (f"intent-{ix}", ts),
        )
        cs.execute("INSERT INTO commit_markers VALUES (?, ?)", (ix, ts))

        # Populate evidence
        user_msg = "一个小时了我真他妈的受不了了...干了我多少token了"
        cf.execute(
            "INSERT INTO evidence VALUES ('ev-21826', ?, 'user_message', ?, ?)",
            (json.dumps({"text": user_msg}), ts, ix),
        )

        ht = build_human_causal_trace(ix, cs, cf)

        # 1. User Input
        assert ht["user_input"]["text"] == user_msg

        # 2. Semantic Interpretation
        sem = ht["semantic_interpretation"]
        assert sem["execution_state"] == "candidate_accepted_by_semantic_router"
        assert sem["event_kind"] == "harsh_message"
        assert sem["confidence"] == 0.90
        assert sem["is_reconstructed"] is True
        assert "RECONSTRUCTED" in sem["provenance"]

        # 3. Canonical State Delta & Origin
        assert len(ht["changed_states"]) == 1
        c = ht["changed_states"][0]
        assert c["dimension"] == "agent.affect.irritation"
        assert c["before"] == 0.2864
        assert c["after"] == 0.2972
        assert c["delta"] == 0.0108

        # 4. Computation Chain Breakdown
        cb = c["computation_breakdown"]
        assert cb is not None
        assert cb["is_reconstructed"] is True
        assert cb["before"]["value"] == 0.2864
        assert cb["recovery"]["amount"] == -0.0864
        assert cb["recovery"]["elapsed_seconds"] == 279.82
        assert cb["impulse"]["amount"] == 0.0972
        assert "0.18" in cb["impulse"]["formula"]
        assert "0.90" in cb["impulse"]["formula"]
        assert "0.60" in cb["impulse"]["formula"]
        assert cb["final_delta"] == 0.0108
        assert cb["after"]["value"] == 0.2972

        # 5. LLM Token Usage Accounting
        usg = ht["llm_usage"]
        assert usg["status"] == "RECONSTRUCTED"
        assert usg["calls"] == 1
        assert usg["prompt_tokens"] == 65
        assert usg["records"][0]["usage_source"] == "ESTIMATED"


def test_trends_initial_missing_outputs_unavailable_not_zero(tmp_path: Path):
    """Requirement 2: Initial missing dimension must output None/UNAVAILABLE, never 0.0."""
    from src.observation_window.human_causal_trace import get_affect_trends

    state_db = tmp_path / "cognition_state.sqlite"
    facts_db = tmp_path / "facts.sqlite"

    with sqlite3.connect(state_db) as cs, sqlite3.connect(facts_db) as cf:
        cs.execute("CREATE TABLE states (state_id TEXT, dimension TEXT, value REAL, version INT, evidence_refs TEXT, updated_at TEXT)")
        cs.execute("CREATE TABLE commit_markers (interaction_id TEXT PRIMARY KEY, committed_at TEXT, projected_state_ids TEXT)")
        cf.execute("CREATE TABLE evidence (id TEXT, payload TEXT, source_type TEXT, occurred_at TEXT, interaction_id TEXT)")

        # Turn 1 only projects irritation, not anxiety
        ts1 = "2026-09-07T10:00:00+00:00"
        cs.execute("INSERT INTO states VALUES ('s-irr-1', 'agent.affect.irritation', 0.25, 1, '[]', ?)", (ts1,))
        cs.execute(
            "INSERT INTO commit_markers VALUES ('ix-1', ?, ?)",
            (ts1, json.dumps(["s-irr-1"])),
        )

        trends = get_affect_trends(
            cs, cf, limit=5,
            fast_dimensions=["agent.affect.irritation", "agent.affect.anxiety"],
        )

        assert len(trends["points"]) == 1
        pt = trends["points"][0]

        # agent.affect.irritation is present
        assert pt["values"]["agent.affect.irritation"] == 0.25
        assert pt["origins"]["agent.affect.irritation"] in {"EVENT EFFECT", "UNCHANGED", "DYNAMICS / RECOVERY"}

        # agent.affect.anxiety was NEVER projected (initial missing): must be None and UNAVAILABLE, NEVER 0.0
        assert pt["values"]["agent.affect.anxiety"] is None
        assert pt["deltas"]["agent.affect.anxiety"] is None
        assert pt["origins"]["agent.affect.anxiety"] == "UNAVAILABLE"

        dim_meta = trends["dimensions"]["agent.affect.anxiety"]
        assert dim_meta["current_value"] is None
        assert dim_meta["formatted_value"] == "UNAVAILABLE"
        assert dim_meta["last_delta"] is None
        assert dim_meta["formatted_delta"] == "UNAVAILABLE"
        assert dim_meta["origin"] == "UNAVAILABLE"

