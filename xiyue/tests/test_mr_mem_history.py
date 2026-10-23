"""Real MR-Mem admission/storage -> existing MR historical context seam."""

import sqlite3
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from mr_mem import MemoryCore, SemanticMemoryCandidate, SourceRef
from mr_mem import Scope as MemScope
from mr_mem import ScopeDomain as MemDomain

from mind_runtime.contracts import Observation, Scope, ScopeDomain, Situation, SyncFields
from mind_runtime.integrations.mr_mem_history import MrMemHistoricalContext

NOW = datetime(2026, 10, 20, tzinfo=UTC)
SCOPE = Scope(ScopeDomain.USER, user_id="u1")
MEM_SCOPE = MemScope(MemDomain.USER, user_id="u1")


def admit(core, *, scope=MEM_SCOPE, known_at=NOW, key="one",
          content="Daily reports should contain exceptions only."):
    ref = SourceRef("native", "session", key, NOW - timedelta(days=1), revision="1")
    admission = core.semantic_admission(
        sources=SimpleNamespace(current_ref=lambda s, r: ref if s == scope else None),
        clock=SimpleNamespace(now=lambda: known_at), origin_runtime_id="test-host",
    )
    # Explicit host-accepted fixture; no claim of automatic semantic correctness.
    return admission.admit(SemanticMemoryCandidate(
        key, scope, content, (ref,), "fixture-v1",
    ))


def read(adapter, scope=SCOPE):
    situation = Situation("s", scope, "runtime", (), "state", NOW, None, None, (), ())
    observation = Observation(
        "o", "turn", scope, "factual", "user_message.observed", {"text": "Daily reports"},
        1.0, NOW, ("e",), "runtime", SyncFields(scope, "runtime", "o", 1, "o"),
    )
    return adapter.read(
        interaction_id="turn", context=situation, observations=(observation,),
        scope=scope, clock=NOW,
    )


@pytest.mark.parametrize("change", ["invalidate", "suppress", "new", "future", "other_scope"])
def test_fresh_read_tracks_durable_memory_changes_without_writes(tmp_path, change):
    path = tmp_path / "canonical.sqlite"
    with MemoryCore(path) as core:
        memory = admit(core)
    adapter = MrMemHistoricalContext(path)
    initial = read(adapter)
    assert initial.episodes[0].external_id == memory.memory_id
    assert initial.episodes[0].scope == SCOPE
    assert initial.source_refs == (memory.provenance.source_refs[0].source_key,)
    with MemoryCore(path) as core:
        if change == "invalidate":
            core.canonical.invalidate_source(
                MEM_SCOPE, memory.provenance.source_refs[0], deleted=True, at=NOW,
            )
        elif change == "suppress":
            core.products.set_attention(memory.memory_id, dont_surface=True)
        else:
            admit(core, key="two", known_at=NOW + timedelta(days=change == "future"),
                  scope=MemScope(MemDomain.USER, user_id="u2") if change == "other_scope"
                  else MEM_SCOPE)
    before = path.read_bytes()
    result = read(adapter)
    if change in ("invalidate", "suppress"):
        assert result is None
    else:
        assert len(result.episodes) == (2 if change == "new" else 1)
    assert path.read_bytes() == before


def test_missing_enabled_database_is_an_error_and_is_not_created(tmp_path):
    path = tmp_path / "missing.sqlite"
    with pytest.raises(sqlite3.OperationalError):
        read(MrMemHistoricalContext(path))
    assert not path.exists()


@pytest.mark.parametrize("with_graph", [False, True])
def test_default_host_assembly_reads_sidecar_on_each_turn_and_after_restart(
    tmp_path, monkeypatch, with_graph,
):
    from mind_runtime import runtime_binding
    from mind_runtime.host.xiyue_adapter import default_adapter
    from mind_runtime.runtime_binding import RuntimeBinding, RuntimeEnvironment

    monkeypatch.setenv("MR_ENABLED", "true")
    monkeypatch.setenv("MR_USER_ID", "u1")
    monkeypatch.setenv("MR_FACTS_DB", str(tmp_path / "facts.sqlite"))
    monkeypatch.setenv("MR_STATE_DB", str(tmp_path / "state.sqlite"))
    monkeypatch.setenv("MR_SEMANTIC_PROVIDER", "off")
    monkeypatch.setattr(runtime_binding, "DEFAULT_PRODUCTION_ROOT", tmp_path / "runtime")
    binding = RuntimeBinding(
        persona_id="kayla_v0", agent_id="assembly-test", runtime_id="assembly-test",
        storage_namespace="production/assembly-test", environment=RuntimeEnvironment.PRODUCTION,
    )
    db = tmp_path / "canonical.sqlite"
    graph_root = tmp_path / "lce_tree" if with_graph else None
    native = tmp_path / "native.sqlite"
    with sqlite3.connect(native) as conn:
        conn.execute("CREATE TABLE messages(content TEXT)")
    original = native.read_bytes()
    with pytest.raises(sqlite3.OperationalError):
        default_adapter(binding=binding, mr_mem_db=native)
    assert native.read_bytes() == original
    adapter = default_adapter(binding=binding, mr_mem_db=db, mr_mem_line_root=graph_root)
    assert db.exists() and adapter._scope.user_id == "u1"
    host = adapter._port
    # Default deterministic turn ports are plumbing fixtures, not accepted algorithms.
    handle = adapter.begin_turn(message="Daily reports", channel="test", session_id="s",
                                message_id="empty", occurred_at=NOW)
    assert handle is not None
    assert adapter.commit_turn(handle)
    with MemoryCore(db) as core:
        memory = admit(core)
        expected = [memory]
        if with_graph:
            from mr_mem.lce.path_a import Attachment, BlockLines, PathATree

            changed = admit(core, key="two", content="Switch to weekly summaries instead.")
            expected.append(changed)
            tree = PathATree(graph_root, MEM_SCOPE, canonical=core.canonical,
                             products=core.products, fingerprint="accepted-fixture")
            tree.apply([
                BlockLines(memory.memory_id, (Attachment(None, None, False, None),)),
                BlockLines(changed.memory_id, (Attachment(None, "b1", True, None),)),
            ], {}, NOW, open_matters=False)
            tree.close()
    restarted = default_adapter(binding=binding, mr_mem_db=db, mr_mem_line_root=graph_root)
    for current, mid in ((adapter, "new"), (restarted, "restart")):
        handle = current.begin_turn(message="Daily reports", channel="test", session_id="s",
                                    message_id=mid, occurred_at=NOW)
        assert handle is not None
        history = current._port.orchestrator._turn.situation.historical_context
        if with_graph:
            assert history.episodes[0].kind == "memory.line"
            assert "Switch to weekly summaries instead." in history.episodes[0].proposition
            assert "Recorded progression:" in history.episodes[0].proposition
            assert len(history.source_refs) == 2
        else:
            assert history.episodes[0].external_id == memory.memory_id
        assert current.commit_turn(handle)
    # Replayed delivery never re-enters the pipeline or creates duplicate canonical memory.
    previous_turn = host.orchestrator._turn
    replay = adapter.begin_turn(message="Daily reports", channel="test", session_id="s",
                                message_id="new", occurred_at=NOW)
    assert replay is not None
    assert host.orchestrator._turn is previous_turn
    with MemoryCore(db) as core:
        assert set(m.memory_id for m in core.load_all()) == {m.memory_id for m in expected}


@pytest.mark.parametrize("boundary", ["hidden", "future", "other_scope"])
def test_mr_graph_expansion_cannot_bypass_surface_policy(tmp_path, boundary):
    from mr_mem.lce.path_a import Attachment, BlockLines, PathATree

    db, root = tmp_path / "canonical.sqlite", tmp_path / "lce_tree"
    with MemoryCore(db) as core:
        first = admit(core)
        second = admit(
            core, key="two", content="Restricted successor text.",
            known_at=NOW + timedelta(days=boundary == "future"),
            scope=MemScope(MemDomain.USER, user_id="other") if boundary == "other_scope"
            else MEM_SCOPE,
        )
        tree = PathATree(root, MEM_SCOPE, canonical=core.canonical,
                         products=core.products, fingerprint="accepted-fixture")
        # Even a malformed graph containing another scope must not leak its content.
        tree.apply([
            BlockLines(first.memory_id, (Attachment(None, None, False, None),)),
            BlockLines(second.memory_id, (Attachment(None, "b1", True, None),)),
        ], {}, NOW, open_matters=False)
        tree.close()
        if boundary == "hidden":
            core.products.set_attention(second.memory_id, dont_surface=True)
    files = [db, *root.rglob("*.sqlite")]
    before = {p: p.read_bytes() for p in files}
    bundle = read(MrMemHistoricalContext(db, line_root=root))
    assert "Restricted successor" not in str(bundle)
    assert bundle.source_refs == (first.provenance.source_refs[0].source_key,)
    assert {p: p.read_bytes() for p in files} == before


@pytest.mark.parametrize("options", [
    {"memory_enabled": True}, {"lce_enabled": True}, {"lce_inspiration_enabled": True},
])
def test_two_memory_compositions_are_rejected_before_storage(tmp_path, options):
    from mind_runtime.host.xiyue_adapter import default_adapter

    with pytest.raises(ValueError, match="legacy Memory/LCE"):
        default_adapter(mr_mem_db=tmp_path / "canonical.sqlite", **options)
    assert list(tmp_path.iterdir()) == []
