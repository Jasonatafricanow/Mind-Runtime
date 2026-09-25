"""Production persona profile loader (C4.5).

Loads versioned, typed persona JSON (configs/personas/*.json) into the
generic PersonaProfile contract with fail-closed validation:

    not found / invalid JSON / wrong shape / unknown version /
    duplicate or unknown-form dimensions / invalid bounds / invalid
    coupling or growth targets  →  PersonaProfileError

The kernel stays dimension-agnostic: the loader enforces nothing about
dimension COUNT and no Kayla-specific names — it validates generic shape.
Identity fields (persona_id, profile_version, migration_source) travel
into trace via PersonaProfile.persona_id/version; calibration metadata is
payload-only, never injected into kernel contracts.

Synthetic test fixtures (kayla_v0 etc.) can NEVER silently become the
production default: production code must load an explicit profile file;
there is no import-from-test path here.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

from mind_runtime.contracts import (
    DISPOSITION_TRAIT_NAMES,
    AffectiveDimensionProfile,
    BehavioralDisposition,
    Scope,
    ScopeDomain,
)
from mind_runtime.dynamics.persona import PersonaProfile

SUPPORTED_PROFILE_VERSION = 1
SUPPORTED_SCHEMA_VERSIONS = (1, 2)

_KNOWN_SCOPE_PREFIXES = tuple(f"{domain.value}." for domain in ScopeDomain)


class PersonaRegistry:
    """Authority tracking registered persona versions and digests.

    Ensures that for any (persona_id, profile_version), the effective content digest
    is unique. If the same persona_id and profile_version is registered with a different
    content digest, a PersonaProfileError is raised (fail-closed conflict rejection).
    """

    def __init__(self) -> None:
        self._entries: dict[tuple[str, int], str] = {}

    def register(
        self,
        persona_id: str,
        profile_version: int,
        effective_content_digest: str,
    ) -> None:
        key = (persona_id, profile_version)
        existing = self._entries.get(key)
        if existing is not None and existing != effective_content_digest:
            raise PersonaProfileError(
                f"persona content conflict for persona_id={persona_id!r}, "
                f"revision={profile_version}: "
                f"existing digest {existing} != incoming digest {effective_content_digest}"
            )
        self._entries[key] = effective_content_digest

    def register_profile(self, profile: PersonaProfile) -> None:
        if profile.effective_content_digest is None:
            raise PersonaProfileError(
                f"persona {profile.persona_id!r} has no effective_content_digest"
            )
        self.register(profile.persona_id, profile.version, profile.effective_content_digest)

    def get_digest(self, persona_id: str, profile_version: int) -> str | None:
        return self._entries.get((persona_id, profile_version))

    def clear(self) -> None:
        self._entries.clear()


_GLOBAL_PERSONA_REGISTRY = PersonaRegistry()


def get_global_persona_registry() -> PersonaRegistry:
    return _GLOBAL_PERSONA_REGISTRY


def clear_persona_registry() -> None:
    _GLOBAL_PERSONA_REGISTRY.clear()


@dataclass(frozen=True)
class LoadedPersona:
    """A validated production persona plus its identity envelope."""

    profile: PersonaProfile
    persona_id: str
    profile_version: int
    migration_source: dict[str, str]
    source_path: str
    schema_version: int = 1
    effective_content_digest: str = ""

    @property
    def behavioral_disposition(self) -> BehavioralDisposition | None:
        return self.profile.behavioral_disposition

    @property
    def persona_content_digest(self) -> str:
        return self.effective_content_digest

    @property
    def is_surface_eligible(self) -> bool:
        return self.profile.is_surface_eligible


class PersonaProfileError(RuntimeError):
    """Fail-closed persona profile validation failure."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise PersonaProfileError(message)


def load_persona_profile(
    path: str | Path,
    *,
    registry: PersonaRegistry | None = _GLOBAL_PERSONA_REGISTRY,
) -> LoadedPersona:
    """Load + validate one persona profile file. Raises, never coerces."""
    file = Path(path)
    if not file.is_file():
        raise PersonaProfileError(f"persona profile not found: {file}")

    try:
        raw = json.loads(file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PersonaProfileError(f"unreadable persona profile {file}: {exc}") from exc

    _require(isinstance(raw, dict), f"{file}: top level must be a JSON object")

    # Schema version separation: absent means legacy schema 1
    if "schema_version" not in raw:
        schema_version = 1
    else:
        raw_schema = raw["schema_version"]
        _require(
            isinstance(raw_schema, int)
            and not isinstance(raw_schema, bool)
            and raw_schema in SUPPORTED_SCHEMA_VERSIONS,
            f"{file}: unsupported schema_version {raw_schema!r} "
            f"(supported: {SUPPORTED_SCHEMA_VERSIONS})",
        )
        schema_version = int(raw_schema)

    # Content revision: must be positive integer
    profile_version_raw = raw.get("profile_version")
    _require(
        isinstance(profile_version_raw, int)
        and not isinstance(profile_version_raw, bool)
        and profile_version_raw >= 1,
        f"{file}: profile_version must be a positive integer, got {profile_version_raw!r}",
    )
    profile_version = int(profile_version_raw)

    persona_id = raw.get("persona_id")
    _require(isinstance(persona_id, str) and bool(persona_id.strip()), "persona_id required")

    # Validate behavioral_disposition by schema_version
    disposition_obj: BehavioralDisposition | None = None
    if schema_version == 1:
        _require(
            "behavioral_disposition" not in raw or raw["behavioral_disposition"] is None,
            f"{file}: schema 1 does not support behavioral_disposition",
        )
    elif schema_version == 2:
        _require(
            "behavioral_disposition" in raw and raw["behavioral_disposition"] is not None,
            f"{file}: schema_version 2 requires behavioral_disposition",
        )
        disp_raw = raw["behavioral_disposition"]
        _require(
            isinstance(disp_raw, dict),
            f"{file}: behavioral_disposition must be a JSON object",
        )
        unknown_keys = set(disp_raw.keys()) - set(DISPOSITION_TRAIT_NAMES)
        _require(
            not unknown_keys,
            f"{file}: unknown behavioral_disposition keys: {sorted(unknown_keys)}",
        )
        missing_keys = set(DISPOSITION_TRAIT_NAMES) - set(disp_raw.keys())
        _require(
            not missing_keys,
            f"{file}: behavioral_disposition missing required traits: {sorted(missing_keys)}",
        )
        parsed_traits: dict[str, float] = {}
        for trait_name in DISPOSITION_TRAIT_NAMES:
            trait_val = disp_raw[trait_name]
            _require(
                trait_val is not None,
                f"{file}: behavioral_disposition.{trait_name} must not be null",
            )
            _require(
                not isinstance(trait_val, bool),
                f"{file}: behavioral_disposition.{trait_name} must not be boolean",
            )
            _require(
                isinstance(trait_val, (int, float)),
                f"{file}: behavioral_disposition.{trait_name} must be a number",
            )
            fval = float(trait_val)
            _require(
                math.isfinite(fval),
                f"{file}: behavioral_disposition.{trait_name} must be finite",
            )
            _require(
                0.0 <= fval <= 1.0,
                f"{file}: behavioral_disposition.{trait_name} out of [0.0, 1.0], got {fval}",
            )
            parsed_traits[trait_name] = fval

        disposition_obj = BehavioralDisposition(
            attachment_approach=parsed_traits["attachment_approach"],
            confrontation_readiness=parsed_traits["confrontation_readiness"],
            expressive_restraint=parsed_traits["expressive_restraint"],
            expressive_warmth_bias=parsed_traits["expressive_warmth_bias"],
        )

    dimensions_raw = raw.get("dimensions")
    _require(isinstance(dimensions_raw, list) and bool(dimensions_raw), "dimensions required")
    _require(len(dimensions_raw) != 12 or True, "")  # count is free: no fixed-12 rule

    seen: set[str] = set()
    for index, entry in enumerate(dimensions_raw):
        _require(isinstance(entry, dict), f"dimensions[{index}] must be an object")
        dimension = entry.get("dimension")
        _require(
            isinstance(dimension, str) and bool(dimension.strip()),
            f"dimensions[{index}].dimension required",
        )
        _require(dimension not in seen, f"duplicate dimension {dimension!r}")
        seen.add(str(dimension))

    # second pass now that the full dimension name set is known, so
    # coupling/growth targets may legally be forward references
    profiles: list[AffectiveDimensionProfile] = []
    for index, entry in enumerate(dimensions_raw):
        entry_dict = dict(entry)  # already shape-checked above
        dimension = str(entry_dict["dimension"])
        _require(
            dimension.startswith(_KNOWN_SCOPE_PREFIXES),
            f"dimensions[{index}].dimension {dimension!r} lacks a scope-domain prefix",
        )

        numeric_fields = (
            "baseline",
            "initial_value",
            "sensitivity",
            "recovery_rate",
            "ceiling",
            "floor",
        )
        values: dict[str, float] = {}
        for field_name in numeric_fields:
            value = entry_dict.get(field_name)
            numeric = (
                float(value)
                if isinstance(value, int | float) and not isinstance(value, bool)
                else None
            )
            if numeric is None:
                raise PersonaProfileError(f"{dimension}.{field_name} must be a number")
            values[field_name] = numeric
        _require(0.0 <= values["sensitivity"] <= 2.0, f"{dimension}.sensitivity out of [0,2]")
        _require(values["recovery_rate"] >= 0.0, f"{dimension}.recovery_rate must be non-negative")
        _require(values["floor"] < values["ceiling"], f"{dimension}: floor must be below ceiling")
        for bounded in ("baseline", "initial_value"):
            _require(
                values["floor"] <= values[bounded] <= values["ceiling"],
                f"{dimension}.{bounded} outside floor..ceiling",
            )

        coupling_profile = _validate_reference_pairs(
            entry_dict.get("coupling_profile", []), "coupling_profile", dimension, seen
        )
        growth_profile = _validate_reference_pairs(
            entry_dict.get("growth_profile", []), "growth_profile", dimension, seen
        )

        profiles.append(
            AffectiveDimensionProfile(
                dimension=dimension,
                baseline=values["baseline"],
                initial_value=values["initial_value"],
                sensitivity=values["sensitivity"],
                recovery_rate=values["recovery_rate"],
                ceiling=values["ceiling"],
                floor=values["floor"],
                growth_profile=growth_profile,
                coupling_profile=coupling_profile,
            )
        )

    migration_raw = raw.get("migration_source", {})
    _require(isinstance(migration_raw, dict), "migration_source must be an object when present")
    migration_source = {
        str(k): str(v)
        for k, v in migration_raw.items()
        if k in {"system", "dimensions_ref", "audit_doc"}
    }

    try:
        profile = PersonaProfile(
            persona_id=str(persona_id),
            dimensions=tuple(profiles),
            version=profile_version,
            behavioral_disposition=disposition_obj,
            schema_version=schema_version,
        )
    except ValueError as exc:
        raise PersonaProfileError(str(exc)) from exc

    effective_content_digest = profile.effective_content_digest or ""

    if registry is not None:
        registry.register(str(persona_id), profile_version, effective_content_digest)

    return LoadedPersona(
        profile=profile,
        persona_id=str(persona_id),
        profile_version=profile_version,
        migration_source=migration_source,
        source_path=str(file),
        schema_version=schema_version,
        effective_content_digest=effective_content_digest,
    )


def _validate_reference_pairs(
    raw: object, field_label: str, dimension: str, known: set[str]
) -> tuple[tuple[str, float], ...]:
    """Validate a (target-dimension, strength) pair list against the file."""
    if raw is None:
        return ()
    pairs_raw = raw if isinstance(raw, list) else None
    if pairs_raw is None:
        raise PersonaProfileError(f"{dimension}.{field_label} must be a list")
    pairs: list[tuple[str, float]] = []
    for pair in pairs_raw:
        _require(
            isinstance(pair, list) and len(pair) == 2,
            f"{dimension}.{field_label} entries must be [target, strength]",
        )
        target = pair[0]
        strength = pair[1]
        _require(isinstance(target, str), f"{dimension}.{field_label} target must be a string")
        _require(
            target in known, f"{dimension}.{field_label} references unknown dimension {target!r}"
        )
        strength_num = (
            strength
            if isinstance(strength, int | float) and not isinstance(strength, bool)
            else None
        )
        if strength_num is None:
            raise PersonaProfileError(f"{dimension}.{field_label} strength must be a number")
        numeric_strength = float(strength_num)
        _require(
            -1.0 <= numeric_strength <= 1.0, f"{dimension}.{field_label} strength out of [-1,1]"
        )
        _require(target != dimension, f"{dimension}.{field_label} must not self-reference")
        pairs.append((target, numeric_strength))
    return tuple(pairs)


def default_production_persona_path() -> Path:
    """Repo-relative production Kayla profile location."""
    return Path(__file__).resolve().parents[2] / "configs" / "personas" / "kayla.json"


def load_kayla_production() -> LoadedPersona:
    """Explicit, typed loader for the production Kayla persona."""
    return load_persona_profile(default_production_persona_path())


def scope_for_persona(profile: PersonaProfile) -> Scope:
    """Agent-scoped affect projection scope for a persona (D7.7 convention)."""
    return Scope(
        domain=ScopeDomain.AGENT, agent_id=profile.persona_id, persona_id=profile.persona_id
    )
