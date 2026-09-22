import importlib
from dataclasses import replace

import pytest
from tests.emotional_transition.test_effects import (
    AGENT_SCOPE,
    candidate,
    context,
    history,
    pattern,
    profile,
    rule,
)

from mind_runtime.contracts import AppraisalModelProposal, SemanticAppraisalContext
from mind_runtime.emotional_transition.appraisal import SemanticAppraisalProducer


class NovelModel:
    calls = 0

    def propose(self, **kwargs):
        self.calls += 1
        return AppraisalModelProposal(
            ("recognition", "relief", "increased_confidence_in_user"),
            "positive",
            "meaningful",
            0.8,
            0.9,
            ("evidence-current",),
        )


def accepted(kind="user_completed_difficult_task_independently"):
    producer = SemanticAppraisalProducer(model=NovelModel())
    assert hasattr(producer, "accept"), "producer must own independent semantic acceptance"
    c = candidate(kind=kind)
    ctx = SemanticAppraisalContext(c, context(), (profile(),), None)
    return producer.accept(
        candidate=c,
        context=ctx,
        interaction_id="interaction-1",
        persona_id="test",
        route_abstention_reasons=(),
        projection_scope=AGENT_SCOPE,
    )


def projector(**kwargs):
    module = importlib.import_module("mind_runtime.emotional_transition.effects")
    assert hasattr(module, "AppraisalProjector"), "single late projector is missing"
    from mind_runtime.contracts import StateDefinition, StateDomain, StateValueType
    from mind_runtime.dynamics.persona import PersonaProfile
    from mind_runtime.state.definitions import StateDefinitionRegistry

    kwargs.setdefault("persona_profile", PersonaProfile("test", (profile(),), 1))
    kwargs.setdefault("definitions", StateDefinitionRegistry((StateDefinition(
        rule().dimension, StateDomain.AGENT, StateValueType.SCALAR,
        "deterministic_affect", None, (0.0, 1.0)),)))
    return module.AppraisalProjector(rules=(rule(),), **kwargs)


def test_novel_accepted_unmapped_meaning_preserved():
    record = accepted()
    result = projector().project(acceptance=record, history=None, persona=(profile(),))
    assert record.status == "ACCEPTED"
    assert result.status == "UNMAPPED"
    assert result.effects == ()
    assert result.reason_codes == ("no_runtime_projection_rule",)
    assert result.source_appraisal_ref == record.appraisal.appraisal_id
    assert record.appraisal.meanings == ("recognition", "relief", "increased_confidence_in_user")


def test_materialization_restart_and_no_model_call(tmp_path):
    record = accepted()
    p = projector()
    module = importlib.import_module("mind_runtime.emotional_transition.projection_journal")
    path = tmp_path / "derived.sqlite"
    journal = module.ProjectionJournal(path)
    result = journal.materialize(p, acceptance=record, history=None, persona=(profile(),))
    journal.close()
    reopened = module.ProjectionJournal(path)
    p.project = lambda **kwargs: pytest.fail("materialized projection was recomputed")
    assert reopened.materialize(p, acceptance=record, history=None, persona=(profile(),)) == result
    assert reopened.get_acceptance(record.acceptance_id) == record
    reopened.close()


def test_dependency_version_and_authorized_history_invalidate():
    record = accepted("plan_cancelled")
    p = projector()
    a = p.project(acceptance=record, history=None, persona=(profile(),))
    assert p.project(acceptance=record, history=None, persona=(profile(),)) == a
    b = projector(version="2").project(acceptance=record, history=None, persona=(profile(),))
    assert b.dependency_digest != a.dependency_digest
    c = p.project(acceptance=record, history=history(pattern()), persona=(profile(),))
    assert c.dependency_digest != a.dependency_digest
    assert a.status == "MAPPED"
    assert len(a.effects) == 1
    assert a.effects[0].target_scope == AGENT_SCOPE
    assert a.effects[0].target_domain == "agent"


def test_forged_scope_and_route_abstention_fail_closed():
    record = accepted()
    from mind_runtime.contracts import Scope, ScopeDomain

    forged = replace(
        record,
        appraisal=replace(record.appraisal, scope=Scope(domain=ScopeDomain.USER, user_id="other")),
    )
    assert (
        projector().project(acceptance=forged, history=None, persona=(profile(),)).status
        == "REJECTED"
    )
    producer = SemanticAppraisalProducer(model=NovelModel())
    c = candidate()
    r = producer.accept(
        candidate=c,
        context=SemanticAppraisalContext(c, context(), (profile(),), None),
        interaction_id="interaction-1",
        persona_id="test",
        route_abstention_reasons=("low_confidence",),
    )
    assert r.status == "ABSTAINED"
    assert (
        projector().project(acceptance=r, history=None, persona=(profile(),)).status == "ABSTAINED"
    )


def test_provider_failure_is_not_accepted():
    class Broken:
        def propose(self, **kwargs):
            raise RuntimeError("offline")

    producer = SemanticAppraisalProducer(model=Broken())
    assert hasattr(producer, "accept"), "acceptance must distinguish provider failure"
    c = candidate()
    r = producer.accept(
        candidate=c,
        context=SemanticAppraisalContext(c, context(), (profile(),), None),
        interaction_id="interaction-1",
        persona_id="test",
        route_abstention_reasons=(),
    )
    assert r.status == "ERROR"
    assert projector().project(acceptance=r, history=None, persona=(profile(),)).effects == ()


def test_rejected_untrusted_evidence_even_when_salience_missing():
    class Forged(NovelModel):
        def propose(self, **kwargs):
            return AppraisalModelProposal(
                ("recognition",), "positive", "meaningful", None, 0.9, ("not-in-trusted-pool",)
            )

    producer = SemanticAppraisalProducer(model=Forged())
    c = candidate()
    record = producer.accept(
        candidate=c,
        context=SemanticAppraisalContext(c, context(), (profile(),), None),
        interaction_id="interaction-1",
        persona_id="test",
        route_abstention_reasons=(),
    )
    assert record.status != "ACCEPTED"


def test_projector_rejects_nonfinite_recipe():
    from mind_runtime.emotional_transition.effects import EventEffectRule

    with pytest.raises(ValueError):
        EventEffectRule("event", "agent.affect.anxiety", float("inf"))


def test_projection_uses_zero_model_calls_and_is_stable_across_processes(monkeypatch):
    import os
    import subprocess
    import sys

    from mind_runtime.contracts.late_projection import canonical_json

    record = accepted("plan_cancelled")

    def forbidden(*args, **kwargs):
        pytest.fail("projector attempted model or acceptance inference")

    monkeypatch.setattr(SemanticAppraisalProducer, "accept", forbidden)
    monkeypatch.setattr(SemanticAppraisalProducer, "assemble", forbidden)
    result = projector().project(acceptance=record, history=None, persona=(profile(),))
    script = """
from tests.late_projection.test_foundation import accepted, projector, profile
from mind_runtime.contracts.late_projection import canonical_json
print(canonical_json(projector().project(acceptance=accepted('plan_cancelled'),
                                       history=None, persona=(profile(),))))
"""
    output = subprocess.check_output(
        [sys.executable, "-c", script], env={**os.environ, "PYTHONPATH": "src"}, text=True
    )
    assert output.strip() == canonical_json(result)


def test_acceptance_rejects_foreign_persona_and_history():
    from mind_runtime.contracts import Scope, ScopeDomain

    c = candidate()
    producer = SemanticAppraisalProducer(model=NovelModel())
    for persona_id, hist in [
        ("FOREIGN", None),
        (
            "test",
            replace(history(pattern()), scope=Scope(domain=ScopeDomain.USER, user_id="other")),
        ),
    ]:
        record = producer.accept(
            candidate=c,
            context=SemanticAppraisalContext(c, context(), (profile(),), hist),
            interaction_id="interaction-1",
            persona_id=persona_id,
            route_abstention_reasons=(),
        )
        assert record.status == "REJECTED"


def test_nested_history_ownership_is_checked_before_model_and_projection():
    from mind_runtime.contracts import Scope, ScopeDomain

    foreign = replace(pattern(), scope=Scope(domain=ScopeDomain.USER, user_id="foreign"))
    hist = history(foreign)
    producer = SemanticAppraisalProducer(model=NovelModel())
    c = candidate()
    record = producer.accept(
        candidate=c,
        context=SemanticAppraisalContext(c, context(), (profile(),), hist),
        interaction_id="interaction-1",
        persona_id="test",
        route_abstention_reasons=(),
        projection_scope=AGENT_SCOPE,
    )
    assert record.status == "REJECTED"
    result = projector().project(acceptance=accepted("plan_cancelled"), history=hist)
    assert result.status == "REJECTED"
    assert not result.effects


def test_accepted_effects_require_target_scope():
    c = candidate()
    record = SemanticAppraisalProducer(model=NovelModel()).accept(
        candidate=c,
        context=SemanticAppraisalContext(c, context(), (profile(),), None),
        interaction_id="interaction-1",
        persona_id="test",
        route_abstention_reasons=(),
    )
    assert record.status == "ACCEPTED"
    result = projector().project(acceptance=record, history=None)
    assert result.status == "REJECTED"
    assert not result.effects


def test_corrupt_cached_projection_fails_closed(tmp_path):
    import json

    module = importlib.import_module("mind_runtime.emotional_transition.projection_journal")
    journal = module.ProjectionJournal(tmp_path / "derived.sqlite")
    record = accepted("plan_cancelled")
    journal.materialize(projector(), acceptance=record, history=None)
    row = journal.connection.execute("SELECT payload FROM appraisal_projections").fetchone()
    corrupt = json.loads(row[0])
    corrupt["effects"][0]["amount"] = 999
    journal.connection.execute("UPDATE appraisal_projections SET payload=?", (json.dumps(corrupt),))
    journal.connection.commit()
    with pytest.raises(ValueError):
        journal.materialize(projector(), acceptance=record, history=None)
    journal.close()


def test_journal_scope_lineage_roundtrip_and_payload_conflict(tmp_path):
    record = accepted()
    module = importlib.import_module("mind_runtime.emotional_transition.projection_journal")
    with_journal = module.ProjectionJournal(tmp_path / "derived.sqlite")
    result = with_journal.materialize(projector(), acceptance=record, history=None)
    assert with_journal.get_projection(result.projection_id) == result
    forged = replace(record, appraisal=replace(record.appraisal, evidence_refs=("forged",)))
    with pytest.raises(ValueError, match="lineage"):
        with_journal.materialize(projector(), acceptance=forged, history=None)
    with_journal.close()
