"""RED contracts for target authority and versioned evaluation identity."""

import os
import subprocess
import sys
from dataclasses import replace
from datetime import timedelta

import pytest
from tests.emotional_transition.test_effects import history, pattern
from tests.late_projection.test_foundation import accepted, profile

from mind_runtime.contracts import StateDefinition, StateDomain, StateValueType
from mind_runtime.contracts.late_projection import ProjectionEffect, canonical_json, digest
from mind_runtime.dynamics.engine import DynamicsEngine
from mind_runtime.dynamics.persona import PersonaProfile
from mind_runtime.emotional_transition.effects import (
    AppraisalProjector,
    EventEffectRule,
    mapping_from_projection,
)
from mind_runtime.emotional_transition.projection_journal import ProjectionJournal
from mind_runtime.state.definitions import StateDefinitionRegistry

FAST = "agent.affect.anxiety"
SLOW = "agent.slow.trust"
OTHER = "agent.affect.curiosity"


def definition(key, policy, *, bounds=(0.0, 1.0), domain=StateDomain.AGENT):
    return StateDefinition(key, domain, StateValueType.SCALAR, policy, None, bounds)


def registry(*, fast=None, slow=None, other=None):
    return StateDefinitionRegistry(tuple(item for item in (fast, slow, other) if item is not None))


def fast_definition(**changes):
    return replace(definition(FAST, "deterministic_affect"), **changes)


def slow_definition(**changes):
    return replace(definition(SLOW, "accumulator"), **changes)


def owner(*, version=1, sensitivity=0.5):
    return PersonaProfile("test", (replace(profile(), sensitivity=sensitivity),), version)


def projector(rule, *, persona=None, definitions=None, version="1"):
    return AppraisalProjector(
        rules=(rule,),
        persona_profile=persona or owner(),
        definitions=definitions or registry(fast=fast_definition(), slow=slow_definition()),
        version=version,
    )


def evaluate(rule, *, persona=None, definitions=None, appraisal=None, selected_history=None):
    return projector(rule, persona=persona, definitions=definitions).project(
        acceptance=appraisal or accepted("plan_cancelled"), history=selected_history
    )


def with_scope(record, scope):
    record = replace(record, projection_scope=scope)
    return replace(
        record,
        acceptance_id="acceptance-"
        + digest(
            (
                record.appraisal,
                record.candidate,
                record.interaction_id,
                record.persona_id,
                record.trusted_evidence_refs,
                record.route_abstention_reasons,
                record.status,
                record.reason_codes,
                record.projection_scope,
            )
        ),
    )


def test_f1_unmapped_cannot_hide_foreign_projection_scope():
    record = accepted("novel_semantic_event")
    foreign = with_scope(record, replace(record.projection_scope, persona_id="other"))
    instance = projector(EventEffectRule("plan_cancelled", FAST, 0.1))
    rejected = instance.project(acceptance=foreign, history=None)
    assert rejected.status == "REJECTED"
    assert rejected.effects == ()
    assert rejected.reason_codes != ("no_runtime_projection_rule",)
    legal = with_scope(record, replace(record.projection_scope, agent_id="agent-instance-7"))
    unmapped = instance.project(acceptance=legal, history=None)
    assert unmapped.status == "UNMAPPED"
    assert unmapped.effects == ()


def test_f1_r1_affect_target_cannot_be_absolute():
    rule = EventEffectRule(
        "plan_cancelled",
        FAST,
        0.1,
        longitudinal_target_dimension=FAST,
        longitudinal_proposed_value=0.8,
    )
    result = evaluate(rule)
    assert result.status == "REJECTED"
    assert result.effects == ()


def test_f1_r2_longitudinal_target_cannot_be_delta():
    result = evaluate(EventEffectRule("plan_cancelled", SLOW, 0.1))
    assert result.status == "REJECTED"
    assert result.effects == ()


def test_f1_r3_missing_definition_is_rejection_not_unmapped():
    result = evaluate(
        EventEffectRule("plan_cancelled", FAST, 0.1), definitions=registry(slow=slow_definition())
    )
    assert result.status == "REJECTED"
    assert result.effects == ()
    assert result.reason_codes != ("no_runtime_projection_rule",)


def test_f1_r4_foreign_owner_scope_and_runtime_rejected():
    rule = EventEffectRule("plan_cancelled", FAST, 0.1)
    record = accepted("plan_cancelled")
    assert (
        evaluate(rule, persona=PersonaProfile("other", (profile(),), 1), appraisal=record).status
        == "REJECTED"
    )
    foreign_scope = replace(record.projection_scope, persona_id="other")
    from mind_runtime.contracts.late_projection import digest

    forged = replace(record, projection_scope=foreign_scope)
    forged = replace(
        forged,
        acceptance_id="acceptance-"
        + digest(
            (
                forged.appraisal,
                forged.candidate,
                forged.interaction_id,
                forged.persona_id,
                forged.trusted_evidence_refs,
                forged.route_abstention_reasons,
                forged.status,
                forged.reason_codes,
                forged.projection_scope,
            )
        ),
    )
    assert evaluate(rule, appraisal=forged).status == "REJECTED"
    bad_runtime = replace(record, candidate=replace(record.candidate, origin_runtime_id="foreign"))
    assert evaluate(rule, appraisal=bad_runtime).status == "REJECTED"


def test_f1_agent_identity_can_differ_from_persona_identity():
    rule = EventEffectRule("plan_cancelled", FAST, 0.1)
    record = accepted("plan_cancelled")
    scope = replace(record.projection_scope, agent_id="agent-instance-7")
    from mind_runtime.contracts.late_projection import digest

    record = replace(record, projection_scope=scope)
    record = replace(
        record,
        acceptance_id="acceptance-"
        + digest(
            (
                record.appraisal,
                record.candidate,
                record.interaction_id,
                record.persona_id,
                record.trusted_evidence_refs,
                record.route_abstention_reasons,
                record.status,
                record.reason_codes,
                record.projection_scope,
            )
        ),
    )
    assert evaluate(rule, appraisal=record).status == "MAPPED"


def test_f1_r5_malformed_operation_domain_pair_is_rejected():
    record = accepted("plan_cancelled")
    with pytest.raises(ValueError):
        ProjectionEffect(
            FAST,
            0.1,
            "event:source",
            operation="proposed_value",
            target_domain="user",
            target_scope=record.projection_scope,
        )
    with pytest.raises(ValueError):
        ProjectionEffect(
            FAST,
            0.1,
            "event:source",
            operation="rewrite",
            target_domain="agent",
            target_scope=record.projection_scope,
        )


def test_f1_r6_one_valid_one_invalid_rejects_whole_result():
    rule = EventEffectRule(
        "plan_cancelled",
        FAST,
        0.1,
        longitudinal_target_dimension=SLOW,
        longitudinal_proposed_value=0.8,
    )
    result = evaluate(rule, definitions=registry(fast=fast_definition()))
    assert result.status == "REJECTED"
    assert result.effects == ()


def test_f1_r6_unexpected_mapped_effect_rejects_whole_result():
    rule = EventEffectRule("plan_cancelled", FAST, 0.1)
    instance = projector(rule)
    original = instance._map_legacy

    def malformed(*, routing, history):
        good = original(routing=routing, history=history)
        bad = replace(good, impulses=good.impulses + (replace(good.impulses[0], dimension=OTHER),))
        return bad

    instance._map_legacy = malformed
    result = instance.project(acceptance=accepted("plan_cancelled"), history=None)
    assert result.status == "REJECTED"
    assert result.effects == ()


def test_f1_definition_policy_not_dimension_prefix_selects_fast():
    custom = "agent.temper"
    rule = EventEffectRule("plan_cancelled", custom, 0.1)
    persona = PersonaProfile("test", (replace(profile(), dimension=custom),), 1)
    definitions = registry(fast=definition(custom, "deterministic_affect"))
    assert evaluate(rule, persona=persona, definitions=definitions).status == "MAPPED"


@pytest.mark.parametrize("tamper", ("operation", "domain"))
def test_f1_materialization_rejects_forged_effect_pair(tmp_path, tamper):
    rule = EventEffectRule("plan_cancelled", FAST, 0.1)
    record = accepted("plan_cancelled")
    instance = projector(rule)
    valid = instance.project(acceptance=record, history=None)
    effect = valid.effects[0]
    if tamper == "operation":
        effect = replace(effect, operation="proposed_value")
    else:
        effect = replace(effect, target_scope=None, target_domain="user")
    forged = replace(valid, effects=(effect,))
    instance.project = lambda **kwargs: forged
    journal = ProjectionJournal(tmp_path / "derived.sqlite")
    with pytest.raises(ValueError, match="projection effect"):
        journal.materialize(instance, acceptance=record, history=None)
    assert journal.get_acceptance(record.acceptance_id) is None
    assert journal.get_projection(forged.projection_id) is None
    journal.close()


def test_f1_materialization_rejects_empty_mapped_result(tmp_path):
    rule = EventEffectRule("plan_cancelled", FAST, 0.1)
    record = accepted("plan_cancelled")
    instance = projector(rule)
    valid = instance.project(acceptance=record, history=None)
    forged = replace(
        valid,
        effects=(),
        mapping_json=canonical_json(replace(mapping_from_projection(valid), impulses=())),
    )
    instance.project = lambda **kwargs: forged
    journal = ProjectionJournal(tmp_path / "derived.sqlite")
    with pytest.raises(ValueError, match="projection effect"):
        journal.materialize(instance, acceptance=record, history=None)
    assert journal.get_projection(forged.projection_id) is None
    journal.close()


def test_f1_valid_fast_slow_and_history_outputs_remain_unscaled():
    rule = EventEffectRule(
        "plan_cancelled",
        FAST,
        0.2,
        0.03,
        0.05,
        longitudinal_target_dimension=SLOW,
        longitudinal_proposed_value=0.8,
    )
    record = accepted("plan_cancelled")
    before = canonical_json(record)
    result = evaluate(rule, appraisal=record, selected_history=history(pattern()))
    assert result.status == "MAPPED"
    assert [(e.dimension, e.operation) for e in result.effects] == [
        (FAST, "delta"),
        (SLOW, "proposed_value"),
        (FAST, "delta"),
    ]
    assert result.effects[0].amount == pytest.approx(0.2 * record.candidate.confidence)
    assert result.effects[1].amount == 0.8
    assert result.effects[2].amount == 0.05
    assert canonical_json(record) == before


def test_f2_persona_version_and_consumed_definition_change_key_only():
    rule = EventEffectRule(
        "plan_cancelled",
        FAST,
        0.2,
        longitudinal_target_dimension=SLOW,
        longitudinal_proposed_value=0.8,
    )
    record = accepted("plan_cancelled")
    base_registry = registry(
        fast=fast_definition(),
        slow=slow_definition(),
        other=definition(OTHER, "deterministic_affect"),
    )
    same = projector(rule, definitions=base_registry)
    a = same.project(acceptance=record, history=None)
    assert a == same.project(acceptance=record, history=None)
    b = projector(rule, persona=owner(version=2), definitions=base_registry).project(
        acceptance=record, history=None
    )
    c = projector(
        rule,
        definitions=registry(
            fast=fast_definition(bounds=(0.0, 0.9)),
            slow=slow_definition(),
            other=definition(OTHER, "deterministic_affect"),
        ),
    ).project(acceptance=record, history=None)
    d = projector(
        rule,
        definitions=registry(
            fast=fast_definition(),
            slow=slow_definition(),
            other=definition(OTHER, "deterministic_affect", bounds=(0.0, 0.8)),
        ),
    ).project(acceptance=record, history=None)
    assert a.dependency_digest != b.dependency_digest
    assert a.dependency_digest != c.dependency_digest
    assert a.dependency_digest == d.dependency_digest
    slow_changed = projector(
        rule,
        definitions=registry(
            fast=fast_definition(),
            slow=slow_definition(bounds=(0.0, 0.9)),
            other=definition(OTHER, "deterministic_affect"),
        ),
    ).project(acceptance=record, history=None)
    assert a.dependency_digest != slow_changed.dependency_digest
    assert (
        a.dependency_digest
        == same.project(
            acceptance=record, history=None, persona=owner().dimensions
        ).dependency_digest
    )
    assert canonical_json(record) == canonical_json(accepted("plan_cancelled"))


def test_f2_restart_reuses_same_evaluation_and_old_version_remains(tmp_path):
    rule = EventEffectRule("plan_cancelled", FAST, 0.2)
    record = accepted("plan_cancelled")
    path = tmp_path / "derived.sqlite"
    first = ProjectionJournal(path)
    initial = first.materialize(projector(rule), acceptance=record, history=None)
    first.close()
    second = ProjectionJournal(path)
    same = projector(rule)
    same.project = lambda **kwargs: pytest.fail("evaluation must be reused")
    assert second.materialize(same, acceptance=record, history=None) == initial
    changed = second.materialize(
        projector(rule, persona=owner(version=2)), acceptance=record, history=None
    )
    assert changed.projection_id != initial.projection_id
    assert second.get_projection(initial.projection_id) == initial
    assert second.get_acceptance(record.acceptance_id) == record
    assert tuple(
        second.connection.execute("SELECT name FROM sqlite_master WHERE name LIKE 'appraisal_%'")
    )
    second.close()


def test_f2_cross_process_restart_does_not_call_model_or_projector(tmp_path):
    rule = EventEffectRule("plan_cancelled", FAST, 0.2)
    record = accepted("plan_cancelled")
    path = tmp_path / "derived.sqlite"
    journal = ProjectionJournal(path)
    original = journal.materialize(projector(rule), acceptance=record, history=None)
    journal.close()
    script = """
import sys
from tests.late_projection.test_f1_f2_hardening import projector, FAST
from mind_runtime.emotional_transition.effects import EventEffectRule
from mind_runtime.emotional_transition.projection_journal import ProjectionJournal
journal = ProjectionJournal(sys.argv[1])
record = journal.get_acceptance(sys.argv[2])
projector_instance = projector(EventEffectRule('plan_cancelled', FAST, .2))
projector_instance.project = lambda **kwargs: (_ for _ in ()).throw(AssertionError('recomputed'))
result = journal.materialize(projector_instance, acceptance=record, history=None)
print(result.projection_id)
journal.close()
"""
    output = subprocess.check_output(
        [sys.executable, "-c", script, str(path), record.acceptance_id],
        env={**os.environ, "PYTHONPATH": "src"},
        text=True,
    )
    assert output.strip() == original.projection_id


def test_f2_gain_once_with_fixed_acceptance():
    record = accepted("plan_cancelled")
    before = canonical_json(record)
    rule = EventEffectRule("plan_cancelled", FAST, 0.2)
    amounts = []
    contributions = []
    for sensitivity in (0.5, 1.5):
        persona = owner(sensitivity=sensitivity)
        projection = projector(rule, persona=persona).project(acceptance=record, history=None)
        mapped = mapping_from_projection(projection)
        amounts.append(mapped.impulses[0].amount)
        step = DynamicsEngine(persona=persona).step(
            current={FAST: 0.25}, elapsed=timedelta(0), impulses=mapped.impulses
        )
        contributions.append(
            next(item.amount for item in step.contributions if item.source.startswith("impulse:"))
        )
    assert amounts[0] == amounts[1]
    assert contributions == pytest.approx([amounts[0] * 0.5, amounts[1] * 1.5])
    assert canonical_json(record) == before
