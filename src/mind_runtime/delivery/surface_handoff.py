"""Read-only recovery of the C7 admitted SURFACE_V1 provider envelope."""

from __future__ import annotations

from mind_runtime.contracts import Scope
from mind_runtime.delivery import DeliveryRequest
from mind_runtime.delivery.persistence import DeliveryBackend
from mind_runtime.expression.expression_map import (
    CANDIDATE_MAP_DIGEST,
    CANDIDATE_MAP_ID,
    CANDIDATE_MAP_VERSION,
)
from mind_runtime.expression.renderer import DeterministicContextRenderer
from mind_runtime.surface.recipe import (
    CANDIDATE_RECIPE_DIGEST,
    CANDIDATE_RECIPE_ID,
    CANDIDATE_RECIPE_VERSION,
)


def _admitted_sections(text: str) -> dict[str, list[tuple[str, str]]]:
    """Read the renderer wire shape without reinterpreting any cognition."""
    sections: dict[str, list[tuple[str, str]]] = {}
    section: str | None = None
    for line in text.splitlines():
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1]
            sections.setdefault(section, [])
            continue
        if section is None or not line.startswith("- ") or ": " not in line:
            raise ValueError("SURFACE_HANDOFF_ENVELOPE_MALFORMED")
        key, value = line[2:].split(": ", 1)
        sections[section].append((key, value))
    return sections


def recover_admitted_surface_handoff(
    backend: DeliveryBackend, request_id: str, *,
    origin_runtime_id: str, scope: Scope,
) -> DeliveryRequest:
    """Recover immutable consumer-use evidence without rerunning cognition."""
    row = backend.get_durable_request(request_id)
    if row is None or row.request.surface_handoff is None:
        raise ValueError("SURFACE_HANDOFF_REPLAY_UNAVAILABLE")
    request = row.request
    if request.origin_runtime_id != origin_runtime_id or request.scope != scope:
        raise ValueError("SURFACE_HANDOFF_BINDING_MISMATCH")
    evidence = request.surface_handoff
    if evidence is None:
        raise ValueError("SURFACE_HANDOFF_REPLAY_UNAVAILABLE")
    if (
        evidence.recipe_ref != (
            f"{CANDIDATE_RECIPE_ID}:{CANDIDATE_RECIPE_VERSION}:"
            f"{CANDIDATE_RECIPE_DIGEST}"
        )
        or evidence.expression_map_ref != (
            f"{CANDIDATE_MAP_ID}:{CANDIDATE_MAP_VERSION}:{CANDIDATE_MAP_DIGEST}"
        )
    ):
        raise ValueError("SURFACE_HANDOFF_CANDIDATE_IDENTITY_MISMATCH")
    text = request.payload_bytes.decode("utf-8", errors="strict")
    DeterministicContextRenderer.verify_provider_information_isolation(text)
    sections = _admitted_sections(text)
    if sections.get("ACTION") != [("selected_action", evidence.action_type)]:
        raise ValueError("SURFACE_HANDOFF_ACTION_MISSING")
    if sorted(sections.get("POLICY_CONSTRAINT", [])) != sorted(
        (constraint, constraint) for constraint in evidence.policy_constraints
    ):
        raise ValueError("SURFACE_HANDOFF_POLICY_CONSTRAINT_MISSING")
    if sorted(sections.get("SURFACE_GUIDANCE", [])) != list(evidence.qualitative_guidance):
        raise ValueError("SURFACE_HANDOFF_ENVELOPE_CONFLICT")
    if "INTERNAL_STATE" in sections or "SURFACE_CONTROL" in sections:
        raise ValueError("SURFACE_HANDOFF_ENVELOPE_CONFLICT")
    return request
