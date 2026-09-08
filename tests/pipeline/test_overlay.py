"""D4.8 current-turn factual overlay tests: read-your-writes and commit/abort."""

from datetime import UTC, datetime, timedelta
from typing import Any

from mind_runtime.contracts import (
    Evidence,
    Interaction,
    InteractionStatus,
    Observation,
    Scope,
    SyncFields,
)
from mind_runtime.facts.ports import FactAdmissionDisposition, FactAdmissionResult
from mind_runtime.pipeline.orchestrator import TurnOrchestrator
from mind_runtime.pipeline.trace import TraceRecorder
from mind_runtime.state.definitions import StateDefinitionRegistry
from mind_runtime.state.lifecycle import StateLifecycle
from mind_runtime.state.reconciler import StateIntent, interpret_observation
from tests.golden.fixtures.common import make_evidence, make_scope
from tests.support.fake_clock import FakeClock

NOW = datetime(2026, 8, 21, 22, 0, tzinfo=UTC)


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


class TypedFactPort:
    """Fact port that returns dimension-typed observations (test adapter)."""

    def __init__(self, *, key: str, value: object) -> None:
        self._key = key
        self._value = value

    def admit(
        self,
        evidence: Evidence,
        *,
        interaction_id: str,
        writing_runtime: str,
        writing_persona_id: str | None,
    ) -> FactAdmissionResult:
        scope = evidence.scope
        observation = Observation(
            id=f"observation-{evidence.id}",
            interaction_id=interaction_id,
            scope=scope,
            origin_runtime_id=writing_runtime,
            type="factual",
            key=self._key,
            value=self._value,
            confidence=1.0,
            observed_at=evidence.occurred_at,
            evidence_refs=(evidence.id,),
            sync=SyncFields(scope, writing_runtime, f"observation-{evidence.id}", 1, "idem"),
        )
        return FactAdmissionResult(observation, FactAdmissionDisposition.NEW)


def make_orchestrator(
    key: str = "user.sleep.phase.observed", value: object = "awake", **kwargs: Any
) -> TurnOrchestrator:
    return TurnOrchestrator(
        clock=FakeClock(NOW),
        trace=TraceRecorder(),
        fact_ingest=TypedFactPort(key=key, value=value),
        **kwargs,
    )


def run_turn(orchestrator: TurnOrchestrator) -> None:
    orchestrator.begin_turn(make_interaction())
    orchestrator.ingest(make_evidence(text="我刚睡醒"))
    orchestrator.run()


# --- interpret_observation ---


def test_interpret_value_observation() -> None:
    result = make_orchestrator().fact_ingest.admit(
        make_evidence(text="x"),
        interaction_id="i-1",
        writing_runtime="runtime-1",
        writing_persona_id=None,
    )
    observation = result.observation
    intent = interpret_observation(observation)
    assert intent == StateIntent(
        dimension="user.sleep.phase",
        value="awake",
        observed_at=observation.observed_at,
        scope=observation.scope,
        origin_runtime_id="runtime-1",
        evidence_refs=observation.evidence_refs,
        lifecycle=None,
    )


def test_interpret_terminal_observation() -> None:
    result = TypedFactPort(key="user.planning.calligraphy.cancelled", value="cancelled").admit(
        make_evidence(text="x"),
        interaction_id="i-1",
        writing_runtime="runtime-1",
        writing_persona_id=None,
    )
    observation = result.observation
    intent = interpret_observation(observation)
    assert intent is not None
    assert intent.dimension == "user.planning.calligraphy"
    assert intent.lifecycle is StateLifecycle.CANCELLED


def test_interpret_source_typed_observation_returns_none() -> None:
    from mind_runtime.facts.service import FactIngestService

    service = FactIngestService(clock=FakeClock(NOW))
    result = service.admit(
        make_evidence(text="我刚睡醒"),
        interaction_id="i-1",
        writing_runtime="runtime-1",
        writing_persona_id=None,
    )
    observation = result.observation
    assert observation.key == "user_message.observed"
    assert interpret_observation(observation) is None


def test_interpret_unregistered_dimension_still_yields_intent() -> None:
    """Interpretation is structural; policy resolution is the registry's job."""
    result = TypedFactPort(key="user.never.registered.observed", value="x").admit(
        make_evidence(text="x"),
        interaction_id="i-1",
        writing_runtime="runtime-1",
        writing_persona_id=None,
    )
    assert interpret_observation(result.observation) is not None


def test_interpret_malformed_keys_return_none() -> None:
    for key in ("no-suffix", "user..observed", "bogus.phase.observed", "user.phase.weird"):
        result = TypedFactPort(key=key, value="x").admit(
            make_evidence(text="x"),
            interaction_id="i-1",
            writing_runtime="runtime-1",
            writing_persona_id=None,
        )
        assert interpret_observation(result.observation) is None, key


# --- orchestrator ingest-commit (D5.3 read-your-writes) ---


def test_run_commits_facts_into_canonical_before_projection() -> None:
    orchestrator = make_orchestrator()
    run_turn(orchestrator)
    assert len(orchestrator.overlay) == 1
    overlay_state = orchestrator.overlay[0]
    assert overlay_state.dimension == "user.sleep.phase"
    assert overlay_state.value == "awake"
    # D5.3: facts are ingest-committed — canonical already carries them.
    assert any(
        state.dimension == "user.sleep.phase" and state.value == "awake"
        for state in orchestrator.canonical
    )
    # The decision context references the committed factual state.
    assert orchestrator.decision_context is not None
    assert orchestrator.decision_context.effective_user_state_ref == overlay_state.state_id
    # The projection is NOT canonical yet.
    assert not any(state.dimension == "user.affect.stub" for state in orchestrator.canonical)


def test_commit_promotes_projection_on_top_of_facts() -> None:
    orchestrator = make_orchestrator()
    run_turn(orchestrator)
    assert orchestrator.projected is not None
    orchestrator.commit_turn()
    assert any(
        state.dimension == "user.sleep.phase" and state.value == "awake"
        for state in orchestrator.canonical
    )
    assert any(
        state.state_id == orchestrator.projected.projected_states[0].state_id
        for state in orchestrator.canonical
    )


def test_abort_keeps_ingested_facts_discards_projection() -> None:
    """G13b core: ingested facts survive a cognitive abort."""
    orchestrator = make_orchestrator()
    run_turn(orchestrator)
    projected = orchestrator.projected
    assert projected is not None
    projected_id = projected.projected_states[0].state_id
    orchestrator.abort_turn()
    # Facts stay committed.
    assert any(
        state.dimension == "user.sleep.phase" and state.value == "awake"
        for state in orchestrator.canonical
    )
    # The projection was discarded.
    assert not any(state.state_id == projected_id for state in orchestrator.canonical)


def test_ingest_transitions_exposed_for_turn() -> None:
    orchestrator = make_orchestrator()
    run_turn(orchestrator)
    assert len(orchestrator.ingest_transitions) == 0  # creation has no before
    orchestrator.begin_turn(make_interaction())
    orchestrator.ingest(make_evidence(text="我刚睡醒", occurred_at=NOW))
    orchestrator.run()
    # Second turn reaffirms the same value -> one transition.
    assert len(orchestrator.ingest_transitions) == 1


def test_run_without_typed_observations_has_empty_overlay() -> None:
    from mind_runtime.facts.service import FactIngestService

    orchestrator = TurnOrchestrator(
        clock=FakeClock(NOW),
        trace=TraceRecorder(),
        fact_ingest=FactIngestService(clock=FakeClock(NOW)),
    )
    run_turn(orchestrator)
    assert orchestrator.overlay == ()
    assert orchestrator.canonical == ()


def test_ingest_commit_is_deterministic_across_fresh_runs() -> None:
    """Same inputs + same clock -> same canonical, same overlay (replay)."""

    def run_fresh() -> tuple[tuple[object, ...], object]:
        orchestrator = make_orchestrator()
        run_turn(orchestrator)
        canonical = tuple(
            (state.dimension, state.value, state.version) for state in orchestrator.canonical
        )
        return canonical, orchestrator.overlay

    first = run_fresh()
    second = run_fresh()
    assert first == second


def test_overlay_uses_definition_policies() -> None:
    from mind_runtime.contracts import StateDefinition, StateDomain, StateValueType

    definition = StateDefinition(
        key="user.sleep.phase",
        domain=StateDomain.USER,
        value_type=StateValueType.CATEGORICAL,
        dynamics_policy="categorical_lifecycle",
        default_validity_policy="ttl:6h",
        bounds=None,
    )
    orchestrator = TurnOrchestrator(
        clock=FakeClock(NOW),
        trace=TraceRecorder(),
        fact_ingest=TypedFactPort(key="user.sleep.phase.observed", value="awake"),
        definitions=StateDefinitionRegistry((definition,)),
    )
    run_turn(orchestrator)
    assert orchestrator.overlay[0].valid_until == NOW + timedelta(hours=6)
