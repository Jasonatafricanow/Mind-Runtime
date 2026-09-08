"""D5.2 TurnProjection tests: projection is never canonical until commit."""

from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

from mind_runtime.contracts import (
    Interaction,
    InteractionStatus,
    Scope,
    ScopeDomain,
    TurnProjection,
)
from mind_runtime.pipeline.orchestrator import TurnOrchestrator
from mind_runtime.pipeline.trace import TraceRecorder
from mind_runtime.state.intents import TURN_COMMIT_PHASE
from tests.golden.fixtures.common import make_evidence, make_scope, make_state
from tests.support.fake_clock import FakeClock

NOW = datetime(2026, 8, 22, 10, 0, tzinfo=UTC)


def make_interaction(*, scope: Scope | None = None) -> Interaction:
    return Interaction(
        interaction_id="interaction-1",
        scope=scope or make_scope(),
        channel="chat",
        session_id="session-1",
        turn_id="turn-1",
        started_at=NOW,
        committed_at=None,
        status=InteractionStatus.OPEN,
    )


def make_orchestrator(**kwargs: Any) -> TurnOrchestrator:
    return TurnOrchestrator(clock=FakeClock(NOW), trace=TraceRecorder(), **kwargs)


def run_turn(orchestrator: TurnOrchestrator) -> None:
    orchestrator.begin_turn(make_interaction())
    orchestrator.ingest(make_evidence(text="我刚睡醒"))
    orchestrator.run()


def test_run_assembles_complete_turn_projection() -> None:
    orchestrator = make_orchestrator()
    run_turn(orchestrator)
    projection = orchestrator.turn_projection
    assert projection is not None
    assert isinstance(projection, TurnProjection)
    assert projection.interaction_id == "interaction-1"
    assert projection.scope == make_scope()
    assert projection.observations == orchestrator.observations
    assert projection.situation is not None
    assert projection.assessment_trace_ref is not None
    assert projection.projected_mind_state is orchestrator.projected
    assert projection.projected_mind_state.committed is False
    intent = orchestrator.intent
    assert intent is not None
    assert projection.intent_refs == (intent.intent_id,)
    assert projection.policy_result_ref is not None
    assert projection.created_at == NOW
    assert projection.projection_id == "projection-interaction-1"


def test_projection_is_not_canonical_before_commit() -> None:
    orchestrator = make_orchestrator()
    run_turn(orchestrator)
    assert orchestrator.turn_projection is not None
    assert orchestrator.canonical == ()  # projection not promoted


def test_stub_projection_has_no_turn_commit_intent() -> None:
    """The stub projects a fresh dimension; no real before/after pair exists."""
    orchestrator = make_orchestrator()
    run_turn(orchestrator)
    assert orchestrator.turn_projection is not None
    assert orchestrator.turn_projection.transition_intents == ()


def test_same_dimension_projection_carries_turn_commit_intent() -> None:
    from mind_runtime.contracts import (
        EmotionalTransitionInput,
        EmotionalTransitionResult,
        ProjectedMindState,
        RuntimeState,
        StateDefinition,
        StateDomain,
        StateValueType,
        SyncFields,
    )
    from mind_runtime.pipeline.stubs import StubEmotionalTransition
    from mind_runtime.state.definitions import StateDefinitionRegistry

    class SameDimensionTransition:
        """Projects the effective dimension (a real before/after pair)."""

        def __init__(self) -> None:
            self._delegate = StubEmotionalTransition(clock=FakeClock(NOW))

        def transition(
            self, transition_input: EmotionalTransitionInput
        ) -> EmotionalTransitionResult:
            state = RuntimeState(
                state_id="user.sleep.phase:2",
                scope=transition_input.scope,
                origin_runtime_id="runtime-1",
                dimension="user.sleep.phase",
                value="awake",
                status="active",
                valid_from=NOW,
                valid_until=None,
                relevant_until=None,
                last_observed_at=NOW,
                evidence_refs=("evidence-1",),
                transition_refs=(),
                updated_at=NOW,
                version=2,
                sync=SyncFields(
                    transition_input.scope,
                    "runtime-1",
                    "user.sleep.phase:2",
                    2,
                    "idem",
                ),
            )
            projection = ProjectedMindState(
                projection_id=f"projection-{transition_input.interaction_id}",
                scope=transition_input.scope,
                origin_runtime_id="runtime-1",
                projected_states=(state,),
                sync=SyncFields(
                    transition_input.scope,
                    "runtime-1",
                    f"projection-{transition_input.interaction_id}",
                    1,
                    "idem",
                ),
                committed=False,
            )
            return replace(
                self._delegate.transition(transition_input),
                projected=projection,
            )

    definition = StateDefinition(
        key="user.sleep.phase",
        domain=StateDomain.USER,
        value_type=StateValueType.CATEGORICAL,
        dynamics_policy="categorical_lifecycle",
        default_validity_policy=None,
        bounds=None,
    )
    canonical = make_state(dimension="user.sleep.phase", value="sleeping", status="active")
    orchestrator = make_orchestrator(
        emotional_transition=SameDimensionTransition(),
        definitions=StateDefinitionRegistry((definition,)),
        canonical_snapshot=(canonical,),
    )
    run_turn(orchestrator)
    projection = orchestrator.turn_projection
    assert projection is not None
    assert len(projection.transition_intents) == 1
    intent = projection.transition_intents[0]
    assert intent.commit_phase == TURN_COMMIT_PHASE
    assert intent.target_dimension == "user.sleep.phase"
    assert intent.proposed_after.dimension == "user.sleep.phase"
    assert intent.before is canonical


def test_commit_promotes_projection_to_canonical() -> None:
    orchestrator = make_orchestrator()
    run_turn(orchestrator)
    orchestrator.commit_turn()
    assert orchestrator.turn_projection is not None
    projected_state = orchestrator.turn_projection.projected_mind_state.projected_states[0]
    assert any(state.state_id == projected_state.state_id for state in orchestrator.canonical)


def test_abort_discards_projection_canonical_unchanged() -> None:
    orchestrator = make_orchestrator()
    run_turn(orchestrator)
    canonical_before = orchestrator.canonical
    orchestrator.abort_turn()
    assert orchestrator.canonical == canonical_before
    assert orchestrator.turn_projection is not None  # kept for inspection


def test_properties_empty_before_begin_turn() -> None:
    orchestrator = make_orchestrator()
    assert orchestrator.turn_projection is None
    assert orchestrator.transition_result is None
    assert orchestrator.intent is None
    assert orchestrator.projected is None
    assert orchestrator.situation is None


def test_commit_without_run_promotes_nothing() -> None:
    orchestrator = make_orchestrator()
    orchestrator.begin_turn(make_interaction())
    orchestrator.commit_turn()
    assert orchestrator.canonical == ()


def test_allowed_policy_records_consistent_permission_and_result() -> None:
    from mind_runtime.contracts import (
        ActionDecision,
        ActionPermission,
        ActionPolicyInput,
        ActionPolicyResult,
    )

    class NoPermissionPolicy:
        def policy(self, policy_input: ActionPolicyInput) -> ActionPolicyResult:
            intent = policy_input.intent
            scope = policy_input.scope
            return ActionPolicyResult(
                policy_id="policy-1",
                scope=scope,
                origin_runtime_id="runtime-1",
                intent_id=intent.intent_id,
                decision=ActionDecision.ALLOW,
                permission=ActionPermission(
                    permission_id="permission-1",
                    scope=scope,
                    origin_runtime_id="runtime-1",
                    action_type=intent.kind,
                    allowed=True,
                    reasons=("stub",),
                    constraints=(),
                ),
                reason_codes=("stub",),
            )

    orchestrator = make_orchestrator(action_policy=NoPermissionPolicy())
    run_turn(orchestrator)
    projection = orchestrator.turn_projection
    assert projection is not None
    assert projection.policy_result_ref == "policy-1"


def test_agent_failure_never_promotes_projection() -> None:
    from mind_runtime.pipeline.ports import AgentFailure

    class FailingAgent:
        def respond(self, provider_context: object) -> str:
            raise AgentFailure("agent boom")

    orchestrator = make_orchestrator(agent=FailingAgent())
    orchestrator.begin_turn(make_interaction())
    orchestrator.ingest(make_evidence(text="hello"))
    try:
        orchestrator.run()
    except AgentFailure:
        pass
    # The projection may be assembled, but it is never promoted: canonical
    # stays empty and the turn ends ABORTED.
    assert orchestrator.canonical == ()
    assert orchestrator.state.value == "aborted"
    assert orchestrator.projected is not None
    assert orchestrator.projected.committed is False


def test_commit_rejects_stale_projection() -> None:
    """D5.3 optimistic commit: a moved canonical rejects the projection."""
    from mind_runtime.pipeline.orchestrator import StaleProjectionError

    orchestrator = make_orchestrator()
    run_turn(orchestrator)
    assert orchestrator.projected is not None
    # Simulate a concurrent writer committing a higher-version state.
    from dataclasses import replace

    from tests.golden.fixtures.common import make_state

    base = make_state(dimension="user.other.fact", value="x", status="active")
    concurrent = replace(base, version=2, sync=replace(base.sync, version=2))
    orchestrator._canonical[concurrent.state_id] = concurrent
    try:
        orchestrator.commit_turn()
    except StaleProjectionError as error:
        assert "stale" in str(error)
    else:
        raise AssertionError("stale projection must not commit silently")
    # The stale projection was NOT promoted.
    assert not any(
        state.state_id == orchestrator.projected.projected_states[0].state_id
        for state in orchestrator.canonical
    )
    assert orchestrator.state.value == "dispatching"


def test_runtime_id_flows_into_context_and_receipt() -> None:
    """D5 review NIT: no hard-coded runtime-1 in derived artifacts."""
    orchestrator = make_orchestrator(runtime_id="lara")
    run_turn(orchestrator)
    assert orchestrator.decision_context is not None
    assert orchestrator.decision_context.origin_runtime_id == "lara"
    assert orchestrator.action_receipt is not None
    assert orchestrator.action_receipt.origin_runtime_id == "lara"
    assert orchestrator.action_receipt.sync.origin_runtime_id == "lara"
    projection = orchestrator.turn_projection
    assert projection is not None
    assert projection.origin_runtime_id == "lara"


def test_persona_defaults_transition_to_engine_port() -> None:
    """D7.6/D7.7: a persona swaps the stub for the real engine port, and the
    agent affect projects into the persona's own scope (never the user
    interaction scope)."""
    from mind_runtime.dynamics.kayla_v0 import kayla_v0_profile
    from mind_runtime.dynamics.ports import EngineEmotionalTransitionPort

    persona = kayla_v0_profile()
    orchestrator = make_orchestrator(persona=persona)
    assert isinstance(orchestrator.emotional_transition, EngineEmotionalTransitionPort)
    run_turn(orchestrator)
    assert orchestrator.projected is not None
    projected_states = orchestrator.projected.projected_states
    assert tuple(state.dimension for state in projected_states) == persona.dimension_keys()
    kayla_scope = Scope(domain=ScopeDomain.AGENT, agent_id="kayla_v0", persona_id="kayla_v0")
    assert all(state.scope == kayla_scope for state in projected_states)
    # The turn projection envelope stays in the user interaction scope.
    assert orchestrator.turn_projection is not None
    assert orchestrator.turn_projection.scope == make_scope()


def test_kayla_turn_commit_promotes_agent_scoped_affect() -> None:
    """D7.7: a user-scope Kayla turn commits the agent-scoped affect into
    canonical through the real orchestrator."""
    from mind_runtime.dynamics.kayla_v0 import kayla_v0_profile

    orchestrator = make_orchestrator(persona=kayla_v0_profile())
    run_turn(orchestrator)
    orchestrator.commit_turn()
    assert orchestrator.projected is not None
    projected_states = orchestrator.projected.projected_states
    projected_ids = {state.state_id for state in projected_states}
    committed = tuple(state for state in orchestrator.canonical if state.state_id in projected_ids)
    assert {state.dimension for state in committed} == {
        "agent.affect.longing",
        "agent.affect.irritation",
        "agent.affect.anxiety",
        "agent.affect.excitement",
    }
    assert all(
        state.scope == Scope(domain=ScopeDomain.AGENT, agent_id="kayla_v0", persona_id="kayla_v0")
        for state in committed
    )


def test_kayla_turn_abort_never_promotes_agent_affect() -> None:
    """D7.7: aborting a Kayla turn leaves canonical untouched."""
    from mind_runtime.dynamics.kayla_v0 import kayla_v0_profile

    orchestrator = make_orchestrator(persona=kayla_v0_profile())
    run_turn(orchestrator)
    canonical_before = orchestrator.canonical
    orchestrator.abort_turn()
    assert orchestrator.canonical == canonical_before
