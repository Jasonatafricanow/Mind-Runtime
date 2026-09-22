"""Offline reconciliation evidence; no production writes or live provider calls.

Run from the reconciliation worktree with PYTHONPATH=src;.
"""
from dataclasses import replace
from datetime import timedelta
import json
from tempfile import TemporaryDirectory
from pathlib import Path

from tests.late_projection.test_foundation import accepted, projector, profile
from tests.emotional_transition.test_open_vendor_vocabulary import OBS, CONTEXT, VALID
from mind_runtime.contracts import AppraisalModelProposal, SemanticAppraisalContext, Scope, ScopeDomain
from mind_runtime.contracts.late_projection import canonical_json
from mind_runtime.emotional_transition.appraisal import SemanticAppraisalProducer
from mind_runtime.emotional_transition.effects import AppraisalProjector, EventEffectRule, mapping_from_projection
from mind_runtime.emotional_transition.glm_provider import GLMSemanticProvider
from mind_runtime.emotional_transition.zen_provider import ZenHy3Provider
from mind_runtime.emotional_transition.projection_journal import ProjectionJournal
from mind_runtime.dynamics.engine import DynamicsEngine
from mind_runtime.dynamics.persona import PersonaProfile

out = {}
r = accepted('plan_cancelled')
before = canonical_json(r)
rows = []
for sensitivity in (0.5, 1.5):
    p = replace(profile(), sensitivity=sensitivity)
    result = projector().project(acceptance=r, persona=(p,))
    mapped = mapping_from_projection(result)
    engine = DynamicsEngine(persona=PersonaProfile('test', (p,), 1))
    stepped = engine.step(current={p.dimension: 0.25}, elapsed=timedelta(0), impulses=mapped.impulses)
    impulse = next(c.amount for c in stepped.contributions if c.source.startswith('impulse:'))
    assert abs(impulse - mapped.impulses[0].amount * sensitivity) < 1e-12
    assert canonical_json(r) == before
    rows.append({'sensitivity': sensitivity, 'pre_sensitivity': mapped.impulses[0].amount, 'engine_contribution': impulse})
assert rows[0]['pre_sensitivity'] == rows[1]['pre_sensitivity']
out['gain_once_fixed_acceptance'] = rows
owners = [PersonaProfile('test', (profile(),), version) for version in (1, 2)]
keys = [projector().dependency_digest(acceptance=r, history=None, persona=owner.dimensions) for owner in owners]
assert keys[0] == keys[1]
out['persona_version_not_bound_by_dimension_tuple'] = {'owner_versions': [1, 2], 'dependency_digests': keys}

class Model:
    def propose(self, **kwargs):
        return AppraisalModelProposal(('recognition', 'relief'), 'positive', 'meaningful', .8, .9, OBS.evidence_refs)

out['offline_real_parser_to_journal'] = []
for provider in (GLMSemanticProvider(api_key='offline-test'), ZenHy3Provider()):
    if isinstance(provider, GLMSemanticProvider):
        provider._classify_with_usage = lambda messages: (VALID, None, 'offline')
    else:
        provider._classify = lambda messages: VALID
    proposal = provider.propose_with_telemetry(observations=(OBS,), context=CONTEXT, scope=OBS.scope)
    c = proposal.candidates[0]
    record = SemanticAppraisalProducer(model=Model()).accept(
        candidate=c, context=SemanticAppraisalContext(c, CONTEXT, (profile(),), None),
        interaction_id=OBS.interaction_id, persona_id='kayla', route_abstention_reasons=(),
        projection_scope=Scope(domain=ScopeDomain.AGENT, agent_id='kayla', persona_id='kayla'))
    with TemporaryDirectory() as temp:
        path = Path(temp) / 'derived.sqlite'
        journal = ProjectionJournal(path)
        result = journal.materialize(projector(), acceptance=record, history=None)
        journal.close()
        journal = ProjectionJournal(path)
        p = projector()
        p.project = lambda **kwargs: (_ for _ in ()).throw(AssertionError('re-evaluation'))
        assert journal.materialize(p, acceptance=record, history=None) == result
        assert journal.get_acceptance(record.acceptance_id).appraisal.meanings == ('recognition', 'relief')
        assert record.status == 'ACCEPTED' and result.status == 'UNMAPPED' and result.effects == ()
        engine = DynamicsEngine(persona=PersonaProfile('test', (profile(),), 1))
        state = {profile().dimension: .25}
        step = engine.step(current=state, elapsed=timedelta(0), impulses=mapping_from_projection(result).impulses)
        assert dict(step.proposed) == state and step.contributions == ()
        tables = [row[0] for row in journal.connection.execute("select name from sqlite_master where type='table'")]
        out['offline_real_parser_to_journal'].append({'provider': type(provider).__name__, 'status': str(result.status), 'effects': [], 'meaning_survives_restart': True, 'fixed_clock_mutation': 0, 'tables': tables})
        journal.close()

out['target_operation_counterexamples'] = []
for rule in (
    EventEffectRule('plan_cancelled', 'agent.affect.anxiety', .1, longitudinal_target_dimension='agent.affect.anxiety', longitudinal_proposed_value=.8),
    EventEffectRule('plan_cancelled', 'agent.slow.trust', .1),
):
    result = AppraisalProjector(rules=(rule,)).project(acceptance=r, persona=(profile(),))
    out['target_operation_counterexamples'].append({'status': str(result.status), 'effects': [{'dimension': e.dimension, 'operation': e.operation, 'amount': e.amount} for e in result.effects]})
print(json.dumps(out, indent=2, ensure_ascii=False))
