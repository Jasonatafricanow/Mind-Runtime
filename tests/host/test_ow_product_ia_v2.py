"""Tests for OW-PRODUCT-IA-V2.

Product Information Architecture V2 Contracts:
1. Bounded SQL queries for /api/trends (<= 3 indexed queries to cognition_state.sqlite).
2. Deterministic linear affect trajectory points and delta origin provenance.
3. Accumulated Self strictly from canonical states versions (NOT ESTABLISHED if uninitialized).
4. Factual Moments feed projection with factual flags (has_delta, max_abs_delta, has_slow_write).
5. Primary routes and backward-compatibility aliases return 200 HTML.
6. Full Live Trace capability preserved.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from observation_window.human_causal_trace import (
    get_affect_trends,
    is_moment_eligible,
    list_committed_turns,
)
from observation_window.binding import StateSurface
from observation_window.web.runtime import build_ow_app_from_db_dir

# Xiyue compat descriptor (declared surface, Phase 01 fixture authority)
_FAST_DIMS = (
    "agent.affect.irritation",
    "agent.affect.anxiety",
    "agent.affect.excitement",
    "agent.affect.longing",
)
_SLOW_DIM = "agent.longitudinal.relationship_security"


def _surface() -> StateSurface:
    return StateSurface(fast_dimensions=_FAST_DIMS, slow_dimensions=(_SLOW_DIM,))


class QueryCountingConnection:
    """Wrapper to monitor and count SQL queries executed against cognition_state."""

    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn
        self.query_count = 0
        self.executed_queries: list[str] = []

    def execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        self.query_count += 1
        self.executed_queries.append(sql)
        return self._conn.execute(sql, params)

    def fetchall(self):
        return self._conn.fetchall()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._conn, name)


@pytest.fixture
def product_ia_test_dbs(tmp_path: Path):
    """Create test SQLite DBs with fast affect turns and slow state versions."""
    state_db_path = tmp_path / "cognition_state.sqlite"
    facts_db_path = tmp_path / "facts.sqlite"

    conn_s = sqlite3.connect(state_db_path)
    conn_s.execute("""
        CREATE TABLE commit_markers (
            scope_domain TEXT NOT NULL,
            scope_user_id TEXT NOT NULL DEFAULT '',
            interaction_id TEXT NOT NULL,
            committed_at TEXT NOT NULL,
            projected_state_ids TEXT NOT NULL,
            PRIMARY KEY (scope_domain, scope_user_id, interaction_id)
        )
    """)
    conn_s.execute("""
        CREATE TABLE state_transitions (
            transition_id TEXT PRIMARY KEY,
            scope_domain TEXT NOT NULL,
            scope_user_id TEXT NOT NULL DEFAULT '',
            scope_agent_id TEXT NOT NULL DEFAULT '',
            scope_persona_id TEXT NOT NULL DEFAULT '',
            scope_relationship_id TEXT NOT NULL DEFAULT '',
            scope_world_id TEXT NOT NULL DEFAULT '',
            scope_interaction_id TEXT NOT NULL DEFAULT '',
            origin_runtime_id TEXT NOT NULL,
            intent_id TEXT NOT NULL,
            from_state_id TEXT NOT NULL,
            to_state_id TEXT NOT NULL,
            committed_at TEXT NOT NULL,
            sync_version INTEGER NOT NULL,
            sync_idem_key TEXT NOT NULL
        )
    """)
    conn_s.execute("""
        CREATE TABLE states (
            scope_domain TEXT NOT NULL,
            scope_user_id TEXT NOT NULL DEFAULT '',
            scope_agent_id TEXT NOT NULL DEFAULT '',
            scope_persona_id TEXT NOT NULL DEFAULT '',
            scope_relationship_id TEXT NOT NULL DEFAULT '',
            scope_world_id TEXT NOT NULL DEFAULT '',
            scope_interaction_id TEXT NOT NULL DEFAULT '',
            state_id TEXT NOT NULL,
            dimension TEXT NOT NULL,
            status TEXT NOT NULL,
            value TEXT NOT NULL,
            valid_from TEXT NOT NULL,
            valid_until TEXT,
            relevant_until TEXT,
            last_observed_at TEXT NOT NULL,
            evidence_refs TEXT NOT NULL,
            transition_refs TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            origin_runtime_id TEXT NOT NULL,
            version INTEGER NOT NULL,
            sync_version INTEGER NOT NULL,
            sync_idem_key TEXT NOT NULL,
            PRIMARY KEY (scope_domain, scope_user_id, scope_agent_id, scope_persona_id, scope_relationship_id, scope_world_id, scope_interaction_id, state_id)
        )
    """)
    conn_s.execute("""
        CREATE TABLE slow_contribution_window (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scope_domain TEXT NOT NULL,
            scope_user_id TEXT NOT NULL DEFAULT '',
            scope_agent_id TEXT NOT NULL DEFAULT '',
            scope_persona_id TEXT NOT NULL DEFAULT '',
            scope_relationship_id TEXT NOT NULL DEFAULT '',
            scope_world_id TEXT NOT NULL DEFAULT '',
            scope_interaction_id TEXT NOT NULL DEFAULT '',
            target_dimension TEXT NOT NULL,
            sequence INTEGER NOT NULL,
            accepted_at TEXT NOT NULL,
            proposed_value REAL NOT NULL,
            salience REAL NOT NULL,
            evidence_refs TEXT NOT NULL,
            source_event_ref TEXT NOT NULL,
            source_decision_id TEXT NOT NULL
        )
    """)

    conn_f = sqlite3.connect(facts_db_path)
    conn_f.execute("""
        CREATE TABLE evidence (
            id TEXT PRIMARY KEY,
            interaction_id TEXT NOT NULL,
            source_type TEXT NOT NULL,
            payload TEXT NOT NULL,
            occurred_at TEXT NOT NULL
        )
    """)

    # Populate 15 committed turns
    base_time = datetime(2026, 9, 5, 12, 0, 0, tzinfo=timezone.utc)
    dims = [
        "agent.affect.irritation",
        "agent.affect.anxiety",
        "agent.affect.excitement",
        "agent.affect.longing",
    ]

    for i in range(1, 16):
        t_iso = (base_time + timedelta(minutes=i * 2)).isoformat()
        ix_id = f"mr-test-turn:{i:04d}"

        # Insert user message fact
        ev_id = f"ev-{ix_id}"
        conn_f.execute(
            "INSERT INTO evidence (id, interaction_id, source_type, payload, occurred_at) VALUES (?, ?, ?, ?, ?)",
            (ev_id, ix_id, "user_message", json.dumps({"text": f"User question {i}"}), t_iso),
        )

        # Create states for each fast dimension
        proj_ids = []
        for dim in dims:
            s_id = f"{dim}:v{i}:{ix_id}"
            val = round(0.20 + (i * 0.01 if "irritation" in dim else 0.0), 4)
            ev_refs = json.dumps([ev_id]) if (i % 2 == 1 and "irritation" in dim) else "[]"
            conn_s.execute(
                """
                INSERT INTO states (
                    scope_domain, state_id, dimension, status, value,
                    valid_from, last_observed_at, evidence_refs, transition_refs,
                    updated_at, origin_runtime_id, version, sync_version, sync_idem_key
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "agent", s_id, dim, "active", str(val),
                    t_iso, t_iso, ev_refs, "[]",
                    t_iso, "test-rt", i, 1, f"idem-{i}"
                ),
            )
            proj_ids.append(s_id)

        conn_s.execute(
            """
            INSERT INTO commit_markers (scope_domain, interaction_id, committed_at, projected_state_ids)
            VALUES (?, ?, ?, ?)
            """,
            ("agent", ix_id, t_iso, json.dumps(proj_ids)),
        )

    conn_s.commit()
    conn_f.commit()
    conn_s.close()
    conn_f.close()

    return tmp_path


def test_trends_bounded_queries(product_ia_test_dbs: Path):
    """GET /api/trends must execute <= 3 indexed queries to cognition_state.sqlite."""
    state_db = product_ia_test_dbs / "cognition_state.sqlite"
    facts_db = product_ia_test_dbs / "facts.sqlite"

    conn_s = sqlite3.connect(state_db)
    conn_f = sqlite3.connect(facts_db)
    counting_conn = QueryCountingConnection(conn_s)

    # 1. Fetch 10 turns
    data_10 = get_affect_trends(counting_conn, conn_f, limit=10,
        fast_dimensions=_FAST_DIMS, slow_dimension=_SLOW_DIM)
    assert counting_conn.query_count <= 3, f"Expected <= 3 queries, got {counting_conn.query_count}"
    assert len(data_10["points"]) == 10

    # 2. Fetch 15 turns (query count remains <= 3, bounded O(1))
    counting_conn.query_count = 0
    data_15 = get_affect_trends(counting_conn, conn_f, limit=15,
        fast_dimensions=_FAST_DIMS, slow_dimension=_SLOW_DIM)
    assert counting_conn.query_count <= 3, f"Expected <= 3 queries, got {counting_conn.query_count}"
    assert len(data_15["points"]) == 15

    conn_s.close()
    conn_f.close()


def test_trends_data_structure_and_interpolation(product_ia_test_dbs: Path):
    """Validate linear trajectory points, delta computation, and origin tags."""
    state_db = product_ia_test_dbs / "cognition_state.sqlite"
    facts_db = product_ia_test_dbs / "facts.sqlite"

    conn_s = sqlite3.connect(state_db)
    conn_f = sqlite3.connect(facts_db)

    trends = get_affect_trends(conn_s, conn_f, limit=15,
        fast_dimensions=_FAST_DIMS, slow_dimension=_SLOW_DIM)
    points = trends["points"]
    assert len(points) == 15

    # Check chronological ordering: T_{-14} -> T_0
    for i in range(len(points) - 1):
        assert points[i]["committed_at"] <= points[i + 1]["committed_at"]

    # Check values and deltas
    latest_pt = points[-1]
    assert "agent.affect.irritation" in latest_pt["values"]
    assert latest_pt["user_preview"] == "User question 15"

    # Verify origin badges are strictly from canonical provenance
    valid_origins = {"EVENT EFFECT", "DYNAMICS / RECOVERY", "SLOW PLASTICITY", "UNCHANGED", "UNAVAILABLE"}
    for pt in points:
        for dim, orig in pt["origins"].items():
            assert orig in valid_origins

    # Verify dimensions metadata
    dims_meta = trends["dimensions"]
    assert "agent.affect.irritation" in dims_meta
    assert len(dims_meta["agent.affect.irritation"]["sparkline"]) == 15
    assert dims_meta["agent.affect.irritation"]["current_value"] > 0.0

    conn_s.close()
    conn_f.close()


def test_accumulated_self_provenance_and_status(product_ia_test_dbs: Path):
    """Accumulated self reads strictly from states table; uninitialized is NOT ESTABLISHED."""
    state_db = product_ia_test_dbs / "cognition_state.sqlite"
    conn_s = sqlite3.connect(state_db)

    # 1. Uninitialized check
    trends_uninit = get_affect_trends(conn_s, limit=10,
        fast_dimensions=_FAST_DIMS, slow_dimension=_SLOW_DIM)
    acc = trends_uninit["accumulated_self"]
    assert acc["status"] == "NOT ESTABLISHED"
    assert acc["current_value"] is None
    assert acc["formatted_value"] == "NOT ESTABLISHED"
    assert acc["history"] == []

    # 2. Insert canonical version in states table
    now_iso = datetime.now(timezone.utc).isoformat()
    conn_s.execute(
        """
        INSERT INTO states (
            scope_domain, state_id, dimension, status, value,
            valid_from, last_observed_at, evidence_refs, transition_refs,
            updated_at, origin_runtime_id, version, sync_version, sync_idem_key
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "agent", "sec-01", "agent.longitudinal.relationship_security", "active", "0.4500",
            now_iso, now_iso, "[]", "[]",
            now_iso, "test-rt", 1, 1, "sec-idem-1"
        ),
    )
    conn_s.commit()

    # 3. Established check
    trends_init = get_affect_trends(conn_s, limit=10,
        fast_dimensions=_FAST_DIMS, slow_dimension=_SLOW_DIM)
    acc_init = trends_init["accumulated_self"]
    assert acc_init["status"] == "ESTABLISHED"
    assert acc_init["current_value"] == 0.45
    assert acc_init["formatted_value"] == "0.4500"
    assert acc_init["version"] == 1
    assert len(acc_init["history"]) == 1

    conn_s.close()


def test_factual_moments_feed_projection(product_ia_test_dbs: Path):
    """Moments feed contains factual flags without subjective LLM ranking."""
    state_db = product_ia_test_dbs / "cognition_state.sqlite"
    facts_db = product_ia_test_dbs / "facts.sqlite"

    conn_s = sqlite3.connect(state_db)
    conn_f = sqlite3.connect(facts_db)

    turns = list_committed_turns(conn_s, conn_f, limit=10)
    assert len(turns) == 10

    for turn in turns:
        assert "has_delta" in turn
        assert "max_abs_delta" in turn
        assert "has_slow_write" in turn
        assert "has_semantic_event" in turn
        assert "is_aborted" in turn
        assert "is_moment" in turn
        assert "delta_summary" in turn
        assert isinstance(turn["has_delta"], bool)
        assert isinstance(turn["max_abs_delta"], float)
        assert isinstance(turn["has_slow_write"], bool)
        assert isinstance(turn["has_semantic_event"], bool)
        assert isinstance(turn["is_aborted"], bool)
        assert isinstance(turn["is_moment"], bool)
        assert turn["is_aborted"] is False

    conn_s.close()
    conn_f.close()


def test_routes_and_backward_compatibility_aliases(product_ia_test_dbs: Path):
    """Verify primary V2 pages and backwards compatibility aliases return 200 HTML."""
    app, _ = build_ow_app_from_db_dir(product_ia_test_dbs, state_surface=_surface())
    client = TestClient(app)

    # Primary V2 routes
    primary_routes = [
        ("/", "Companion State"),
        ("/moments", "交互记录"),
        ("/debug/causal", "Human Causal Trace"),
        ("/debug/ledger", "State Ledger"),
        ("/debug/live-trace", "RUNTIME HEADER"),
    ]
    for route, expected_text in primary_routes:
        res = client.get(route)
        assert res.status_code == 200, f"Primary route {route} failed with {res.status_code}"
        assert "text/html" in res.headers["content-type"]
        assert expected_text in res.text

    # Backwards compatibility aliases
    aliases = [
        ("/overview", 200),
        ("/timeline", 200),
        ("/causal", 200),
        ("/history", 200),
        ("/live", 200),
        ("/live-trace", 200),
        ("/debug/runtime", 200),
    ]
    for route, expected_code in aliases:
        res = client.get(route)
        assert res.status_code == expected_code, f"Alias {route} failed with {res.status_code}"
        assert "text/html" in res.headers["content-type"]

    # API endpoint GET /api/trends
    res_trends = client.get("/api/trends?limit=15")
    assert res_trends.status_code == 200
    t_data = res_trends.json()
    assert "points" in t_data
    assert "dimensions" in t_data
    assert "accumulated_self" in t_data
    assert len(t_data["points"]) == 15


@pytest.fixture
def moments_eligibility_dbs(tmp_path: Path):
    """Create test SQLite DBs with semantic-only, aborted, and abstain turns."""
    state_db_path = tmp_path / "cognition_state.sqlite"
    facts_db_path = tmp_path / "facts.sqlite"
    trace_db_path = tmp_path / "observation_trace.sqlite"

    conn_s = sqlite3.connect(state_db_path)
    conn_s.execute("""
        CREATE TABLE commit_markers (
            scope_domain TEXT NOT NULL,
            scope_user_id TEXT NOT NULL DEFAULT '',
            interaction_id TEXT NOT NULL,
            committed_at TEXT NOT NULL,
            projected_state_ids TEXT NOT NULL,
            PRIMARY KEY (scope_domain, scope_user_id, interaction_id)
        )
    """)
    conn_s.execute("""
        CREATE TABLE state_transitions (
            transition_id TEXT PRIMARY KEY,
            scope_domain TEXT NOT NULL,
            scope_user_id TEXT NOT NULL DEFAULT '',
            scope_agent_id TEXT NOT NULL DEFAULT '',
            scope_persona_id TEXT NOT NULL DEFAULT '',
            scope_relationship_id TEXT NOT NULL DEFAULT '',
            scope_world_id TEXT NOT NULL DEFAULT '',
            scope_interaction_id TEXT NOT NULL DEFAULT '',
            origin_runtime_id TEXT NOT NULL,
            intent_id TEXT NOT NULL,
            from_state_id TEXT NOT NULL,
            to_state_id TEXT NOT NULL,
            committed_at TEXT NOT NULL,
            sync_version INTEGER NOT NULL,
            sync_idem_key TEXT NOT NULL
        )
    """)
    conn_s.execute("""
        CREATE TABLE states (
            scope_domain TEXT NOT NULL,
            scope_user_id TEXT NOT NULL DEFAULT '',
            scope_agent_id TEXT NOT NULL DEFAULT '',
            scope_persona_id TEXT NOT NULL DEFAULT '',
            scope_relationship_id TEXT NOT NULL DEFAULT '',
            scope_world_id TEXT NOT NULL DEFAULT '',
            scope_interaction_id TEXT NOT NULL DEFAULT '',
            state_id TEXT NOT NULL,
            dimension TEXT NOT NULL,
            status TEXT NOT NULL,
            value TEXT NOT NULL,
            valid_from TEXT NOT NULL,
            valid_until TEXT,
            relevant_until TEXT,
            last_observed_at TEXT NOT NULL,
            evidence_refs TEXT NOT NULL,
            transition_refs TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            origin_runtime_id TEXT NOT NULL,
            version INTEGER NOT NULL,
            sync_version INTEGER NOT NULL,
            sync_idem_key TEXT NOT NULL,
            PRIMARY KEY (scope_domain, scope_user_id, scope_agent_id, scope_persona_id, scope_relationship_id, scope_world_id, scope_interaction_id, state_id)
        )
    """)
    conn_s.execute("""
        CREATE TABLE slow_contribution_window (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scope_domain TEXT NOT NULL,
            scope_user_id TEXT NOT NULL DEFAULT '',
            scope_agent_id TEXT NOT NULL DEFAULT '',
            scope_persona_id TEXT NOT NULL DEFAULT '',
            scope_relationship_id TEXT NOT NULL DEFAULT '',
            scope_world_id TEXT NOT NULL DEFAULT '',
            scope_interaction_id TEXT NOT NULL DEFAULT '',
            target_dimension TEXT NOT NULL,
            sequence INTEGER NOT NULL,
            accepted_at TEXT NOT NULL,
            proposed_value REAL NOT NULL,
            salience REAL NOT NULL,
            evidence_refs TEXT NOT NULL,
            source_event_ref TEXT NOT NULL,
            source_decision_id TEXT NOT NULL
        )
    """)

    conn_f = sqlite3.connect(facts_db_path)
    conn_f.execute("""
        CREATE TABLE evidence (
            id TEXT PRIMARY KEY,
            interaction_id TEXT NOT NULL,
            source_type TEXT NOT NULL,
            payload TEXT NOT NULL,
            occurred_at TEXT NOT NULL
        )
    """)

    conn_t = sqlite3.connect(trace_db_path)
    conn_t.execute("""
        CREATE TABLE trace_events (
            event_id TEXT PRIMARY KEY,
            interaction_id TEXT NOT NULL,
            stage TEXT NOT NULL,
            occurred_at TEXT NOT NULL,
            sequence_no INTEGER NOT NULL,
            status TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            source_refs_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)
    conn_t.execute("""
        CREATE TABLE journal_metadata (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    """)

    t0 = "2026-09-05T12:00:00+00:00"
    t1 = "2026-09-05T12:02:00+00:00"
    t2 = "2026-09-05T12:04:00+00:00"
    t3 = "2026-09-05T12:06:00+00:00"

    # Base initial state at t0
    conn_s.execute("""
        INSERT INTO states (scope_domain, state_id, dimension, status, value, valid_from, last_observed_at, evidence_refs, transition_refs, updated_at, origin_runtime_id, version, sync_version, sync_idem_key)
        VALUES ('agent', 's_base', 'agent.affect.irritation', 'active', '0.2000', ?, ?, '[]', '[]', ?, 'test', 1, 1, 'idem0')
    """, (t0, t0, t0))

    # Turn 1: Semantic-only turn (delta = 0, has_semantic_event = True)
    ix_sem = "turn-01-semantic-only"
    conn_f.execute("INSERT INTO evidence VALUES (?, ?, ?, ?, ?)", ("ev-01", ix_sem, "user_message", json.dumps({"text": "Hello semantic"}), t1))
    conn_s.execute("""
        INSERT INTO states (scope_domain, state_id, dimension, status, value, valid_from, last_observed_at, evidence_refs, transition_refs, updated_at, origin_runtime_id, version, sync_version, sync_idem_key)
        VALUES ('agent', 's_sem', 'agent.affect.irritation', 'active', '0.2000', ?, ?, '[]', '[]', ?, 'test', 2, 1, 'idem1')
    """, (t1, t1, t1))
    conn_s.execute("""
        INSERT INTO state_transitions VALUES ('tr-01', 'agent', '', '', '', '', '', '', 'test', 'intent-1', 's_base', 's_sem', ?, 1, 'idem-tr1')
    """, (t1,))
    conn_s.execute("INSERT INTO commit_markers VALUES ('agent', '', ?, ?, ?)", (ix_sem, t1, json.dumps(['s_sem'])))
    conn_t.execute("""
        INSERT INTO trace_events VALUES ('te-01', ?, 'SEMANTIC_CANDIDATE', ?, 1, 'RECORDED', '{"event_kind": "USER_APPRECIATION"}', '[]', ?)
    """, (ix_sem, t1, t1))

    # Turn 2: Aborted turn (is_aborted = True, never committed to canonical states)
    ix_abort = "turn-02-aborted"
    conn_f.execute("INSERT INTO evidence VALUES (?, ?, ?, ?, ?)", ("ev-02", ix_abort, "user_message", json.dumps({"text": "Abort this turn"}), t2))
    conn_t.execute("""
        INSERT INTO trace_events VALUES ('te-02', ?, 'TURN_ABORT', ?, 1, 'RECORDED', '{"reason": "host_requested"}', '[]', ?)
    """, (ix_abort, t2, t2))

    # Turn 3: Ordinary zero-delta semantic-abstain turn (delta = 0, has_semantic_event = False)
    ix_abstain = "turn-03-abstain-zero-delta"
    conn_f.execute("INSERT INTO evidence VALUES (?, ?, ?, ?, ?)", ("ev-03", ix_abstain, "user_message", json.dumps({"text": "Nothing special"}), t3))
    conn_s.execute("""
        INSERT INTO states (scope_domain, state_id, dimension, status, value, valid_from, last_observed_at, evidence_refs, transition_refs, updated_at, origin_runtime_id, version, sync_version, sync_idem_key)
        VALUES ('agent', 's_abstain', 'agent.affect.irritation', 'active', '0.2000', ?, ?, '[]', '[]', ?, 'test', 3, 1, 'idem3')
    """, (t3, t3, t3))
    conn_s.execute("""
        INSERT INTO state_transitions VALUES ('tr-03', 'agent', '', '', '', '', '', '', 'test', 'intent-3', 's_sem', 's_abstain', ?, 1, 'idem-tr3')
    """, (t3,))
    conn_s.execute("INSERT INTO commit_markers VALUES ('agent', '', ?, ?, ?)", (ix_abstain, t3, json.dumps(['s_abstain'])))
    conn_t.execute("""
        INSERT INTO trace_events VALUES ('te-03', ?, 'SEMANTIC_ABSTAIN', ?, 1, 'RECORDED', '{"abstention_reasons": ["no_meaning"]}', '[]', ?)
    """, (ix_abstain, t3, t3))

    conn_s.commit()
    conn_f.commit()
    conn_t.commit()
    conn_s.close()
    conn_f.close()
    conn_t.close()

    return tmp_path


def test_moments_eligibility_semantic_only_zero_delta_turn_appears(moments_eligibility_dbs: Path):
    """Semantic-only / zero-delta turn must appear in Moments feed."""
    state_db = moments_eligibility_dbs / "cognition_state.sqlite"
    facts_db = moments_eligibility_dbs / "facts.sqlite"
    trace_db = moments_eligibility_dbs / "observation_trace.sqlite"

    conn_s = sqlite3.connect(state_db)
    conn_f = sqlite3.connect(facts_db)

    # 1. Full list projection includes semantic flag
    all_turns = list_committed_turns(conn_s, conn_f, trace_db=trace_db, moments_only=False,
    slow_dimension=_SLOW_DIM)
    turn_map = {t["interaction_id"]: t for t in all_turns}
    assert "turn-01-semantic-only" in turn_map
    t_sem = turn_map["turn-01-semantic-only"]

    assert t_sem["has_delta"] is False
    assert t_sem["max_abs_delta"] == 0.0
    assert t_sem["has_semantic_event"] is True
    assert t_sem["has_slow_write"] is False
    assert t_sem["is_aborted"] is False
    assert t_sem["is_moment"] is True
    assert is_moment_eligible(t_sem) is True

    # 2. Moments-only filter must include it
    moments = list_committed_turns(conn_s, conn_f, trace_db=trace_db, moments_only=True, slow_dimension=_SLOW_DIM)
    moment_ids = [m["interaction_id"] for m in moments]
    assert "turn-01-semantic-only" in moment_ids

    conn_s.close()
    conn_f.close()


def test_moments_eligibility_aborted_turn_appears(moments_eligibility_dbs: Path):
    """Aborted turn must appear in Moments, visibly labeled ABORTED, and never masquerade as lived change."""
    state_db = moments_eligibility_dbs / "cognition_state.sqlite"
    facts_db = moments_eligibility_dbs / "facts.sqlite"
    trace_db = moments_eligibility_dbs / "observation_trace.sqlite"

    conn_s = sqlite3.connect(state_db)
    conn_f = sqlite3.connect(facts_db)

    # 1. Full list projection identifies aborted turn
    all_turns = list_committed_turns(conn_s, conn_f, trace_db=trace_db, moments_only=False,
    slow_dimension=_SLOW_DIM)
    turn_map = {t["interaction_id"]: t for t in all_turns}
    assert "turn-02-aborted" in turn_map
    t_abort = turn_map["turn-02-aborted"]

    assert t_abort["is_aborted"] is True
    assert t_abort["has_delta"] is False
    assert t_abort["max_abs_delta"] == 0.0
    assert t_abort["has_slow_write"] is False
    assert t_abort["composition"] == "OFF"
    assert "aborted" in t_abort["delta_summary"]
    assert t_abort["is_moment"] is True
    assert is_moment_eligible(t_abort) is True

    # 2. Moments-only filter must include it
    moments = list_committed_turns(conn_s, conn_f, trace_db=trace_db, moments_only=True, slow_dimension=_SLOW_DIM)
    moment_ids = [m["interaction_id"] for m in moments]
    assert "turn-02-aborted" in moment_ids

    conn_s.close()
    conn_f.close()


def test_moments_eligibility_ordinary_zero_delta_semantic_abstain_turn_excluded(moments_eligibility_dbs: Path):
    """Ordinary zero-delta semantic-abstain turn must NOT appear in Moments feed."""
    state_db = moments_eligibility_dbs / "cognition_state.sqlite"
    facts_db = moments_eligibility_dbs / "facts.sqlite"
    trace_db = moments_eligibility_dbs / "observation_trace.sqlite"

    conn_s = sqlite3.connect(state_db)
    conn_f = sqlite3.connect(facts_db)

    # 1. Full list includes it, but flags it as non-moment
    all_turns = list_committed_turns(conn_s, conn_f, trace_db=trace_db, moments_only=False,
    slow_dimension=_SLOW_DIM)
    turn_map = {t["interaction_id"]: t for t in all_turns}
    assert "turn-03-abstain-zero-delta" in turn_map
    t_abstain = turn_map["turn-03-abstain-zero-delta"]

    assert t_abstain["has_delta"] is False
    assert t_abstain["max_abs_delta"] == 0.0
    assert t_abstain["has_semantic_event"] is False
    assert t_abstain["has_slow_write"] is False
    assert t_abstain["is_aborted"] is False
    assert t_abstain["is_moment"] is False
    assert is_moment_eligible(t_abstain) is False

    # 2. Moments-only filter must strictly exclude it
    moments = list_committed_turns(conn_s, conn_f, trace_db=trace_db, moments_only=True, slow_dimension=_SLOW_DIM)
    moment_ids = [m["interaction_id"] for m in moments]
    assert "turn-03-abstain-zero-delta" not in moment_ids

    conn_s.close()
    conn_f.close()


def test_moments_api_endpoint_filters_factual_eligibility(moments_eligibility_dbs: Path):
    """GET /api/turns?moments_only=true returns only factual moments."""
    app, _ = build_ow_app_from_db_dir(moments_eligibility_dbs)
    client = TestClient(app)

    # 1. Without moments_only: returns all 3 turns
    res_all = client.get("/api/turns")
    assert res_all.status_code == 200
    all_ids = [t["interaction_id"] for t in res_all.json()["turns"]]
    assert len(all_ids) == 3
    assert "turn-01-semantic-only" in all_ids
    assert "turn-02-aborted" in all_ids
    assert "turn-03-abstain-zero-delta" in all_ids

    # 2. With moments_only=true: returns only semantic-only and aborted turns
    res_moments = client.get("/api/turns?moments_only=true")
    assert res_moments.status_code == 200
    moment_turns = res_moments.json()["turns"]
    moment_ids = [t["interaction_id"] for t in moment_turns]
    assert len(moment_turns) == 2
    assert "turn-01-semantic-only" in moment_ids
    assert "turn-02-aborted" in moment_ids
    assert "turn-03-abstain-zero-delta" not in moment_ids

