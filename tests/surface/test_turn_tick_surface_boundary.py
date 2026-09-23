"""W3 Single Surface Port for User Turn and Cognitive Ticker.

RED BY DESIGN: Production turn/tick Surface wiring is intentionally absent in W3-B0.
These assertions freeze the requirement:
- Turn uses ONE Surface port
- Tick uses the SAME Surface port
- Zero separate personality derivation in CognitiveTicker
"""

import pytest


def test_turn_orchestrator_and_cognitive_ticker_share_single_surface_port():
    """Turn orchestrator and CognitiveTicker must consume the exact same SurfaceProjectionPort."""
    try:
        from mind_runtime.cognition.tick import CognitiveTicker
        from mind_runtime.pipeline.orchestrator import TurnOrchestrator
    except ImportError as e:
        pytest.fail(f"RED BY DESIGN: Orchestrator/Ticker production import missing: {e}")

    # Orchestrator and Ticker must both accept and wire the single SurfaceProjectionPort
    if not hasattr(TurnOrchestrator, "surface_port") and not hasattr(
        TurnOrchestrator, "surface_projection_port"
    ):
        pytest.fail(
            "RED BY DESIGN: TurnOrchestrator missing surface_projection_port seam"
        )
    if not hasattr(CognitiveTicker, "surface_port") and not hasattr(
        CognitiveTicker, "surface_projection_port"
    ):
        pytest.fail(
            "RED BY DESIGN: CognitiveTicker missing surface_projection_port seam"
        )
    pytest.fail("RED BY DESIGN: Single SurfaceProjectionPort wiring for turn and tick missing")
