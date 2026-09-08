"""Tests for OW-STATE-RESPONSIVE-SCALE-V1.

Responsive/density frontend contracts (final acceptance is visual):
1. Breakpoint-controlled chart heights exist (no fluid height).
2. No viewport-proportional scaling rules (vw/vh/aspect-ratio).
3. Trajectory SVG uses a stable viewBox coordinate system.
4. Trajectory strokes and grid lines use non-scaling strokes.
5. Density tokens exist and are consumed by card/sparkline/chart geometry.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from observation_window.web.runtime import build_ow_app_from_db_dir

_STATIC_DIR = Path(__file__).parents[2] / "src" / "observation_window" / "web" / "static"


@pytest.fixture
def scale_test_client(tmp_path: Path) -> TestClient:
    app, _ = build_ow_app_from_db_dir(tmp_path)
    return TestClient(app)


def test_breakpoint_chart_heights_exist():
    """Chart height is controlled by breakpoints (300/270/240/220), not fluid rules."""
    css = (_STATIC_DIR / "style.css").read_text(encoding="utf-8")
    assert "--chart-height: 300px" in css
    assert "--chart-height: 270px" in css
    assert "--chart-height: 240px" in css
    assert "--chart-height: 210px" in css
    assert "max-width: 1439px" in css
    assert "max-width: 1023px" in css
    assert "max-width: 767px" in css
    assert "var(--chart-height)" in css


def test_no_viewport_proportional_scaling_rules():
    """No vw/vh/aspect-ratio geometry scaling in the shared stylesheet."""
    css = (_STATIC_DIR / "style.css").read_text(encoding="utf-8")
    assert "aspect-ratio" not in css
    assert not re.search(r"\d+(\.\d+)?v[wh]\b", css), "found vw/vh unit in style.css"


def test_trajectory_svg_uses_stable_viewbox():
    """The trajectory SVG renders into a fixed 1200x300 coordinate space."""
    html = (_STATIC_DIR / "state.html").read_text(encoding="utf-8")
    assert 'viewBox="0 0 1200 300"' in html
    assert 'preserveAspectRatio="none"' in html
    # Height must not be derived from client dimensions in the renderer.
    assert "clientHeight" not in html


def test_non_scaling_strokes_on_chart_and_sparkline():
    """Trajectory strokes, grid lines and sparklines keep constant pixel width."""
    html = (_STATIC_DIR / "state.html").read_text(encoding="utf-8")
    # Grid lines + trajectory paths + sparkline path all carry vector-effect.
    assert html.count('vector-effect="non-scaling-stroke"') >= 3


def test_density_tokens_exist_and_are_consumed():
    """Density tokens are defined as a coherent set and consumed by geometry."""
    css = (_STATIC_DIR / "style.css").read_text(encoding="utf-8")
    for token in (
        "--ui-body",
        "--ui-meta",
        "--ui-title",
        "--state-value",
        "--card-height",
        "--spark-height",
        "--chart-height",
    ):
        assert token in css
    for consumer in (
        "var(--ui-body)",
        "var(--ui-title)",
        "var(--state-value)",
        "var(--card-height)",
        "var(--spark-height)",
        "var(--chart-height)",
    ):
        assert consumer in css


def test_product_route_serves_scaled_chart_page(scale_test_client: TestClient):
    """Product route still serves the State page with the responsive chart markup."""
    res = scale_test_client.get("/")
    assert res.status_code == 200
    assert 'viewBox="0 0 1200 300"' in res.text
    assert "chart-overlay" in res.text
    assert "chart-xaxis" in res.text
