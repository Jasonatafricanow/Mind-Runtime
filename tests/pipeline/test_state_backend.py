"""D5.8 StateBackend tests: canonical state is durable across restart.

The TurnOrchestrator loads canonical state from the durable backend at
startup (highest version per scope+dimension), persists ingest-committed
facts and turn-committed projections through it, and a fresh orchestrator
on the same backend restores canonical after restart.
"""

from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

from mind_runtime.contracts import (
    EmotionalTransitionInput,
    EmotionalTransitionResult,
    Evidence,
    Interaction,
    InteractionStatus,
    Observation,
    ProjectedMindState,
    RuntimeState,
    StateDefinition,
    StateDomain,
    StateValueType,
    SyncFields,
)
from mind_runtime.facts.ports import FactAdmissionDisposition, FactAdmissionResult
from mind_runtime.pipeline.orchestrator import TurnOrchestrator
from mind_runtime.pipeline.stubs import StubEmotionalTransition
from mind_runtime.pipeline.trace import TraceRecorder
from mind_runtime.state.definitions import StateDefinitionRegistry
from mind_runtime.state.persistence import SqliteStateBackend
from tests.golden.fixtures.common import make_evidence, make_scope, make_state
from tests.support.fake_clock import FakeClock

NOW = datetime(2026, 8, 23, 11, 0, tzinfo=UTC)


class _TypedFactPort:
    """Fact port returning one dimension-typed observation per evidence."""

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


def make_interaction() -> Interaction:
    return Interaction(
        interaction_id="interaction-1",
        scope=make_scope(),
        channel="chat",
        session_id="session-1",
        turn_id="turn-1",
        started_at=NOW,
        committed_at=None,
        status=InteractionStatus.OPEN,
    )


def make_orchestrator(backend: SqliteStateBackend, **kwargs: Any) -> TurnOrchestrator:
    return TurnOrchestrator(
        clock=FakeClock(NOW),
        trace=TraceRecorder(),
        fact_ingest=_TypedFactPort(key="user.sleep.phase.observed", value="awake"),
        state_backend=backend,
        **kwargs,
    )


def run_turn(orchestrator: TurnOrchestrator) -> None:
    orchestrator.begin_turn(make_interaction())
    orchestrator.ingest(make_evidence(text="我刚睡醒"))
    orchestrator.run()


def test_state_backend_loads_canonical_at_startup(tmp_path: Any) -> None:
    backend = SqliteStateBackend(tmp_path / "state.db")
    backend.save_state(make_state(dimension="user.sleep.phase", value="awake"))
    orchestrator = make_orchestrator(backend)
    assert any(
        state.dimension == "user.sleep.phase" and state.value == "awake"
        for state in orchestrator.canonical
    )
    backend.close()


def test_startup_load_keeps_highest_version_per_dimension(tmp_path: Any) -> None:
    from dataclasses import replace

    backend = SqliteStateBackend(tmp_path / "state.db")
    v1 = make_state(dimension="user.sleep.phase", value="sleeping")
    v2 = replace(
        v1,
        state_id="state-user.sleep.phase:2",
        value="awake",
        version=2,
        sync=SyncFields(v1.scope, v1.origin_runtime_id, "state-user.sleep.phase:2", 2, "idem-2"),
    )
    backend.save_state(v1)
    backend.save_state(v2)
    orchestrator = make_orchestrator(backend)
    values = [
        state.value for state in orchestrator.canonical if state.dimension == "user.sleep.phase"
    ]
    assert values == ["awake"]
    backend.close()


def test_startup_load_keeps_single_record_on_version_tie(tmp_path: Any) -> None:
    """Equal-version duplicates collapse to one current record per dimension."""
    backend = SqliteStateBackend(tmp_path / "state.db")
    backend.save_state(make_state(dimension="user.sleep.phase", value="awake", state_id="dup-a"))
    backend.save_state(make_state(dimension="user.sleep.phase", value="awake", state_id="dup-b"))
    orchestrator = make_orchestrator(backend)
    records = [state for state in orchestrator.canonical if state.dimension == "user.sleep.phase"]
    assert len(records) == 1
    backend.close()


def test_backend_and_snapshot_conflict_fails_closed(tmp_path: Any) -> None:
    import pytest

    backend = SqliteStateBackend(tmp_path / "state.db")
    with pytest.raises(ValueError, match="cannot both be provided"):
        TurnOrchestrator(
            clock=FakeClock(NOW),
            trace=TraceRecorder(),
            state_backend=backend,
            canonical_snapshot=(make_state(),),
        )
    backend.close()


def test_ingest_commit_persists_states_and_transitions(tmp_path: Any) -> None:
    backend = SqliteStateBackend(tmp_path / "state.db")
    # Seed a prior canonical record so the ingest turn is a state CHANGE
    # (a real before/after pair) and the reconciler emits a transition.
    backend.save_state(make_state(dimension="user.sleep.phase", value="sleeping"))
    orchestrator = make_orchestrator(backend)
    run_turn(orchestrator)
    loaded = backend.load_states()
    assert any(state.dimension == "user.sleep.phase" and state.value == "awake" for state in loaded)
    assert any(t.to_state.dimension == "user.sleep.phase" for t in backend.load_transitions())
    backend.close()


def test_commit_persists_projected_state(tmp_path: Any) -> None:
    from mind_runtime.dynamics.kayla_v0 import kayla_v0_profile

    backend = SqliteStateBackend(tmp_path / "state.db")
    orchestrator = make_orchestrator(backend, persona=kayla_v0_profile())
    run_turn(orchestrator)
    orchestrator.commit_turn()
    assert orchestrator.projected is not None
    projected_id = orchestrator.projected.projected_states[0].state_id
    assert any(state.state_id == projected_id for state in backend.load_states())
    backend.close()


def test_commit_persists_turn_commit_transition(tmp_path: Any) -> None:
    """A same-dimension projection persists its materialized transition."""
    definition = StateDefinition(
        key="user.sleep.phase",
        domain=StateDomain.USER,
        value_type=StateValueType.CATEGORICAL,
        dynamics_policy="categorical_lifecycle",
        default_validity_policy=None,
        bounds=None,
    )
    canonical = make_state(dimension="user.sleep.phase", value="sleeping", status="active")

    class SameDimensionTransition:
        def __init__(self) -> None:
            self._delegate = StubEmotionalTransition(clock=FakeClock(NOW))

        def transition(
            self, transition_input: EmotionalTransitionInput
        ) -> EmotionalTransitionResult:
            # MR-RUNTIME-05: the ingest reconciler durably commits :2
            # (superseded seed) and :3 (the 'awake' observation) before
            # commit_turn, so the turn-commit projection must target a
            # fresh version — re-projecting :2 with different content is
            # now (correctly) refused as a stale-writer conflict.
            state = RuntimeState(
                state_id="user.sleep.phase:4",
                scope=transition_input.scope,
                origin_runtime_id="runtime-1",
                dimension="user.sleep.phase",
                value="awake",
                status="active",
                valid_from=NOW,
                valid_until=None,
                relevant_until=None,
                last_observed_at=NOW,
                evidence_refs=(),
                transition_refs=(),
                updated_at=NOW,
                version=4,
                sync=SyncFields(
                    transition_input.scope,
                    "runtime-1",
                    "user.sleep.phase:4",
                    4,
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

    backend = SqliteStateBackend(tmp_path / "state.db")
    backend.save_state(canonical)
    orchestrator = TurnOrchestrator(
        clock=FakeClock(NOW),
        trace=TraceRecorder(),
        fact_ingest=_TypedFactPort(key="user.sleep.phase.observed", value="awake"),
        state_backend=backend,
        emotional_transition=SameDimensionTransition(),
        definitions=StateDefinitionRegistry((definition,)),
    )
    run_turn(orchestrator)
    orchestrator.commit_turn()
    transitions = backend.load_transitions()
    assert any(
        t.to_state.dimension == "user.sleep.phase" and t.to_state.value == "awake"
        for t in transitions
    )
    backend.close()


def test_abort_persists_only_ingested_facts(tmp_path: Any) -> None:
    from mind_runtime.dynamics.kayla_v0 import kayla_v0_profile

    backend = SqliteStateBackend(tmp_path / "state.db")
    orchestrator = make_orchestrator(backend, persona=kayla_v0_profile())
    run_turn(orchestrator)
    orchestrator.abort_turn()
    assert orchestrator.projected is not None
    projected_id = orchestrator.projected.projected_states[0].state_id
    loaded = backend.load_states()
    assert not any(state.state_id == projected_id for state in loaded)
    assert any(state.dimension == "user.sleep.phase" for state in loaded)
    backend.close()


def test_restart_recovers_canonical(tmp_path: Any) -> None:
    """G12a core: a fresh orchestrator on the same backend restores canonical."""
    backend = SqliteStateBackend(tmp_path / "state.db")
    first = make_orchestrator(backend)
    run_turn(first)
    first.commit_turn()
    canonical_after_commit = first.canonical
    first_dims = sorted((state.dimension, state.value) for state in canonical_after_commit)

    # Restart: a brand-new orchestrator on the same backend.
    restarted = make_orchestrator(backend)
    restarted_dims = sorted((state.dimension, state.value) for state in restarted.canonical)
    assert restarted_dims == first_dims
    assert any(
        state.dimension == "user.sleep.phase" and state.value == "awake"
        for state in restarted.canonical
    )
    backend.close()


def test_restart_recovers_committed_agent_affect(tmp_path: Any) -> None:
    """D7.7 + D5.8: committed agent-scoped affect survives restart."""
    from mind_runtime.dynamics.kayla_v0 import kayla_v0_profile

    backend = SqliteStateBackend(tmp_path / "state.db")
    first = make_orchestrator(backend, persona=kayla_v0_profile())
    run_turn(first)
    first.commit_turn()
    assert first.projected is not None
    projected_states = first.projected.projected_states
    projected_ids = {state.state_id for state in projected_states}

    restarted = make_orchestrator(backend)
    restarted_affect = tuple(
        state for state in restarted.canonical if state.state_id in projected_ids
    )
    assert {state.dimension for state in restarted_affect} == {
        "agent.affect.longing",
        "agent.affect.irritation",
        "agent.affect.anxiety",
        "agent.affect.excitement",
    }
    assert all(state.scope.domain.value == "agent" for state in restarted_affect)
    backend.close()
