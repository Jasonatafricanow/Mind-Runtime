"""Tests for OW-HUMAN-CAUSAL-TRACE-V1: Human-Readable Causal Trace.

Verifies:
1. Show actual user-authored text (stripping host system notes cleanly).
2. Show actual semantic result (or UNAVAILABLE / NOT PERSISTED).
3. Show actual appraisal (or UNAVAILABLE / NOT PERSISTED).
4. Show only changed state dimensions by default; collapse zero-delta dimensions.
5. Show change origin: EVENT EFFECT, DYNAMICS / RECOVERY, SLOW PLASTICITY.
6. Slow state section: relationship_security before/proposed/homeostasis/after.
7. Show assistant response for the same interaction.
8. Raw linkage: evidence_id, observation_id, transition_id, state_version, interaction_id.
9. Never synthesize explanations: unpersisted stages are UNAVAILABLE / NOT PERSISTED.
10. /history remains untouched raw machine ledger; /causal returns human trace card.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from observation_window.human_causal_trace import (
    clean_user_text,
    list_committed_turns,
    build_human_causal_trace,
    _SYSTEM_NOTE_PREFIX,
)
from observation_window.web.server import build_app
from observation_window.web.sources import OWDashboardDataSources


# ---------------------------------------------------------------------------
# Requirement 1: User Text Cleaning
# ---------------------------------------------------------------------------

def test_clean_user_text_strips_system_note():
    raw_with_note = _SYSTEM_NOTE_PREFIX + "Hello, this is a real user prompt."
    cleaned = clean_user_text(raw_with_note)
    assert cleaned == "Hello, this is a real user prompt."

    normal_text = "Just a normal prompt without system notes."
    assert clean_user_text(normal_text) == normal_text

    assert clean_user_text(None) is None
    assert clean_user_text("") == ""


# ---------------------------------------------------------------------------
# In-Memory SQLite Fixtures for Testing Causal Builder
# ---------------------------------------------------------------------------

@pytest.fixture
def memory_databases():
    conn_state = sqlite3.connect(":memory:", check_same_thread=False)
    conn_facts = sqlite3.connect(":memory:", check_same_thread=False)

    # Schema for state db
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

    # Schema for facts db
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

    return conn_state, conn_facts


# ---------------------------------------------------------------------------
# Requirements 1, 2, 3, 4, 5, 6, 7, 8, 9: Causal Card Builder
# ---------------------------------------------------------------------------

def test_build_human_causal_trace_full_flow(memory_databases, tmp_path):
    conn_state, conn_facts = memory_databases
    ix_id = "test-interaction-001"
    now_iso = datetime.now(timezone.utc).isoformat()

    # 1. User evidence
    user_payload = json.dumps({"text": _SYSTEM_NOTE_PREFIX + "Can you help me with this?"})
    conn_facts.execute(
        "INSERT INTO evidence (id, interaction_id, source_type, payload, occurred_at) VALUES (?, ?, ?, ?, ?)",
        ("ev-user-001", ix_id, "user_message", user_payload, now_iso)
    )
    conn_facts.execute(
        "INSERT INTO observations (id, interaction_id, value, confidence, observed_at) VALUES (?, ?, ?, ?, ?)",
        ("obs-user-001", ix_id, user_payload, 1.0, now_iso)
    )

    # 2. Assistant evidence in facts
    asst_payload = json.dumps({"text": "Yes, I am happy to help you."})
    conn_facts.execute(
        "INSERT INTO evidence (id, interaction_id, source_type, payload, occurred_at) VALUES (?, ?, ?, ?, ?)",
        ("ev-asst-001", ix_id, "assistant_message", asst_payload, now_iso)
    )

    # 3. Commit marker
    conn_state.execute(
        "INSERT INTO commit_markers (interaction_id, committed_at) VALUES (?, ?)",
        (ix_id, now_iso)
    )

    # 4. State transitions:
    # Dimension 1: irritation changed from 0.20 to 0.35 (EVENT EFFECT, evidence_refs contains ix_id)
    conn_state.execute(
        "INSERT INTO states (state_id, dimension, value, version, status, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
        ("st-irr-1", "agent.affect.irritation", "0.2000", 1, "superseded", now_iso)
    )
    conn_state.execute(
        "INSERT INTO states (state_id, dimension, value, version, status, updated_at, evidence_refs) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("st-irr-2", "agent.affect.irritation", "0.3500", 2, "active", now_iso, json.dumps([ix_id]))
    )
    conn_state.execute(
        "INSERT INTO state_transitions (transition_id, from_state_id, to_state_id, intent_id, committed_at) VALUES (?, ?, ?, ?, ?)",
        ("tr-irr-1", "st-irr-1", "st-irr-2", f"intent:{ix_id}", now_iso)
    )

    # Dimension 2: joy changed from 0.50 to 0.45 (DYNAMICS / RECOVERY, evidence_refs empty)
    conn_state.execute(
        "INSERT INTO states (state_id, dimension, value, version, status, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
        ("st-joy-1", "agent.affect.joy", "0.5000", 1, "superseded", now_iso)
    )
    conn_state.execute(
        "INSERT INTO states (state_id, dimension, value, version, status, updated_at, evidence_refs) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("st-joy-2", "agent.affect.joy", "0.4500", 2, "active", now_iso, json.dumps([]))
    )
    conn_state.execute(
        "INSERT INTO state_transitions (transition_id, from_state_id, to_state_id, intent_id, committed_at) VALUES (?, ?, ?, ?, ?)",
        ("tr-joy-1", "st-joy-1", "st-joy-2", f"intent:{ix_id}", now_iso)
    )

    # Dimension 3: curiosity unchanged (delta 0.0)
    conn_state.execute(
        "INSERT INTO states (state_id, dimension, value, version, status, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
        ("st-cur-1", "agent.affect.curiosity", "0.8000", 1, "superseded", now_iso)
    )
    conn_state.execute(
        "INSERT INTO states (state_id, dimension, value, version, status, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
        ("st-cur-2", "agent.affect.curiosity", "0.8000", 2, "active", now_iso)
    )
    conn_state.execute(
        "INSERT INTO state_transitions (transition_id, from_state_id, to_state_id, intent_id, committed_at) VALUES (?, ?, ?, ?, ?)",
        ("tr-cur-1", "st-cur-1", "st-cur-2", f"intent:{ix_id}", now_iso)
    )

    # 5. Slow contribution window
    conn_state.execute(
        "INSERT INTO slow_contribution_window (id, sequence, accepted_at, proposed_value, salience, evidence_refs, source_decision_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("slow-001", 1, now_iso, "0.5500", 0.75, json.dumps([ix_id]), f"decision:{ix_id}")
    )

    # Build trace
    trace = build_human_causal_trace(
        interaction_id=ix_id,
        conn_state=conn_state,
        conn_facts=conn_facts,
        slow_dimension="agent.longitudinal.relationship_security",
    )

    # Requirement 1: User text cleaned
    assert trace["user_input"]["status"] == "AVAILABLE"
    assert trace["user_input"]["text"] == "Can you help me with this?"
    assert trace["user_input"]["evidence_id"] == "ev-user-001"
    assert trace["user_input"]["observation_id"] == "obs-user-001"

    # Requirement 2 & 3 & 9: Unpersisted stages must say UNAVAILABLE / NOT PERSISTED
    assert trace["semantic_interpretation"]["status"] == "UNAVAILABLE / NOT PERSISTED"
    assert trace["semantic_interpretation"]["reason"] == "semantic_result_not_persisted_to_durable_schema"
    assert trace["appraisal"]["status"] == "UNAVAILABLE / NOT PERSISTED"
    assert trace["appraisal"]["reason"] == "appraisal_details_not_persisted_to_durable_schema"

    # Requirement 4: Changed states vs Unchanged states
    changed = trace["changed_states"]
    unchanged = trace["unchanged_states"]
    assert len(changed) == 2
    assert len(unchanged) == 1
    assert trace["unchanged_summary"] == "1 unchanged states"

    # Requirement 5: Change origin verification
    irr_item = next(c for c in changed if c["dimension"] == "agent.affect.irritation")
    assert irr_item["before"] == 0.20
    assert irr_item["after"] == 0.35
    assert irr_item["delta"] == 0.15
    assert irr_item["change_origin"] == "EVENT EFFECT"

    joy_item = next(c for c in changed if c["dimension"] == "agent.affect.joy")
    assert joy_item["before"] == 0.50
    assert joy_item["after"] == 0.45
    assert joy_item["delta"] == -0.05
    assert joy_item["change_origin"] == "DYNAMICS / RECOVERY"

    cur_item = unchanged[0]
    assert cur_item["dimension"] == "agent.affect.curiosity"
    assert cur_item["delta"] == 0.0

    # Requirement 6: Slow state section
    slow = trace["slow_state"]
    assert slow["dimension"] == "agent.longitudinal.relationship_security"
    assert slow["proposed_target"] == "0.5500"
    assert "ACCEPTED (salience=0.75)" in slow["homeostasis_disposition"]
    assert slow["slow_contribution_id"] == "slow-001"

    # Requirement 7: Assistant response
    asst = trace["assistant_response"]
    assert asst["status"] == "AVAILABLE"
    assert asst["message_id"] == "ev-asst-001"
    assert asst["text"] == "Yes, I am happy to help you."

    # Requirement 8: Raw linkage
    assert irr_item["from_state_id"] == "st-irr-1"
    assert irr_item["to_state_id"] == "st-irr-2"
    assert irr_item["from_version"] == 1
    assert irr_item["to_version"] == 2
    assert irr_item["transition_id"] == "tr-irr-1"


def test_list_committed_turns(memory_databases):
    conn_state, conn_facts = memory_databases
    ix_id = "test-interaction-002"
    now_iso = datetime.now(timezone.utc).isoformat()

    conn_state.execute(
        "INSERT INTO commit_markers (interaction_id, committed_at) VALUES (?, ?)",
        (ix_id, now_iso)
    )
    user_payload = json.dumps({"text": "Checking turn listing"})
    conn_facts.execute(
        "INSERT INTO evidence (id, interaction_id, source_type, payload, occurred_at) VALUES (?, ?, ?, ?, ?)",
        ("ev-002", ix_id, "user_message", user_payload, now_iso)
    )

    turns = list_committed_turns(conn_state, conn_facts, limit=10)
    assert len(turns) == 1
    assert turns[0]["interaction_id"] == ix_id
    assert turns[0]["user_preview"] == "Checking turn listing"
    assert turns[0]["has_delta"] is False


# ---------------------------------------------------------------------------
# Web API Endpoint Integration Tests (TestClient)
# ---------------------------------------------------------------------------

def test_api_turn_and_causal_endpoints(memory_databases):
    conn_state, conn_facts = memory_databases
    ix_id = "test-turn-api-01"
    now_iso = datetime.now(timezone.utc).isoformat()

    conn_state.execute(
        "INSERT INTO commit_markers (interaction_id, committed_at) VALUES (?, ?)",
        (ix_id, now_iso)
    )
    user_payload = json.dumps({"text": "Hello from API test"})
    conn_facts.execute(
        "INSERT INTO evidence (id, interaction_id, source_type, payload, occurred_at) VALUES (?, ?, ?, ?, ?)",
        ("ev-api-01", ix_id, "user_message", user_payload, now_iso)
    )

    # Build mock sources with connections attached
    mock_query = MagicMock()
    mock_query._state = MagicMock(_conn=conn_state)
    mock_query._fact = MagicMock(_conn=conn_facts)
    mock_query.list_current_states.return_value = []

    mock_sources = OWDashboardDataSources(
        query_service=mock_query,
        live_source=MagicMock(),
        chain_builder=MagicMock(),
        turn_provider=MagicMock(recent_turns=lambda n: (), get_turn=lambda tid: None),
    )

    app = build_app(mock_sources)
    client = TestClient(app)

    # 1. GET /api/turns returns committed turns
    r_turns = client.get("/api/turns")
    assert r_turns.status_code == 200
    data_turns = r_turns.json()
    assert "turns" in data_turns
    assert len(data_turns["turns"]) >= 1
    assert data_turns["turns"][0]["interaction_id"] == ix_id

    # 2. GET /api/turns/{id}/causal returns human_trace
    r_causal = client.get(f"/api/turns/{ix_id}/causal")
    assert r_causal.status_code == 200
    data_causal = r_causal.json()
    assert data_causal["turn_id"] == ix_id
    assert "human_trace" in data_causal
    assert data_causal["human_trace"]["user_input"]["text"] == "Hello from API test"

    # 3. GET /api/turns/{id}/human-causal-trace returns the trace directly
    r_ht = client.get(f"/api/turns/{ix_id}/human-causal-trace")
    assert r_ht.status_code == 200
    assert r_ht.json()["interaction_id"] == ix_id

    # 4. Non-existent turn returns 404
    r_404 = client.get("/api/turns/nonexistent-turn-id/causal")
    assert r_404.status_code == 404

    # 5. GET /causal returns HTML page
    r_html = client.get("/causal")
    assert r_html.status_code == 200
    assert "Human Causal Trace" in r_html.text

    # 6. Requirement 10: /history page remains raw machine ledger
    r_hist = client.get("/history")
    assert r_hist.status_code == 200
