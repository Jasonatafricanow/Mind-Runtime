"""Consumers reject forged Surface identities even with recomputed digests."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from mind_runtime.contracts import ProjectedMindState, RuntimeState, Scope, ScopeDomain, SyncFields
from mind_runtime.contracts.surface import SurfaceProjectionResult, SurfaceProjectionStatus
from mind_runtime.dynamics.persona import surface_digest
from mind_runtime.surface.lineage import validate_projected_surface
from tests.surface.spec_support import sample_candidate


def _thaw(value):
    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_thaw(item) for item in value]
    return value


def _case(surface):
    source = sample_candidate()
    result = surface.project(source)
    scope = Scope(
        domain=ScopeDomain.AGENT,
        agent_id="fixture-persona",
        persona_id="persona-fixture-a",
    )
    now = datetime(2026, 9, 23, tzinfo=UTC)
    states = tuple(
        RuntimeState(
            state_id=wire["state_id"],
            scope=scope,
            origin_runtime_id="fixture-runtime",
            dimension=wire["dimension"],
            value=wire["value"],
            status="active",
            valid_from=now,
            valid_until=None,
            relevant_until=None,
            last_observed_at=now,
            evidence_refs=(),
            transition_refs=(),
            updated_at=now,
            version=wire["version"],
            sync=SyncFields(
                scope,
                "fixture-runtime",
                wire["state_id"],
                wire["version"],
                f"idem-{wire['state_id']}",
            ),
        )
        for wire in source["projected_dynamics"]["states"]
    )
    projected = ProjectedMindState(
        projection_id=source["projected_dynamics"]["source_projection_id"],
        scope=scope,
        origin_runtime_id="fixture-runtime",
        projected_states=states,
        sync=SyncFields(scope, "fixture-runtime", "projection:fixture-1", 1, "idem-proj"),
    )
    return source, result, projected


def _validates(source, result, projected):
    return validate_projected_surface(
        result,
        projected=projected,
        runtime_id="fixture-runtime",
        interaction_or_tick_ref="interaction:fixture-1",
        persona_id=source["persona"]["persona_id"],
        persona_version=source["persona"]["persona_version"],
        persona_content_digest=source["persona"]["persona_content_digest"],
    )


def _forged(result, path, value, *, rehash=False):
    controls = _thaw(result.controls)
    target = controls
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    if rehash:
        semantic = {
            key: item
            for key, item in controls.items()
            if key not in ("controls_id", "evaluation_ref")
        }
        controls["controls_id"] = "surface:" + surface_digest("controls", semantic)
    return SurfaceProjectionResult(
        status=SurfaceProjectionStatus.AVAILABLE, reasons=[], controls=controls
    )


def test_consumer_accepts_exact_projected_source(surface):
    source, result, projected = _case(surface)
    assert _validates(source, result, projected)


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("runtime_id",), "other"),
        (("owner", "owner_runtime_id"), "other"),
        (("scope", "agent_id"), "other"),
        (("interaction_or_tick_ref",), "interaction:other"),
        (("persona_id",), "other"),
        (("persona_version",), 0),
        (("persona_content_digest",), "0" * 64),
        (("source_projection_id",), "projection:other"),
        (("source_phase",), "committed"),
        (("recipe_id",), "surface-reference-v1"),
        (("recipe_version",), 1),
        (("recipe_digest",), "0" * 64),
        (("dependencies_by_control",), {}),
        (("derived_only",), False),
        (("canonical",), True),
        (("values",), {}),
        (("values", "contact_seeking"), True),
        (("values", "contact_seeking"), 1.1),
    ],
)
def test_consumer_rejects_changed_identity_or_control(surface, path, value):
    source, result, projected = _case(surface)
    assert not _validates(source, _forged(result, path, value), projected)


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("source_states",), {}),
        (("source_states", 0, "state_id"), "state-forged"),
        (("source_states", 0, "value_digest"), "0" * 64),
    ],
)
def test_rehashed_source_evidence_still_must_match_canonical_states(surface, path, value):
    source, result, projected = _case(surface)
    forged = _forged(result, path, value, rehash=True)
    assert not _validates(source, forged, projected)


def test_consumer_rejects_missing_canonical_root(surface):
    source, result, projected = _case(surface)
    incomplete = replace(projected, projected_states=projected.projected_states[1:])
    assert not _validates(source, result, incomplete)


def test_consumer_rejects_unavailable_result(surface):
    source, _result, projected = _case(surface)
    unavailable = SurfaceProjectionResult(
        status=SurfaceProjectionStatus.UNAVAILABLE,
        reasons=["SURFACE_MISSING_STATE"],
        controls=None,
    )
    assert not _validates(source, unavailable, projected)
