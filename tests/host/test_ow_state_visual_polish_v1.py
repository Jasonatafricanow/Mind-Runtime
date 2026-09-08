"""Tests for OW-STATE-VISUAL-POLISH-V1.

Interaction-polish frontend contracts (final acceptance is visual/manual):
1. Legend contains the four canonical Fast Affect dimensions.
2. Focus is the default chart mode; Compare exists as an explicit mode.
3. Selected-turn guide element exists in the chart renderer.
4. Y-axis stays fixed canonical [0,1] — no dynamic Y-range calculation.
5. No backend/API surface changes: the State page still calls only
   /api/overview and /api/trends.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from observation_window.web.runtime import build_ow_app_from_db_dir

_STATIC_DIR = Path(__file__).parents[2] / "src" / "observation_window" / "web" / "static"


@pytest.fixture
def polish_test_client(tmp_path: Path) -> TestClient:
    app, _ = build_ow_app_from_db_dir(tmp_path)
    return TestClient(app)


def _state_html() -> str:
    return (_STATIC_DIR / "state.html").read_text(encoding="utf-8")


def test_legend_contains_four_canonical_dimensions():
    # Phase 01: legend membership is descriptor-driven — the page contains
    # the legend renderer but NO hardcoded canonical membership; the four
    # dimensions are declared by the Xiyue binding adapter's state_surface.
    html = _state_html()
    assert 'id="chart-legend"' in html
    assert "renderLegend" in html
    assert "applyStateSurface" in html
    for dim in ("agent.affect.irritation", "agent.affect.anxiety",
                "agent.affect.excitement", "agent.affect.longing"):
        assert dim not in html
    adapter = (_STATIC_DIR.parent.parent / "binding_xiyue.py").read_text(encoding="utf-8")
    for dim in ("agent.affect.irritation", "agent.affect.anxiety",
                "agent.affect.excitement", "agent.affect.longing"):
        assert dim in adapter


def test_focus_is_default_and_compare_exists():
    html = _state_html()
    assert 'let chartMode = "focus"' in html
    assert 'id="btn-mode-focus"' in html
    assert 'id="btn-mode-compare"' in html
    assert "setChartMode" in html


def test_selected_guide_element_exists():
    html = _state_html()
    assert "chart-guide" in html
    # Guide aligns with the committed node: same x mapping is used.
    assert "xv(selectedTurnIndex, n)" in html


def test_fixed_canonical_y_range_no_dynamic_scaling():
    html = _state_html()
    # Fixed viewBox height and fixed [0,1] clamp mapping
    assert 'viewBox="0 0 1200 300"' in html
    assert "Math.max(0, Math.min(1, v))" in html
    # No dynamic Y-domain computation for the main chart
    assert not re.search(r"y\s*(Max|Min|Domain)\s*=", html)


def test_state_page_calls_only_bounded_product_apis():
    html = _state_html()
    calls = set(re.findall(r'(?:fetch\(API \+ |OWRuntimeScope\.runtimeFetch\(runtimeSelection,\s*)"([^"]+)"', html))
    assert calls == {"/api/overview", "/api/trends?limit=30"}
    # No hover-driven fetches: fetch appears only inside loadHeader/loadTrends.
    fetch_count = html.count("OWRuntimeScope.runtimeFetch(") or html.count("fetch(")
    assert fetch_count == 2


def test_product_route_serves_polished_page(polish_test_client: TestClient):
    res = polish_test_client.get("/")
    assert res.status_code == 200
    assert "chart-legend" in res.text
    assert "chart-facts" in res.text
    assert ">单维度</button>" in res.text
    assert ">对比</button>" in res.text
