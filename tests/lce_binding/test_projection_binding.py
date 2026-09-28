"""MR canonical Memory -> current LCE Path-B projection binding."""

from __future__ import annotations

import sqlite3
from dataclasses import replace

import pytest

pytest.importorskip("lce", reason="optional current lce-core package is not installed")

from mind_runtime.integrations.lce_projection import (
    MrLceCanonicalSourceAdapter,
    open_lce_projection_binding,
)
from mind_runtime.integrations.lce import open_lce_thread_handoff
from mind_runtime.memory.product import MemoryProductStore
from mind_runtime.memory.store import CanonicalMemoryStore
from mind_runtime.runtime_binding import (
    RuntimeBinding,
    RuntimeEnvironment,
    bind_storage,
)
from tests.facts.test_admission import make_evidence, make_scope
from tests.memory.test_admission import admit, setup_plane


@pytest.fixture
def projection_plane(tmp_path):
    binding = RuntimeBinding(
        "persona",
        "body",
        "runtime-1",
        "lab/lce-projection",
        RuntimeEnvironment.LAB,
    )
    roots = {
        "production_root": tmp_path / "production",
        "lab_root": tmp_path / "lab",
    }
    paths = bind_storage(binding, **roots)
    service, _, store, backend = setup_plane(paths.root)
    for index in range(3):
        evidence = replace(
            make_evidence(evidence_id=f"source-{index}"),
            payload={"text": f"Canonical path B fact {index}"},
        )
        admit(
            service,
            evidence,
            interaction_id=f"interaction-{index}",
        )
    memories = store.load_all()
    store.close()
    backend.close()
    assert len(memories) == 3
    return binding, roots, paths, memories


def _source(projection_plane) -> MrLceCanonicalSourceAdapter:
    binding, roots, _, _ = projection_plane
    from mind_runtime.integrations.lce import MrMemorySubstrateAdapter

    return MrLceCanonicalSourceAdapter(
        MrMemorySubstrateAdapter(
            binding,
            make_scope(),
            **roots,
        )
    )


def test_same_interaction_memory_rows_are_one_lce_authority_unit(
    projection_plane,
) -> None:
    _, _, paths, memories = projection_plane
    base = memories[0]
    clone_id = "same-interaction-second-memory"
    clone = replace(
        base,
        memory_id=clone_id,
        content="A second canonical memory extracted from the same interaction.",
        sync=replace(
            base.sync,
            object_id=clone_id,
            idempotency_key=clone_id,
        ),
    )
    store = CanonicalMemoryStore(paths.memory_db)
    try:
        store._commit((clone,))
    finally:
        store.close()

    materials = _source(projection_plane).list_current_valid_evidence()
    assert len(materials) == 3

    grouped = next(
        item
        for item in materials
        if base.memory_id in item.provenance["memory_ids"]
    )
    assert set(grouped.provenance["memory_ids"]) == {
        base.memory_id,
        clone_id,
    }
    assert grouped.provenance["interaction_ids"] == (
        base.provenance.interaction_id,
    )
    assert set(grouped.provenance["evidence_refs"]) == set(
        base.provenance.evidence_refs
    )


def test_independent_interactions_remain_independent_lce_sources(
    projection_plane,
) -> None:
    materials = _source(projection_plane).list_current_valid_evidence()
    assert len(materials) == 3
    assert len({item.evidence_id for item in materials}) == 3
    assert {
        tuple(item.provenance["interaction_ids"])
        for item in materials
    } == {
        ("interaction-0",),
        ("interaction-1",),
        ("interaction-2",),
    }


def test_path_b_projection_keeps_raw_authority_out_of_lce_store(
    projection_plane,
) -> None:
    binding, roots, paths, _ = projection_plane
    canonical = CanonicalMemoryStore(paths.memory_db, read_only=True)
    try:
        before = canonical.load_all()
    finally:
        canonical.close()

    session = open_lce_projection_binding(
        binding,
        make_scope(),
        enabled=True,
        **roots,
    )
    assert session is not None
    with session:
        results = session.sync_all()
        assert len(results) == 3
        assert session.core.memory.list_current_valid_evidence()
        projection_db = (
            session.core.root
            / "projection_state"
            / "projection_state.sqlite"
        )
        assert projection_db.exists()
        with sqlite3.connect(projection_db) as conn:
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
        assert "raw_evidence" not in tables
        assert "semantic_blocks" in tables

    canonical = CanonicalMemoryStore(paths.memory_db, read_only=True)
    try:
        assert canonical.load_all() == before
    finally:
        canonical.close()


def test_projection_binding_replay_is_idempotent_and_uses_shared_baseline_root(
    projection_plane,
) -> None:
    binding, roots, paths, _ = projection_plane
    session = open_lce_projection_binding(
        binding,
        make_scope(),
        enabled=True,
        **roots,
    )
    assert session is not None
    with session:
        first = session.sync_all()
        second = session.sync_all()
        assert len(first) == len(second) == 3
        assert all(
            result.compiler_result.replayed
            for result in second
        )
        assert (
            session.db_path.parent.name == "baselines"
        )
        assert session.db_path.is_relative_to(paths.lce_root)


def test_disabled_projection_binding_has_no_storage_side_effect(
    projection_plane,
) -> None:
    binding, roots, paths, _ = projection_plane
    assert not paths.lce_root.exists()
    assert (
        open_lce_projection_binding(
            binding,
            make_scope(),
            enabled=False,
            **roots,
        )
        is None
    )
    assert not paths.lce_root.exists()


def test_path_a_and_path_b_share_one_scope_baseline_store(
    projection_plane,
) -> None:
    binding, roots, paths, memories = projection_plane

    projection = open_lce_projection_binding(
        binding,
        make_scope(),
        enabled=True,
        **roots,
    )
    assert projection is not None
    with projection:
        projection.sync_all()
        path_b_db = projection.db_path

    canonical = CanonicalMemoryStore(paths.memory_db)
    product = MemoryProductStore(paths.memory_db, canonical)
    try:
        thread = product.open_thread(
            thread_id="shared-lineage",
            scope=make_scope(),
            open_question="Does Path A share the LCE store?",
            supporting_memory_ids=(memories[0].memory_id,),
            at=memories[0].committed_at,
            working_summary="The explicit line is still developing.",
        )
        thread = product.update_thread(
            thread.thread_id,
            supporting_memory_ids=(
                memories[0].memory_id,
                memories[1].memory_id,
            ),
            at=memories[1].committed_at,
            working_summary="The explicit line has independent support.",
            mature=True,
        )
    finally:
        product.close()
        canonical.close()

    handoff = open_lce_thread_handoff(
        binding,
        make_scope(),
        enabled=True,
        **roots,
    )
    assert handoff is not None
    with handoff:
        assert handoff.db_path == path_b_db
        result = handoff.handoff_thread(thread)
        assert result.baseline.region_id == "mr-thread:shared-lineage"
