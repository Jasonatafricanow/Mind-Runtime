"""Tests for OW-OVERVIEW-USABILITY-V1: Observation-Only UI Fix.

Verifies:
1. Current States: group by (scope, dimension), display latest canonical version only.
2. Hide placeholder/stub dimensions by default; toggle support.
3. Separate: FAST STATE vs SLOW / ACCUMULATED SELF vs DEBUG / PLACEHOLDER.
4. Explicitly surface agent.longitudinal.relationship_security (show "not established" when absent).
5. Replace ambiguous Turn Count with Current Epoch Turns, Persisted/Committed Turns, Last Committed Turn.
6. Compact bundle header: Bundle State, Gateway PID, MR, Semantic, Appraisal, Slow Writer, OW, runtime_ready_at.
7. Overview state row layout (short label, value, delta, updated_at).
8. History retains all versions; Overview does NOT display v1/v2/v3 duplicates.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from mind_runtime.contracts.common import SyncFields
from mind_runtime.contracts.scope import Scope, ScopeDomain
from mind_runtime.contracts.state import RuntimeState
from observation_window.web.api import (
    _extract_bundle_header,
    _extract_turn_stats,
    _group_latest_states,
)
from observation_window.web.server import build_app
from observation_window.web.sources import OWDashboardDataSources


def _make_dummy_scope(domain: ScopeDomain = ScopeDomain.AGENT, agent_id: str = "xiyue") -> Scope:
    if domain == ScopeDomain.USER:
        return Scope(domain=domain, user_id="telegram:default")
    return Scope(
        domain=domain,
        agent_id=agent_id,
        persona_id=f"persona-{agent_id}",
    )


def _make_state(
    state_id: str,
    dimension: str,
    value: Any,
    version: int,
    updated_at: datetime | None = None,
    domain: ScopeDomain = ScopeDomain.AGENT,
) -> RuntimeState:
    t = updated_at or datetime.now(timezone.utc)
    scope = _make_dummy_scope(domain=domain)
    return RuntimeState(
        state_id=state_id,
        scope=scope,
        dimension=dimension,
        value=value,
        status="active",
        valid_from=t,
        valid_until=None,
        relevant_until=None,
        last_observed_at=t,
        evidence_refs=("ev-1",),
        transition_refs=("tr-1",),
        updated_at=t,
        origin_runtime_id="runtime-1",
        version=version,
        sync=SyncFields(scope, "runtime-1", state_id, version, f"idem-{state_id}"),
    )


def test_group_latest_states_deduplication_and_delta():
    """1 & 8: Group by (scope, dimension) and display latest canonical version only."""
    t0 = datetime(2026, 9, 5, 10, 0, 0, tzinfo=timezone.utc)
    t1 = datetime(2026, 9, 5, 10, 1, 0, tzinfo=timezone.utc)
    t2 = datetime(2026, 9, 5, 10, 2, 0, tzinfo=timezone.utc)

    raw_states = [
        _make_state("s1", "agent.affect.longing", 0.10, version=1, updated_at=t0),
        _make_state("s2", "agent.affect.longing", 0.15, version=2, updated_at=t1),
        _make_state("s3", "agent.affect.longing", 0.25, version=3, updated_at=t2),
        _make_state("s4", "agent.affect.irritation", 0.30, version=1, updated_at=t0),
        _make_state("s5", "agent.affect.irritation", 0.20, version=2, updated_at=t1),
    ]

    grouped = _group_latest_states(
        raw_states, slow_dimensions=("agent.longitudinal.relationship_security",)
    )
    by_dim = {s["dimension"]: s for s in grouped}

    assert "agent.affect.longing" in by_dim
    assert by_dim["agent.affect.longing"]["version"] == 3
    assert by_dim["agent.affect.longing"]["value"] == 0.25
    assert by_dim["agent.affect.longing"]["delta"] == 0.10
    assert by_dim["agent.affect.longing"]["display_name"] == "longing"

    assert "agent.affect.irritation" in by_dim
    assert by_dim["agent.affect.irritation"]["version"] == 2
    assert by_dim["agent.affect.irritation"]["value"] == 0.20
    assert by_dim["agent.affect.irritation"]["delta"] == -0.10


def test_categorization_fast_slow_placeholder():
    """2 & 3: Separate FAST, SLOW, and PLACEHOLDER states."""
    raw_states = [
        _make_state("s1", "agent.affect.anxiety", 0.2, version=1),
        _make_state("s2", "agent.longitudinal.relationship_security", 0.85, version=1),
        _make_state("s3", "user.affect.stub", "dummy", version=1, domain=ScopeDomain.USER),
    ]

    grouped = _group_latest_states(
        raw_states, slow_dimensions=("agent.longitudinal.relationship_security",)
    )
    by_dim = {s["dimension"]: s for s in grouped}

    assert by_dim["agent.affect.anxiety"]["category"] == "fast"
    assert by_dim["agent.affect.anxiety"]["is_placeholder"] is False

    assert by_dim["agent.longitudinal.relationship_security"]["category"] == "slow"
    assert by_dim["agent.longitudinal.relationship_security"]["is_placeholder"] is False
    assert by_dim["agent.longitudinal.relationship_security"]["value"] == 0.85

    assert by_dim["user.affect.stub"]["category"] == "placeholder"
    assert by_dim["user.affect.stub"]["is_placeholder"] is True


def test_explicit_surface_relationship_security_when_absent():
    """4: Explicitly surface agent.longitudinal.relationship_security as 'not established' if absent."""
    raw_states = [
        _make_state("s1", "agent.affect.longing", 0.3, version=1),
    ]

    grouped = _group_latest_states(raw_states, slow_dimensions=("agent.longitudinal.relationship_security",))
    by_dim = {s["dimension"]: s for s in grouped}

    assert "agent.longitudinal.relationship_security" in by_dim
    rel_sec = by_dim["agent.longitudinal.relationship_security"]
    assert rel_sec["category"] == "slow"
    assert rel_sec["status"] == "not established"
    assert rel_sec["value"] is None
    assert rel_sec["version"] is None
    assert rel_sec["delta"] is None


def test_extract_turn_stats():
    """5: Turn stats replace ambiguous count with epoch, persisted, and last committed."""
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.execute.return_value = mock_cursor
    mock_cursor.fetchone.side_effect = [
        (1,),  # table_check
        (42,),  # total_committed
        ("mr-turn-999", "2026-09-05T12:00:00Z"),  # last_row
        (5,),   # epoch_turns
    ]

    mock_sources = MagicMock()
    mock_sources.query_service._commits._conn = mock_conn


    stats = _extract_turn_stats(mock_sources, "2026-09-05T11:00:00Z")
    assert stats["persisted_committed_turns"] == 42
    assert stats["current_epoch_turns"] == 5
    assert stats["last_committed_turn"]["interaction_id"] == "mr-turn-999"
    assert stats["last_committed_turn"]["committed_at"] == "2026-09-05T12:00:00Z"


def test_bundle_header_fields():
    """6: Verify compact bundle header fields from the normalized
    RuntimeStatusProjection (Phase 01: readiness abstraction)."""
    from observation_window.binding import (
        ObservationContext,
        RuntimeStatusProjection,
        StateSurface,
        TelemetrySource,
        AssistantMessageSource,
    )

    class _StubStatusProvider:
        def projection(self):
            return RuntimeStatusProjection(
                status="READY",
                summary_code="CORE_READY",
                observed_at="2026-09-05T10:00:00Z",
                detail={
                    "gateway_pid": 12345,
                    "epoch_id": "epoch-12345",
                    "runtime_ready_at": "2026-09-05T10:00:00Z",
                },
            )

    context = ObservationContext(
        binding_scope_key="test",
        state_surface=StateSurface(),
        telemetry_source=TelemetrySource(db_path=None),
        assistant_message_source=AssistantMessageSource(db_path=None),
        runtime_status_provider=_StubStatusProvider(),
        runtime_detail_provider=lambda: {
            "semantic_status": "ACTIVE",
            "appraisal_status": "ACTIVE",
            "slow_writer_status": "ACTIVE",
        },
    )

    header = _extract_bundle_header(context)
    assert header["bundle_state"] == "READY"
    assert header["gateway_pid"] == 12345
    assert header["mr_status"] == "ACTIVE"
    assert header["semantic_status"] == "ACTIVE"
    assert header["appraisal_status"] == "ACTIVE"
    assert header["slow_writer_status"] == "ACTIVE"
    assert header["ow_status"] == "ONLINE"
    assert header["runtime_ready_at"] == "2026-09-05T10:00:00Z"
    assert header["epoch_id"] == "epoch-12345"
    # Normalized projection is included for the debug channel
    assert header["runtime_status"]["status"] == "READY"


def test_overview_endpoint_contract():
    """Full integration check on /api/overview endpoint and HTML template."""
    mock_sources = MagicMock()
    mock_sources.query_service.list_current_states.return_value = [
        _make_state("s1", "agent.affect.longing", 0.4, version=1),
        _make_state("s2", "agent.affect.longing", 0.5, version=2),
    ]
    mock_sources.query_service._commits = None
    mock_sources.query_service._state = None
    mock_sources.recent_turns.return_value = []

    from observation_window.binding import (
        AssistantMessageSource,
        ObservationContext,
        RuntimeStatusProjection,
        StateSurface,
        TelemetrySource,
    )

    class _StubStatusProvider:
        def projection(self):
            return RuntimeStatusProjection(
                status="READY",
                summary_code="CORE_READY",
                detail={
                    "gateway_pid": 12345,
                    "epoch_id": "epoch-12345",
                    "runtime_ready_at": "2026-09-05T10:00:00Z",
                },
            )

    context = ObservationContext(
        binding_scope_key="test",
        state_surface=StateSurface(
            fast_dimensions=("agent.affect.longing",),
            slow_dimensions=("agent.longitudinal.relationship_security",),
        ),
        telemetry_source=TelemetrySource(db_path=None),
        assistant_message_source=AssistantMessageSource(db_path=None),
        runtime_status_provider=_StubStatusProvider(),
        runtime_detail_provider=lambda: {
            "semantic_status": "ACTIVE",
            "appraisal_status": "ACTIVE",
            "slow_writer_status": "ACTIVE",
        },
    )

    app = build_app(mock_sources, context)
    client = TestClient(app)

    res = client.get("/api/overview")
    assert res.status_code == 200
    data = res.json()

    assert "bundle_header" in data
    assert "turn_stats" in data
    assert "current_states" in data
    assert "turn_count" in data

    dims = [s["dimension"] for s in data["current_states"]]
    assert "agent.affect.longing" in dims
    assert "agent.longitudinal.relationship_security" in dims

    # Verify overview HTML is served and contains key usability elements
    res_html = client.get("/")
    assert res_html.status_code == 200
    html = res_html.text
    # OW-STATE-LIGHT-THEME-V1 + OW-RESPONSIVE-I18N-ZH-V1: Chinese-first
    # product hierarchy labels replace the engineering phrase.
    assert "状态" in html
    assert "动态时序" in html
    assert "权威快状态" in html
    assert "bundle-header-area" in html
    assert "toggle-debug-states" in html
    assert "stat-epoch-turns" in html
    assert "stat-committed-turns" in html
