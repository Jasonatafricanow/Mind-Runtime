"""Committed Surface replay requires canonical marker and exact authorities."""

from __future__ import annotations

import pytest

from mind_runtime.contracts import Scope, ScopeDomain
from mind_runtime.persona_publication import (
    PersonaConfigPublicationRepository,
    PersonaRevisionRef,
    ReplayUnavailable,
)
from mind_runtime.state.persistence import SqliteCommitMarkerStore, SqliteStateBackend
from mind_runtime.surface.cognition import recompute_committed_surface
from mind_runtime.surface.projector import DeterministicSurfaceProjector


def _inputs(tmp_path):
    backend = SqliteStateBackend(tmp_path / "states.sqlite")
    marker = SqliteCommitMarkerStore(tmp_path / "states.sqlite", connection=backend.connection)
    return {
        "surface_port": DeterministicSurfaceProjector(),
        "persona_publication": PersonaConfigPublicationRepository(tmp_path / "published"),
        "persona_revision_ref": PersonaRevisionRef("persona-a", 2, "a" * 64),
        "state_backend": backend,
        "commit_markers": marker,
        "interaction_id": "missing-turn",
        "interaction_scope": Scope(domain=ScopeDomain.USER, user_id="user-a"),
        "runtime_id": "runtime-a",
    }


@pytest.mark.parametrize(
    ("field", "reason"),
    [
        ("persona_publication", "immutable publication repository"),
        ("persona_revision_ref", "must be exact"),
        ("state_backend", "canonical SQLite"),
        ("commit_markers", "canonical SQLite"),
    ],
)
def test_recomputation_rejects_noncanonical_authority(tmp_path, field, reason):
    inputs = _inputs(tmp_path)
    inputs[field] = None
    with pytest.raises(TypeError, match=reason):
        recompute_committed_surface(**inputs)


def test_recomputation_rejects_missing_commit_marker(tmp_path):
    inputs = _inputs(tmp_path)
    with pytest.raises(ReplayUnavailable, match="canonical commit marker missing"):
        recompute_committed_surface(**inputs)


def test_recomputation_rejects_malformed_commit_marker(tmp_path, monkeypatch):
    inputs = _inputs(tmp_path)

    def malformed(**_kwargs):
        raise ValueError("invalid marker")

    monkeypatch.setattr(inputs["commit_markers"], "committed_state_ids", malformed)
    with pytest.raises(ReplayUnavailable, match="canonical commit marker malformed"):
        recompute_committed_surface(**inputs)
