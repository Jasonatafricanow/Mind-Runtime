"""Compatibility adapter for the single derived Surface projection authority."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from mind_runtime.contracts.surface import SurfaceProjectionResult
from mind_runtime.surface.projector import DeterministicSurfaceProjector


class SurfaceProductionAdapter:
    """Expose the one deterministic projector through the Surface port."""

    def __init__(self, projector: DeterministicSurfaceProjector | None = None) -> None:
        self._projector = projector or DeterministicSurfaceProjector()

    def project(self, supplied: Mapping[str, Any]) -> SurfaceProjectionResult:
        return self._projector.project(supplied)
