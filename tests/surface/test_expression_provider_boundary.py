"""W3-D Expression, Renderer, Host, and Provider Boundary Tests.

RED BY DESIGN: Production Expression Surface compiler/renderer seams are absent in W3-B0.
These assertions freeze the W3-D contract requirements:
- SURFACE_V1 disables raw affect bands, duplicate style, and Host Slow numeric summary
- Qualitative guidance bundle is visible at actual provider bytes
- Provider text must not contain raw Surface floats, traits, dynamics values, or digests
- Essential bundle budget failure: if budget cannot fit the bundle, dispatch is withheld
"""

import pytest


def test_surface_v1_disables_raw_affect_bands_and_slow_numeric_summary():
    """W3-D: In SURFACE_V1 mode, compiler omits raw affect bands and Slow numeric summaries."""
    try:
        from mind_runtime.expression.context import DecisionContextCompiler
    except ImportError as e:
        pytest.fail(f"RED BY DESIGN: DecisionContextCompiler production seam missing: {e}")

    if not hasattr(DecisionContextCompiler, "compile_surface_v1") and not hasattr(
        DecisionContextCompiler, "admit_surface_controls"
    ):
        pytest.fail(
            "RED BY DESIGN: DecisionContextCompiler missing SURFACE_V1 admission seam"
        )
    pytest.fail("RED BY DESIGN: SURFACE_V1 compiler admission seam missing")


def test_surface_qualitative_bundle_visible_at_actual_provider_bytes():
    """W3-D: Qualitative guidance (directness/warmth/restraint) must reach provider payload."""
    try:
        from mind_runtime.expression.renderer import DeterministicContextRenderer
    except ImportError as e:
        pytest.fail(f"RED BY DESIGN: DeterministicContextRenderer production seam missing: {e}")

    if not hasattr(DeterministicContextRenderer, "render_surface_bundle") and not hasattr(
        DeterministicContextRenderer, "format_surface_guidance"
    ):
        pytest.fail(
            "RED BY DESIGN: DeterministicContextRenderer missing surface bundle rendering seam"
        )
    pytest.fail("RED BY DESIGN: Surface qualitative bundle renderer seam missing")


def test_provider_context_contains_no_raw_numbers_or_digests():
    """W3-D: Provider context contains zero raw floats, raw traits, raw dynamics, or digests."""
    try:
        from mind_runtime.expression.renderer import DeterministicContextRenderer
    except ImportError as e:
        pytest.fail(f"RED BY DESIGN: DeterministicContextRenderer production seam missing: {e}")

    if not hasattr(DeterministicContextRenderer, "verify_provider_information_isolation"):
        pytest.fail(
            "RED BY DESIGN: DeterministicContextRenderer missing information isolation seam"
        )
    pytest.fail("RED BY DESIGN: Provider information isolation inspection seam missing")


def test_essential_bundle_overflow_withholds_provider_dispatch():
    """W3-D: If prompt budget cannot accommodate essential bundle, dispatch is withheld."""
    try:
        from mind_runtime.expression.context import DecisionContextCompiler
    except ImportError as e:
        pytest.fail(f"RED BY DESIGN: DecisionContextCompiler production seam missing: {e}")

    if not hasattr(DecisionContextCompiler, "withhold_on_budget_overflow"):
        pytest.fail(
            "RED BY DESIGN: DecisionContextCompiler missing bundle overflow withholding seam"
        )
    pytest.fail("RED BY DESIGN: Essential bundle budget withholding seam missing")
