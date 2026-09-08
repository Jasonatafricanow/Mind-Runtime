from dataclasses import replace

import pytest

from mind_runtime.contracts import Situation
from tests.facts.test_admission import make_evidence, make_service
from tests.memory.test_contracts import memory
from tests.memory_retrieval.test_retrieval import candidate, service


def inputs():
    m = memory()
    observation = (
        make_service()
        .admit(
            make_evidence(evidence_id="current-evidence", scope=m.scope),
            interaction_id="turn",
            writing_runtime=m.origin_runtime_id,
            writing_persona_id=None,
        )
        .observation
    )
    context = Situation(
        "s",
        m.scope,
        m.origin_runtime_id,
        (),
        "state",
        m.committed_at,
        None,
        None,
        (),
        ("current-evidence",),
    )
    return dict(
        interaction_id="turn",
        context=context,
        observations=(observation,),
        scope=m.scope,
        clock=m.committed_at,
    )


def test_existing_port_projects_only_canonical_content_and_provenance(tmp_path):
    from mind_runtime.memory.history import MemoryHistoricalContextAdapter

    reader, db, provider = service(tmp_path, (candidate(provider_text="lie", score=0.9),))
    adapter = MemoryHistoricalContextAdapter(reader)
    before = db.load_all()
    for _ in range(3):
        bundle = adapter.read(**inputs())
        assert bundle.episodes[0].proposition == "hello"
        assert bundle.episodes[0].external_id == "memory-1"
        assert bundle.source_refs == ("evidence-1",)
        assert bundle.episodes[0].confidence is None
        assert bundle.episodes[0].relevance_hint is None
        assert bundle.pattern_summaries == ()
    assert db.load_all() == before
    assert provider.queries[0].text == "hello"


@pytest.mark.parametrize("current_ref", ["observation", "evidence"])
def test_current_sources_never_reenter_as_history(tmp_path, current_ref):
    from mind_runtime.memory.history import MemoryHistoricalContextAdapter

    m = memory()
    provenance = replace(
        m.provenance,
        **(
            {"observation_id": inputs()["observations"][0].id}
            if current_ref == "observation"
            else {"evidence_refs": ("current-evidence",)}
        ),
    )
    reader, _, _ = service(tmp_path, (candidate(),), (replace(m, provenance=provenance),))
    assert MemoryHistoricalContextAdapter(reader).read(**inputs()) is None


def test_no_current_message_no_query_and_outage_is_not_empty(tmp_path):
    from mind_runtime.memory.history import MemoryHistoricalContextAdapter
    from mind_runtime.memory.retrieval import RetrievalProviderUnavailable

    reader, _, provider = service(tmp_path, error=TimeoutError())
    adapter = MemoryHistoricalContextAdapter(reader)
    assert adapter.read(**(inputs() | {"observations": ()})) is None
    assert provider.queries == []
    with pytest.raises(RetrievalProviderUnavailable):
        adapter.read(**inputs())


def test_scope_mismatch_fails_before_discovery(tmp_path):
    from mind_runtime.memory.history import MemoryHistoricalContextAdapter

    reader, _, provider = service(tmp_path, (candidate(),))
    values = inputs()
    values["scope"] = replace(memory().scope, user_id="other")
    assert MemoryHistoricalContextAdapter(reader).read(**values) is None
    assert provider.queries == []
