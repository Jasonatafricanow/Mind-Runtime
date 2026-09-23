"""Test fixtures for Surface Affect W3-B0.

RED binding only. Production seam remains intentionally missing until W3-B/C/D.
"""

from typing import Any

import pytest


def pytest_configure(config: Any) -> None:
    config.addinivalue_line(
        "markers", "reference_only: mark test as historical reference fixture only"
    )


@pytest.fixture
def surface() -> Any:
    class ProductionSurfaceSeam:
        def __getattr__(self, name: str) -> Any:
            msg = (
                "MISSING_W3_PRODUCTION_SEAM: Surface production adapter intentionally "
                f"absent; requested {name}"
            )
            raise RuntimeError(msg)

    return ProductionSurfaceSeam()


@pytest.fixture
def intent_surface_validator() -> Any:
    def _validate(*args: Any, **kwargs: Any) -> Any:
        try:
            from mind_runtime.intents.surface_validator import (  # type: ignore[import-not-found]
                validate_intent_rule_surface_overlap,
            )

            return validate_intent_rule_surface_overlap(*args, **kwargs)
        except ImportError as exc:
            raise RuntimeError(
                f"MISSING_W3_PRODUCTION_SEAM: Intent Surface validator seam missing: {exc}"
            ) from exc

    return _validate


@pytest.fixture
def expression_surface_compiler() -> Any:
    class CompilerSeam:
        def __getattr__(self, name: str) -> Any:
            from mind_runtime.expression.context import DecisionContextCompiler

            if hasattr(DecisionContextCompiler, name):
                return getattr(DecisionContextCompiler, name)
            msg = (
                "MISSING_W3_PRODUCTION_SEAM: DecisionContextCompiler Surface seam "
                f"missing; requested {name}"
            )
            raise RuntimeError(msg)

    return CompilerSeam()


@pytest.fixture
def expression_surface_renderer() -> Any:
    class RendererSeam:
        def __getattr__(self, name: str) -> Any:
            from mind_runtime.expression.renderer import DeterministicContextRenderer

            if hasattr(DeterministicContextRenderer, name):
                return getattr(DeterministicContextRenderer, name)
            msg = (
                "MISSING_W3_PRODUCTION_SEAM: DeterministicContextRenderer Surface seam "
                f"missing; requested {name}"
            )
            raise RuntimeError(msg)

    return RendererSeam()


@pytest.fixture
def turn_tick_surface_port_seam() -> Any:
    class TurnTickPortSeam:
        def verify_port_sharing(self) -> bool:
            from mind_runtime.cognition.tick import CognitiveTicker
            from mind_runtime.pipeline.orchestrator import TurnOrchestrator

            if not hasattr(TurnOrchestrator, "surface_projection_port") or not hasattr(
                CognitiveTicker, "surface_projection_port"
            ):
                msg = (
                    "MISSING_W3_PRODUCTION_SEAM: Single SurfaceProjectionPort wiring "
                    "for TurnOrchestrator and CognitiveTicker missing"
                )
                raise RuntimeError(msg)
            return True

    return TurnTickPortSeam()
