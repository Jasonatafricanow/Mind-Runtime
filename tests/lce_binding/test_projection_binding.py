"""MR canonical Memory -> current LCE Path-B projection binding."""

from __future__ import annotations

import sqlite3
from dataclasses import fields, replace
from datetime import datetime, timedelta

import pytest

pytest.importorskip("lce", reason="optional current lce-core package is not installed")

from lce.cognition.inspiration import InspirationKind, InspirationPackage

from mind_runtime.cognition import CognitiveMode
from mind_runtime.integrations.lce import open_lce_thread_handoff
from mind_runtime.integrations.lce_inspiration import LceInspirationBackgroundWorker
from mind_runtime.integrations.lce_projection import (
    LceInspirationMaterial,
    LcePostCommitProjector,
    MrLceCanonicalSourceAdapter,
    lce_projection_reconcile_required,
    open_lce_projection_binding,
    reconcile_lce_projection,
)
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

def test_inspiration_material_binding_keeps_downstream_surface_narrow(
    projection_plane,
) -> None:
    assert [field.name for field in fields(LceInspirationMaterial)] == [
        "material_id",
        "content",
    ]

    binding, roots, _, _ = projection_plane
    session = open_lce_projection_binding(
        binding,
        make_scope(),
        enabled=True,
        **roots,
    )
    assert session is not None

    with session:
        session.sync_all()
        sources = session.core.memory.list_current_valid_evidence()
        assert sources
        cutoff = max(
            item.effective_known_at for item in sources
        ) + timedelta(days=1)
        blocks = session.core.memory.list_semantic_blocks_at_knowledge_cutoff(
            cutoff,
            current_valid_only=True,
        )
        assert blocks
        block = blocks[0]
        assert block.state_id is not None

        # The MR binding test verifies only the narrow downstream seam. LCE's
        # own suite separately verifies association/extension discovery. Do
        # not assume MR's semantic compiler emits one block per canonical
        # Memory item; several inputs may correctly extend one block.
        assert session.discover_inspiration(
            knowledge_cutoff=cutoff,
        ) == ()

        package = InspirationPackage(
            kind=InspirationKind.ASSOCIATION,
            candidate_id="mr-binding-fixture",
            content_fragments=(block.content,),
            block_ids=(block.block_id,),
            state_ids=(block.state_id,),
            raw_evidence_ids=block.raw_evidence_ids,
            knowledge_cutoff=cutoff,
        )
        stored = session.core.inspiration.store.put(
            material_id="insp_mr_binding_fixture",
            content=(
                "Possible connection to explore (not established): "
                "binding fixture"
            ),
            package=package,
            trace={"test": True},
        )
        assert stored is not None

        pending = session.inspiration_materials(limit=10)
        assert pending == (
            LceInspirationMaterial(
                material_id="insp_mr_binding_fixture",
                content=(
                    "Possible connection to explore (not established): "
                    "binding fixture"
                ),
            ),
        )
        session.consume_inspiration(pending[0].material_id)
        assert session.inspiration_materials(limit=10) == ()

def test_background_inspiration_worker_checkpoints_canonical_catchup(
    projection_plane,
    tmp_path,
) -> None:
    binding, roots, _, memories = projection_plane
    session = open_lce_projection_binding(
        binding,
        make_scope(),
        enabled=True,
        **roots,
    )
    assert session is not None

    with session:
        sources = _source(projection_plane).list_current_valid_evidence()
        cutoff = max(
            item.effective_known_at for item in sources
        ) + timedelta(days=1)
        worker = LceInspirationBackgroundWorker(
            session,
            state_path=tmp_path / "background-inspiration.sqlite",
        )

        first = worker.refresh(
            mode=CognitiveMode.DAYDREAM,
            now=cutoff,
        )
        second = worker.refresh(
            mode=CognitiveMode.DREAM,
            now=cutoff + timedelta(seconds=1),
        )

        assert first.new_memory_ids == len(memories)
        assert second.new_memory_ids == 0
        assert second.discovered_materials == 0
        assert worker.state_path.exists()

        with pytest.raises(
            ValueError,
            match="DAYDREAM or DREAM",
        ):
            worker.refresh(
                mode=CognitiveMode.ACTIVE,
                now=cutoff,
            )


def test_background_worker_reservation_consumes_only_after_delivery_commit(
    projection_plane,
    tmp_path,
) -> None:
    binding, roots, _, _ = projection_plane
    session = open_lce_projection_binding(
        binding,
        make_scope(),
        enabled=True,
        **roots,
    )
    assert session is not None

    with session:
        session.sync_all()
        sources = session.core.memory.list_current_valid_evidence()
        cutoff = max(
            item.effective_known_at for item in sources
        ) + timedelta(days=1)
        blocks = session.core.memory.list_semantic_blocks_at_knowledge_cutoff(
            cutoff,
            current_valid_only=True,
        )
        block = blocks[0]
        assert block.state_id is not None
        package = InspirationPackage(
            kind=InspirationKind.ASSOCIATION,
            candidate_id="worker-reservation-fixture",
            content_fragments=(block.content,),
            block_ids=(block.block_id,),
            state_ids=(block.state_id,),
            raw_evidence_ids=block.raw_evidence_ids,
            knowledge_cutoff=cutoff,
        )
        stored = session.core.inspiration.store.put(
            material_id="insp-worker-reservation",
            content="Possible connection to explore (not established): worker fixture",
            package=package,
            trace={"test": True},
        )
        assert stored is not None

        worker = LceInspirationBackgroundWorker(
            session,
            state_path=tmp_path / "reservation-state.sqlite",
        )
        reserved = worker.reserve_next("wake-1")
        assert reserved is not None
        assert reserved.material_id == "insp-worker-reservation"

        assert worker.release_for_wake("wake-1") == reserved.material_id
        assert worker.pending_materials() == (reserved,)

        reserved_again = worker.reserve_next("wake-2")
        assert reserved_again == reserved
        assert worker.consume_for_wake("wake-2") == reserved.material_id
        assert worker.pending_materials() == ()

def test_background_worker_fails_closed_on_invalid_inputs(
    projection_plane,
    tmp_path,
) -> None:
    with pytest.raises(TypeError, match="LceProjectionSession"):
        LceInspirationBackgroundWorker(  # type: ignore[arg-type]
            object(),
            state_path=tmp_path / "invalid.sqlite",
        )

    binding, roots, _, _ = projection_plane
    session = open_lce_projection_binding(
        binding,
        make_scope(),
        enabled=True,
        **roots,
    )
    assert session is not None
    with session:
        worker = LceInspirationBackgroundWorker(
            session,
            state_path=tmp_path / "valid.sqlite",
        )
        with pytest.raises(ValueError, match="aware UTC"):
            worker.refresh(
                mode=CognitiveMode.DAYDREAM,
                now=datetime(2026, 9, 28),
            )
        with pytest.raises(ValueError, match="wake_id"):
            worker.reserve_next("")
        assert worker.consume_for_wake("missing") is None
        assert worker.release_for_wake("missing") is None


def test_background_worker_reservation_survives_worker_reopen(
    projection_plane,
    tmp_path,
) -> None:
    binding, roots, _, _ = projection_plane
    session = open_lce_projection_binding(
        binding,
        make_scope(),
        enabled=True,
        **roots,
    )
    assert session is not None

    with session:
        session.sync_all()
        sources = session.core.memory.list_current_valid_evidence()
        cutoff = max(
            item.effective_known_at for item in sources
        ) + timedelta(days=1)
        block = session.core.memory.list_semantic_blocks_at_knowledge_cutoff(
            cutoff,
            current_valid_only=True,
        )[0]
        assert block.state_id is not None
        package = InspirationPackage(
            kind=InspirationKind.ASSOCIATION,
            candidate_id="durable-reservation-fixture",
            content_fragments=(block.content,),
            block_ids=(block.block_id,),
            state_ids=(block.state_id,),
            raw_evidence_ids=block.raw_evidence_ids,
            knowledge_cutoff=cutoff,
        )
        stored = session.core.inspiration.store.put(
            material_id="insp-durable-reservation",
            content="Possible connection to explore (not established): durable fixture",
            package=package,
            trace={"test": True},
        )
        assert stored is not None

        state_path = tmp_path / "durable-reservation.sqlite"
        first_worker = LceInspirationBackgroundWorker(
            session,
            state_path=state_path,
        )
        reserved = first_worker.reserve_next("wake-durable")
        assert reserved is not None
        assert first_worker.reserve_next("wake-durable") == reserved

        reopened = LceInspirationBackgroundWorker(
            session,
            state_path=state_path,
        )
        assert reopened.reserve_next("wake-durable") == reserved
        assert reopened.reserve_next("wake-other") is None

        # If the underlying LCE material stopped being pending, reopening the
        # same wake cleans the stale reservation instead of pinning it forever.
        session.consume_inspiration(reserved.material_id)
        assert reopened.reserve_next("wake-durable") is None
        assert reopened.release_for_wake("wake-durable") is None


def test_source_identity_changes_when_interaction_memory_membership_changes(
    projection_plane,
) -> None:
    _, _, paths, memories = projection_plane
    source = _source(projection_plane)
    before = source.list_current_valid_evidence()
    base = memories[0]
    old = next(
        item for item in before
        if base.memory_id in item.provenance["memory_ids"]
    )
    assert old.evidence_id.startswith("mr-source:v2:")

    clone_id = "same-interaction-v2-membership"
    clone = replace(
        base,
        memory_id=clone_id,
        content="second committed Memory in the same interaction",
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

    after = source.list_current_valid_evidence()
    new = next(
        item for item in after
        if base.memory_id in item.provenance["memory_ids"]
    )
    assert new.evidence_id != old.evidence_id
    assert set(new.provenance["memory_ids"]) == {
        base.memory_id,
        clone_id,
    }


def test_warm_reconcile_retires_old_source_identity_and_catches_up(
    projection_plane,
) -> None:
    binding, roots, paths, memories = projection_plane
    first = open_lce_projection_binding(
        binding,
        make_scope(),
        enabled=True,
        **roots,
    )
    assert first is not None
    with first:
        first.sync_all()
        old_sources = {
            item.evidence_id
            for item in first.core.memory.list_current_valid_evidence()
        }

    base = memories[0]
    clone_id = "warm-reconcile-new-member"
    clone = replace(
        base,
        memory_id=clone_id,
        content="new member changes the grouped source identity",
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

    reopened = open_lce_projection_binding(
        binding,
        make_scope(),
        enabled=True,
        **roots,
    )
    assert reopened is not None
    with reopened:
        report = reopened.reconcile_canonical(
            cutoff=max(
                memory.committed_at for memory in (*memories, clone)
            ) + timedelta(days=1),
        )
        current_sources = {
            item.evidence_id
            for item in reopened.core.memory.list_current_valid_evidence()
        }
        current_block_sources = {
            evidence_id
            for block in reopened.core.memory.list_semantic_blocks(
                current_valid_only=True
            )
            for evidence_id in block.raw_evidence_ids
        }

    assert report.canonical_sources == 3
    assert report.processed_sources == 3
    assert set(report.stale_sources) & old_sources
    assert current_sources != old_sources
    assert current_block_sources <= current_sources


def test_post_commit_projector_projects_complete_interaction_group(
    projection_plane,
) -> None:
    binding, roots, _, memories = projection_plane
    projector = LcePostCommitProjector(
        binding,
        enabled=True,
        **roots,
    )
    projected = projector.project_interaction(
        scope=make_scope(),
        interaction_id=memories[0].provenance.interaction_id,
    )
    assert projected == 1

    reopened = open_lce_projection_binding(
        binding,
        make_scope(),
        enabled=True,
        **roots,
    )
    assert reopened is not None
    with reopened:
        matching = tuple(
            item
            for item in reopened.core.memory.list_current_valid_evidence()
            if memories[0].memory_id in item.provenance["memory_ids"]
        )
        assert len(matching) == 1
        assert (
            reopened.core.memory.get_pipeline_stage(
                matching[0].evidence_id
            )
            == "complete"
        )


def test_warm_reconcile_wrapper_persists_clean_consumer_state(
    projection_plane,
) -> None:
    binding, roots, _, _ = projection_plane
    assert lce_projection_reconcile_required(
        binding,
        make_scope(),
        **roots,
    )

    first = reconcile_lce_projection(
        binding,
        make_scope(),
        enabled=True,
        **roots,
    )
    assert first is not None
    assert first.current
    assert not lce_projection_reconcile_required(
        binding,
        make_scope(),
        **roots,
    )

    # Process-local warm-start cache is safe only while the durable dirty bit
    # remains clear.
    second = reconcile_lce_projection(
        binding,
        make_scope(),
        enabled=True,
        **roots,
    )
    assert second == first


def test_post_commit_failure_stays_dirty_until_retry_reconciles(
    projection_plane,
    monkeypatch,
) -> None:
    import mind_runtime.integrations.lce_projection as integration

    binding, roots, _, memories = projection_plane
    projector = LcePostCommitProjector(
        binding,
        enabled=True,
        **roots,
    )
    original_open = integration.open_lce_projection_binding

    def fail_open(*args, **kwargs):
        raise RuntimeError("synthetic LCE outage")

    monkeypatch.setattr(
        integration,
        "open_lce_projection_binding",
        fail_open,
    )
    with pytest.raises(RuntimeError, match="synthetic LCE outage"):
        projector.project_interaction(
            scope=make_scope(),
            interaction_id=memories[0].provenance.interaction_id,
        )
    assert lce_projection_reconcile_required(
        binding,
        make_scope(),
        **roots,
    )

    monkeypatch.setattr(
        integration,
        "open_lce_projection_binding",
        original_open,
    )
    assert projector.project_interaction(
        scope=make_scope(),
        interaction_id=memories[0].provenance.interaction_id,
    ) >= 0
    assert not lce_projection_reconcile_required(
        binding,
        make_scope(),
        **roots,
    )


def test_post_commit_projector_noop_and_identity_validation(
    projection_plane,
) -> None:
    binding, roots, _, _ = projection_plane
    disabled = LcePostCommitProjector(
        binding,
        enabled=False,
        **roots,
    )
    assert disabled.project_interaction(
        scope=make_scope(),
        interaction_id="anything",
    ) == 0

    enabled = LcePostCommitProjector(
        binding,
        enabled=True,
        **roots,
    )
    with pytest.raises(ValueError, match="interaction_id"):
        enabled.project_interaction(
            scope=make_scope(),
            interaction_id="",
        )

    # A terminal turn with no canonical Memory is harmless, but if a previous
    # projection is dirty this same seam is also allowed to perform recovery.
    assert enabled.project_interaction(
        scope=make_scope(),
        interaction_id="missing-interaction",
    ) == 0


def test_disabled_warm_reconcile_has_no_sync_state_side_effect(
    projection_plane,
) -> None:
    binding, roots, _, _ = projection_plane
    assert (
        reconcile_lce_projection(
            binding,
            make_scope(),
            enabled=False,
            **roots,
        )
        is None
    )
