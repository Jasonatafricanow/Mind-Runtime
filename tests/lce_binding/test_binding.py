"""Real factual admission -> canonical Memory -> frozen, separately installed LCE."""

import json
import sqlite3
from dataclasses import replace
from datetime import UTC, datetime

import pytest

pytest.importorskip("lce", reason="optional frozen lce-core package is not installed")

from lce.contracts.consolidation import CandidateBaseline
from lce.contracts.external_memory import MemorySubstratePort
from lce.testing.fake_consolidator import ScriptableFakeConsolidator

from mind_runtime.integrations.lce import (
    LceThreadProjectionCompiler,
    MemorySelectionError,
    MrMemorySubstrateAdapter,
    open_lce_binding,
    open_lce_read_binding,
    open_lce_thread_handoff,
)
from mind_runtime.memory.product import MemoryProductStore, MemoryThread, ThreadStatus
from mind_runtime.memory.store import CanonicalMemoryStore
from mind_runtime.runtime_binding import (
    BindingManifestMismatchError,
    RuntimeBinding,
    RuntimeEnvironment,
    bind_storage,
    production_binding,
)
from tests.facts.test_admission import make_evidence, make_scope
from tests.memory.test_admission import admit, setup_plane


@pytest.fixture
def plane(tmp_path):
    binding = RuntimeBinding("persona", "body", "runtime-1", "lab/bind", RuntimeEnvironment.LAB)
    roots = dict(production_root=tmp_path / "production", lab_root=tmp_path / "lab")
    paths = bind_storage(binding, **roots)
    service, _, store, backend = setup_plane(paths.root)
    for index in range(3):
        evidence = replace(
            make_evidence(evidence_id=f"source-{index}"),
            payload={"text": f"Canonical fact {index}"},
        )
        admit(service, evidence, interaction_id=f"interaction-{index}")
    memories = store.load_all()
    assert len(memories) == 3
    store.close()
    backend.close()
    from mind_runtime.intents.lifecycle import IntentLifecycleService
    from mind_runtime.intents.persistence import SqliteIntentBackend
    from tests.intents.test_persistence import candidate
    from tests.state.test_persistence import make_reconciled

    state_backend, _ = make_reconciled(paths.state_db)
    state_backend.close()
    intent_backend = SqliteIntentBackend(paths.root / "intents.sqlite")
    IntentLifecycleService(intent_backend).admit(candidate())
    intent_backend.close()
    return binding, roots, paths, memories


def adapter(plane, scope=None):
    binding, roots, _, _ = plane
    return MrMemorySubstrateAdapter(binding, scope or make_scope(), **roots)


def opened(plane, scope=None, consolidator=None):
    binding, roots, _, _ = plane
    if consolidator is None:
        consolidator = ScriptableFakeConsolidator()
        if plane[3]:
            consolidator.queue_response(CandidateBaseline("Fixture understanding", ids(plane)))
    return open_lce_binding(
        binding,
        scope or make_scope(),
        enabled=True,
        consolidator=consolidator,
        **roots,
    )


def ids(plane):
    return tuple(m.memory_id for m in plane[3])


def snapshot(paths):
    return {
        p.relative_to(paths.root): p.read_bytes()
        for p in paths.root.rglob("*")
        if p.is_file() and paths.lce_root not in p.parents and p.name != ".lock"
    }


def test_canonical_mapping_order_and_real_provenance(plane):
    port = adapter(plane)
    assert isinstance(port, MemorySubstratePort)
    selected = ids(plane)[::-1]
    views = port.get_by_ids(selected)
    assert tuple(v.memory_id for v in views) == selected
    canonical = {m.memory_id: m for m in plane[3]}
    for view in views:
        memory = canonical[view.memory_id]
        assert view.content == memory.content
        assert view.source_refs == memory.provenance.evidence_refs
        assert view.retrieval_metadata == {}
        with pytest.raises(TypeError):
            view.retrieval_metadata["score"] = 999
        assert memory.origin_runtime_id == memory.sync.origin_runtime_id == "runtime-1"


@pytest.mark.parametrize(
    "selection", [(), ["x"], ("",), (None,), ("x", "x"), tuple(str(i) for i in range(101))]
)
def test_invalid_and_duplicate_requests_rejected(plane, selection):
    with pytest.raises((ValueError, TypeError)):
        adapter(plane).get_by_ids(selection)


@pytest.mark.parametrize("bad_id", ["unknown", "a0f2f10d-15d2-4635-872a-42d873b4a852"])
def test_unknown_or_provider_uuid_rejects_entire_set_before_consolidator(plane, bad_id):
    consolidator = ScriptableFakeConsolidator()
    with opened(plane, consolidator=consolidator) as session:
        with pytest.raises(MemorySelectionError):
            session.core.consolidate("opaque", (ids(plane)[0], bad_id, ids(plane)[1]))
        assert consolidator.calls == ()
        assert session.core.get_current_baseline("opaque") is None


def test_wrong_scope_rejected(plane):
    with pytest.raises(MemorySelectionError):
        adapter(plane, make_scope("other")).get_by_ids(ids(plane))


@pytest.mark.parametrize("lifecycle", ["archived", "superseded"])
def test_ineligible_canonical_lifecycle_rejected(plane, lifecycle):
    # Fixture-only historical state injection; no production lifecycle emitter.
    with sqlite3.connect(plane[2].memory_db) as conn:
        payload = json.loads(
            conn.execute(
                "SELECT payload FROM canonical_memory WHERE memory_id=?", (ids(plane)[0],)
            ).fetchone()[0]
        )
        payload["lifecycle"] = lifecycle
        conn.execute(
            "UPDATE canonical_memory SET payload=? WHERE memory_id=?",
            (json.dumps(payload), ids(plane)[0]),
        )
    with pytest.raises(MemorySelectionError):
        adapter(plane).get_by_ids(ids(plane))


def test_manifest_rechecked_each_read(plane):
    port = adapter(plane)
    port.get_by_ids(ids(plane))
    plane[2].binding_manifest.write_text("{}", encoding="utf-8")
    with pytest.raises(BindingManifestMismatchError):
        port.get_by_ids(ids(plane))


def test_real_core_durable_revision_restart_and_no_reverse_authority(plane):
    before = snapshot(plane[2])
    fake = ScriptableFakeConsolidator()
    fake.queue_response(CandidateBaseline("A stable understanding", ids(plane)))
    fake.queue_response(CandidateBaseline(" A  stable\nunderstanding ", ids(plane)))
    fake.queue_response(CandidateBaseline("Updated understanding", ids(plane)))
    with opened(plane, consolidator=fake) as session:
        first = session.core.consolidate("opaque-lineage", ids(plane))
        assert first.baseline.supporting_memory_ids == ids(plane)
        assert first.baseline.revision_number == 1
        noop = session.core.consolidate("opaque-lineage", ids(plane))
        assert not noop.revised
        assert noop.baseline == first.baseline
        second = session.core.consolidate("opaque-lineage", ids(plane))
        assert second.baseline.previous_baseline_id == first.baseline.baseline_id
        history = session.core.get_history("opaque-lineage")
        assert len(history.revisions) == 2
    with opened(plane) as restarted:
        assert restarted.core.get_current_baseline("opaque-lineage") == second.baseline
        assert restarted.core.get_history("opaque-lineage") == history
        assert tuple(v.memory_id for v in adapter(plane).get_by_ids(ids(plane))) == ids(plane)
    assert snapshot(plane[2]) == before


def _durable_mature_thread(plane):
    _, _, paths, memories = plane
    support = tuple(item.memory_id for item in memories[:2])
    canonical = CanonicalMemoryStore(paths.memory_db)
    product = MemoryProductStore(paths.memory_db, canonical)
    try:
        opened_thread = product.open_thread(
            thread_id="computer-replacement",
            scope=make_scope(),
            open_question="Will the computer be replaced?",
            supporting_memory_ids=(support[0],),
            at=datetime(2026, 9, 20, tzinfo=UTC),
            importance=7,
            working_summary="Replacement remains open.",
        )
        assert not opened_thread.mature
        return product.update_thread(
            opened_thread.thread_id,
            supporting_memory_ids=support,
            at=datetime(2026, 9, 25, tzinfo=UTC),
            working_summary=(
                "Price delayed replacement; later performance pressure reopened it."
            ),
            mature=True,
        )
    finally:
        product.close()
        canonical.close()


def test_mature_thread_handoff_reuses_online_reasoning_and_readback(plane):
    binding, roots, _, _ = plane
    thread = _durable_mature_thread(plane)
    support = thread.handoff_memory_ids

    session = open_lce_thread_handoff(binding, make_scope(), enabled=True, **roots)
    assert session is not None
    with session:
        first = session.handoff_thread(thread)
        assert first.revised
        assert first.baseline.region_id == "mr-thread:computer-replacement"
        assert first.baseline.supporting_memory_ids == support
        assert first.baseline.content == thread.working_summary

        replay = session.handoff_thread(thread)
        assert not replay.revised
        assert replay.baseline.baseline_id == first.baseline.baseline_id

        views = session.accepted_understandings("performance replacement", limit=3)
        assert len(views) == 1
        assert views[0].baseline_id == first.baseline.baseline_id

    reader = open_lce_read_binding(binding, make_scope(), enabled=True, **roots)
    assert reader is not None
    assert not hasattr(reader, "handoff_thread")
    with reader:
        views = reader.accepted_understandings("performance", limit=3)
        assert len(views) == 1
        assert views[0].baseline_id == first.baseline.baseline_id
        assert views[0].supporting_memory_ids == support
        assert views[0].source_refs


def test_thread_handoff_rejects_forged_or_stale_thread_object(plane):
    binding, roots, paths, memories = plane
    authoritative = _durable_mature_thread(plane)

    session = open_lce_thread_handoff(binding, make_scope(), enabled=True, **roots)
    assert session is not None
    with session:
        forged = replace(
            authoritative,
            working_summary="Forged caller-owned summary.",
        )
        with pytest.raises(ValueError, match="durable MR product state"):
            session.handoff_thread(forged)

    canonical = CanonicalMemoryStore(paths.memory_db)
    product = MemoryProductStore(paths.memory_db, canonical)
    try:
        current = product.update_thread(
            authoritative.thread_id,
            supporting_memory_ids=tuple(item.memory_id for item in memories[:3]),
            at=datetime(2026, 9, 26, tzinfo=UTC),
            working_summary="A newer durable Thread revision.",
            mature=True,
        )
        assert current != authoritative
    finally:
        product.close()
        canonical.close()

    session = open_lce_thread_handoff(binding, make_scope(), enabled=True, **roots)
    assert session is not None
    with session:
        with pytest.raises(ValueError, match="durable MR product state"):
            session.handoff_thread(authoritative)


def test_generic_lce_binding_cannot_claim_thread_namespace(plane):
    with opened(plane) as session:
        with pytest.raises(ValueError, match="reserved"):
            session.core.consolidate("mr-thread:forged", ids(plane)[:2])
        assert session.core.get_history("mr-thread:forged").revisions == ()


def test_projection_compiler_returns_accepted_baseline_identity(plane):
    binding, roots, _, _ = plane
    thread = _durable_mature_thread(plane)
    compiler = LceThreadProjectionCompiler(binding, enabled=True, **roots)
    baseline_id = compiler.compile(thread)
    assert baseline_id is not None

    reader = open_lce_read_binding(binding, make_scope(), enabled=True, **roots)
    assert reader is not None
    with reader:
        views = reader.accepted_understandings("replacement", limit=3)
        assert views[0].baseline_id == baseline_id


def test_thread_handoff_requires_durable_mature_non_abandoned_structure(plane):
    binding, roots, paths, memories = plane
    canonical = CanonicalMemoryStore(paths.memory_db)
    product = MemoryProductStore(paths.memory_db, canonical)
    try:
        base = product.open_thread(
            thread_id="t",
            scope=make_scope(),
            open_question="open?",
            supporting_memory_ids=(memories[0].memory_id,),
            at=datetime(2026, 9, 20, tzinfo=UTC),
        )
    finally:
        product.close()
        canonical.close()

    session = open_lce_thread_handoff(binding, make_scope(), enabled=True, **roots)
    assert session is not None
    with session:
        with pytest.raises(ValueError, match="not mature"):
            session.handoff_thread(base)

    canonical = CanonicalMemoryStore(paths.memory_db)
    product = MemoryProductStore(paths.memory_db, canonical)
    try:
        product.abandon_thread("t", at=datetime(2026, 9, 21, tzinfo=UTC))
        abandoned = product.get_thread("t")
        assert abandoned is not None
    finally:
        product.close()
        canonical.close()

    session = open_lce_thread_handoff(binding, make_scope(), enabled=True, **roots)
    assert session is not None
    with session:
        with pytest.raises(ValueError, match="abandoned"):
            session.handoff_thread(abandoned)


def test_baselines_physically_separated_by_scope_and_runtime(plane):
    with opened(plane) as first:
        first.core.consolidate("same-opaque-region", ids(plane))
        first_path = first.db_path
    with opened(plane, make_scope("other")) as other_scope:
        assert other_scope.db_path != first_path
        assert other_scope.core.get_current_baseline("same-opaque-region") is None
        with pytest.raises(MemorySelectionError):
            other_scope.core.consolidate("same-opaque-region", ids(plane))
    with opened(plane, make_scope("other")) as restarted_other:
        assert restarted_other.core.get_history("same-opaque-region").revisions == ()
    with opened(plane) as restarted_first:
        assert len(restarted_first.core.get_history("same-opaque-region").revisions) == 1
    for other in (replace(plane[0], storage_namespace="lab/other"), production_binding("persona")):
        paths = bind_storage(other, **plane[1])
        _, _, store, backend = setup_plane(paths.root)
        store.close()
        backend.close()
        other_plane = other, plane[1], paths, ()
        with opened(other_plane) as session:
            assert session.db_path != first_path
            assert session.core.get_current_baseline("same-opaque-region") is None
            with pytest.raises(MemorySelectionError):
                session.core.consolidate("same-opaque-region", ids(plane))


def test_default_disabled_does_not_create_storage(plane):
    assert open_lce_binding(plane[0], make_scope(), **plane[1]) is None
    assert not plane[2].lce_root.exists()


def test_missing_enabled_dependency_is_distinct(plane, monkeypatch):
    import sys

    from mind_runtime.integrations.lce import LceIntegrationUnavailable

    monkeypatch.setitem(sys.modules, "lce.core.engine", None)
    with pytest.raises(LceIntegrationUnavailable):
        opened(plane)
    assert not plane[2].lce_root.exists()


def test_enabled_missing_canonical_store_does_not_create_it(plane):
    plane[2].memory_db.unlink()  # only disposable fixture database
    with pytest.raises(sqlite3.OperationalError):
        opened(plane)
    assert not plane[2].memory_db.exists()
    assert not plane[2].lce_root.exists()


def test_real_qdrant_stale_text_then_provider_removal(plane):
    pytest.importorskip("qdrant_client")
    from mind_runtime.memory.providers.qdrant import open_qdrant_index
    from mind_runtime.memory.retrieval import MemoryRetrievalQuery, MemoryRetrievalService
    from mind_runtime.memory.store import CanonicalMemoryStore
    from tests.memory_vector.test_qdrant import FixtureEmbedding, project

    binding, roots, paths, memories = plane
    store = CanonicalMemoryStore(paths.memory_db)
    index = open_qdrant_index(binding, embedding=FixtureEmbedding(), create=True, **roots)
    assert project(store, index) == (3, 0)
    point_ids = [index.point_id(mid) for mid in ids(plane)]
    index._client.set_payload(index.collection, {"text": "STALE PROVIDER TEXT"}, point_ids)
    query = MemoryRetrievalQuery(make_scope(), "related facts", limit=3)
    selected = tuple(
        r.memory.memory_id
        for r in MemoryRetrievalService(store=store, provider=index.retrieval()).search(query)
    )
    points = index._client.retrieve(index.collection, point_ids, with_vectors=True)
    before = snapshot(paths)
    fake = ScriptableFakeConsolidator()
    fake.queue_response(CandidateBaseline("Selected understanding", selected))
    with opened(plane, consolidator=fake) as session:
        session.core.consolidate("selected", selected)
    supplied = fake.calls[0]["memories"]
    assert tuple(v.memory_id for v in supplied) == selected
    canonical = {m.memory_id: m for m in memories}
    assert all(v.content == canonical[v.memory_id].content for v in supplied)
    assert index._client.retrieve(index.collection, point_ids, with_vectors=True) == points
    assert snapshot(paths) == before
    index.wipe()
    index.close()
    store.close()
    after_wipe = snapshot(paths)
    with opened(plane) as session:
        assert session.core.consolidate("without-provider", ids(plane)).revised
    assert snapshot(paths) == after_wipe


def test_frozen_lce_still_rejects_consolidator_forged_support(plane):
    from lce.contracts.consolidation import UnauthorizedSourceError

    fake = ScriptableFakeConsolidator()
    fake.queue_response(CandidateBaseline("forged understanding", ("provider-id",)))
    with opened(plane, consolidator=fake) as session:
        with pytest.raises(UnauthorizedSourceError):
            session.core.consolidate("opaque", ids(plane))
        assert session.core.get_history("opaque").revisions == ()
