"""Static chart contract guards; these do not constitute visual acceptance."""

import re
from pathlib import Path

_STATIC_DIR = Path(__file__).parents[2] / "src" / "observation_window" / "web" / "static"


def _state_html() -> str:
    return (_STATIC_DIR / "state.html").read_text(encoding="utf-8")


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
    calls = set(re.findall(
        r'(?:fetch\(API \+ |OWRuntimeScope\.runtimeFetch\(runtimeSelection,\s*)"([^"]+)"', html
    ))
    assert calls == {"/api/overview", "/api/trends?limit=30"}
    # Count both styles: an extra direct fetch must not hide behind runtimeFetch.
    assert len(re.findall(r"\b(?:runtimeFetch|fetch)\s*\(", html)) == 2
