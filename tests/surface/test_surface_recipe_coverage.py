"""Tests for candidate recipe validation and surface cognition edge cases."""

from copy import deepcopy
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from mind_runtime.contracts import (
    ProjectedMindState,
    RuntimeState,
    Scope,
    ScopeDomain,
    SyncFields,
)
from mind_runtime.contracts.surface import SurfaceProjectionResult, SurfaceProjectionStatus
from mind_runtime.persona_publication import (
    PersonaConfigPublicationRepository,
    PersonaRevisionRef,
    ReplayUnavailable,
)
from mind_runtime.surface.cognition import (
    project_surface_for_cognition,
    recompute_committed_surface,
)
from mind_runtime.surface.lineage import validate_projected_surface
from mind_runtime.surface.recipe import (
    candidate_recipe,
    validate_candidate_recipe,
)

NOW = datetime(2026, 9, 26, 12, 0, tzinfo=UTC)
DIGEST_64 = "a" * 64


def _make_state(
    scope: Scope, dimension: str, value: float = 0.5, runtime_id: str = "rt-1"
) -> RuntimeState:
    state_id = f"{dimension}:1"
    return RuntimeState(
        state_id=state_id,
        scope=scope,
        dimension=dimension,
        value=value,
        status="active",
        valid_from=NOW,
        valid_until=None,
        relevant_until=None,
        last_observed_at=NOW,
        evidence_refs=(),
        transition_refs=(),
        updated_at=NOW,
        origin_runtime_id=runtime_id,
        version=1,
        sync=SyncFields(scope, runtime_id, state_id, 1, f"idem-{state_id}"),
    )


def test_validate_candidate_recipe_valid() -> None:
    recipe = candidate_recipe()
    valid, err = validate_candidate_recipe(recipe)
    assert valid is True
    assert err is None


def test_validate_candidate_recipe_wrong_id_or_version() -> None:
    recipe = candidate_recipe()
    r1 = deepcopy(recipe)
    r1["recipe_id"] = "wrong-id"
    valid, err = validate_candidate_recipe(r1)
    assert valid is False
    assert err == "SURFACE_RECIPE_UNSUPPORTED"

    r2 = deepcopy(recipe)
    r2["recipe_version"] = 999
    valid, err = validate_candidate_recipe(r2)
    assert valid is False
    assert err == "SURFACE_RECIPE_UNSUPPORTED"


def test_validate_candidate_recipe_mismatched_digest_and_rules() -> None:
    recipe = candidate_recipe()

    # Rule count mismatch
    r1 = deepcopy(recipe)
    r1["rules"] = r1["rules"][:-1]
    valid, err = validate_candidate_recipe(r1)
    assert valid is False
    assert err == "SURFACE_RECIPE_CONTENT_CONFLICT"

    # Unknown control_id in rules
    r2 = deepcopy(recipe)
    r2["rules"][0]["control_id"] = "unknown_control"
    valid, err = validate_candidate_recipe(r2)
    assert valid is False
    assert err == "SURFACE_RECIPE_CONTENT_CONFLICT"

    # Invalid AST primitive in formula
    r3 = deepcopy(recipe)
    r3["rules"][0]["formula"] = ["INVALID_OP", 1, 2]
    valid, err = validate_candidate_recipe(r3)
    assert valid is False
    assert err == "SURFACE_RECIPE_CONTENT_CONFLICT"

    # Mismatched AST lookups
    r4 = deepcopy(recipe)
    r4["rules"][0]["formula"] = ["LOOKUP", "unrelated.key"]
    valid, err = validate_candidate_recipe(r4)
    assert valid is False
    assert err == "SURFACE_RECIPE_CONTENT_CONFLICT"


def test_validate_projected_surface_edges() -> None:
    scope = Scope(domain=ScopeDomain.AGENT, agent_id="kayla", persona_id="kayla")
    state = _make_state(scope, "agent.affect.valence")
    projected = ProjectedMindState(
        projection_id="proj-1",
        scope=scope,
        origin_runtime_id="rt-1",
        projected_states=(state,),
        sync=SyncFields(scope, "rt-1", "proj-1", 1, "idem-proj-1"),
    )
    bad_surface = SurfaceProjectionResult(
        status=SurfaceProjectionStatus.AVAILABLE,
        reasons=(),
    )
    object.__setattr__(bad_surface, "controls", "not_a_mapping")
    assert (
        validate_projected_surface(
            bad_surface,
            projected=projected,
            runtime_id="rt-1",
            interaction_or_tick_ref="int-1",
            persona_id="kayla",
            persona_version=1,
            persona_content_digest=DIGEST_64,
        )
        is False
    )


def test_project_surface_for_cognition_eligibility() -> None:
    scope = Scope(domain=ScopeDomain.AGENT, agent_id="kayla", persona_id="kayla")
    state = _make_state(scope, "agent.affect.valence")
    projected = ProjectedMindState(
        projection_id="proj-1",
        scope=scope,
        origin_runtime_id="rt-1",
        projected_states=(state,),
        sync=SyncFields(scope, "rt-1", "proj-1", 1, "idem-proj-1"),
    )
    # Port is None
    assert (
        project_surface_for_cognition(
            surface_port=None,
            persona=MagicMock(is_surface_eligible=True),
            projected=projected,
            runtime_id="rt-1",
            scope=scope,
            interaction_or_tick_ref="int-1",
        )
        is None
    )

    # Persona is None
    assert (
        project_surface_for_cognition(
            surface_port=MagicMock(),
            persona=None,
            projected=projected,
            runtime_id="rt-1",
            scope=scope,
            interaction_or_tick_ref="int-1",
        )
        is None
    )

    # Persona not eligible
    ineligible_persona = MagicMock(is_surface_eligible=False)
    assert (
        project_surface_for_cognition(
            surface_port=MagicMock(),
            persona=ineligible_persona,
            projected=projected,
            runtime_id="rt-1",
            scope=scope,
            interaction_or_tick_ref="int-1",
        )
        is None
    )


def test_reconstruct_committed_surface_for_replay_type_checks() -> None:
    from mind_runtime.state.persistence import SqliteCommitMarkerStore, SqliteStateBackend

    scope = Scope(domain=ScopeDomain.AGENT, agent_id="kayla", persona_id="kayla")
    rev = PersonaRevisionRef(
        persona_id="kayla",
        profile_version=1,
        effective_content_digest=DIGEST_64,
    )

    # Wrong persona_publication type
    with pytest.raises(TypeError, match="persona_publication"):
        recompute_committed_surface(
            persona_publication="invalid",  # type: ignore[arg-type]
            persona_revision_ref=rev,
            state_backend=MagicMock(spec=SqliteStateBackend),
            commit_markers=MagicMock(spec=SqliteCommitMarkerStore),
            surface_port=MagicMock(),
            runtime_id="rt-1",
            interaction_id="int-1",
            interaction_scope=scope,
        )

    # Wrong persona_revision_ref type
    repo = MagicMock(spec=PersonaConfigPublicationRepository)
    with pytest.raises(TypeError, match="persona_revision_ref"):
        recompute_committed_surface(
            persona_publication=repo,
            persona_revision_ref="invalid",  # type: ignore[arg-type]
            state_backend=MagicMock(spec=SqliteStateBackend),
            commit_markers=MagicMock(spec=SqliteCommitMarkerStore),
            surface_port=MagicMock(),
            runtime_id="rt-1",
            interaction_id="int-1",
            interaction_scope=scope,
        )

    # Wrong backend types
    with pytest.raises(TypeError, match="canonical SQLite"):
        recompute_committed_surface(
            persona_publication=repo,
            persona_revision_ref=rev,
            state_backend="invalid",  # type: ignore[arg-type]
            commit_markers=MagicMock(spec=SqliteCommitMarkerStore),
            surface_port=MagicMock(),
            runtime_id="rt-1",
            interaction_id="int-1",
            interaction_scope=scope,
        )


def test_reconstruct_committed_surface_for_replay_missing_markers_and_roots() -> None:
    from mind_runtime.state.persistence import SqliteCommitMarkerStore, SqliteStateBackend

    scope = Scope(domain=ScopeDomain.AGENT, agent_id="kayla", persona_id="kayla")
    repo = MagicMock(spec=PersonaConfigPublicationRepository)
    rev = PersonaRevisionRef(
        persona_id="kayla",
        profile_version=1,
        effective_content_digest=DIGEST_64,
    )
    backend = MagicMock(spec=SqliteStateBackend)
    markers = MagicMock(spec=SqliteCommitMarkerStore)

    # Malformed markers raises ReplayUnavailable
    markers.committed_state_ids.side_effect = ValueError("malformed")
    with pytest.raises(ReplayUnavailable, match="malformed"):
        recompute_committed_surface(
            persona_publication=repo,
            persona_revision_ref=rev,
            state_backend=backend,
            commit_markers=markers,
            surface_port=MagicMock(),
            runtime_id="rt-1",
            interaction_id="int-1",
            interaction_scope=scope,
        )

    # Missing markers (None) raises ReplayUnavailable
    markers.committed_state_ids.side_effect = None
    markers.committed_state_ids.return_value = None
    with pytest.raises(ReplayUnavailable, match="missing"):
        recompute_committed_surface(
            persona_publication=repo,
            persona_revision_ref=rev,
            state_backend=backend,
            commit_markers=markers,
            surface_port=MagicMock(),
            runtime_id="rt-1",
            interaction_id="int-1",
            interaction_scope=scope,
        )

    # Incomplete dynamics roots
    persona = MagicMock(persona_id="kayla")
    repo.resolve.return_value = MagicMock(profile=persona)
    markers.committed_state_ids.return_value = ("agent.affect.valence:1",)
    state = _make_state(scope, "agent.affect.valence")
    backend.load_states.return_value = (state,)
    with pytest.raises(ReplayUnavailable, match="Dynamics roots incomplete"):
        recompute_committed_surface(
            persona_publication=repo,
            persona_revision_ref=rev,
            state_backend=backend,
            commit_markers=markers,
            surface_port=MagicMock(),
            runtime_id="rt-1",
            interaction_id="int-1",
            interaction_scope=scope,
        )
