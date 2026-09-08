"""Tests for OW-TRANSIENT-TRACE-JOURNAL-V1: Transient Trace Journal & Observability.

Verifies the 11 required scenarios:
1. test_semantic_candidate_captured:
   provider returns candidate, assert row in observation_trace.sqlite,
   stage = SEMANTIC_CANDIDATE, status = PROPOSED, payload contains candidate fields.
2. test_semantic_abstention_captured:
   provider returns None (abstain), assert stage = SEMANTIC_ABSTAIN, status = ABSTAINED.
3. test_appraisal_captured:
   appraisal completes, assert stage = APPRAISAL, status = ACCEPTED,
   payload contains valence, salience, meanings, appraisal_confidence.
4. test_homeostasis_truth_captured:
   homeostasis gate runs, assert stage = HOMEOSTASIS, payload contains disposition/etc.
   OW reads this and does NOT recompute.
5. test_state_causal_linkage:
   irritation 0.20 -> 0.35 linked to interaction_id, appraisal, effect in journal.
6. test_dynamics_recovery_linkage:
   state changes without evidence (baseline drift) linked as DYNAMICS / RECOVERY.
7. test_slow_accept_captured:
   slow plasticity fires, stage = SLOW_DECISION status = ACCEPTED,
   stage = SLOW_WRITE status = COMMITTED (after canonical write).
8. test_exact_assistant_linkage:
   assistant message linked by exact durable Hermes message ID (hermes-msg:{id}), NEVER guessed.
9. test_telemetry_db_failure_does_not_break_turn:
   corrupted/locked observation_trace.sqlite: turn completes successfully (fail-open).
10. test_aborted_turn_records_telemetry_cleanly:
    turn aborted, journal records TURN_ABORT, no COMMITTED rows, OW displays turn as ABORTED.
11. test_pre_journal_historical_turn_fallback:
    historical turn from before journal existed renders UNAVAILABLE / NOT PERSISTED, never calls models.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
import sqlite3
from typing import Any
from unittest.mock import MagicMock

import pytest

from mind_runtime.contracts.telemetry import TelemetryStage, TelemetrySinkProtocol
from mind_runtime.contracts import (
    AffectiveDimensionProfile,
    EmotionalTransitionInput,
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
    SemanticAppraisal,
    SemanticRoutingResult,
)
from mind_runtime.dynamics.persona import PersonaProfile
from mind_runtime.dynamics.ports import EngineEmotionalTransitionPort
from mind_runtime.dynamics.engine import DynamicsEngine
from observation_window.transient_trace_journal import TransientTraceJournal
from observation_window.human_causal_trace import build_human_causal_trace


# ---------------------------------------------------------------------------
# Helpers & Fixtures
# ---------------------------------------------------------------------------

USER_SCOPE = Scope(domain=ScopeDomain.USER, user_id="test-user")
AGENT_SCOPE = Scope(domain=ScopeDomain.AGENT, agent_id="test-agent", persona_id="test-persona")
NOW = datetime(2026, 9, 5, 12, 0, 0, tzinfo=timezone.utc)


def make_profile(dimension: str, *, baseline: float = 0.3) -> AffectiveDimensionProfile:
    return AffectiveDimensionProfile(
        dimension=dimension,
        baseline=baseline,
        initial_value=baseline,
        sensitivity=0.8,
        recovery_rate=0.2,
        ceiling=1.0,
        floor=0.0,
        growth_profile=(),
        coupling_profile=(),
    )


def _make_route(scope: Scope, path: AppraisalPath = AppraisalPath.TYPED_MAPPING) -> AppraisalRouteDecision:
    return AppraisalRouteDecision(
        route_id="route-test-1",
        scope=scope,
        path=path,
        ambiguity_score=0.1,
        confidence=0.9,
        reason_codes=("ok",),
    )


def _make_context() -> Situation:
    return Situation(
        situation_id="sit-test-1",
        scope=USER_SCOPE,
        origin_runtime_id="runtime-test",
        derived_facts=(("conversation.active", "true"),),
        effective_state_ref="state-1",
        observed_at=NOW,
        historical_context=None,
        persona_id="test-persona",
        relationship_ids=(),
        evidence_refs=("ev-test-1",),
    )


def _make_input(
    interaction_id: str = "ix-test-01",
    current: tuple[RuntimeState, ...] = (),
    dimensions: tuple[AffectiveDimensionProfile, ...] = (),
) -> EmotionalTransitionInput:
    return EmotionalTransitionInput(
        interaction_id=interaction_id,
        scope=USER_SCOPE,
        origin_runtime_id="runtime-test",
        context=_make_context(),
        current_affect=current,
        elapsed=timedelta(seconds=1),
        persona_id="test-persona",
        persona_version=1,
        persona=dimensions,
        observations=(),
        semantic_candidates=(),
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
def empty_dbs(tmp_path):
    conn_state = sqlite3.connect(":memory:", check_same_thread=False)
    conn_facts = sqlite3.connect(":memory:", check_same_thread=False)

    conn_state.executescript("""
        CREATE TABLE commit_markers (
            interaction_id TEXT PRIMARY KEY,
            committed_at TEXT NOT NULL,
            projected_state_ids TEXT
        );
        CREATE TABLE states (
            state_id TEXT PRIMARY KEY,
            dimension TEXT NOT NULL,
            value TEXT NOT NULL,
            version INTEGER NOT NULL,
            status TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            evidence_refs TEXT,
            transition_refs TEXT
        );
        CREATE TABLE state_transitions (
            transition_id TEXT PRIMARY KEY,
            from_state_id TEXT,
            to_state_id TEXT NOT NULL,
            intent_id TEXT NOT NULL,
            committed_at TEXT NOT NULL
        );
        CREATE TABLE slow_contribution_window (
            id TEXT PRIMARY KEY,
            sequence INTEGER NOT NULL,
            accepted_at TEXT NOT NULL,
            proposed_value TEXT,
            salience REAL,
            evidence_refs TEXT,
            source_decision_id TEXT
        );
    """)

    conn_facts.executescript("""
        CREATE TABLE evidence (
            id TEXT PRIMARY KEY,
            interaction_id TEXT,
            source_type TEXT NOT NULL,
            payload TEXT NOT NULL,
            occurred_at TEXT NOT NULL
        );
        CREATE TABLE observations (
            id TEXT PRIMARY KEY,
            interaction_id TEXT,
            value TEXT NOT NULL,
            confidence REAL,
            observed_at TEXT NOT NULL
        );
    """)

    journal_path = tmp_path / "observation_trace.sqlite"
    journal = TransientTraceJournal(journal_path)

    return conn_state, conn_facts, journal


# ---------------------------------------------------------------------------
# Scenario 1: Semantic Candidate Captured
# ---------------------------------------------------------------------------

def test_semantic_candidate_captured(tmp_path):
    journal_path = tmp_path / "observation_trace.sqlite"
    journal = TransientTraceJournal(journal_path)

    cand = SemanticEventCandidate(
        candidate_id="cand-live-101",
        scope=USER_SCOPE,
        origin_runtime_id="runtime-test",
        kind="user_praise",
        attributes=(),
        confidence=0.915,
        evidence_refs=("ev-praise-1",),
    )

    mock_router = MagicMock()
    mock_router.route.return_value = SemanticRoutingResult(
        route=_make_route(USER_SCOPE),
        candidates=(cand,),
        provider_call_count=1,
        abstention_reasons=(),
    )

    dims = (make_profile("agent.affect.joy", baseline=0.5),)
    port = EngineEmotionalTransitionPort(
        engine=DynamicsEngine(
            persona=PersonaProfile(
                persona_id="test-persona",
                dimensions=dims,
            )
        ),
        runtime_id="runtime-test",
        semantic_router=mock_router,
        telemetry_sink=journal,
    )

    tx_input = _make_input(
        interaction_id="ix-candidate-001",
        current=(_make_affect_state("agent.affect.joy", 0.5),),
        dimensions=dims,
    )

    port.transition(tx_input)

    events = journal.get_events_for_interaction("ix-candidate-001")
    cand_events = [e for e in events if e["stage"] == TelemetryStage.SEMANTIC_CANDIDATE]
    assert len(cand_events) == 1

    ev = cand_events[0]
    assert ev["status"] == "PROPOSED"
    assert ev["payload"]["candidate_id"] == "cand-live-101"
    assert ev["payload"]["event_kind"] == "user_praise"
    assert ev["payload"]["confidence"] == 0.915
    assert ev["payload"]["evidence_refs"] == ["ev-praise-1"]
    assert ev["source_refs"] == ["ev-praise-1"]


# ---------------------------------------------------------------------------
# Scenario 2: Semantic Abstention Captured
# ---------------------------------------------------------------------------

def test_semantic_abstention_captured(tmp_path):
    journal_path = tmp_path / "observation_trace.sqlite"
    journal = TransientTraceJournal(journal_path)

    mock_router = MagicMock()
    mock_router.route.return_value = SemanticRoutingResult(
        route=_make_route(USER_SCOPE),
        candidates=(),
        provider_call_count=1,
        abstention_reasons=("ambiguous_statement", "low_confidence"),
    )

    dims = (make_profile("agent.affect.joy", baseline=0.5),)
    port = EngineEmotionalTransitionPort(
        engine=DynamicsEngine(
            persona=PersonaProfile(
                persona_id="test-persona",
                dimensions=dims,
            )
        ),
        runtime_id="runtime-test",
        semantic_router=mock_router,
        telemetry_sink=journal,
    )

    tx_input = _make_input(
        interaction_id="ix-abstain-002",
        current=(_make_affect_state("agent.affect.joy", 0.5),),
        dimensions=dims,
    )

    port.transition(tx_input)

    events = journal.get_events_for_interaction("ix-abstain-002")
    abstain_events = [e for e in events if e["stage"] == TelemetryStage.SEMANTIC_ABSTAIN]
    assert len(abstain_events) == 1

    ev = abstain_events[0]
    assert ev["status"] == "ABSTAINED"
    assert "ambiguous_statement" in ev["payload"]["abstention_reasons"]
    assert "low_confidence" in ev["payload"]["abstention_reasons"]


# ---------------------------------------------------------------------------
# Scenario 3: Appraisal Captured
# ---------------------------------------------------------------------------

def test_appraisal_captured(tmp_path):
    journal_path = tmp_path / "observation_trace.sqlite"
    journal = TransientTraceJournal(journal_path)

    cand = SemanticEventCandidate(
        candidate_id="cand-app-003",
        scope=USER_SCOPE,
        origin_runtime_id="runtime-test",
        kind="boundary_violation",
        attributes=(),
        confidence=0.88,
        evidence_refs=("ev-viol-1",),
    )

    mock_router = MagicMock()
    mock_router.route.return_value = SemanticRoutingResult(
        route=_make_route(USER_SCOPE),
        candidates=(cand,),
        provider_call_count=1,
        abstention_reasons=(),
    )

    mock_producer = MagicMock()
    mock_producer.assemble.return_value = SemanticAppraisal(
        appraisal_id="app-row-003",
        scope=USER_SCOPE,
        origin_runtime_id="runtime-test",
        situation_ref="sit-test-1",
        meanings=("boundary_crossing", "disrespect"),
        valence="-0.75",
        relationship_relevance="high",
        confidence=0.92,
        salience=0.85,
        evidence_refs=("ev-viol-1",),
    )

    dims = (make_profile("agent.affect.irritation", baseline=0.2),)
    port = EngineEmotionalTransitionPort(
        engine=DynamicsEngine(
            persona=PersonaProfile(
                persona_id="test-persona",
                dimensions=dims,
            )
        ),
        runtime_id="runtime-test",
        semantic_router=mock_router,
        appraisal_producer=mock_producer,
        telemetry_sink=journal,
    )

    tx_input = _make_input(
        interaction_id="ix-appraisal-003",
        current=(_make_affect_state("agent.affect.irritation", 0.2),),
        dimensions=dims,
    )

    port.transition(tx_input)

    events = journal.get_events_for_interaction("ix-appraisal-003")
    app_events = [e for e in events if e["stage"] == TelemetryStage.APPRAISAL]
    assert len(app_events) == 1

    ev = app_events[0]
    assert ev["status"] == "ACCEPTED"
    assert ev["payload"]["appraisal_id"] == "app-row-003"
    assert ev["payload"]["valence"] == "-0.75"
    assert ev["payload"]["salience"] == 0.85
    assert ev["payload"]["confidence"] == 0.92
    assert ev["payload"]["appraisal_confidence"] == 0.92
    assert "boundary_crossing" in ev["payload"]["meanings"]


# ---------------------------------------------------------------------------
# Scenario 4: Homeostasis Truth Captured (OW reads truth, does NOT recompute)
# ---------------------------------------------------------------------------

def test_homeostasis_truth_captured(empty_dbs):
    conn_state, conn_facts, journal = empty_dbs
    ix_id = "ix-homeo-004"
    now_iso = NOW.isoformat()

    conn_state.execute(
        "INSERT INTO commit_markers (interaction_id, committed_at) VALUES (?, ?)",
        (ix_id, now_iso),
    )

    # Telemetry records exact executed homeostasis decision
    journal.record(
        interaction_id=ix_id,
        stage=TelemetryStage.HOMEOSTASIS,
        status="EXECUTED",
        occurred_at=NOW,
        payload={
            "decision_id": "dec-homeo-004",
            "target_dimension": "agent.longitudinal.relationship_security",
            "proposed_value": "0.6200",
            "prior_value": "0.5000",
            "disposition": "slow_accept",
            "salience": 0.85,
            "confidence": 0.90,
            "reason": "salience 0.85 >= threshold 0.51",
        },
        source_refs=("ev-test-1",),
    )

    # Build human causal trace
    trace = build_human_causal_trace(
        interaction_id=ix_id,
        conn_state=conn_state,
        conn_facts=conn_facts,
        trace_db=journal.db_path,
    )

    assert trace["homeostasis_gate"]["status"] == "AVAILABLE"
    assert trace["homeostasis_gate"]["provenance"].startswith("OBSERVER TELEMETRY")
    assert trace["homeostasis_gate"]["disposition"] == "slow_accept"
    assert trace["homeostasis_gate"]["target_dimension"] == "agent.longitudinal.relationship_security"
    assert trace["homeostasis_gate"]["salience"] == 0.85
    assert trace["homeostasis_gate"]["reason"] == "salience 0.85 >= threshold 0.51"


# ---------------------------------------------------------------------------
# Scenario 5: State Causal Linkage
# ---------------------------------------------------------------------------

def test_state_causal_linkage(empty_dbs):
    conn_state, conn_facts, journal = empty_dbs
    ix_id = "ix-linkage-005"
    now_iso = NOW.isoformat()

    # User input
    user_payload = json.dumps({"text": "Why did you break our agreement?"})
    conn_facts.execute(
        "INSERT INTO evidence (id, interaction_id, source_type, payload, occurred_at) VALUES (?, ?, ?, ?, ?)",
        ("ev-user-005", ix_id, "user_message", user_payload, now_iso),
    )
    conn_facts.execute(
        "INSERT INTO observations (id, interaction_id, value, confidence, observed_at) VALUES (?, ?, ?, ?, ?)",
        ("obs-user-005", ix_id, user_payload, 1.0, now_iso),
    )

    # Commit marker
    conn_state.execute(
        "INSERT INTO commit_markers (interaction_id, committed_at) VALUES (?, ?)",
        (ix_id, now_iso),
    )

    # Canonical transition: irritation 0.20 -> 0.35 (linked to ix_id)
    conn_state.execute(
        "INSERT INTO states (state_id, dimension, value, version, status, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
        ("st-irr-1", "agent.affect.irritation", "0.2000", 1, "superseded", now_iso),
    )
    conn_state.execute(
        "INSERT INTO states (state_id, dimension, value, version, status, updated_at, evidence_refs) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("st-irr-2", "agent.affect.irritation", "0.3500", 2, "active", now_iso, json.dumps([ix_id])),
    )
    conn_state.execute(
        "INSERT INTO state_transitions (transition_id, from_state_id, to_state_id, intent_id, committed_at) VALUES (?, ?, ?, ?, ?)",
        ("tr-irr-005", "st-irr-1", "st-irr-2", f"intent:{ix_id}", now_iso),
    )

    # Journal records full causal stages
    journal.record(
        interaction_id=ix_id,
        stage=TelemetryStage.SEMANTIC_CANDIDATE,
        status="PROPOSED",
        occurred_at=NOW,
        payload={"event_kind": "boundary_violation", "confidence": 0.9},
        source_refs=("ev-user-005",),
    )
    journal.record(
        interaction_id=ix_id,
        stage=TelemetryStage.APPRAISAL,
        status="ACCEPTED",
        occurred_at=NOW,
        payload={"valence": -0.6, "salience": 0.8, "confidence": 0.9},
        source_refs=("ev-user-005",),
    )
    journal.record(
        interaction_id=ix_id,
        stage=TelemetryStage.IMPULSE,
        status="EXECUTED",
        occurred_at=NOW,
        payload={
            "impulses": [{"dimension": "agent.affect.irritation", "amount": 0.15, "source_ref": "rule-viol"}],
            "rule_ids": ["rule-viol"],
        },
    )
    journal.record(
        interaction_id=ix_id,
        stage=TelemetryStage.STATE_TRANSITION,
        status="COMMITTED",
        occurred_at=NOW,
        payload={
            "dimension": "agent.affect.irritation",
            "before": 0.20,
            "after": 0.35,
            "delta": 0.15,
            "version": 2,
        },
    )

    trace = build_human_causal_trace(
        interaction_id=ix_id,
        conn_state=conn_state,
        conn_facts=conn_facts,
        trace_db=journal.db_path,
    )

    # Check state delta
    changed = trace["changed_states"]
    assert len(changed) == 1
    irr_item = changed[0]
    assert irr_item["dimension"] == "agent.affect.irritation"
    assert irr_item["before"] == 0.20
    assert irr_item["after"] == 0.35
    assert irr_item["delta"] == 0.15
    assert irr_item["change_origin"] == "EVENT EFFECT"

    # Check causal links in OW trace
    assert trace["semantic_interpretation"]["status"] == "AVAILABLE"
    assert trace["semantic_interpretation"]["event_kind"] == "boundary_violation"
    assert trace["appraisal"]["status"] == "AVAILABLE"
    assert trace["appraisal"]["valence"] == -0.6
    assert trace["effect"]["status"] == "AVAILABLE"
    assert len(trace["effect"]["impulses"]) == 1


# ---------------------------------------------------------------------------
# Scenario 6: Dynamics Recovery Linkage
# ---------------------------------------------------------------------------

def test_dynamics_recovery_linkage(empty_dbs):
    conn_state, conn_facts, journal = empty_dbs
    ix_id = "ix-recovery-006"
    now_iso = NOW.isoformat()

    conn_state.execute(
        "INSERT INTO commit_markers (interaction_id, committed_at) VALUES (?, ?)",
        (ix_id, now_iso),
    )

    # Joy decays towards baseline without evidence refs
    conn_state.execute(
        "INSERT INTO states (state_id, dimension, value, version, status, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
        ("st-joy-1", "agent.affect.joy", "0.5000", 1, "superseded", now_iso),
    )
    conn_state.execute(
        "INSERT INTO states (state_id, dimension, value, version, status, updated_at, evidence_refs) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("st-joy-2", "agent.affect.joy", "0.4500", 2, "active", now_iso, json.dumps([])),
    )
    conn_state.execute(
        "INSERT INTO state_transitions (transition_id, from_state_id, to_state_id, intent_id, committed_at) VALUES (?, ?, ?, ?, ?)",
        ("tr-joy-006", "st-joy-1", "st-joy-2", f"intent:{ix_id}", now_iso),
    )

    trace = build_human_causal_trace(
        interaction_id=ix_id,
        conn_state=conn_state,
        conn_facts=conn_facts,
        trace_db=journal.db_path,
    )

    changed = trace["changed_states"]
    assert len(changed) == 1
    joy_item = changed[0]
    assert joy_item["dimension"] == "agent.affect.joy"
    assert joy_item["before"] == 0.50
    assert joy_item["after"] == 0.45
    assert joy_item["delta"] == -0.05
    assert joy_item["change_origin"] == "DYNAMICS / RECOVERY"


# ---------------------------------------------------------------------------
# Scenario 7: Slow Accept Captured (Decided -> Committed)
# ---------------------------------------------------------------------------

def test_slow_accept_captured(empty_dbs):
    conn_state, conn_facts, journal = empty_dbs
    ix_id = "ix-slow-007"
    now_iso = NOW.isoformat()

    # 1. Slow decision executed and proposed
    journal.record(
        interaction_id=ix_id,
        stage=TelemetryStage.SLOW_DECISION,
        status="ACCEPTED",
        occurred_at=NOW,
        payload={
            "decision_id": "dec-slow-007",
            "target_dimension": "agent.longitudinal.relationship_security",
            "proposed_value": "0.6000",
            "salience": 0.8,
            "confidence": 0.85,
        },
        source_refs=("ev-test-1",),
    )

    # 2. Slow write committed after canonical persistence
    journal.record(
        interaction_id=ix_id,
        stage=TelemetryStage.SLOW_WRITE,
        status="COMMITTED",
        occurred_at=NOW,
        payload={
            "target_dimension": "agent.longitudinal.relationship_security",
            "target_scope": "agent:test-agent",
            "flush_status": "flushed",
            "decision_id": "dec-slow-007",
        },
        source_refs=("ev-test-1",),
    )

    # 3. Canonical slow contribution table row
    conn_state.execute(
        "INSERT INTO slow_contribution_window (id, sequence, accepted_at, proposed_value, salience, evidence_refs, source_decision_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("slow-row-007", 1, now_iso, "0.6000", 0.8, json.dumps([ix_id]), "dec-slow-007"),
    )
    conn_state.execute(
        "INSERT INTO commit_markers (interaction_id, committed_at) VALUES (?, ?)",
        (ix_id, now_iso),
    )

    # Check journal queries
    events = journal.get_events_for_interaction(ix_id)
    slow_dec = next(e for e in events if e["stage"] == TelemetryStage.SLOW_DECISION)
    slow_wrt = next(e for e in events if e["stage"] == TelemetryStage.SLOW_WRITE)

    assert slow_dec["status"] == "ACCEPTED"
    assert slow_dec["payload"]["proposed_value"] == "0.6000"

    assert slow_wrt["status"] == "COMMITTED"
    assert slow_wrt["payload"]["flush_status"] == "flushed"

    # Check OW trace
    trace = build_human_causal_trace(
        interaction_id=ix_id,
        conn_state=conn_state,
        conn_facts=conn_facts,
        trace_db=journal.db_path,
    )
    slow = trace["slow_state"]
    assert slow["proposed_target"] == "0.6000"
    assert slow["write_status"] == "COMMITTED"
    assert slow["slow_contribution_id"] == "slow-row-007"


# ---------------------------------------------------------------------------
# Scenario 8: Exact Assistant Linkage (NEVER guessed)
# ---------------------------------------------------------------------------

def test_exact_assistant_linkage(empty_dbs):
    conn_state, conn_facts, journal = empty_dbs
    ix_id = "ix-asst-008"
    now_iso = NOW.isoformat()

    conn_state.execute(
        "INSERT INTO commit_markers (interaction_id, committed_at) VALUES (?, ?)",
        (ix_id, now_iso),
    )

    # Telemetry captures exact durable message ID from Hermes session db
    journal.record(
        interaction_id=ix_id,
        stage=TelemetryStage.ASSISTANT_RESPONSE,
        status="COMMITTED",
        occurred_at=NOW,
        payload={
            "text": "I understand and will respect your boundaries.",
            "durable_message_id": "hermes-msg:108",
            "timestamp": now_iso,
        },
    )

    trace = build_human_causal_trace(
        interaction_id=ix_id,
        conn_state=conn_state,
        conn_facts=conn_facts,
        trace_db=journal.db_path,
    )

    asst = trace["assistant_response"]
    assert asst["status"] == "AVAILABLE"
    assert asst["message_id"] == "hermes-msg:108"
    assert asst["provenance"] == "OBSERVER TELEMETRY — exact captured persistence link"
    assert asst["text"] == "I understand and will respect your boundaries."

    # Negative check: unpersisted assistant row without durable ID
    ix_empty = "ix-asst-empty-008"
    conn_state.execute(
        "INSERT INTO commit_markers (interaction_id, committed_at) VALUES (?, ?)",
        (ix_empty, now_iso),
    )
    trace_empty = build_human_causal_trace(
        interaction_id=ix_empty,
        conn_state=conn_state,
        conn_facts=conn_facts,
        trace_db=journal.db_path,
    )
    assert trace_empty["assistant_response"]["status"] == "UNAVAILABLE / NOT PERSISTED"
    assert trace_empty["assistant_response"]["message_id"] == "UNAVAILABLE"
    assert trace_empty["assistant_response"]["provenance"] == "UNAVAILABLE"


# ---------------------------------------------------------------------------
# Scenario 9: Telemetry DB Failure Does Not Break Turn (Fail-Open)
# ---------------------------------------------------------------------------

def test_telemetry_db_failure_does_not_break_turn(tmp_path):
    # Point journal to an invalid path that cannot be written to
    invalid_path = tmp_path / "nonexistent_dir" / "readonly.sqlite"
    journal = TransientTraceJournal(invalid_path)

    # Monkeypatch get_connection to simulate database failure / disk error
    def _broken_conn(*args, **kwargs):
        raise sqlite3.OperationalError("Simulated trace db lock / IO error")

    journal._get_connection = _broken_conn

    # Port appraise with broken telemetry sink
    dims = (make_profile("agent.affect.joy", baseline=0.5),)
    port = EngineEmotionalTransitionPort(
        engine=DynamicsEngine(
            persona=PersonaProfile(
                persona_id="test-persona",
                dimensions=dims,
            )
        ),
        runtime_id="runtime-test",
        telemetry_sink=journal,
    )

    tx_input = _make_input(
        interaction_id="ix-fail-open-009",
        current=(_make_affect_state("agent.affect.joy", 0.5),),
        dimensions=dims,
    )

    # MUST NOT raise: fail-open contract
    outcome = port.transition(tx_input)
    assert outcome is not None
    assert outcome.projected is not None


# ---------------------------------------------------------------------------
# Scenario 10: Aborted Turn Records Telemetry Cleanly
# ---------------------------------------------------------------------------

def test_aborted_turn_records_telemetry_cleanly(empty_dbs):
    conn_state, conn_facts, journal = empty_dbs
    ix_id = "ix-aborted-010"

    # Journal records abort event
    journal.record(
        interaction_id=ix_id,
        stage=TelemetryStage.TURN_ABORT,
        status="ABORTED",
        occurred_at=NOW,
        payload={"reason": "controlled provider fault injection"},
    )

    events = journal.get_events_for_interaction(ix_id)
    abort_events = [e for e in events if e["stage"] == TelemetryStage.TURN_ABORT]
    assert len(abort_events) == 1
    assert abort_events[0]["status"] == "ABORTED"

    # Assert NO committed events exist in journal for this interaction
    committed_events = [e for e in events if e["status"] == "COMMITTED"]
    assert len(committed_events) == 0

    # OW renders turn as aborted
    trace = build_human_causal_trace(
        interaction_id=ix_id,
        conn_state=conn_state,
        conn_facts=conn_facts,
        trace_db=journal.db_path,
    )
    assert trace["is_aborted"] is True
    assert trace["abort_reason"] == "controlled provider fault injection"


# ---------------------------------------------------------------------------
# Scenario 11: Pre-journal Historical Turn Fallback
# ---------------------------------------------------------------------------

def test_pre_journal_historical_turn_fallback(empty_dbs):
    conn_state, conn_facts, journal = empty_dbs
    ix_id = "ix-historic-011"
    now_iso = NOW.isoformat()

    user_payload = json.dumps({"text": "An old prompt from last month"})
    conn_facts.execute(
        "INSERT INTO evidence (id, interaction_id, source_type, payload, occurred_at) VALUES (?, ?, ?, ?, ?)",
        ("ev-hist-011", ix_id, "user_message", user_payload, now_iso),
    )
    conn_state.execute(
        "INSERT INTO commit_markers (interaction_id, committed_at) VALUES (?, ?)",
        (ix_id, now_iso),
    )

    # Empty journal (no telemetry events for ix-historic-011)
    trace = build_human_causal_trace(
        interaction_id=ix_id,
        conn_state=conn_state,
        conn_facts=conn_facts,
        trace_db=journal.db_path,
    )

    # Transient stages must be reported as UNAVAILABLE / NOT PERSISTED
    assert trace["semantic_interpretation"]["status"] == "UNAVAILABLE / NOT PERSISTED"
    assert trace["appraisal"]["status"] == "UNAVAILABLE / NOT PERSISTED"
    assert trace["effect"]["status"] == "UNAVAILABLE / NOT PERSISTED"
    assert trace["homeostasis_gate"]["status"] == "UNAVAILABLE / NOT PERSISTED"

    # User input from canonical facts is still available
    assert trace["user_input"]["status"] == "AVAILABLE"
    assert trace["user_input"]["text"] == "An old prompt from last month"
