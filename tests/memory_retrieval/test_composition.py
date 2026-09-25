import json
from types import SimpleNamespace

import pytest

from mind_runtime.memory.retrieval import MemorySurfaceBudget
from mind_runtime.memory.store import CanonicalMemoryStore
from mind_runtime.runtime_binding import bind_storage, production_binding
from tests.host.test_runtime_binding import lab_binding
from tests.memory.test_contracts import memory
from tests.memory_retrieval.test_history import inputs
from tests.memory_retrieval.test_retrieval import ScriptedProvider, candidate


def test_default_null_does_not_touch_storage(tmp_path):
    from mind_runtime.memory.retrieval_composition import build_memory_history

    port = build_memory_history(lab_binding("absent"), lab_root=tmp_path / "absent")
    assert port.read(**inputs()) is None
    assert not (tmp_path / "absent").exists()


def test_bound_production_lab_isolation_and_restart(tmp_path):
    from mind_runtime.memory.retrieval_composition import build_memory_history

    roots = dict(production_root=tmp_path / "prod", lab_root=tmp_path / "lab")
    production, lab = production_binding("kayla_v0"), lab_binding("retrieval")
    prod_paths = bind_storage(production, **roots)
    lab_paths = bind_storage(lab, **roots)
    for paths, memories in ((prod_paths, (memory(),)), (lab_paths, ())):
        db = CanonicalMemoryStore(paths.memory_db)
        db._commit(memories)
        db.close()
    before = {p: p.read_bytes() for root in roots.values() for p in root.rglob("*") if p.is_file()}
    for _ in range(3):
        prod = build_memory_history(production, provider=ScriptedProvider((candidate(),)), **roots)
        isolated = build_memory_history(lab, provider=ScriptedProvider((candidate(),)), **roots)
        assert prod.read(**inputs()).episodes[0].proposition == "hello"
        assert isolated.read(**inputs()) is None
    assert all(p.read_bytes() == contents for p, contents in before.items())


def test_active_thread_projection_is_available_without_raw_retrieval_provider(tmp_path):
    from datetime import timedelta

    from mind_runtime.memory.product import MemoryProductStore
    from mind_runtime.memory.retrieval_composition import build_memory_history

    roots = dict(production_root=tmp_path / "prod", lab_root=tmp_path / "lab")
    binding = lab_binding("thread-history")
    paths = bind_storage(binding, **roots)
    db = CanonicalMemoryStore(paths.memory_db)
    db._commit((memory(),))
    product = MemoryProductStore(paths.memory_db, db)
    product.open_thread(
        thread_id="hello-line",
        scope=memory().scope,
        open_question="Will hello continue?",
        supporting_memory_ids=("memory-1",),
        at=memory().committed_at - timedelta(days=1),
        working_summary="Hello remains an active unresolved line.",
    )
    product.close()
    db.close()

    port = build_memory_history(
        binding,
        thread_enabled=True,
        **roots,
    )
    bundle = port.read(**inputs())
    assert bundle is not None
    assert len(bundle.episodes) == 1
    assert bundle.episodes[0].kind == "memory.thread_projection"
    assert bundle.episodes[0].external_id == "hello-line"
    assert bundle.episodes[0].proposition == "Hello remains an active unresolved line."
    assert bundle.provider_trace == "active-thread-projection"


def test_thread_projection_read_is_opt_in_and_flag_is_typed(tmp_path):
    from mind_runtime.emotional_transition.history import NullHistoricalContext
    from mind_runtime.memory.retrieval_composition import build_memory_history

    binding = lab_binding("thread-disabled")
    assert isinstance(
        build_memory_history(binding, lab_root=tmp_path),
        NullHistoricalContext,
    )
    with pytest.raises(TypeError, match="thread_enabled"):
        build_memory_history(binding, thread_enabled=1, lab_root=tmp_path)


def test_accepted_lce_understanding_precedes_raw_memory_within_shared_budget(
    tmp_path, monkeypatch
):
    from mind_runtime.memory import retrieval_composition

    roots = dict(production_root=tmp_path / "prod", lab_root=tmp_path / "lab")
    binding = lab_binding("lce-history")
    paths = bind_storage(binding, **roots)
    db = CanonicalMemoryStore(paths.memory_db)
    db._commit((memory(),))
    db.close()

    class Reader:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

        def accepted_understandings(self, current_context, *, limit):
            assert current_context == "hello"
            assert limit == 1
            return (
                SimpleNamespace(
                    content="Compiled understanding about hello.",
                    baseline_id="base-1",
                    region_id="mr-thread:t1",
                    revision_number=2,
                    supporting_memory_ids=("memory-1",),
                    source_refs=("evidence-1",),
                    relevance=1.0,
                ),
            )

    monkeypatch.setattr(
        retrieval_composition,
        "open_lce_read_binding",
        lambda *args, **kwargs: Reader(),
    )
    port = retrieval_composition.build_memory_history(
        binding,
        provider=ScriptedProvider((candidate(),)),
        budget=MemorySurfaceBudget(max_items=1, max_characters=4096),
        lce_enabled=True,
        **roots,
    )
    bundle = port.read(**inputs())
    assert bundle is not None
    assert len(bundle.episodes) == 1
    assert bundle.episodes[0].kind == "lce.accepted_understanding"
    assert bundle.episodes[0].proposition == "Compiled understanding about hello."
    assert bundle.provider_trace.startswith("lce-accepted-baseline")


def test_lce_only_history_path_does_not_require_raw_retrieval_provider(tmp_path, monkeypatch):
    from mind_runtime.memory import retrieval_composition

    roots = dict(production_root=tmp_path / "prod", lab_root=tmp_path / "lab")
    binding = lab_binding("lce-only")
    paths = bind_storage(binding, **roots)
    db = CanonicalMemoryStore(paths.memory_db)
    db._commit((memory(),))
    db.close()

    class Reader:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

        def accepted_understandings(self, current_context, *, limit):
            return (
                SimpleNamespace(
                    content="Accepted cognition.",
                    baseline_id="base-only",
                    region_id="mr-thread:t",
                    revision_number=1,
                    supporting_memory_ids=("memory-1",),
                    source_refs=("evidence-1",),
                    relevance=0.5,
                ),
            )

    monkeypatch.setattr(
        retrieval_composition,
        "open_lce_read_binding",
        lambda *args, **kwargs: Reader(),
    )
    port = retrieval_composition.build_memory_history(
        binding,
        lce_enabled=True,
        **roots,
    )
    bundle = port.read(**inputs())
    assert bundle is not None
    assert bundle.episodes[0].external_id == "base-only"


def test_history_composer_empty_and_mismatch_paths_are_bounded(tmp_path, monkeypatch):
    from dataclasses import replace

    from mind_runtime.memory import retrieval_composition

    roots = dict(production_root=tmp_path / "prod", lab_root=tmp_path / "lab")
    binding = lab_binding("projection-empty")
    paths = bind_storage(binding, **roots)
    db = CanonicalMemoryStore(paths.memory_db)
    db._commit((memory(),))
    product = retrieval_composition.MemoryProductStore(paths.memory_db, db)
    product.open_thread(
        thread_id="other-line",
        scope=memory().scope,
        open_question="Will an unrelated purchase happen?",
        supporting_memory_ids=("memory-1",),
        at=memory().committed_at,
    )
    product.close()
    db.close()

    port = retrieval_composition.build_memory_history(
        binding,
        thread_enabled=True,
        lce_enabled=True,
        **roots,
    )

    # Wrong Scope fails before opening any derived read path.
    values = inputs()
    values["scope"] = replace(memory().scope, user_id="other")
    assert port.read(**values) is None

    # No usable current message produces neither Thread nor LCE context.
    values = inputs()
    values["observations"] = ()
    assert port.read(**values) is None

    # A lexical miss does not dump an unrelated active Thread into context.
    values = inputs()
    observation = values["observations"][0]
    values["observations"] = (
        replace(observation, value={"text": "completely different topic"}),
    )
    monkeypatch.setattr(
        retrieval_composition,
        "open_lce_read_binding",
        lambda *args, **kwargs: None,
    )
    assert port.read(**values) is None


def test_lce_empty_read_paths_do_not_create_context(tmp_path, monkeypatch):
    from mind_runtime.memory import retrieval_composition

    roots = dict(production_root=tmp_path / "prod", lab_root=tmp_path / "lab")
    binding = lab_binding("lce-empty")
    paths = bind_storage(binding, **roots)
    db = CanonicalMemoryStore(paths.memory_db)
    db._commit((memory(),))
    db.close()

    class EmptyReader:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

        def accepted_understandings(self, current_context, *, limit):
            return ()

    monkeypatch.setattr(
        retrieval_composition,
        "open_lce_read_binding",
        lambda *args, **kwargs: EmptyReader(),
    )
    port = retrieval_composition.build_memory_history(
        binding,
        lce_enabled=True,
        **roots,
    )
    assert port.read(**inputs()) is None

    with pytest.raises(TypeError, match="lce_enabled"):
        retrieval_composition.build_memory_history(binding, lce_enabled=1, **roots)


def test_merge_projection_budget_skips_duplicate_and_oversized_items():
    from mind_runtime.contracts.historical import HistoricalContextBundle, HistoricalContextItem
    from mind_runtime.memory import retrieval_composition

    scope = memory().scope
    short = HistoricalContextItem(
        item_id="same",
        scope=scope,
        external_id="same",
        kind="lce.accepted_understanding",
        proposition="ok",
        source_refs=("a",),
        confidence=None,
        relevance_hint=1.0,
    )
    duplicate = replace(short, proposition="duplicate")
    oversized = replace(short, item_id="big", external_id="big", proposition="x" * 50)
    lce = HistoricalContextBundle(
        bundle_id="lce",
        scope=scope,
        origin_runtime_id="runtime-1",
        episodes=(short,),
        stable_facts=(),
        relationship_events=(),
        pattern_summaries=(),
        source_refs=("a",),
        provider_trace="lce",
    )
    thread = replace(
        lce,
        bundle_id="thread",
        episodes=(duplicate, oversized),
        provider_trace="thread",
    )
    merged = retrieval_composition._merge_bundles(
        interaction_id="i",
        scope=scope,
        origin_runtime_id="runtime-1",
        budget=MemorySurfaceBudget(max_items=2, max_characters=4),
        lce=lce,
        thread=thread,
        memory=None,
    )
    assert merged is not None
    assert [item.item_id for item in merged.episodes] == ["same"]
    assert merged.provider_trace == "lce+thread"

    assert retrieval_composition._merge_bundles(
        interaction_id="i",
        scope=scope,
        origin_runtime_id="runtime-1",
        budget=MemorySurfaceBudget(max_items=1, max_characters=1),
        lce=lce,
        thread=None,
        memory=None,
    ) is None


def test_enabled_missing_or_mismatched_manifest_fails_closed(tmp_path):
    from mind_runtime.memory.retrieval_composition import build_memory_history
    from mind_runtime.runtime_binding import BindingManifestMismatchError

    binding = lab_binding("retrieval")
    port = build_memory_history(binding, provider=ScriptedProvider(), lab_root=tmp_path)
    with pytest.raises(BindingManifestMismatchError):
        port.read(**inputs())
    paths = bind_storage(binding, lab_root=tmp_path)
    paths.binding_manifest.write_text(json.dumps({"runtime_id": "other"}))
    with pytest.raises(BindingManifestMismatchError):
        port.read(**inputs())
    assert not paths.memory_db.exists()


def test_xiyue_optional_retrieval_uses_existing_port_default_null(tmp_path, monkeypatch):
    from mind_runtime.emotional_transition.history import NullHistoricalContext
    from mind_runtime.host.xiyue_adapter import default_adapter

    monkeypatch.setenv("MR_FACTS_DB", str(tmp_path / "facts.sqlite"))
    monkeypatch.setenv("MR_STATE_DB", str(tmp_path / "state.sqlite"))
    default = default_adapter()
    assert isinstance(default._port._orchestrator.historical_context, NullHistoricalContext)
    assert not (tmp_path / "memory.sqlite").exists()
    db = CanonicalMemoryStore(tmp_path / "memory.sqlite")
    db._commit((memory(),))
    db.close()
    configured = default_adapter(retrieval_provider=ScriptedProvider((candidate(),)))
    bundle = configured._port._orchestrator.historical_context.read(**inputs())
    assert bundle.episodes[0].external_id == "memory-1"


def test_actual_host_admitted_message_reaches_retrieval(tmp_path, monkeypatch):
    from mind_runtime.host.xiyue_adapter import default_adapter

    monkeypatch.setenv("MR_ENABLED", "true")
    monkeypatch.setenv("MR_FACTS_DB", str(tmp_path / "facts.sqlite"))
    monkeypatch.setenv("MR_STATE_DB", str(tmp_path / "state.sqlite"))
    db = CanonicalMemoryStore(tmp_path / "memory.sqlite")
    db._commit((memory(),))
    db.close()
    before = (tmp_path / "memory.sqlite").read_bytes()
    provider = ScriptedProvider((candidate(),))
    adapter = default_adapter(retrieval_provider=provider)
    handle = adapter.begin_turn(
        message="recall hello", channel="test", session_id="s", message_id="1"
    )
    assert handle is not None
    assert len(provider.queries) == 1
    assert provider.queries[0].text == "recall hello"
    assert provider.queries[0].scope == memory().scope
    assert (tmp_path / "memory.sqlite").read_bytes() == before


def test_reads_leave_all_existing_runtime_databases_unchanged(tmp_path, monkeypatch):
    from mind_runtime.host.xiyue_adapter import default_adapter

    monkeypatch.setenv("MR_FACTS_DB", str(tmp_path / "facts.sqlite"))
    monkeypatch.setenv("MR_STATE_DB", str(tmp_path / "state.sqlite"))
    db = CanonicalMemoryStore(tmp_path / "memory.sqlite")
    db._commit((memory(),))
    db.close()
    adapter = default_adapter(retrieval_provider=ScriptedProvider((candidate(),)))
    before = {p: p.read_bytes() for p in tmp_path.iterdir() if p.is_file()}
    for _ in range(5):
        assert adapter._port._orchestrator.historical_context.read(**inputs()) is not None
    assert {p: p.read_bytes() for p in tmp_path.iterdir() if p.is_file()} == before


def test_retrieval_with_site_packages_disabled(tmp_path):
    import subprocess
    import sys
    from pathlib import Path

    source = Path(__file__).resolve().parents[2] / "src"
    metadata = tmp_path / "mind_runtime-0.0.0.dist-info"
    metadata.mkdir()
    (metadata / "METADATA").write_text("Name: mind-runtime\nVersion: 0.0.0\n")
    db = CanonicalMemoryStore(tmp_path / "memory.sqlite")
    db._commit((memory(),))
    db.close()
    code = """
import sys
sys.path[:0] = sys.argv[1:3]
from pathlib import Path
from mind_runtime.contracts import Scope, ScopeDomain
from mind_runtime.memory.store import CanonicalMemoryStore
from mind_runtime.memory.retrieval import (
    MemoryRetrievalService, MemoryRetrievalQuery, RetrievedMemoryCandidate,
)
from mind_runtime.memory.history import MemoryHistoricalContextAdapter
class Provider:
    def search(self, query): return (RetrievedMemoryCandidate('memory-1', 'fake'),)
db = CanonicalMemoryStore(Path(sys.argv[2]) / 'memory.sqlite', read_only=True)
reader = MemoryRetrievalService(store=db, provider=Provider())
query = MemoryRetrievalQuery(Scope(ScopeDomain.USER, user_id='user'), 'hello')
assert reader.search(query)[0].memory.content == 'hello'
assert not any(k.startswith(('mem0', 'chromadb', 'qdrant', 'langchain')) for k in sys.modules)
db.close()
"""
    result = subprocess.run(
        [sys.executable, "-S", "-c", code, str(source), str(tmp_path)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
