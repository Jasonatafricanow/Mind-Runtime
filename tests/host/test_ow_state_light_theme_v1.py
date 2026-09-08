"""Tests for OW-STATE-LIGHT-THEME-V1.

Light product theme frontend contracts (visual-only ticket):
1. Light theme tokens are present in the shared stylesheet.
2. Product routes serve the light State page with product language.
3. Debug submenu is hidden by default (CSS contract).
4. Moments threshold filter no longer uses "Major Changes" style judgment language.
5. Debug surfaces keep the dark engineering scope (body.theme-dark) while
   sharing the same navigation component.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from observation_window.web.runtime import build_ow_app_from_db_dir


@pytest.fixture
def theme_test_client(tmp_path: Path) -> TestClient:
    app, _ = build_ow_app_from_db_dir(tmp_path)
    return TestClient(app)


def test_light_theme_tokens_present(theme_test_client: TestClient):
    """Shared stylesheet defines the light product palette and dark debug scope."""
    res = theme_test_client.get("/static/style.css")
    assert res.status_code == 200
    css = res.text
    assert "--page-bg" in css
    assert "#F7F8FA" in css
    assert "body.theme-dark" in css


def test_product_route_serves_light_state_page(theme_test_client: TestClient):
    """GET / serves the product State page with product-facing hierarchy labels."""
    res = theme_test_client.get("/")
    assert res.status_code == 200
    assert "text/html" in res.headers["content-type"]
    assert "Companion State" in res.text
    # OW-RESPONSIVE-I18N-ZH-V1: product headings are Chinese-first.
    assert "状态" in res.text
    assert "动态时序" in res.text
    assert "关键轮次" in res.text
    assert "长期状态" in res.text
    # The engineering phrase must not be the main heading anymore.
    assert "CURRENT STATES (CANONICAL)" not in res.text
    assert "Current State" not in res.text
    assert "Recent Trajectory" not in res.text
    # Product page stays on the light default (no dark scope class).
    assert "theme-dark" not in res.text


def test_debug_submenu_hidden_by_default(theme_test_client: TestClient):
    """Nav dropdown menu is display:none until opened (hover/focus/.open)."""
    css = theme_test_client.get("/static/style.css").text
    blocks = []
    start = 0
    while True:
        idx = css.find(".nav-dropdown-menu {", start)
        if idx == -1:
            break
        blocks.append(css[idx:css.find("}", idx)])
        start = idx + 1
    assert blocks
    assert any("display: none" in b for b in blocks)


def test_moments_threshold_label_neutral(theme_test_client: TestClient):
    """Moments filter uses neutral product language for the |delta| threshold."""
    res = theme_test_client.get("/moments")
    assert res.status_code == 200
    # OW-RESPONSIVE-I18N-ZH-V1: neutral threshold label, Chinese filters.
    assert "Δ ≥ 0.05" in res.text
    assert "Major" not in res.text
    assert "交互记录" in res.text


def test_debug_pages_keep_dark_scope(theme_test_client: TestClient):
    """Debug surfaces opt into the dark engineering scope via body.theme-dark."""
    for route in ("/debug/causal", "/debug/ledger", "/debug/live-trace"):
        res = theme_test_client.get(route)
        assert res.status_code == 200, route
        assert 'class="theme-dark"' in res.text, route
