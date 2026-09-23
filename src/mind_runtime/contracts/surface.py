"""Mind Runtime Surface typed contracts and reason codes.

Frozen under ADR-0028 and Candidate Recipe v2.
Surface is pure derived projection, non-canonical, and never persisted.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
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


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(k): _freeze(v) for k, v in value.items()})
    if isinstance(value, (list, tuple)):
        return _FrozenSequence(_freeze(v) for v in value)
    return value


class _FrozenSequence(tuple):
    """Immutable wire sequence retaining JSON-list comparison semantics."""

    def __eq__(self, other: object) -> bool:
        if isinstance(other, (list, tuple)):
            return tuple(self) == tuple(other)
        return NotImplemented

    def __ne__(self, other: object) -> bool:
        equal = self.__eq__(other)
        return NotImplemented if equal is NotImplemented else not equal

    __hash__ = tuple.__hash__


@dataclass(frozen=True, slots=True)
class SurfaceProjectionResult(Mapping[str, Any]):
    """Deeply immutable derived view with read-only mapping compatibility."""

    status: str
    reasons: tuple[str, ...]
    controls: Mapping[str, Any] | None = None
    _wire: Mapping[str, Any] = field(init=False, repr=False, compare=False)

    def __init__(
        self, *, status: SurfaceProjectionStatus | str,
        reasons: list[str] | tuple[str, ...],
        controls: Mapping[str, Any] | None = None,
    ) -> None:
        stat_val = status.value if isinstance(status, SurfaceProjectionStatus) else str(status)
        frozen_controls = None if controls is None else _freeze(controls)
        immutable_reasons = tuple(reasons)
        object.__setattr__(self, "status", stat_val)
        object.__setattr__(self, "reasons", immutable_reasons)
        object.__setattr__(self, "controls", frozen_controls)
        object.__setattr__(
            self, "_wire", MappingProxyType({
                "status": stat_val, "reasons": immutable_reasons,
                "controls": frozen_controls,
            }),
        )

    def __getitem__(self, key: str) -> Any:
        return self._wire[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._wire)

    def __len__(self) -> int:
        return len(self._wire)

    @property
    def is_available(self) -> bool:
        """Typed admission predicate for consumers outside the Surface layer."""
        return self.status == SurfaceProjectionStatus.AVAILABLE and self.controls is not None

    def __deepcopy__(self, memo: dict[int, Any]) -> SurfaceProjectionResult:
        return self


@runtime_checkable
class SurfaceProjectionPort(Protocol):
    """Port for single deterministic surface projection."""

    def project(self, supplied: Any) -> SurfaceProjectionResult:
        """Project current dynamics snapshot + persona disposition into surface controls."""
        ...
