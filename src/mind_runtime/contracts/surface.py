"""Mind Runtime Surface typed contracts and reason codes.

Frozen under ADR-0028 and Candidate Recipe v2.
Surface is pure derived projection, non-canonical, and never persisted.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Protocol, runtime_checkable


class SurfaceProjectionStatus(StrEnum):
    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"


class SurfaceControl(StrEnum):
    CONTACT_SEEKING = "contact_seeking"
    INITIATIVE = "initiative"
    CONFRONTATION = "confrontation"
    EXPRESSIVE_WARMTH = "expressive_warmth"
    EXPRESSIVE_RESTRAINT = "expressive_restraint"


ENABLED_CONTROLS = (
    "confrontation",
    "contact_seeking",
    "expressive_restraint",
    "expressive_warmth",
    "initiative",
)
DEFERRED_CONTROLS = ("reassurance_seeking", "withdrawal")

# Fail-Closed Reason Codes
SURFACE_MISSING_STATE = "SURFACE_MISSING_STATE"
SURFACE_NUMERIC_TYPE = "SURFACE_NUMERIC_TYPE"
SURFACE_NONFINITE = "SURFACE_NONFINITE"
SURFACE_RANGE = "SURFACE_RANGE"
SURFACE_RECIPE_CONTENT_CONFLICT = "SURFACE_RECIPE_CONTENT_CONFLICT"
SURFACE_PERSONA_CONTENT_MISMATCH = "SURFACE_PERSONA_CONTENT_MISMATCH"
SURFACE_INELIGIBLE_PERSONA = "SURFACE_INELIGIBLE_PERSONA"
SURFACE_SCHEMA_MISMATCH = "SURFACE_SCHEMA_MISMATCH"
SURFACE_RECIPE_UNSUPPORTED = "SURFACE_RECIPE_UNSUPPORTED"


class SurfaceProjectionResult(dict[str, Any]):
    """Derived, non-canonical, immutable projection result.

    Subclasses dict for transparent JSON/wire/mapping compatibility.
    """

    def __init__(
        self,
        *,
        status: SurfaceProjectionStatus | str,
        reasons: list[str] | tuple[str, ...],
        controls: dict[str, Any] | None = None,
    ) -> None:
        stat_val = status.value if hasattr(status, "value") else str(status)
        super().__init__(
            status=stat_val,
            reasons=list(reasons),
            controls=controls,
        )

    @property
    def status(self) -> str:
        return self["status"]

    @property
    def reasons(self) -> list[str]:
        return self["reasons"]

    @property
    def controls(self) -> dict[str, Any] | None:
        return self.get("controls")


@runtime_checkable
class SurfaceProjectionPort(Protocol):
    """Port for single deterministic surface projection."""

    def project(self, supplied: Any) -> SurfaceProjectionResult:
        """Project current dynamics snapshot + persona disposition into surface controls."""
        ...
