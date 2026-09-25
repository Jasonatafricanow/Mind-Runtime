from pathlib import Path

import pytest

from tests.facts.test_admission import NOW
from tests.memory.test_admission import admit
from tests.support.fake_clock import FakeClock


def test_bound_fact_composition_default_off_and_explicit_on(tmp_path, monkeypatch):
    from mind_runtime.memory.composition import build_bound_fact_service
    from mind_runtime.memory.store import CanonicalMemoryStore
    from mind_runtime.runtime_binding import bind_storage, production_binding

    monkeypatch.setenv("MR_FACTS_DB", str(tmp_path / "facts.sqlite"))
    monkeypatch.setenv("MR_STATE_DB", str(tmp_path / "state.sqlite"))
    binding = production_binding("p", runtime_id="runtime-1")
    paths = bind_storage(binding)
    service = build_bound_fact_service(binding, clock=FakeClock(NOW))
    admit(service)
    assert not paths.memory_db.exists()
    service = build_bound_fact_service(binding, clock=FakeClock(NOW), enabled=True)
    admit(service)  # historical replay remains excluded
    from tests.facts.test_admission import make_evidence

    admit(service, make_evidence(evidence_id="new-source"))
    store = CanonicalMemoryStore(paths.memory_db)
    assert len(store.load_all()) == 1
    assert store.load_all()[0].provenance.evidence_refs == ("new-source",)
    store.close()


def test_thread_projection_composition_keeps_compiler_behind_port():
    from mind_runtime.memory.composition import build_bound_thread_updates
    from mind_runtime.runtime_binding import production_binding

    binding = production_binding("p")
    assert build_bound_thread_updates(binding) is None
    with pytest.raises(ValueError, match="enabled"):
        build_bound_thread_updates(binding, enabled=1)
    with pytest.raises(ValueError, match="projection_compiler"):
        build_bound_thread_updates(binding, projection_compiler=object())


def test_stack_enabled_requires_matching_binding_paths(tmp_path):
    from mind_runtime.shadow.runtime_loop import build_runtime_stack

    with pytest.raises(ValueError, match="binding"):
        build_runtime_stack(
            clock=FakeClock(NOW),
            facts_db=tmp_path / "facts.sqlite",
            state_db=tmp_path / "state.sqlite",
            memory_enabled=True,
            origin_runtime_id="runtime-1",
            user_id="user",
        )


def test_runtime_composition_injects_lce_compiler_above_memory_core(tmp_path, monkeypatch):
    from mind_runtime.integrations.lce import LceThreadProjectionCompiler
    from mind_runtime.runtime_binding import production_binding
    from mind_runtime.shadow.runtime_loop import build_runtime_stack

    monkeypatch.setenv("MR_FACTS_DB", str(tmp_path / "facts.sqlite"))
    monkeypatch.setenv("MR_STATE_DB", str(tmp_path / "state.sqlite"))
    binding = production_binding("p", runtime_id="runtime-1")

    orchestrator, _ = build_runtime_stack(
        clock=FakeClock(NOW),
        facts_db=tmp_path / "facts.sqlite",
        state_db=tmp_path / "state.sqlite",
        origin_runtime_id="runtime-1",
        user_id="user",
        memory_enabled=True,
        memory_binding=binding,
        lce_enabled=True,
    )
    assert orchestrator._thread_updates is not None
    assert isinstance(
        orchestrator._thread_updates._projection_compiler,
        LceThreadProjectionCompiler,
    )

    with pytest.raises(ValueError, match="lce_enabled"):
        build_runtime_stack(
            clock=FakeClock(NOW),
            facts_db=tmp_path / "facts.sqlite",
            state_db=tmp_path / "state.sqlite",
            origin_runtime_id="runtime-1",
            user_id="user",
            lce_enabled=1,
        )


def test_xiyue_enabled_new_fact_commits_in_bound_memory_db(tmp_path, monkeypatch):
    from mind_runtime.host.xiyue_adapter import default_adapter
    from mind_runtime.memory.store import CanonicalMemoryStore
    from mind_runtime.runtime_binding import production_binding

    monkeypatch.setenv("MR_FACTS_DB", str(tmp_path / "facts.sqlite"))
    monkeypatch.setenv("MR_STATE_DB", str(tmp_path / "state.sqlite"))
    binding = production_binding("kayla_v0", runtime_id="runtime-1")
    adapter = default_adapter(binding=binding, memory_enabled=True)
    # The actual production stack's FactIngestService owns admission.
    admit(adapter._port._orchestrator.fact_ingest)
    store = CanonicalMemoryStore(tmp_path / "memory.sqlite")
    assert len(store.load_all()) == 1
    assert store.load_all()[0].origin_runtime_id == binding.runtime_id
    store.close()


def test_real_host_turn_flows_through_memory_admission(tmp_path, monkeypatch):
    from mind_runtime.host.xiyue_adapter import default_adapter
    from mind_runtime.memory.store import CanonicalMemoryStore

    monkeypatch.setenv("MR_ENABLED", "true")
    monkeypatch.setenv("MR_FACTS_DB", str(tmp_path / "facts.sqlite"))
    monkeypatch.setenv("MR_STATE_DB", str(tmp_path / "state.sqlite"))
    adapter = default_adapter(memory_enabled=True)
    handle = adapter.begin_turn(message="hello", channel="test", session_id="s", message_id="1")
    assert handle is not None
    db = CanonicalMemoryStore(tmp_path / "memory.sqlite")
    assert len(db.load_all()) == 1
    assert db.load_all()[0].content == "hello"
    db.close()


def test_production_and_lab_admission_have_zero_cross_visibility(tmp_path, monkeypatch):
    import mind_runtime.runtime_binding as rb
    from mind_runtime.memory.composition import build_bound_fact_service
    from mind_runtime.memory.store import CanonicalMemoryStore
    from tests.facts.test_admission import make_evidence

    monkeypatch.delenv("MR_FACTS_DB", raising=False)
    monkeypatch.delenv("MR_STATE_DB", raising=False)
    monkeypatch.setattr(rb, "DEFAULT_PRODUCTION_ROOT", tmp_path / "prod")
    monkeypatch.setattr(rb, "DEFAULT_LAB_ROOT", tmp_path / "lab")
    production = rb.production_binding("p", runtime_id="runtime-1")
    lab = rb.RuntimeBinding("p", "same-body", "lab-runtime", "exp", rb.RuntimeEnvironment.LAB)
    a = build_bound_fact_service(production, clock=FakeClock(NOW), enabled=True)
    b = build_bound_fact_service(lab, clock=FakeClock(NOW), enabled=True)
    admit(a, make_evidence(evidence_id="production-only"))
    admit(b, make_evidence(evidence_id="lab-only"))
    for binding, expected in [(production, "production-only"), (lab, "lab-only")]:
        db = CanonicalMemoryStore(rb.resolve_storage_paths(binding).memory_db)
        assert [m.provenance.evidence_refs for m in db.load_all()] == [(expected,)]
        db.close()


@pytest.mark.parametrize("mismatch", ["facts", "state", "origin"])
def test_conflicting_binding_rejected_before_memory_creation(tmp_path, monkeypatch, mismatch):
    from mind_runtime.runtime_binding import production_binding
    from mind_runtime.shadow.runtime_loop import build_runtime_stack

    monkeypatch.setenv("MR_FACTS_DB", str(tmp_path / "facts.sqlite"))
    monkeypatch.setenv("MR_STATE_DB", str(tmp_path / "state.sqlite"))
    kwargs = dict(
        facts_db=tmp_path / "facts.sqlite",
        state_db=tmp_path / "state.sqlite",
        origin_runtime_id="xiyue",
    )
    kwargs[{"facts": "facts_db", "state": "state_db", "origin": "origin_runtime_id"}[mismatch]] = (
        "other"
    )
    with pytest.raises(ValueError, match="binding"):
        build_runtime_stack(
            clock=FakeClock(NOW),
            user_id="user",
            memory_enabled=True,
            memory_binding=production_binding("p"),
            **kwargs,
        )
    assert not (tmp_path / "memory.sqlite").exists()


def test_no_site_packages_required_for_canonical_authority(tmp_path):
    import subprocess
    import sys

    source = Path(__file__).resolve().parents[2] / "src"
    # The package requires its own distribution metadata, not third-party imports.
    metadata = tmp_path / "mind_runtime-0.0.0.dist-info"
    metadata.mkdir()
    (metadata / "METADATA").write_text("Name: mind-runtime\nVersion: 0.0.0\n")
    code = """
import sys
sys.path.insert(0, sys.argv[1])
sys.path.insert(0, sys.argv[2])
from mind_runtime.memory.composition import build_bound_fact_service
from mind_runtime.memory.store import CanonicalMemoryStore
from mind_runtime.memory.projection import ProjectionWorker
from mind_runtime.runtime_binding import production_binding
from mind_runtime.contracts import (
    Evidence, Scope, ScopeDomain, Authority, AuthorityLevel, SyncFields,
)
from datetime import datetime, UTC
from pathlib import Path
import os
os.environ['MR_FACTS_DB'] = str(Path(sys.argv[2]) / 'facts.sqlite')
os.environ['MR_STATE_DB'] = str(Path(sys.argv[2]) / 'state.sqlite')
class Clock:
    def now(self): return datetime(2026, 9, 7, tzinfo=UTC)
clock = Clock()
scope = Scope(ScopeDomain.USER, user_id='u')
ev = Evidence(id='e', scope=scope, origin_runtime_id='xiyue', source_type='user_message',
    source_id='s', authority_level=AuthorityLevel.ASSERTED,
    authority=Authority(scope, AuthorityLevel.ASSERTED, 's'), occurred_at=clock.now(),
    received_at=clock.now(), payload={'text':'hello'}, sync=SyncFields(scope,'xiyue','e',1,'e'))
svc = build_bound_fact_service(production_binding('p'), clock=clock, enabled=True)
svc.admit(ev, interaction_id='i', writing_runtime='xiyue', writing_persona_id=None)
db = CanonicalMemoryStore(Path(sys.argv[2]) / 'memory.sqlite')
assert len(db.load_all()) == 1
assert not any(k.startswith(('mem0', 'chromadb', 'qdrant', 'langchain')) for k in sys.modules)
db.close()
"""
    result = subprocess.run(
        [sys.executable, "-S", "-c", code, str(source), str(tmp_path)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
