import json

import pytest

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
