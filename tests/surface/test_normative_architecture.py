"""Layer A: Normative Architecture Invariants.

RED BY DESIGN: Production Surface adapter is intentionally absent in W3-B0.
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
    targets = surface.forbidden_call_targets()
    assert set(targets) == {"provider", "clock", "random", "network", "database", "file"}

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
        for entries in targets.values():
            for obj, attr in entries:
                m.setattr(obj, attr, forbidden)
        result = project(x)
    assert calls == []
    assert result["status"] == "AVAILABLE"


def test_normative_no_input_mutation(surface):
    """Layer A3: Surface evaluation must not mutate input Dynamics or Persona."""
    x = sample_candidate()
    before = canonical(x)
    expect_ok(surface, x)
    assert canonical(x) == before


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
    """Layer A3 & A5: Restart recomputation via real backend + loader without persisting Surface."""
    x = sample_candidate()
    x["projected_dynamics"]["source_phase"] = "committed"
    probe = surface.restart_probe(str(tmp_path), x)
    assert probe["parent_pid"] != probe["child_pid"]
    assert probe["canonical_before"] == probe["canonical_after"]
    assert probe["reconstructed_input"] == x
    assert canonical(probe["before"]) == canonical(probe["after"])
    assert probe["surface_reads"] == probe["surface_writes"] == 0
    assert not any("surface" in t.lower() for t in probe["tables_after"])


def test_normative_aborted_projection_never_published(surface, tmp_path):
    """Layer A5: Turn abort never publishes or persists projected Surface."""
    probe = surface.abort_probe(str(tmp_path), sample_candidate())
    assert probe["outcome"] == "ABORTED"
    assert probe["surface"]["source_phase"] == "projected"
    assert probe["surface"]["canonical"] is False
    assert probe["surface_writes"] == probe["surface_publications"] == 0
    assert probe["projected_state_publications"] == 0


def test_normative_unrelated_fast_dimension_isolation(surface):
    """Layer A2: Unrelated valid Fast dimension (social_pull) does not alter Surface or digests."""
    a = sample_candidate()
    b = deepcopy(a)
    state(b, "social_pull")["value"] = 0.99

    x, y = expect_ok(surface, a), expect_ok(surface, b)
    assert x["values"] == y["values"]
    assert x["dependency_digest"] == y["dependency_digest"]
    assert x["controls_id"] == y["controls_id"]
