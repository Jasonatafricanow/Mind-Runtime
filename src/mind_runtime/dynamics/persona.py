"""Persona trait/profile models (D7.1).

The frozen rule: Trait != Current State. A persona profile carries trait
parameters only (baseline, initial_value, floor, ceiling, sensitivity,
recovery_rate, coupling); the current value of an affect dimension lives
exclusively in runtime/projected state, never in the profile.
"""

import hashlib
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from mind_runtime.contracts import (
    AffectiveDimensionProfile,
    BehavioralDisposition,
)


def canonical_surface_c14n(value: Any) -> bytes:
    """MR-surface-c14n-1 canonical wire serializer."""

    def wire(x: Any) -> Any:
        if type(x) is float:
            if not math.isfinite(x):
                raise ValueError("nonfinite float in canonical wire")
            return {"$f64": (0.0 if x == 0 else x).hex()}
        if x is None or type(x) in (str, bool, int):
            return x
        if isinstance(x, (list, tuple)):
            return [wire(v) for v in x]
        if isinstance(x, Mapping) and all(type(k) is str for k in x):
            return {k: wire(v) for k, v in x.items()}
        raise TypeError(f"unsupported canonical type: {type(x).__name__}")

    return json.dumps(
        wire(value),
        sort_keys=True,
        ensure_ascii=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("ascii")


def surface_digest(domain: str, value: Any) -> str:
    """Compute sha256 domain-separated digest using MR-surface-c14n-1."""
    return hashlib.sha256(
        domain.encode("ascii") + b"\n" + canonical_surface_c14n(value)
    ).hexdigest()


def compute_persona_content_digest(
    *,
    persona_id: str,
    profile_version: int,
    schema_version: int,
    dimensions: tuple[AffectiveDimensionProfile, ...],
    behavioral_disposition: BehavioralDisposition | Mapping[str, float] | None = None,
) -> str:
    """Compute deterministic canonical digest for a persona revision."""
    dim_list: list[dict[str, Any]] = []
    for d in sorted(dimensions, key=lambda x: x.dimension):
        dim_list.append(
            {
                "baseline": d.baseline,
                "ceiling": d.ceiling,
                "coupling_profile": sorted(
                    [[k, v] for k, v in d.coupling_profile], key=lambda x: x[0]
                ),
                "dimension": d.dimension,
                "floor": d.floor,
                "growth_profile": sorted(
                    [[k, v] for k, v in d.growth_profile], key=lambda x: x[0]
                ),
                "initial_value": d.initial_value,
                "recovery_rate": d.recovery_rate,
                "sensitivity": d.sensitivity,
            }
        )
    content: dict[str, Any] = {
        "dimensions": dim_list,
        "persona_id": persona_id,
        "profile_version": profile_version,
        "schema_version": schema_version,
    }
    if behavioral_disposition is not None:
        content["behavioral_disposition"] = {
            "attachment_approach": float(behavioral_disposition["attachment_approach"]),
            "confrontation_readiness": float(
                behavioral_disposition["confrontation_readiness"]
            ),
            "expressive_restraint": float(
                behavioral_disposition["expressive_restraint"]
            ),
            "expressive_warmth_bias": float(
                behavioral_disposition["expressive_warmth_bias"]
            ),
        }
    return surface_digest("persona", content)


@dataclass(frozen=True)
class PersonaProfile:
    """A named container of trait dimensions and optional disposition (no current values)."""

    persona_id: str
    dimensions: tuple[AffectiveDimensionProfile, ...]
    version: int = 1
    behavioral_disposition: BehavioralDisposition | None = None
    schema_version: int = 1
    effective_content_digest: str | None = None

    def __post_init__(self) -> None:
        if not self.persona_id.strip():
            raise ValueError("persona_id must be non-empty")
        if (
            isinstance(self.version, bool)
            or not isinstance(self.version, int)
            or self.version < 1
        ):
            raise ValueError("version must be at least 1")
        if (
            isinstance(self.schema_version, bool)
            or not isinstance(self.schema_version, int)
            or self.schema_version not in (1, 2)
        ):
            raise ValueError(
                f"unsupported schema_version {self.schema_version!r} (supported: 1, 2)"
            )
        if self.schema_version == 1:
            if self.behavioral_disposition is not None:
                raise ValueError("schema 1 persona profile cannot have behavioral_disposition")
        elif self.schema_version == 2:
            if self.behavioral_disposition is None:
                raise ValueError("schema 2 persona profile requires behavioral_disposition")
            if not isinstance(self.behavioral_disposition, BehavioralDisposition):
                raise ValueError("behavioral_disposition must be a BehavioralDisposition instance")

        seen: set[str] = set()
        for profile in self.dimensions:
            if profile.dimension in seen:
                raise ValueError(f"duplicate dimension {profile.dimension!r} in persona")
            seen.add(profile.dimension)

        computed = compute_persona_content_digest(
            persona_id=self.persona_id,
            profile_version=self.version,
            schema_version=self.schema_version,
            dimensions=self.dimensions,
            behavioral_disposition=self.behavioral_disposition,
        )
        if (
            self.effective_content_digest is not None
            and self.effective_content_digest != computed
        ):
            raise ValueError(
                f"effective_content_digest mismatch for persona {self.persona_id!r}: "
                f"expected {computed}, got {self.effective_content_digest}"
            )
        if self.effective_content_digest is None:
            object.__setattr__(self, "effective_content_digest", computed)

    def for_dimension(self, dimension: str) -> AffectiveDimensionProfile | None:
        for profile in self.dimensions:
            if profile.dimension == dimension:
                return profile
        return None

    def require_dimension(self, dimension: str) -> AffectiveDimensionProfile:
        profile = self.for_dimension(dimension)
        if profile is None:
            raise ValueError(f"persona {self.persona_id!r} has no dimension {dimension!r}")
        return profile

    def dimension_keys(self) -> tuple[str, ...]:
        return tuple(profile.dimension for profile in self.dimensions)

    @property
    def persona_content_digest(self) -> str:
        return self.effective_content_digest or ""

    @property
    def profile_version(self) -> int:
        return self.version

    @property
    def is_surface_eligible(self) -> bool:
        return (
            self.schema_version == 2
            and self.behavioral_disposition is not None
            and isinstance(self.behavioral_disposition, BehavioralDisposition)
            and bool(self.effective_content_digest)
        )
