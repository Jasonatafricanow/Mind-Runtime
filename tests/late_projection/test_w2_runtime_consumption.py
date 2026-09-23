"""Production W2 acceptance, application, and cognition contracts."""

from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace

import pytest
from tests.emotional_transition.test_appraisal_producer import (
    AGENT_SCOPE,
    NOW,
    USER_SCOPE,
    _affect,
    _candidate,
    _history,
    _situation,
)
from tests.emotional_transition.test_effects import candidate as meaning_candidate
from tests.emotional_transition.test_effects import profile as meaning_profile
from tests.expression.test_context import make_compiler, make_compiler_input, make_situation
from tests.golden.fixtures.common import make_state
from tests.late_projection.test_foundation import NovelModel
from tests.pipeline.test_d8_transition_wiring import (
    affect_state,
    interaction,
    persona,
    typed_evidence,
)
from tests.support.fake_clock import FakeClock

from mind_runtime.contracts import (
    EmotionalTransitionInput,
    SemanticAppraisalContext,
    StateDefinition,
    StateDomain,
    StateValueType,
)
from mind_runtime.contracts.late_projection import (
    ApplicationReceipt,
    ApplicationStatus,
    application_identity,
    canonical_json,
)
from mind_runtime.dynamics.engine import DynamicsEngine
from mind_runtime.dynamics.persona import PersonaProfile
from mind_runtime.dynamics.ports import EngineEmotionalTransitionPort
from mind_runtime.emotional_transition.appraisal import (
    ConfiguredSemanticAppraisalModel,
    SemanticAppraisalProducer,
)
from mind_runtime.emotional_transition.effects import AppraisalProjector, EventEffectRule
from mind_runtime.emotional_transition.projection_journal import ProjectionJournal
from mind_runtime.emotional_transition.semantic import SemanticRouter
from mind_runtime.expression.context import DecisionContextCompiler
from mind_runtime.expression.renderer import DeterministicContextRenderer
from mind_runtime.homeostasis.policy import (
    FixedSalienceThresholdConfig,
    SalienceThresholdPolicy,
)
from mind_runtime.host.runtime_adapter import _bounded_context
from mind_runtime.host.xiyue_adapter import render_bounded_context
from mind_runtime.pipeline.orchestrator import CanonicalPersistenceError, TurnOrchestrator
from mind_runtime.pipeline.trace import TraceRecorder
from mind_runtime.slow_plasticity.writer import SlowPlasticityWriter
from mind_runtime.state.definitions import StateDefinitionRegistry
from mind_runtime.state.persistence import SqliteCommitMarkerStore, SqliteStateBackend


def _port(tmp_path, *, rules=(), gate=None):
    owner = PersonaProfile("kayla", (_affect("agent.affect.anxiety"),), 1)
    definitions = StateDefinitionRegistry(
        (
            StateDefinition(
                "agent.affect.anxiety",
                StateDomain.AGENT,
                StateValueType.SCALAR,
                "deterministic_affect",
                None,
                (0.0, 1.0),
            ),
            StateDefinition(
                "agent.longitudinal.relationship_security",
                StateDomain.AGENT,
                StateValueType.SCALAR,
                "accumulator",
                "indefinite",
                (0.0, 1.0),
            ),
        )
    )
    journal = ProjectionJournal(tmp_path / "derived.sqlite")
    port = EngineEmotionalTransitionPort(
        engine=DynamicsEngine(persona=owner),
        runtime_id="runtime-1",
        effect_rules=rules,
        appraisal_producer=SemanticAppraisalProducer(model=ConfiguredSemanticAppraisalModel()),
        projection_journal=journal,
        state_definitions=definitions,
        homeostasis_gate=gate,
    )
    return port, journal


def _input(kind):
    return EmotionalTransitionInput(
        interaction_id="turn-w2-1",
        scope=USER_SCOPE,
        origin_runtime_id="runtime-1",
        context=_situation(),
        current_affect=(),
        elapsed=timedelta(0),
        persona_id="kayla",
        persona_version=1,
        persona=(_affect("agent.affect.anxiety"),),
        observations=(),
        semantic_candidates=(_candidate(kind=kind),),
        history_context=None,
        clock=NOW,
        projection_scope=AGENT_SCOPE,
    )


def test_w2_01_accepted_mapped_production_route(tmp_path):
    port, journal = _port(
        tmp_path, rules=(EventEffectRule("plan_cancelled", "agent.affect.anxiety", 0.2),)
    )
    result = port.transition(_input("plan_cancelled"))
    assert len(result.accepted_appraisals) == len(result.projection_refs) == 1
    acceptance = result.accepted_appraisals[0]
    projection = journal.get_projection(result.projection_refs[0])
    assert acceptance.status == "ACCEPTED"
    assert journal.get_acceptance(acceptance.acceptance_id) == acceptance
    assert projection.status == "MAPPED"
    assert projection.effects[0].amount == 0.2 * acceptance.candidate.confidence
    assert result.accepted_events == (acceptance.candidate,)
    journal.close()


def test_w2_02_accepted_unmapped_survives_without_impulse(tmp_path):
    port, journal = _port(tmp_path)
    result = port.transition(_input("novel_semantic_event"))
    acceptance = result.accepted_appraisals[0]
    projection = journal.get_projection(result.projection_refs[0])
    assert acceptance.status == "ACCEPTED"
    assert acceptance.appraisal.meanings == (
        "novel_semantic_event_interpretation",
        "relational_significance",
    )
    assert projection.status == "UNMAPPED"
    assert projection.effects == ()
    assert result.accepted_events == (acceptance.candidate,)
    assert journal.get_acceptance(acceptance.acceptance_id) == acceptance
    journal.close()


def test_w2_producer_rejection_cannot_fall_back_to_legacy_mapping(tmp_path, monkeypatch):
    port, journal = _port(
        tmp_path, rules=(EventEffectRule("plan_cancelled", "agent.affect.anxiety", 0.2),)
    )
    original = SemanticAppraisalProducer.accept

    def rejected(self, **kwargs):
        return replace(original(self, **kwargs), status="REJECTED")

    monkeypatch.setattr(SemanticAppraisalProducer, "accept", rejected)
    result = port.transition(_input("plan_cancelled"))
    assert result.accepted_appraisals == ()
    assert result.accepted_events == ()
    assert result.legacy_no_appraisal is False
    assert not any(
        contribution.source_kind == "EVENT"
        for contribution in result.assessment_trace.contributions
    )
    journal.close()


def test_w2_crash_after_acceptance_before_projection_retries_without_model(tmp_path, monkeypatch):
    rule = EventEffectRule("plan_cancelled", "agent.affect.anxiety", 0.2)
    port, journal = _port(tmp_path, rules=(rule,))
    original_project = AppraisalProjector.project

    def fail(*args, **kwargs):
        raise RuntimeError("injected projection crash")

    monkeypatch.setattr(AppraisalProjector, "project", fail)
    with pytest.raises(RuntimeError, match="projection crash"):
        port.transition(_input("plan_cancelled"))
    assert len(journal.accepted_for_interaction("turn-w2-1")) == 1
    assert (
        journal.connection.execute("SELECT count(*) FROM appraisal_projections").fetchone()[0] == 0
    )
    journal.close()

    monkeypatch.setattr(AppraisalProjector, "project", original_project)
    restarted, journal = _port(tmp_path, rules=(rule,))
    monkeypatch.setattr(SemanticAppraisalProducer, "accept", fail)
    result = restarted.transition(_input("plan_cancelled"))
    assert result.accepted_appraisals
    assert journal.get_projection(result.projection_refs[0]).status == "MAPPED"
    journal.close()


def test_w2_07_projection_journal_insert_failure_leaves_accepted_only(tmp_path, monkeypatch):
    port, journal = _port(
        tmp_path, rules=(EventEffectRule("plan_cancelled", "agent.affect.anxiety", 0.2),)
    )

    original_insert = ProjectionJournal._insert_immutable

    def fail(self, table, *args, **kwargs):
        if table == "appraisal_projections":
            raise RuntimeError("injected projection insert failure")
        return original_insert(self, table, *args, **kwargs)

    monkeypatch.setattr(ProjectionJournal, "_insert_immutable", fail)
    with pytest.raises(RuntimeError, match="projection insert failure"):
        port.transition(_input("plan_cancelled"))
    assert len(journal.accepted_for_interaction("turn-w2-1")) == 1
    assert (
        journal.connection.execute("SELECT count(*) FROM appraisal_projections").fetchone()[0] == 0
    )
    journal.close()


def test_w2_18_same_interaction_reuses_acceptance_without_model_call(tmp_path):
    port, journal = _port(
        tmp_path, rules=(EventEffectRule("plan_cancelled", "agent.affect.anxiety", 0.2),)
    )
    first = port.transition(_input("plan_cancelled"))
    port._appraisal_producer.accept = lambda **kwargs: pytest.fail("semantic model reran")
    port._projector.project = lambda **kwargs: pytest.fail("projection reran")
    second = port.transition(
        replace(_input("plan_cancelled"), history_context=_history(with_pattern=True))
    )
    assert second.accepted_appraisals == first.accepted_appraisals
    assert second.projection_refs == first.projection_refs
    journal.close()


def test_w2_05_restart_reuses_original_acceptance_and_projection(tmp_path):
    rules = (EventEffectRule("plan_cancelled", "agent.affect.anxiety", 0.2),)
    first_port, first_journal = _port(tmp_path, rules=rules)
    first = first_port.transition(_input("plan_cancelled"))
    first_journal.close()
    restarted_port, restarted_journal = _port(tmp_path, rules=rules)
    restarted_port._appraisal_producer.accept = lambda **kwargs: pytest.fail("model reran")
    restarted_port._projector.project = lambda **kwargs: pytest.fail("projection reran")
    repeated = restarted_port.transition(_input("plan_cancelled"))
    assert repeated.accepted_appraisals == first.accepted_appraisals
    assert repeated.projection_refs == first.projection_refs
    restarted_journal.close()


def test_w2_11_required_joint_slow_denial_prevents_fast_application(tmp_path):
    rule = EventEffectRule(
        "plan_cancelled",
        "agent.affect.anxiety",
        0.2,
        longitudinal_target_dimension="agent.longitudinal.relationship_security",
        longitudinal_proposed_value=0.8,
        admission_mode="required_joint",
    )
    gate = SalienceThresholdPolicy(
        config=FixedSalienceThresholdConfig(
            salience_floor_fast_apply=0.0,
            salience_floor_slow_accept=0.95,
            confidence_floor_slow=0.0,
        )
    )
    port, journal = _port(tmp_path, rules=(rule,), gate=gate)
    with pytest.raises(ValueError, match="required-joint"):
        port.transition(_input("plan_cancelled"))
    assert len(journal.accepted_for_interaction("turn-w2-1")) == 1
    journal.close()


def test_w2_10_legacy_independent_slow_denial_preserves_fast(tmp_path):
    rule = EventEffectRule(
        "plan_cancelled",
        "agent.affect.anxiety",
        0.2,
        longitudinal_target_dimension="agent.longitudinal.relationship_security",
        longitudinal_proposed_value=0.8,
    )
    gate = SalienceThresholdPolicy(
        config=FixedSalienceThresholdConfig(
            salience_floor_fast_apply=0.0,
            salience_floor_slow_accept=0.95,
            confidence_floor_slow=0.0,
        )
    )
    port, journal = _port(tmp_path, rules=(rule,), gate=gate)
    outcome = port.transition_with_gate(_input("plan_cancelled"))
    projection = journal.get_projection(outcome.transition_result.projection_refs[0])
    assert projection.status == "MAPPED"
    assert tuple(effect.operation for effect in projection.effects) == ("delta", "proposed_value")
    assert any(decision.decision.value != "slow_accept" for decision in outcome.slow_decisions)
    assert outcome.transition_result.accepted_events
    assert outcome.transition_result.projected.projected_states[0].value > 0.3
    journal.close()


def _receipt(interaction_id="turn-w2-1"):
    return ApplicationReceipt(
        application_id=application_identity("runtime-1", "acceptance-1", "group-1", "turn-w2-1"),
        projection_id="projection-1",
        acceptance_id="acceptance-1",
        interaction_id=interaction_id,
        effect_group_id="group-1",
        runtime_id="runtime-1",
        scope=AGENT_SCOPE,
        status=ApplicationStatus.PENDING,
        commit_ref=None,
        transition_refs=(),
    )


def test_w2_08_receipt_and_state_rollback_together(tmp_path):
    backend = SqliteStateBackend(tmp_path / "state.sqlite")
    backend.enable_application_receipts()
    state = make_state(
        dimension="agent.affect.anxiety", scope=AGENT_SCOPE, state_id="w2-state-1", now=NOW
    )
    with backend.transaction():
        backend.save_state(state)
        backend.stage_application_receipt(_receipt())
        assert (
            backend.get_application_receipt(_receipt().application_id).status
            is ApplicationStatus.PENDING
        )
        backend.commit_application_receipt(
            replace(
                _receipt(),
                status=ApplicationStatus.COMMITTED,
                commit_ref="commit:turn-w2-1",
                transition_refs=(state.state_id,),
            )
        )
    assert len(backend.load_states()) == 1
    assert (
        backend.get_application_receipt(_receipt().application_id).status
        is ApplicationStatus.COMMITTED
    )

    conflict = replace(_receipt(), projection_id="projection-conflict")
    with pytest.raises(ValueError):
        with backend.transaction():
            backend.save_state(
                make_state(
                    dimension="agent.affect.anxiety",
                    scope=AGENT_SCOPE,
                    state_id="w2-state-2",
                    now=NOW,
                )
            )
            backend.stage_application_receipt(conflict)
    assert len(backend.load_states()) == 1
    assert backend.get_application_receipt(_receipt().application_id).interaction_id == "turn-w2-1"
    backend.close()


def _production_stack(
    tmp_path, *, mixed_mode=None, no_recipe=False, with_cognition=False, deny_slow=False
):
    state_db = tmp_path / "state.sqlite"
    backend = SqliteStateBackend(state_db)
    backend.enable_application_receipts()
    if not backend.load_states():
        backend.save_state(affect_state())
    markers = SqliteCommitMarkerStore(state_db, connection=backend.connection)
    definition_rows = [
        StateDefinition(
            "agent.affect.anxiety",
            StateDomain.AGENT,
            StateValueType.SCALAR,
            "deterministic_affect",
            None,
            (0.0, 1.0),
        )
    ]
    if mixed_mode is not None:
        definition_rows.append(
            StateDefinition(
                "agent.longitudinal.relationship_security",
                StateDomain.AGENT,
                StateValueType.SCALAR,
                "accumulator",
                "indefinite",
                (0.0, 1.0),
            )
        )
    definitions = StateDefinitionRegistry(tuple(definition_rows))
    journal = ProjectionJournal(tmp_path / "derived.sqlite")
    rule = EventEffectRule(
        "plan_cancelled",
        "agent.affect.anxiety",
        0.2,
        **(
            {
                "longitudinal_target_dimension": "agent.longitudinal.relationship_security",
                "longitudinal_proposed_value": 0.8,
                "admission_mode": mixed_mode,
            }
            if mixed_mode
            else {}
        ),
    )
    gate = (
        SalienceThresholdPolicy(
            config=FixedSalienceThresholdConfig(
                salience_floor_fast_apply=0.0,
                salience_floor_slow_accept=0.99 if deny_slow else 0.0,
                confidence_floor_slow=0.0,
            )
        )
        if mixed_mode
        else None
    )
    writer = (
        SlowPlasticityWriter(
            backend=backend, runtime_id="runtime-1", window_size=8, clock=FakeClock(NOW)
        )
        if mixed_mode
        else None
    )
    port = EngineEmotionalTransitionPort(
        engine=DynamicsEngine(persona=persona()),
        runtime_id="runtime-1",
        effect_rules=() if no_recipe else (rule,),
        semantic_router=SemanticRouter(),
        appraisal_producer=SemanticAppraisalProducer(model=ConfiguredSemanticAppraisalModel()),
        projection_journal=journal,
        state_definitions=definitions,
        homeostasis_gate=gate,
    )
    orchestrator = TurnOrchestrator(
        clock=FakeClock(NOW),
        trace=TraceRecorder(),
        runtime_id="runtime-1",
        persona=persona(),
        emotional_transition=port,
        definitions=definitions,
        state_backend=backend,
        commit_markers=markers,
        slow_plasticity_writer=writer,
        decision_context_compiler=(
            DecisionContextCompiler(make_compiler()._config, appraisal_journal=journal)
            if with_cognition
            else None
        ),
        context_renderer=(
            DeterministicContextRenderer(make_compiler()._config) if with_cognition else None
        ),
    )
    return orchestrator, backend, journal


def test_w2_04_production_commit_has_effect_group_receipt(tmp_path):
    orchestrator, backend, journal = _production_stack(tmp_path)
    orchestrator.begin_turn(interaction())
    orchestrator.ingest(typed_evidence())
    orchestrator.run()
    assert orchestrator.transition_result.accepted_appraisals, (
        orchestrator.transition_result.assessment_trace
    )
    acceptance = orchestrator.transition_result.accepted_appraisals[0]
    acceptance_before = canonical_json(acceptance)
    orchestrator.commit_turn()
    assert canonical_json(journal.get_acceptance(acceptance.acceptance_id)) == acceptance_before
    rows = backend.connection.execute("SELECT application_id FROM application_receipts").fetchall()
    assert len(rows) == 1
    receipt = backend.get_application_receipt(rows[0][0])
    assert receipt.acceptance_id == acceptance.acceptance_id
    assert receipt.interaction_id == interaction().interaction_id
    assert receipt.status is ApplicationStatus.COMMITTED
    assert receipt.commit_ref is not None
    journal.close()
    backend.close()


def test_w2_05_committed_restart_does_not_reapply_or_call_model(tmp_path):
    first, backend, journal = _production_stack(tmp_path)
    first.begin_turn(interaction())
    first.ingest(typed_evidence())
    first.run()
    first.commit_turn()
    committed = tuple(backend.load_states())
    receipt_count = backend.connection.execute(
        "SELECT count(*) FROM application_receipts"
    ).fetchone()[0]
    assert receipt_count == 1
    journal.close()
    backend.close()

    restarted, backend, journal = _production_stack(tmp_path)
    restarted.emotional_transition._appraisal_producer.accept = lambda **kwargs: pytest.fail(
        "semantic model reran"
    )
    restarted.emotional_transition._projector.project = lambda **kwargs: pytest.fail(
        "projection reran"
    )
    restarted.begin_turn(interaction())
    restarted.ingest(typed_evidence())
    restarted.run()
    restarted.commit_turn()
    assert tuple(backend.load_states()) == committed
    assert (
        backend.connection.execute("SELECT count(*) FROM application_receipts").fetchone()[0] == 1
    )
    journal.close()
    backend.close()


def _meaning_compiler_input(tmp_path):
    source = make_compiler_input()
    candidate = meaning_candidate(kind="novel_semantic_event")
    situation = make_situation()
    acceptance = SemanticAppraisalProducer(model=NovelModel()).accept(
        candidate=candidate,
        context=SemanticAppraisalContext(candidate, situation, (meaning_profile(),), None),
        interaction_id=source.interaction_id,
        persona_id=source.persona_ref,
        route_abstention_reasons=(),
        projection_scope=source.projected_agent_state.scope,
    )
    journal = ProjectionJournal(tmp_path / "meaning.sqlite")
    definitions = StateDefinitionRegistry(
        (
            StateDefinition(
                "agent.affect.anxiety",
                StateDomain.AGENT,
                StateValueType.SCALAR,
                "deterministic_affect",
                None,
                (0.0, 1.0),
            ),
        )
    )
    projector = AppraisalProjector(
        rules=(),
        persona_profile=PersonaProfile(source.persona_ref, (meaning_profile(),), 1),
        definitions=definitions,
    )
    assert journal.materialize(projector, acceptance=acceptance, history=None).status == "UNMAPPED"
    return replace(source, accepted_appraisals=(acceptance,)), journal


def test_w2_13_cognitive_meaning_reaches_renderer_and_host_bytes(tmp_path):
    compiler_input, journal = _meaning_compiler_input(tmp_path)
    config = make_compiler()._config
    compiler = DecisionContextCompiler(config, appraisal_journal=journal)
    context, trace = compiler.compile(compiler_input)
    rendered = DeterministicContextRenderer(config).render(context)
    bounded = _bounded_context(
        SimpleNamespace(
            decision_context=context, context_renderer=DeterministicContextRenderer(config)
        )
    )
    provider_bytes = render_bounded_context(bounded)
    assert "[COGNITIVE_MEANING]" in rendered.text
    assert "[APPRAISAL_DATA]" in rendered.text
    assert "recognition" in rendered.text
    assert "COGNITIVE_MEANING" in provider_bytes
    assert "recognition" in provider_bytes
    assert "[FACT]" not in provider_bytes
    assert not trace.omitted_item_refs
    journal.close()


@pytest.mark.parametrize(
    "failure_seam", ("receipt", "state", "marker", "receipt_commit", "db_commit")
)
def test_w2_canonical_failure_rolls_back_receipt_and_effect(tmp_path, monkeypatch, failure_seam):
    orchestrator, backend, journal = _production_stack(tmp_path)
    orchestrator.begin_turn(interaction())
    orchestrator.ingest(typed_evidence())
    orchestrator.run()
    before = tuple(backend.load_states())
    assert journal.accepted_for_interaction(interaction().interaction_id)

    def fail(*args, **kwargs):
        raise RuntimeError(f"injected {failure_seam}")

    if failure_seam == "receipt":
        monkeypatch.setattr(SqliteStateBackend, "stage_application_receipt", fail)
    elif failure_seam == "state":
        monkeypatch.setattr(TurnOrchestrator, "_persist_state_idempotent", fail)
    elif failure_seam == "marker":
        monkeypatch.setattr(SqliteCommitMarkerStore, "record_commit", fail)
    elif failure_seam == "receipt_commit":
        monkeypatch.setattr(SqliteStateBackend, "commit_application_receipt", fail)
    else:
        monkeypatch.setattr(SqliteStateBackend, "transaction", _failed_commit_transaction)
    with pytest.raises(CanonicalPersistenceError, match="atomic cognitive admission"):
        orchestrator.commit_turn()
    assert tuple(backend.load_states()) == before
    assert (
        backend.connection.execute("SELECT count(*) FROM application_receipts").fetchone()[0] == 0
    )
    assert not orchestrator.commit_marker_store.has_commit(
        interaction_id=interaction().interaction_id, scope=interaction().scope
    )
    journal.close()
    backend.close()


def _failed_commit_transaction(self):
    from contextlib import contextmanager

    @contextmanager
    def transaction():
        with _ORIGINAL_TRANSACTION(self):
            yield
            raise RuntimeError("injected db_commit")

    return transaction()


_ORIGINAL_TRANSACTION = SqliteStateBackend.transaction


def test_w2_journal_failure_prevents_canonical_application(tmp_path, monkeypatch):
    orchestrator, backend, journal = _production_stack(tmp_path)

    def fail(*args, **kwargs):
        raise RuntimeError("injected journal write")

    monkeypatch.setattr(ProjectionJournal, "materialize", fail)
    before = tuple(backend.load_states())
    orchestrator.begin_turn(interaction())
    orchestrator.ingest(typed_evidence())
    with pytest.raises(RuntimeError, match="journal write"):
        orchestrator.run()
    assert tuple(backend.load_states()) == before
    assert (
        backend.connection.execute("SELECT count(*) FROM application_receipts").fetchone()[0] == 0
    )
    journal.close()
    backend.close()


def test_w2_14_meaning_budget_omission_keeps_acceptance(tmp_path):
    compiler_input, journal = _meaning_compiler_input(tmp_path)
    config = replace(make_compiler()._config, max_meaning_chars=1)
    context, trace = DecisionContextCompiler(config, appraisal_journal=journal).compile(
        compiler_input
    )
    assert "budget_exhausted" in trace.reason_codes
    assert not any(item.kind.value == "cognitive_meaning" for item in context.expression_context)
    assert journal.get_acceptance(compiler_input.accepted_appraisals[0].acceptance_id)
    journal.close()


def test_w2_15_meaning_policy_denied_keeps_projection(tmp_path):
    compiler_input, journal = _meaning_compiler_input(tmp_path)
    config = replace(make_compiler()._config, meaning_policy="policy_denied")
    context, trace = DecisionContextCompiler(config, appraisal_journal=journal).compile(
        compiler_input
    )
    assert "policy_denied" in trace.reason_codes
    assert not any(item.kind.value == "cognitive_meaning" for item in context.expression_context)
    acceptance = compiler_input.accepted_appraisals[0]
    assert journal.get_acceptance(acceptance.acceptance_id) == acceptance
    journal.close()


def test_w2_16_retry_keeps_same_meaning_source_and_fact_separation(tmp_path):
    compiler_input, journal = _meaning_compiler_input(tmp_path)
    config = make_compiler()._config
    compiler = DecisionContextCompiler(config, appraisal_journal=journal)
    context, _ = compiler.compile(compiler_input)
    retried, _ = compiler.retry(context, ("forbidden_opening",))
    meaning = tuple(
        item for item in context.expression_context if item.kind.value == "cognitive_meaning"
    )
    retried_meaning = tuple(
        item for item in retried.expression_context if item.kind.value == "cognitive_meaning"
    )
    assert meaning == retried_meaning
    assert all(item.kind.value != "fact" for item in meaning)
    assert "[APPRAISAL_DATA]" in DeterministicContextRenderer(config).render(retried).text
    journal.close()


def test_w2_16_restart_preserves_current_meaning_item(tmp_path):
    compiler_input, journal = _meaning_compiler_input(tmp_path)
    config = make_compiler()._config
    first, _ = DecisionContextCompiler(config, appraisal_journal=journal).compile(compiler_input)
    journal.close()
    reopened = ProjectionJournal(tmp_path / "meaning.sqlite")
    second, _ = DecisionContextCompiler(config, appraisal_journal=reopened).compile(compiler_input)
    assert first == second
    assert "COGNITIVE_MEANING" in render_bounded_context(
        _bounded_context(
            SimpleNamespace(
                decision_context=second,
                context_renderer=DeterministicContextRenderer(config),
            )
        )
    )
    reopened.close()


def test_w2_06_old_interaction_appraisal_cannot_authorize_new_commit(tmp_path):
    first, backend, journal = _production_stack(tmp_path)
    first.begin_turn(interaction())
    first.ingest(typed_evidence())
    first.run()
    old_result = first.transition_result
    first.commit_turn()
    before = tuple(backend.load_states())
    first.begin_turn(replace(interaction(), interaction_id="interaction-2", turn_id="turn-2"))
    first.ingest(typed_evidence())
    first.run()
    first._turn.transition_result = replace(
        first.transition_result,
        accepted_appraisals=old_result.accepted_appraisals,
        projection_refs=old_result.projection_refs,
    )
    with pytest.raises(CanonicalPersistenceError, match="cross-interaction"):
        first.commit_turn()
    assert tuple(backend.load_states()) == before
    assert (
        backend.connection.execute("SELECT count(*) FROM application_receipts").fetchone()[0] == 1
    )
    journal.close()
    backend.close()


def test_w2_lineage_validation_unbypassable_at_orchestrator_seam(tmp_path):
    """Lineage validation is enforced by orchestrator seam before transaction entry.

    SqliteStateBackend receipt API is a persistence primitive; the canonical
    orchestrator seam owns lineage validation (runtime_id, scope, interaction_id,
    and valid_lineage) and fails closed with CanonicalPersistenceError.
    """
    orchestrator, backend, journal = _production_stack(tmp_path)
    orchestrator.begin_turn(interaction())
    orchestrator.ingest(typed_evidence())
    orchestrator.run()
    acceptance = orchestrator.transition_result.accepted_appraisals[0]

    # Mismatched runtime_id in candidate
    corrupt_candidate = replace(acceptance.candidate, origin_runtime_id="other-runtime")
    corrupt_acceptance = replace(acceptance, candidate=corrupt_candidate)
    orchestrator._turn.transition_result = replace(
        orchestrator.transition_result,
        accepted_appraisals=(corrupt_acceptance,),
    )
    with pytest.raises(CanonicalPersistenceError, match="cross-interaction"):
        orchestrator.commit_turn()

    # Backend has 0 staged or committed receipts
    assert (
        backend.connection.execute("SELECT count(*) FROM application_receipts").fetchone()[0] == 0
    )
    journal.close()
    backend.close()


def test_w2_12_post_commit_publication_failure_recovers_from_durable_state(tmp_path, monkeypatch):
    orchestrator, backend, journal = _production_stack(tmp_path)
    orchestrator.begin_turn(interaction())
    orchestrator.ingest(typed_evidence())
    orchestrator.run()

    def fail(*args, **kwargs):
        raise RuntimeError("injected publication failure")

    monkeypatch.setattr(TurnOrchestrator, "_publish_committed_states", fail)
    with pytest.raises(CanonicalPersistenceError, match="post-commit publication failed"):
        orchestrator.commit_turn()
    assert orchestrator.commit_marker_store.has_commit(
        interaction_id=interaction().interaction_id, scope=interaction().scope
    )
    receipt_id = backend.connection.execute(
        "SELECT application_id FROM application_receipts"
    ).fetchone()[0]
    assert backend.get_application_receipt(receipt_id).status is ApplicationStatus.COMMITTED
    assert all(state in backend.load_states() for state in orchestrator._canonical.values())
    assert any(state.version == 2 for state in orchestrator._canonical.values())
    journal.close()
    backend.close()

    restarted, backend, journal = _production_stack(tmp_path)
    monkeypatch.setattr(SemanticAppraisalProducer, "accept", fail)
    monkeypatch.setattr(AppraisalProjector, "project", fail)
    restarted.begin_turn(interaction())
    restarted.ingest(typed_evidence())
    restarted.run()
    restarted.commit_turn()
    assert (
        backend.connection.execute("SELECT count(*) FROM application_receipts").fetchone()[0] == 1
    )
    journal.close()
    backend.close()


def test_w2_required_joint_recipe_metadata_decodes_for_production():
    from mind_runtime.validation.contracts import _event_effect

    rule = _event_effect(
        {
            "event_kind": "plan_cancelled",
            "dimension": "agent.affect.anxiety",
            "base_amount": 0.2,
            "history_amount_per_match": 0.0,
            "history_amount_cap": 0.0,
            "minimum_history_confidence": 0.0,
            "longitudinal_target_dimension": "agent.longitudinal.relationship_security",
            "longitudinal_proposed_value": 0.8,
            "admission_mode": "required_joint",
        },
        "emotional_effects.rules[0]",
    )
    assert rule.admission_mode == "required_joint"


def test_w2_materialized_group_mode_survives_recipe_version_change(tmp_path):
    joint = EventEffectRule(
        "plan_cancelled",
        "agent.affect.anxiety",
        0.2,
        longitudinal_target_dimension="agent.longitudinal.relationship_security",
        longitudinal_proposed_value=0.8,
        admission_mode="required_joint",
    )
    port, journal = _port(tmp_path, rules=(joint,))
    with pytest.raises(ValueError, match="required-joint"):
        port.transition_with_gate(_input("plan_cancelled"))
    acceptance = journal.accepted_for_interaction("turn-w2-1")[0]
    old_projection = journal.projection_for_acceptance(port._projector, acceptance=acceptance)
    assert old_projection.admission_mode == "required_joint"
    journal.close()

    independent = replace(joint, admission_mode="legacy_independent")
    restarted, journal = _port(tmp_path, rules=(independent,))
    replayed = journal.replay_projection(restarted._projector, acceptance=acceptance)
    assert replayed.admission_mode == "required_joint"
    journal.close()


def test_w2_reads_preexisting_w1_projection_without_group_mode(tmp_path):
    import json

    from mind_runtime.contracts.late_projection import canonical_json, digest

    port, journal = _port(
        tmp_path, rules=(EventEffectRule("plan_cancelled", "agent.affect.anxiety", 0.2),)
    )
    result = port.transition(_input("plan_cancelled"))
    projection_id = result.projection_refs[0]
    raw = json.loads(
        journal.connection.execute(
            "SELECT payload FROM appraisal_projections WHERE projection_id=?", (projection_id,)
        ).fetchone()[0]
    )
    raw.pop("admission_mode")
    journal.connection.execute(
        "UPDATE appraisal_projections SET payload=?, content_digest=? WHERE projection_id=?",
        (canonical_json(raw), digest(raw), projection_id),
    )
    journal.connection.commit()
    assert journal.get_projection(projection_id).admission_mode == "legacy_independent"
    journal.close()


def test_w2_11_required_joint_mixed_group_commits_together(tmp_path):
    orchestrator, backend, journal = _production_stack(tmp_path, mixed_mode="required_joint")
    orchestrator.begin_turn(interaction())
    orchestrator.ingest(typed_evidence())
    orchestrator.run()
    assert any(
        decision.decision.value == "slow_accept" for decision in orchestrator._turn.slow_decisions
    )
    orchestrator.commit_turn()
    states = backend.load_states()
    assert any(state.dimension == "agent.affect.anxiety" and state.version == 2 for state in states)
    assert any(state.dimension == "agent.longitudinal.relationship_security" for state in states)
    receipt_id = backend.connection.execute(
        "SELECT application_id FROM application_receipts"
    ).fetchone()[0]
    receipt = backend.get_application_receipt(receipt_id)
    assert receipt.status is ApplicationStatus.COMMITTED
    assert len(receipt.transition_refs) >= 2
    journal.close()
    backend.close()


def test_w2_23_unmapped_production_acceptance_reaches_host_bytes(tmp_path):
    orchestrator, backend, journal = _production_stack(
        tmp_path, no_recipe=True, with_cognition=True
    )
    before = tuple(backend.load_states())
    orchestrator.begin_turn(interaction())
    orchestrator.ingest(typed_evidence())
    orchestrator.run()
    result = orchestrator.transition_result
    assert result.accepted_appraisals and result.accepted_events
    assert journal.get_projection(result.projection_refs[0]).status == "UNMAPPED"
    assert "COGNITIVE_MEANING" in render_bounded_context(_bounded_context(orchestrator))
    assert "plan_cancelled_interpretation" in render_bounded_context(_bounded_context(orchestrator))
    orchestrator.commit_turn()
    assert (
        backend.connection.execute("SELECT count(*) FROM application_receipts").fetchone()[0] == 0
    )
    assert before[0].value == next(
        state.value
        for state in backend.load_states()
        if state.dimension == "agent.affect.anxiety" and state.version == 1
    )
    journal.close()
    backend.close()


def test_w2_10_slow_write_failure_rolls_back_joint_fast_and_receipt(tmp_path, monkeypatch):
    orchestrator, backend, journal = _production_stack(tmp_path, mixed_mode="required_joint")
    orchestrator.begin_turn(interaction())
    orchestrator.ingest(typed_evidence())
    orchestrator.run()
    before = tuple(backend.load_states())

    def fail(*args, **kwargs):
        raise RuntimeError("injected slow writer failure")

    monkeypatch.setattr(SlowPlasticityWriter, "execute_flush_plan", fail)
    with pytest.raises(CanonicalPersistenceError, match="atomic cognitive admission"):
        orchestrator.commit_turn()
    assert tuple(backend.load_states()) == before
    assert (
        backend.connection.execute("SELECT count(*) FROM application_receipts").fetchone()[0] == 0
    )
    journal.close()
    backend.close()


def test_w2_10_legacy_independent_slow_deny_commits_fast_only(tmp_path):
    orchestrator, backend, journal = _production_stack(
        tmp_path, mixed_mode="legacy_independent", deny_slow=True
    )
    orchestrator.begin_turn(interaction())
    orchestrator.ingest(typed_evidence())
    orchestrator.run()
    assert not any(
        decision.decision.value == "slow_accept" for decision in orchestrator._turn.slow_decisions
    )
    orchestrator.commit_turn()
    states = backend.load_states()
    assert any(state.dimension == "agent.affect.anxiety" and state.version == 2 for state in states)
    assert not any(
        state.dimension == "agent.longitudinal.relationship_security" for state in states
    )
    receipt_id = backend.connection.execute(
        "SELECT application_id FROM application_receipts"
    ).fetchone()[0]
    assert backend.get_application_receipt(receipt_id).status is ApplicationStatus.COMMITTED
    journal.close()
    backend.close()
