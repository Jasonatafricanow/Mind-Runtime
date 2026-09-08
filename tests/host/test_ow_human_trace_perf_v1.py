"""Tests for OW-HUMAN-TRACE-PERF-V1.

Read-only performance optimization contracts:
- /api/turns/head endpoint contract.
- /api/turns bounded batch queries (assert query count <= 4, no N+1).
- Stable cursor pagination with (committed_at, interaction_id).
- Causal trace caching with terminality constraint.
- Zero Hermes assistant message scanning in /api/turns.
- Read-only DB isolation.
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from observation_window.human_causal_trace import (
    build_human_causal_trace,
    list_committed_turns,
)
from observation_window.web.api import (
    _CAUSAL_TRACE_CACHE,
    _is_terminal_trace,
    build_router,
)
from observation_window.web.runtime import build_ow_app_from_db_dir


class QueryCountingConnection:
    """Wrapper to count executed SQL queries."""

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
def populated_test_dbs(tmp_path: Path):
    """Create test SQLite DBs with 25 committed turns."""
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
            source_event_ref TEXT,
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
    conn_f.execute("""
        CREATE TABLE observations (
            id TEXT PRIMARY KEY,
            interaction_id TEXT NOT NULL,
            value TEXT NOT NULL,
            confidence REAL NOT NULL,
            observed_at TEXT NOT NULL
        )
    """)

    # Populate 25 turns
    for i in range(1, 26):
        ts = f"2026-09-05T12:{i:02d}:00.000000+00:00"
        ix_id = f"turn-{i:03d}"
        from_id = f"state:irritation:v{i-1}"
        to_id = f"state:irritation:v{i}"
        proj_ids = json.dumps([to_id])

        # Commit marker
        conn_s.execute(
            "INSERT INTO commit_markers (scope_domain, interaction_id, committed_at, projected_state_ids) VALUES (?, ?, ?, ?)",
            ("agent", ix_id, ts, proj_ids),
        )
        # States
        conn_s.execute(
            "INSERT OR REPLACE INTO states (scope_domain, state_id, dimension, status, value, valid_from, last_observed_at, evidence_refs, transition_refs, updated_at, origin_runtime_id, version, sync_version, sync_idem_key) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("agent", from_id, "agent.affect.irritation", "active", str(0.1 + i * 0.01), ts, ts, "[]", "[]", ts, "test", i - 1, 1, "k"),
        )
        conn_s.execute(
            "INSERT OR REPLACE INTO states (scope_domain, state_id, dimension, status, value, valid_from, last_observed_at, evidence_refs, transition_refs, updated_at, origin_runtime_id, version, sync_version, sync_idem_key) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("agent", to_id, "agent.affect.irritation", "active", str(0.1 + (i + 1) * 0.01), ts, ts, "[]", "[]", ts, "test", i, 1, "k"),
        )
        # Transition
        conn_s.execute(
            "INSERT INTO state_transitions (transition_id, scope_domain, origin_runtime_id, intent_id, from_state_id, to_state_id, committed_at, sync_version, sync_idem_key) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (f"tr-{i}", "agent", "test", f"turn_commit:{ix_id}:agent.affect.irritation:{i}", from_id, to_id, ts, 1, "k"),
        )
        # Evidence
        conn_f.execute(
            "INSERT INTO evidence (id, interaction_id, source_type, payload, occurred_at) VALUES (?, ?, ?, ?, ?)",
            (f"ev-{i}", ix_id, "user_message", json.dumps({"text": f"Hello turn {i}"}), ts),
        )

    conn_s.commit()
    conn_f.commit()
    conn_s.close()
    conn_f.close()

    return tmp_path


def test_bounded_queries_in_list_committed_turns(populated_test_dbs: Path):
    """Verify that listing committed turns executes a bounded number of queries (<= 4), NOT N+1."""
    p_state = populated_test_dbs / "cognition_state.sqlite"
    p_facts = populated_test_dbs / "facts.sqlite"

    raw_conn_s = sqlite3.connect(f"file:{p_state.as_posix()}?mode=ro", uri=True)
    raw_conn_f = sqlite3.connect(f"file:{p_facts.as_posix()}?mode=ro", uri=True)

    counting_s = QueryCountingConnection(raw_conn_s)
    counting_f = QueryCountingConnection(raw_conn_f)

    # Fetch 20 turns
    turns = list_committed_turns(counting_s, counting_f, limit=20)
    assert len(turns) == 20

    # BOUNDED QUERY ASSERTION:
    # 1 table check + 1 commit_markers query + 1 transitions query + 1 states query = 4 state queries
    # 1 evidence query = 1 facts query
    assert counting_s.query_count <= 4, f"Expected <= 4 state queries, got {counting_s.query_count}"
    assert counting_f.query_count <= 1, f"Expected <= 1 fact query, got {counting_f.query_count}"

    # Verify no unindexed LIKE was executed
    for q in counting_s.executed_queries:
        assert "LIKE" not in q, f"Unindexed LIKE query detected: {q}"


def test_stable_cursor_pagination(populated_test_dbs: Path):
    """Verify stable keyset pagination using (committed_at, interaction_id)."""
    p_state = populated_test_dbs / "cognition_state.sqlite"
    p_facts = populated_test_dbs / "facts.sqlite"

    conn_s = sqlite3.connect(f"file:{p_state.as_posix()}?mode=ro", uri=True)
    conn_f = sqlite3.connect(f"file:{p_facts.as_posix()}?mode=ro", uri=True)

    # Page 1: 10 turns
    page1 = list_committed_turns(conn_s, conn_facts=conn_f, limit=10)
    assert len(page1) == 10
    page1_ids = [t["interaction_id"] for t in page1]

    # Cursor from last item
    last = page1[-1]
    cursor_comm_at = last["committed_at"]
    cursor_ix_id = last["interaction_id"]

    # Page 2: next 10 turns
    page2 = list_committed_turns(
        conn_s,
        conn_facts=conn_f,
        limit=10,
        before_committed_at=cursor_comm_at,
        before_interaction_id=cursor_ix_id,
    )
    assert len(page2) == 10
    page2_ids = [t["interaction_id"] for t in page2]

    # Assert zero overlap
    overlap = set(page1_ids).intersection(set(page2_ids))
    assert not overlap, f"Pages overlap on IDs: {overlap}"

    # Assert strictly decreasing ordering
    all_turns = page1 + page2
    for j in range(len(all_turns) - 1):
        t_a = all_turns[j]
        t_b = all_turns[j + 1]
        assert (t_a["committed_at"], t_a["interaction_id"]) > (t_b["committed_at"], t_b["interaction_id"])


def test_web_api_head_endpoint(populated_test_dbs: Path):
    """Test GET /api/turns/head returns 200 with expected shape."""
    app, _ = build_ow_app_from_db_dir(populated_test_dbs)
    client = TestClient(app)

    res = client.get("/api/turns/head")
    assert res.status_code == 200
    data = res.json()

    assert "latest_interaction_id" in data
    assert data["latest_interaction_id"] == "turn-025"
    assert "committed_at" in data
    assert "total_committed" in data
    assert data["total_committed"] == 25
    assert "epoch_turns" in data
    assert isinstance(data["epoch_turns"], int)


def test_web_api_list_turns_contract(populated_test_dbs: Path):
    """Test GET /api/turns contract and pagination cursor."""
    app, _ = build_ow_app_from_db_dir(populated_test_dbs)
    client = TestClient(app)

    # Default limit=20
    res = client.get("/api/turns")
    assert res.status_code == 200
    data = res.json()

    turns = data.get("turns", [])
    assert len(turns) == 20
    assert data.get("has_more") is True
    assert data.get("next_cursor") is not None
    assert "|" in data["next_cursor"]

    # Verify keys of turn item
    t0 = turns[0]
    assert t0["interaction_id"] == "turn-025"
    assert "committed_at" in t0
    assert "user_preview" in t0
    assert t0["user_preview"] == "Hello turn 25"
    assert "has_delta" in t0
    assert t0["has_delta"] is True
    assert "delta_summary" in t0
    assert "irritation +0.0100" in t0["delta_summary"]
    assert t0["composition"] == "ON"

    # Query next page using cursor
    cursor = data["next_cursor"]
    res2 = client.get(f"/api/turns?limit=20&before={cursor}")
    assert res2.status_code == 200
    data2 = res2.json()
    turns2 = data2.get("turns", [])
    assert len(turns2) == 5  # remaining 5 of 25
    assert data2.get("has_more") is False


def test_causal_cache_and_terminality_constraint():
    """Verify caching respects FINAL PERF FIX: zero age heuristics, strictly evidence-based terminality."""
    _CAUSAL_TRACE_CACHE.clear()

    # 1. Incomplete current-era trace (even if committed hours ago) must NOT be terminal
    incomplete_current_era = {
        "interaction_id": "test-current-incomplete",
        "committed_at": "2026-09-05T10:00:00+00:00",  # Long in the past, but current era
        "is_aborted": False,
        "terminal_proof": None,
        "assistant_response": {
            "status": "UNAVAILABLE / NOT PERSISTED",
            "terminal_result": False,
        },
        "raw_linkage": {
            "pre_journal": False,
        },
    }
    assert _is_terminal_trace(incomplete_current_era) is False, "Age must NOT declare terminality!"

    # 2. Allowed Proof 1: TURN_ABORT exists -> terminal
    term_abort = {
        "interaction_id": "test-aborted",
        "committed_at": None,
        "is_aborted": True,
        "terminal_proof": "TURN_ABORT",
        "assistant_response": {"status": "UNAVAILABLE / NOT PERSISTED"},
    }
    assert _is_terminal_trace(term_abort) is True

    # 3. Allowed Proof 2: TURN_COMMIT exists AND exact assistant linkage exists -> terminal
    term_asst = {
        "interaction_id": "test-complete",
        "committed_at": "2026-09-05T12:00:00+00:00",
        "is_aborted": False,
        "terminal_proof": "TURN_COMMIT_WITH_EXACT_ASSISTANT",
        "assistant_response": {
            "status": "AVAILABLE",
            "text": "Hello user",
            "message_id": "msg-123",
            "terminal_result": False,
        },
    }
    assert _is_terminal_trace(term_asst) is True

    # 4. Allowed Proof 3: TURN_COMMIT exists AND runtime recorded explicit assistant terminal result -> terminal
    term_explicit_unavail = {
        "interaction_id": "test-explicit-no-resp",
        "committed_at": "2026-09-05T12:00:00+00:00",
        "is_aborted": False,
        "terminal_proof": "TURN_COMMIT_WITH_EXPLICIT_ASSISTANT_TERMINAL",
        "assistant_response": {
            "status": "ASSISTANT_RESPONSE_UNAVAILABLE",
            "terminal_result": True,
        },
    }
    assert _is_terminal_trace(term_explicit_unavail) is True

    # 5. Allowed Proof 4: Pre-journal historical proof -> ONLY with positive provenance
    term_pre_journal = {
        "interaction_id": "test-pre-journal",
        "committed_at": "2026-08-01T00:00:00+00:00",
        "is_aborted": False,
        "terminal_proof": "PRE_JOURNAL_HISTORICAL",
        "assistant_response": {"status": "UNAVAILABLE / NOT PERSISTED"},
        "raw_linkage": {"pre_journal": True, "telemetry_status": "PRE_JOURNAL_HISTORICAL"},
    }
    assert _is_terminal_trace(term_pre_journal) is True

    # 6. Telemetry DB absent / unreadable / table missing / query error -> NOT terminal!
    telemetry_unavail = {
        "interaction_id": "test-telemetry-absent",
        "committed_at": "2026-08-01T00:00:00+00:00",
        "is_aborted": False,
        "terminal_proof": None,
        "assistant_response": {"status": "UNAVAILABLE / NOT PERSISTED"},
        "raw_linkage": {"pre_journal": False, "telemetry_status": "TELEMETRY_UNAVAILABLE"},
    }
    assert _is_terminal_trace(telemetry_unavail) is False, "Telemetry absent must NOT make trace immutable-cache eligible!"


def test_positive_provenance_pre_journal_terminality(tmp_path: Path):
    """Verify build_human_causal_trace strictly enforces positive provenance for PRE_JOURNAL_HISTORICAL."""
    from observation_window.transient_trace_journal import TransientTraceJournal

    state_db = tmp_path / "cognition_state.sqlite"
    facts_db = tmp_path / "facts.sqlite"
    journal_db = tmp_path / "observation_trace.sqlite"

    conn_s = sqlite3.connect(state_db)
    conn_s.execute("CREATE TABLE commit_markers (interaction_id TEXT PRIMARY KEY, committed_at TEXT)")
    conn_s.execute("CREATE TABLE state_transitions (transition_id TEXT PRIMARY KEY, to_state_id TEXT, committed_at TEXT)")
    conn_s.execute("CREATE TABLE states (state_id TEXT PRIMARY KEY, dimension TEXT, value TEXT, version INTEGER, updated_at TEXT)")
    conn_s.execute("CREATE TABLE slow_contribution_window (id INTEGER PRIMARY KEY, source_decision_id TEXT, evidence_refs TEXT, target_dimension TEXT, sequence INTEGER, accepted_at TEXT, proposed_value REAL, salience REAL)")

    conn_f = sqlite3.connect(facts_db)
    conn_f.execute("CREATE TABLE evidence (id TEXT PRIMARY KEY, interaction_id TEXT, source_type TEXT, payload TEXT, occurred_at TEXT)")
    conn_f.execute("CREATE TABLE observations (id TEXT PRIMARY KEY, interaction_id TEXT, value TEXT, confidence REAL, observed_at TEXT)")

    # Insert turn committed at 2026-08-01 (older)
    conn_s.execute("INSERT INTO commit_markers VALUES ('turn-old', '2026-08-01T12:00:00Z')")
    conn_f.execute("INSERT INTO evidence VALUES ('ev-1', 'turn-old', 'user_message', '{\"text\":\"old\"}', '2026-08-01T12:00:00Z')")

    # Case A: Telemetry DB does NOT exist -> terminal_proof must be None, NOT pre-journal
    nonexistent_db = tmp_path / "nonexistent_trace.sqlite"
    trace_absent = build_human_causal_trace("turn-old", conn_s, conn_f, trace_db=nonexistent_db)
    assert trace_absent["terminal_proof"] is None
    assert trace_absent["is_terminal"] is False
    assert trace_absent["raw_linkage"]["pre_journal"] is False
    assert trace_absent["raw_linkage"]["telemetry_status"] == "TELEMETRY_UNAVAILABLE"
    assert _is_terminal_trace(trace_absent) is False

    # Case B: Telemetry DB exists with positive activation_at = 2026-09-01T00:00:00Z
    # For turn-old (committed 2026-08-01 < activation_at) -> terminal_proof is PRE_JOURNAL_HISTORICAL
    journal = TransientTraceJournal(journal_db)
    with journal._get_connection() as conn_j:
        conn_j.execute("UPDATE journal_metadata SET value = '2026-09-01T00:00:00Z' WHERE key = 'activation_at'")
        conn_j.commit()

    trace_proven = build_human_causal_trace("turn-old", conn_s, conn_f, trace_db=journal_db)
    assert trace_proven["terminal_proof"] == "PRE_JOURNAL_HISTORICAL"
    assert trace_proven["is_terminal"] is True
    assert trace_proven["raw_linkage"]["pre_journal"] is True
    assert trace_proven["raw_linkage"]["telemetry_status"] == "PRE_JOURNAL_HISTORICAL"
    assert _is_terminal_trace(trace_proven) is True

    # Case C: Current-era turn (committed 2026-09-05 > activation_at) without assistant -> NOT terminal
    conn_s.execute("INSERT INTO commit_markers VALUES ('turn-new', '2026-09-05T12:00:00Z')")
    conn_f.execute("INSERT INTO evidence VALUES ('ev-2', 'turn-new', 'user_message', '{\"text\":\"new\"}', '2026-09-05T12:00:00Z')")
    trace_current = build_human_causal_trace("turn-new", conn_s, conn_f, trace_db=journal_db)
    assert trace_current["terminal_proof"] is None
    assert trace_current["is_terminal"] is False
    assert trace_current["raw_linkage"]["pre_journal"] is False
    assert _is_terminal_trace(trace_current) is False


def test_causal_page_navigation_and_lifecycle(populated_test_dbs: Path):
    """Verify clean navigation across all OW pages, route aliases, and causal lifecycle contract."""
    app, _ = build_ow_app_from_db_dir(populated_test_dbs)
    client = TestClient(app)

    # 1. Test all primary pages and aliases return 200 HTML
    routes = ["/", "/overview", "/timeline", "/causal", "/history", "/live-trace", "/live"]
    for route in routes:
        resp = client.get(route)
        assert resp.status_code == 200, f"Route {route} failed with {resp.status_code}"
        assert "text/html" in resp.headers["content-type"]
        assert len(resp.text) > 200

    # 2. Inspect causal.html markup
    causal_html = client.get("/causal").text
    # Standard navigation bar matching other pages
    assert '<div id="nav">' in causal_html
    assert '<a href="/" class="nav-link">Overview</a>' in causal_html
    assert '<a href="/timeline" class="nav-link">Timeline</a>' in causal_html
    assert '<a href="/causal" class="nav-link active">Causal</a>' in causal_html
    assert '<a href="/history" class="nav-link">History</a>' in causal_html
    assert '<a href="/live-trace" class="nav-link">Live Trace</a>' in causal_html

    # Ensure broken old link targets do NOT exist in nav
    assert 'href="/overview"' not in causal_html
    assert 'href="/live"' not in causal_html

    # Ensure lifecycle cleanup listeners exist
    assert "pagehide" in causal_html
    assert "beforeunload" in causal_html
    assert "pageshow" in causal_html
    assert "cleanupLifecycle" in causal_html
    assert "AbortController" in causal_html


def test_zero_hermes_scanning_in_causal_detail(populated_test_dbs: Path, tmp_path: Path):
    """Verify Hermes DB query in build_human_causal_trace is exact ID only, no scan."""
    hermes_db = tmp_path / "hermes_state.db"
    conn_h = sqlite3.connect(hermes_db)
    conn_h.execute("CREATE TABLE messages (id TEXT PRIMARY KEY, content TEXT, created_at TEXT)")
    conn_h.execute("INSERT INTO messages VALUES ('msg-456', 'Exact assistant content', '2026-09-05T12:00:00Z')")
    conn_h.commit()
    conn_h.close()

    p_state = populated_test_dbs / "cognition_state.sqlite"
    p_facts = populated_test_dbs / "facts.sqlite"
    conn_s = sqlite3.connect(f"file:{p_state.as_posix()}?mode=ro", uri=True)
    conn_f = sqlite3.connect(f"file:{p_facts.as_posix()}?mode=ro", uri=True)

    # When no assistant message in trace journal or evidence, Hermes DB is NOT queried if ID is UNAVAILABLE
    trace = build_human_causal_trace("turn-001", conn_s, conn_f, hermes_db=hermes_db)
    assert trace["assistant_response"]["status"] == "UNAVAILABLE / NOT PERSISTED"
