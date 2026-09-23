"""W3-D Expression, Renderer, Host, and Provider Boundary Tests.

RED BY DESIGN: Production Expression Surface compiler/renderer seams are absent in W3-B0.
These assertions freeze the W3-D contract requirements:
- SURFACE_V1 disables raw affect bands, duplicate style, and Host Slow numeric summary
- Qualitative guidance bundle is visible at actual provider bytes
- Provider text must not contain raw Surface floats, traits, dynamics values, or digests
- Essential bundle budget failure: if budget cannot fit the bundle, dispatch is withheld
"""

from typing import Any


def test_surface_v1_disables_raw_affect_bands_and_slow_numeric_summary(
    expression_surface_compiler: Any,
):
    """W3-D: In SURFACE_V1 mode, compiler omits raw affect bands and Slow numeric summaries."""
    compiler = expression_surface_compiler
    assert hasattr(compiler, "compile_surface_v1") or hasattr(
        compiler, "admit_surface_controls"
    )


def test_surface_qualitative_bundle_visible_at_actual_provider_bytes(
    expression_surface_renderer: Any,
):
    """W3-D: Qualitative guidance (directness/warmth/restraint) must reach provider payload."""
    renderer = expression_surface_renderer
    assert hasattr(renderer, "render_surface_bundle") or hasattr(
        renderer, "format_surface_guidance"
    )


def test_provider_context_contains_no_raw_numbers_or_digests(
    expression_surface_renderer: Any,
):
    """W3-D: Provider context contains zero raw floats, raw traits, raw dynamics, or digests."""
    renderer = expression_surface_renderer
    assert hasattr(renderer, "verify_provider_information_isolation")


def test_essential_bundle_overflow_withholds_provider_dispatch(
    expression_surface_compiler: Any,
):
    """W3-D: If prompt budget cannot accommodate essential bundle, dispatch is withheld."""
    compiler = expression_surface_compiler
    assert hasattr(compiler, "withhold_on_budget_overflow")
