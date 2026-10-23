"""Static chart contract guards; these do not constitute visual acceptance."""

import re
from pathlib import Path

_STATIC_DIR = Path(__file__).parents[2] / "src" / "observation_window" / "web" / "static"


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
    # Check each populated chart element; the empty sparkline is not a substitute.
    for anchor in ('<line x1="0" y1="${y}"', '<path d="${d}"', '<path d="${pathD}"'):
        element = re.search(re.escape(anchor) + r"[^>]*>", html)
        assert element is not None, anchor
        assert 'vector-effect="non-scaling-stroke"' in element.group(), anchor
