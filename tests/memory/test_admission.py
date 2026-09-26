from dataclasses import replace

import pytest

from mind_runtime.facts.persistence import SqliteFactBackend
from mind_runtime.facts.service import FactIngestService
from mind_runtime.facts.validators import AuthorityError
from tests.facts.test_admission import NOW, make_evidence
from tests.support.fake_clock import FakeClock


def setup_plane(tmp_path, enabled=True, extractor=None):
    from mind_runtime.memory.admission import MemoryAdmissionService
    from mind_runtime.memory.store import CanonicalMemoryStore

    backend = SqliteFactBackend(tmp_path / "facts.sqlite")
    store = CanonicalMemoryStore(tmp_path / "memory.sqlite")
    admission = MemoryAdmissionService(
        store=store,
        facts=backend,
        clock=FakeClock(NOW),
        origin_runtime_id="runtime-1",
        enabled=enabled,
        extractor=extractor,
    )
    service = FactIngestService(clock=FakeClock(NOW), backend=backend, after_admission=admission)
    return service, admission, store, backend


def admit(service, evidence=None, *, interaction_id="interaction-1"):
    return service.admit(
        evidence or make_evidence(),
        interaction_id=interaction_id,
        writing_runtime="runtime-1",
        writing_persona_id=None,
    )


def test_admission_on_commits_once_and_restart_replay_is_noop(tmp_path):
    service, _, store, backend = setup_plane(tmp_path)
    admit(service)
    original = store.load_all()
    assert len(original) == 1
    assert original[0].provenance.evidence_refs == ("evidence-1",)
    assert original[0].provenance.interaction_id == "interaction-1"
    assert original[0].content == "hello"
    store.close()
    backend.close()
    service, _, store, backend = setup_plane(tmp_path)
    admit(service)
    assert store.load_all() == original
    store.close()
    backend.close()


def test_default_admission_off_writes_no_jobs_or_memory(tmp_path):
    from mind_runtime.memory.admission import MemoryAdmissionService
    from mind_runtime.memory.store import CanonicalMemoryStore

    backend = SqliteFactBackend(tmp_path / "facts.sqlite")
    store = CanonicalMemoryStore(tmp_path / "memory.sqlite")
    hook = MemoryAdmissionService(
        store=store, facts=backend, clock=FakeClock(NOW), origin_runtime_id="runtime-1"
    )
    admit(FactIngestService(clock=FakeClock(NOW), backend=backend, after_admission=hook))
    assert store.load_all() == ()
    assert store._conn.execute("SELECT COUNT(*) FROM admission_jobs").fetchone()[0] == 0


def test_rejected_evidence_never_creates_job_or_memory(tmp_path):
    service, _, store, _ = setup_plane(tmp_path)
    with pytest.raises(AuthorityError):
        admit(service, make_evidence(source_type="assistant_output"))
    assert service.evidence.count() == 1  # retained for audit, not admitted
    assert store.load_all() == ()
    assert store._conn.execute("SELECT COUNT(*) FROM admission_jobs").fetchone()[0] == 0


def test_enabling_does_not_backfill_historical_replay(tmp_path):
    service, _, store, backend = setup_plane(tmp_path, enabled=False)
    admit(service)
    store.close()
    backend.close()
    service, _, store, _ = setup_plane(tmp_path)
    admit(service)
    assert store.load_all() == ()


@pytest.mark.parametrize("forgery", ["unknown_ref", "scope", "observation"])
def test_extractor_cannot_forge_provenance(tmp_path, forgery):
    from mind_runtime.memory.extraction import DeterministicExtractor

    class Forged:
        def extract(self, evidence, observation):
            c = DeterministicExtractor().extract(evidence, observation)[0]
            if forgery == "unknown_ref":
                c = replace(c, provenance=replace(c.provenance, evidence_refs=("unknown",)))
            elif forgery == "observation":
                c = replace(c, provenance=replace(c.provenance, observation_id="forged"))
            else:
                c = replace(c, scope=replace(c.scope, user_id="intruder"))
            return (c,)

    service, _, store, _ = setup_plane(tmp_path, extractor=Forged())
    assert admit(service).disposition.value == "new"
    assert store.load_all() == ()


def test_extractor_cannot_choose_source_interaction(tmp_path):
    from mind_runtime.memory.extraction import DeterministicExtractor

    class ForgedInteraction:
        def extract(self, evidence, observation):
            candidate = DeterministicExtractor().extract(evidence, observation)[0]
            return (
                replace(
                    candidate,
                    provenance=replace(
                        candidate.provenance,
                        interaction_id="forged-interaction",
                    ),
                ),
            )

    service, _, store, _ = setup_plane(tmp_path, extractor=ForgedInteraction())
    assert (
        admit(service, interaction_id="authoritative-interaction").disposition.value
        == "new"
    )
    memories = store.load_all()
    assert len(memories) == 1
    assert memories[0].provenance.interaction_id == "authoritative-interaction"


def test_forged_admission_result_without_durable_pair_rejected(tmp_path):
    from mind_runtime.facts.ports import FactAdmissionDisposition, FactAdmissionResult

    service, hook, store, _ = setup_plane(tmp_path)
    evidence = make_evidence()
    fake = service._build_observation(evidence, interaction_id="i", observed_at=NOW)
    with pytest.raises(ValueError):
        hook.after_admission(evidence, FactAdmissionResult(fake, FactAdmissionDisposition.NEW))
    assert store.load_all() == ()


def test_extraction_failure_resumes_only_registered_job(tmp_path):
    class Down:
        def extract(self, evidence, observation):
            raise RuntimeError("extractor unavailable")

    service, _, store, backend = setup_plane(tmp_path, extractor=Down())
    assert admit(service).disposition.value == "new"
    assert store.load_all() == ()
    store.close()
    backend.close()
    service, _, store, _ = setup_plane(tmp_path)
    admit(service)
    assert len(store.load_all()) == 1


def test_candidate_identity_is_stable_and_separate(tmp_path):
    from mind_runtime.memory.extraction import DeterministicExtractor, memory_identity

    service, _, store, _ = setup_plane(tmp_path)
    evidence = make_evidence()
    result = admit(service, evidence)
    c = DeterministicExtractor().extract(evidence, result.observation)[0]
    mid = memory_identity(c, "runtime-1")
    assert mid == store.load_all()[0].memory_id
    assert mid == memory_identity(c, "runtime-1")
    assert mid != memory_identity(replace(c, candidate_id="different"), "runtime-1")


def test_fact_to_job_crash_does_not_authorize_backfill(tmp_path, monkeypatch):
    service, _, store, backend = setup_plane(tmp_path)

    def crash(*args):
        raise KeyboardInterrupt("before job registration")

    monkeypatch.setattr(store, "_register_job", crash)
    with pytest.raises(KeyboardInterrupt):
        admit(service)
    store.close()
    backend.close()
    service, _, store, _ = setup_plane(tmp_path)
    admit(service)
    assert store.load_all() == ()


def test_atomic_job_completion_reuses_frozen_candidates_after_failure(tmp_path):
    import sqlite3

    service, _, store, backend = setup_plane(tmp_path)
    with sqlite3.connect(tmp_path / "memory.sqlite") as fault:
        fault.execute(
            "CREATE TRIGGER fail_outbox BEFORE INSERT ON projection_intents "
            "BEGIN SELECT RAISE(ABORT, 'outbox unavailable'); END"
        )
    assert admit(service).disposition.value == "new"
    assert store.load_all() == ()
    assert store._conn.execute("SELECT done FROM admission_jobs").fetchone() == (0,)
    store.close()
    backend.close()
    with sqlite3.connect(tmp_path / "memory.sqlite") as fault:
        fault.execute("DROP TRIGGER fail_outbox")

    class MustNotReextract:
        def extract(self, evidence, observation):
            raise AssertionError("frozen candidate must survive restart")

    service, _, store, _ = setup_plane(tmp_path, extractor=MustNotReextract())
    admit(service)
    assert len(store.load_all()) == 1
    assert store._conn.execute("SELECT done FROM admission_jobs").fetchone() == (1,)


def test_repaired_old_evidence_does_not_register_memory(tmp_path):
    service, _, store, backend = setup_plane(tmp_path)
    backend.save_evidence(make_evidence(), interaction_id="interaction-1")
    store.close()
    backend.close()
    service, _, store, _ = setup_plane(tmp_path)
    assert admit(service).disposition.value == "repaired"
    assert store.load_all() == ()


def test_multiple_candidates_are_atomic_on_conflict(tmp_path):
    from mind_runtime.memory.extraction import DeterministicExtractor

    class Duplicate:
        def extract(self, evidence, observation):
            candidate = DeterministicExtractor().extract(evidence, observation)[0]
            return (candidate, replace(candidate, content="different"))

    service, _, store, _ = setup_plane(tmp_path, extractor=Duplicate())
    assert admit(service).disposition.value == "new"
    assert store.load_all() == ()
    assert store.projection_queue().pending(10) == ()


def test_optional_memory_failure_preserves_new_factual_result(tmp_path, caplog):
    class Down:
        def extract(self, evidence, observation):
            raise RuntimeError("extractor unavailable")

    service, _, store, _ = setup_plane(tmp_path, extractor=Down())
    assert admit(service).disposition.value == "new"
    assert service.observations.count() == 1
    assert store.load_all() == ()
    assert "RuntimeError" in caplog.text


def test_orchestrator_consumes_new_once_when_memory_fails(tmp_path):
    from tests.pipeline.test_fact_admission_turn import make_interaction, make_orchestrator

    class Down:
        def extract(self, evidence, observation):
            raise RuntimeError("unavailable")

    service, _, store, _ = setup_plane(tmp_path, extractor=Down())
    orch = make_orchestrator(service)
    interaction = replace(make_interaction(), scope=make_evidence().scope)
    orch.begin_turn(interaction)
    orch.ingest(make_evidence())
    assert len(orch.observations) == 1
    orch.abort_turn()
    orch.begin_turn(replace(interaction, interaction_id="interaction-2", turn_id="turn-2"))
    orch.ingest(make_evidence())
    assert orch.observations == ()
    assert store.load_all() == ()
