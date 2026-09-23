"""W3 Single Surface Port for User Turn and Cognitive Ticker.

RED BY DESIGN: Production turn/tick Surface wiring is intentionally absent in W3-B0.
These assertions freeze the requirement:
- Turn uses ONE Surface port
- Tick uses the SAME Surface port
- Zero separate personality derivation in CognitiveTicker
"""

from typing import Any


def test_turn_orchestrator_and_cognitive_ticker_share_single_surface_port(
    turn_tick_surface_port_seam: Any,
):
    """Turn orchestrator and CognitiveTicker must consume the exact same SurfaceProjectionPort."""
    assert turn_tick_surface_port_seam.verify_port_sharing() is True
