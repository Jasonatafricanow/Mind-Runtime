"""Layer A: Normative Architecture Invariants.

These assertions verify architecture invariants independent of numerical recipe:
- exact 5 controls, deferred absent
- pure derived state (no I/O, no clock, no random, no mutation)
- determinism, caller evaluation_ref isolation
- phase lineage (PROJECTED vs COMMITTED)
- restart recomputation and abort isolation
- unrelated Fast dimension isolation
"""

import builtins
import io
import os
import random
import socket
import sqlite3
import time
import uuid
from copy import deepcopy
from dataclasses import FrozenInstanceError

import pytest

from tests.surface.spec_support import (
    DEFERRED,
    ENABLED,
    canonical,
    expect_ok,
    sample_candidate,
    state,
)


def test_normative_exact_five_controls_and_no_deferred(surface):
    """Layer A1: Five enabled controls returned; deferred are absent."""
    out = expect_ok(surface, sample_candidate())
    assert sorted(out["values"]) == ENABLED
    for name in DEFERRED:
        assert name not in out["values"]
        assert name not in out["dependencies_by_control"]


def test_normative_pure_derived_state_no_io_or_clock(surface, monkeypatch):
    """Layer A3: Surface is pure; traps verify zero I/O, clock, random, network, or DB calls."""
    x = sample_candidate()
    project = surface.project

    calls = []

    def forbidden(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("Surface attempted forbidden external dependency")

    with monkeypatch.context() as m:
        for module, names in [
            (builtins, ["open"]),
            (io, ["open"]),
            (os, ["urandom"]),
            (socket, ["socket", "create_connection", "getaddrinfo"]),
            (sqlite3, ["connect"]),
            (uuid, ["uuid4"]),
            (time, ["time", "monotonic", "perf_counter", "time_ns"]),
            (random, ["random", "randint", "choice", "uniform", "getrandbits"]),
        ]:
            for name in names:
                m.setattr(module, name, forbidden)
        result = project(x)
    assert calls == []
    assert result["status"] == "AVAILABLE"


def test_normative_no_input_mutation(surface):
    """Layer A3: Surface evaluation must not mutate input Dynamics or Persona."""
    x = sample_candidate()
    before = canonical(x)
    expect_ok(surface, x)
    assert canonical(x) == before


def test_surface_result_authority_fields_cannot_mutate(surface):
    result = surface.project(sample_candidate())
    assert result.status == "AVAILABLE"
    original = result.controls["controls_id"]
    with pytest.raises(TypeError):
        result["controls"]["values"]["expressive_warmth"] = 1.0
    with pytest.raises(TypeError):
        result.controls["source_states"][0]["state_id"] = "forged"
    with pytest.raises((FrozenInstanceError, AttributeError)):
        result.controls = {"controls_id": "forged"}
    assert result.controls["controls_id"] == original


@pytest.mark.parametrize(
    "field, expected",
    [
        ("state_owner", "SURFACE_STATE_AUTHORITY_MISMATCH"),
        ("state_runtime", "SURFACE_STATE_AUTHORITY_MISMATCH"),
        ("source_projection", "SURFACE_SOURCE_PROJECTION_MISMATCH"),
        ("illegal_phase", "SURFACE_SOURCE_PHASE_INVALID"),
    ],
)
def test_projector_rejects_authority_mismatch(surface, field, expected):
    supplied = sample_candidate()
    if field == "state_owner":
        supplied["projected_dynamics"]["states"][0]["owner"]["owner_persona_id"] = "other"
    elif field == "state_runtime":
        supplied["projected_dynamics"]["states"][0]["runtime_id"] = "other-runtime"
    elif field == "source_projection":
        supplied["projected_dynamics"]["source_projection_id"] = "projection:other"
    else:
        supplied["projected_dynamics"]["source_phase"] = "aborted"
    result = surface.project(supplied)
    assert result.status == "UNAVAILABLE"
    assert result.controls is None
    assert expected in result.reasons


def test_normative_determinism_and_caller_ref_isolation(surface):
    """Layer A5: Determinism under reordering, and evaluation_ref does not alter controls_id."""
    x = sample_candidate()
    a = expect_ok(surface, x)

    # 1. Ten repeated evaluations produce identical bytes
    for _ in range(10):
        assert canonical(expect_ok(surface, deepcopy(x))) == canonical(a)

    # 2. Reordering inputs preserves identical output
    x["projected_dynamics"]["states"].reverse()
    x["persona"]["content"]["dimensions"].reverse()
    x["recipe"]["rules"].reverse()
    for manifest in x["recipe"]["dependency_manifest"].values():
        manifest["dynamics"].reverse()
        manifest["disposition"].reverse()
    assert expect_ok(surface, x) == a

    # 3. Changing evaluation_ref changes only evaluation_ref, not controls_id
    x["evaluation_ref"] = "eval:another-attempt"
    b = expect_ok(surface, x)
    assert b["evaluation_ref"] != a["evaluation_ref"]
    assert b["controls_id"] == a["controls_id"]


def test_normative_phase_lineage_projected_vs_committed(surface):
    """Layer A5: Source phase (PROJECTED vs COMMITTED) changes controls_id."""
    a = sample_candidate()
    b = deepcopy(a)
    b["projected_dynamics"]["source_phase"] = "committed"

    out_a = expect_ok(surface, a)
    out_b = expect_ok(surface, b)

    assert out_a["values"] == out_b["values"]
    assert out_a["source_phase"] == "projected"
    assert out_b["source_phase"] == "committed"
    assert out_a["controls_id"] != out_b["controls_id"]
    assert out_a["canonical"] is out_b["canonical"] is False


def test_normative_restart_recomputation_probe(surface, tmp_path):
    """Real canonical SQLite commit + published Persona recomputes after reopen."""
    import json
    from datetime import UTC, datetime

    from mind_runtime.contracts import RuntimeState, Scope, ScopeDomain, SyncFields
    from mind_runtime.persona_publication import PersonaConfigPublicationRepository
    from mind_runtime.state.persistence import SqliteCommitMarkerStore, SqliteStateBackend
    from mind_runtime.surface.cognition import recompute_committed_surface

    x = sample_candidate()
    source = tmp_path / "persona.json"
    source.write_text(json.dumps(x["persona"]["content"]), encoding="utf-8")
    publication = PersonaConfigPublicationRepository(tmp_path / "publication")
    ref = publication.publish(source)
    now = datetime(2026, 9, 23, tzinfo=UTC)
    scope = Scope(domain=ScopeDomain.AGENT, agent_id="fixture-persona", persona_id=ref.persona_id)
    turn_scope = Scope(domain=ScopeDomain.USER, user_id="fixture-user")
    db = tmp_path / "canonical.sqlite"
    backend = SqliteStateBackend(db)
    marker = SqliteCommitMarkerStore(db, connection=backend.connection)
    ids = []
    for item in x["projected_dynamics"]["states"]:
        state = RuntimeState(
            state_id=item["state_id"],
            scope=scope,
            dimension=item["dimension"],
            value=item["value"],
            status="active",
            valid_from=now,
            valid_until=None,
            relevant_until=None,
            last_observed_at=now,
            evidence_refs=(),
            transition_refs=(),
            updated_at=now,
            origin_runtime_id="fixture-runtime",
            version=item["version"],
            sync=SyncFields(
                scope,
                "fixture-runtime",
                item["state_id"],
                item["version"],
                f"idem-{item['state_id']}",
            ),
        )
        assert backend.save_state(state)
        ids.append(state.state_id)
    with backend.transaction():
        assert marker.record_commit(
            interaction_id="fixture-1",
            scope=turn_scope,
            committed_at=now,
            projected_state_ids=tuple(ids),
            commit=False,
        )
    before = recompute_committed_surface(
        surface_port=surface,
        persona_publication=publication,
        persona_revision_ref=ref,
        state_backend=backend,
        commit_markers=marker,
        interaction_id="fixture-1",
        interaction_scope=turn_scope,
        runtime_id="fixture-runtime",
    )
    backend.close()
    marker.close()
    restored_backend = SqliteStateBackend(db)
    restored_marker = SqliteCommitMarkerStore(db, connection=restored_backend.connection)
    after = recompute_committed_surface(
        surface_port=surface,
        persona_publication=PersonaConfigPublicationRepository(tmp_path / "publication"),
        persona_revision_ref=ref,
        state_backend=restored_backend,
        commit_markers=restored_marker,
        interaction_id="fixture-1",
        interaction_scope=turn_scope,
        runtime_id="fixture-runtime",
    )
    assert before.controls["controls_id"] == after.controls["controls_id"]
    assert after.controls["source_phase"] == "committed"
    assert not any("surface" in name.lower() for name in restored_backend.table_names())
    from dataclasses import replace

    from mind_runtime.persona_publication import ReplayUnavailable

    other_scope = Scope(domain=ScopeDomain.AGENT, agent_id="other-agent", persona_id=ref.persona_id)
    committed = restored_backend.load_states()[0]
    duplicate = replace(
        committed,
        scope=other_scope,
        sync=SyncFields(
            other_scope,
            "fixture-runtime",
            committed.state_id,
            committed.version,
            f"idem-other-{committed.state_id}",
        ),
    )
    assert restored_backend.save_state(duplicate)
    with pytest.raises(ReplayUnavailable, match="ambiguous"):
        recompute_committed_surface(
            surface_port=surface,
            persona_publication=publication,
            persona_revision_ref=ref,
            state_backend=restored_backend,
            commit_markers=restored_marker,
            interaction_id="fixture-1",
            interaction_scope=turn_scope,
            runtime_id="fixture-runtime",
        )
    restored_backend.close()
    restored_marker.close()


def test_no_production_test_probes(surface):
    """The production adapter exposes no test-only abort/restart probe."""
    assert not hasattr(surface, "abort_probe")
    assert not hasattr(surface, "restart_probe")


def test_normative_unrelated_fast_dimension_isolation(surface):
    """Layer A2: Unrelated valid Fast dimension (social_pull) does not alter Surface or digests."""
    a = sample_candidate()
    b = deepcopy(a)
    state(b, "social_pull")["value"] = 0.99

    x, y = expect_ok(surface, a), expect_ok(surface, b)
    assert x["values"] == y["values"]
    assert x["dependency_digest"] == y["dependency_digest"]
    assert x["controls_id"] == y["controls_id"]
