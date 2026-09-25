"""Replay-stable Reality eligibility tests."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest
from tests.reality.test_reality_input import (
    NOW,
    FakePersistent,
    evidence,
    interaction,
    make_runtime,
    run_turn,
)
from tests.support.fake_clock import FakeClock

from mind_runtime.contracts import (
    Authority,
    AuthorityLevel,
    EffectiveWindow,
    EffectiveWindowKind,
    Evidence,
    Observation,
    ObservationModality,
    RuntimeState,
    Scope,
    ScopeDomain,
    SemanticPrecision,
    SemanticRelation,
    SemanticTime,
    SyncFields,
)
from mind_runtime.facts.persistence import SqliteFactBackend
from mind_runtime.facts.service import FactIngestService
from mind_runtime.pipeline.orchestrator import TurnOrchestrator
from mind_runtime.pipeline.trace import TraceRecorder
from mind_runtime.reality import RealityInputService
from mind_runtime.reality.eligibility import (
    StateEligibility,
    evaluate_state_eligibility,
)
from mind_runtime.reality.extraction import FastRealityExtractor
from mind_runtime.reality.temporal import normalize_temporal
from mind_runtime.state.definitions import StateDefinitionRegistry
from mind_runtime.state.persistence import SqliteStateBackend

T1 = datetime(2026, 9, 10, 10, 0, tzinfo=UTC)
T2 = T1 + timedelta(days=2)
SCOPE = Scope(domain=ScopeDomain.USER, user_id="replay-user")


def make_current_observation() -> Observation:
    return Observation(
        id="replay-stability-observation",
        interaction_id="original-interaction",
        scope=SCOPE,
        origin_runtime_id="runtime-reality",
        type="factual",
        key="user.health.stomach_pain.observed",
        value="active",
        confidence=1.0,
        observed_at=T1,
        evidence_refs=("evidence-replay-stability",),
        modality=ObservationModality.ASSERTED,
        semantic_time=SemanticTime(
            relation=SemanticRelation.CURRENT,
            precision=SemanticPrecision.INSTANT,
        ),
        effective_window=EffectiveWindow(
            kind=EffectiveWindowKind.INTERVAL,
            start_at=T1,
            end_at=T1 + timedelta(hours=1),
        ),
        sync=SyncFields(
            SCOPE,
            "runtime-reality",
            "replay-stability-observation",
            1,
            "idem-replay-stability-observation",
        ),
    )


def make_plan_state(dimension: str, *, state_scope: Scope = SCOPE) -> RuntimeState:
    state_id = f"state-{dimension.replace('.', '-')}"
    return RuntimeState(
        state_id=state_id,
        scope=state_scope,
        dimension=dimension,
        value="planned",
        status="active",
        valid_from=NOW,
        valid_until=None,
        relevant_until=None,
        last_observed_at=NOW,
        evidence_refs=(f"evidence-{state_id}",),
        transition_refs=(),
        updated_at=NOW,
        origin_runtime_id="runtime-reality",
        version=1,
        sync=SyncFields(state_scope, "runtime-reality", state_id, 1, f"idem-{state_id}"),
    )


def make_terminal_runtime(plan_dimensions: tuple[str, ...]):
    persistent = FakePersistent(
        [
            {
                "type": "plan",
                "key": "calligraphy",
                "value": "cancelled",
                "certainty": "confirmed",
                "time_expression": "now",
                "confidence": 1.0,
            }
        ]
    )
    clock, orchestrator, _ = make_runtime(persistent=persistent)
    states = tuple(make_plan_state(dimension) for dimension in plan_dimensions)
    orchestrator._canonical = {state.state_id: state for state in states}
    return clock, orchestrator


def test_replay_produces_same_eligibility_for_same_observation() -> None:
    observation = make_current_observation()

    initial = evaluate_state_eligibility(observation, admission_anchor=T1)
    replay = evaluate_state_eligibility(observation, admission_anchor=T1)

    assert initial is StateEligibility.ELIGIBLE_CURRENT
    assert replay is initial
    with pytest.raises(ValueError, match="admission_anchor"):
        evaluate_state_eligibility(observation, admission_anchor=T2)


def test_current_assertion_replay_ignores_later_wall_clock() -> None:
    observation = make_current_observation()
    replay_wall_clock = T2

    initial = evaluate_state_eligibility(observation, admission_anchor=observation.observed_at)
    replay = evaluate_state_eligibility(observation, admission_anchor=observation.observed_at)

    assert replay_wall_clock > observation.observed_at
    assert initial is StateEligibility.ELIGIBLE_CURRENT
    assert replay is StateEligibility.ELIGIBLE_CURRENT


def test_current_assertion_replay_through_orchestrator_stays_eligible() -> None:
    clock, orchestrator, _ = make_runtime()
    original = evidence("stomach-stable", "我现在胃疼")

    run_turn(orchestrator, "stomach-stable", "我现在胃疼")
    initial = orchestrator._turn.reality_eligibilities[
        "reality-observation-evidence-stomach-stable-0"
    ]

    clock.set(NOW + timedelta(days=2))
    orchestrator.begin_turn(interaction("stomach-stable-replay"))
    orchestrator.ingest(original)
    replay = orchestrator._turn.reality_eligibilities[
        "reality-observation-evidence-stomach-stable-0"
    ]

    assert initial is StateEligibility.ELIGIBLE_CURRENT
    assert replay is initial


def _with_normalized_temporal(
    *,
    observation_id: str,
    key: str,
    value: str,
    text: str,
    certainty_hint: str | None = None,
) -> Observation:
    temporal = normalize_temporal(
        text,
        anchor=T1,
        timezone=ZoneInfo("Asia/Shanghai"),
        certainty_hint=certainty_hint,
    )
    return replace(
        make_current_observation(),
        id=observation_id,
        key=key,
        value=value,
        modality=temporal.modality,
        semantic_time=temporal.semantic_time,
        effective_window=temporal.effective_window,
        sync=SyncFields(
            SCOPE,
            "runtime-reality",
            observation_id,
            1,
            f"idem-{observation_id}",
        ),
    )


@pytest.mark.parametrize(
    ("observation_id", "text", "certainty_hint", "key", "expected"),
    [
        (
            "stable-planned-calligraphy",
            "我明天下午去写书法",
            None,
            "user.plan.calligraphy.observed",
            StateEligibility.OBSERVATION_ONLY,
        ),
        (
            "stable-tentative-calligraphy",
            "我明天下午可能去写书法",
            "tentative",
            "user.plan.calligraphy.observed",
            StateEligibility.OBSERVATION_ONLY,
        ),
        (
            "stable-past-sleep",
            "我昨晚没睡好",
            None,
            "user.sleep.phase.observed",
            StateEligibility.OBSERVATION_ONLY,
        ),
        (
            "stable-tentative-job",
            "我可能换工作",
            "tentative",
            "user.plan.job.observed",
            StateEligibility.OBSERVATION_ONLY,
        ),
    ],
)
def test_non_current_replay_stays_observation_only_after_window_moves(
    observation_id: str,
    text: str,
    certainty_hint: str | None,
    key: str,
    expected: StateEligibility,
) -> None:
    observation = _with_normalized_temporal(
        observation_id=observation_id,
        key=key,
        value="observed",
        text=text,
        certainty_hint=certainty_hint,
    )

    initial = evaluate_state_eligibility(observation, admission_anchor=observation.observed_at)
    replay = evaluate_state_eligibility(observation, admission_anchor=observation.observed_at)

    assert initial is expected
    assert replay is expected


def test_ordinary_eligibility_does_not_depend_on_canonical_snapshot() -> None:
    observation = make_current_observation()

    without_target = evaluate_state_eligibility(
        observation,
        admission_anchor=observation.observed_at,
        has_exact_target=False,
    )
    with_target = evaluate_state_eligibility(
        observation,
        admission_anchor=observation.observed_at,
        has_exact_target=True,
    )

    assert without_target is StateEligibility.ELIGIBLE_CURRENT
    assert with_target is without_target


def test_fast_extractor_emits_concrete_terminal_plan_key() -> None:
    candidates = FastRealityExtractor().extract("书法我不去了")

    assert FastRealityExtractor().extract("我不去了") == ()
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.dimension == "user.plan.calligraphy"
    assert candidate.lifecycle == "cancelled"
    assert candidate.observation_key == "user.plan.calligraphy.cancelled"
    assert candidate.value == "cancelled"


def test_concrete_terminal_key_cancels_only_exact_plan_dimension() -> None:
    runtime_scope = Scope(domain=ScopeDomain.USER, user_id="reality-user")
    _, orchestrator, _ = make_runtime()
    plans = (
        make_plan_state("user.plan.calligraphy", state_scope=runtime_scope),
        make_plan_state("user.plan.gym", state_scope=runtime_scope),
    )
    orchestrator._canonical = {state.state_id: state for state in plans}

    run_turn(orchestrator, "explicit-terminal", "书法我不去了")

    calligraphy = next(
        state for state in orchestrator.canonical if state.dimension == "user.plan.calligraphy"
    )
    gym = next(state for state in orchestrator.canonical if state.dimension == "user.plan.gym")
    observation = next(
        item
        for item in orchestrator.fact_ingest.observations.all()
        if item.key == "user.plan.calligraphy.cancelled"
    )
    assert calligraphy.status == "cancelled"
    assert gym.status == "active"
    assert (
        orchestrator._turn.reality_eligibilities[observation.id]
        is StateEligibility.ELIGIBLE_TERMINAL
    )
    assert orchestrator._ingest_transitions


def test_terminal_replay_uses_accepted_concrete_observation_without_reextracting() -> None:
    runtime_scope = Scope(domain=ScopeDomain.USER, user_id="reality-user")
    persistent = FakePersistent(
        [
            {
                "type": "plan",
                "key": "calligraphy",
                "value": "cancelled",
                "certainty": "confirmed",
                "time_expression": "now",
                "confidence": 1.0,
            }
        ]
    )
    _, orchestrator, _ = make_runtime(persistent=persistent)
    initial_state = make_plan_state("user.plan.calligraphy", state_scope=runtime_scope)
    orchestrator._canonical = {initial_state.state_id: initial_state}

    original = evidence("provider-terminal", "取消书法安排")
    run_turn(orchestrator, "provider-terminal", "取消书法安排")
    assert persistent.calls == 1
    initial_observation = next(
        item
        for item in orchestrator.fact_ingest.observations.all()
        if item.key == "user.plan.calligraphy.cancelled"
    )
    assert (
        orchestrator._turn.reality_eligibilities[initial_observation.id]
        is StateEligibility.ELIGIBLE_TERMINAL
    )

    replacement = make_plan_state("user.plan.calligraphy", state_scope=runtime_scope)
    orchestrator._canonical = {replacement.state_id: replacement}
    orchestrator.begin_turn(interaction("provider-terminal-replay"))
    orchestrator.ingest(original)

    assert persistent.calls == 1
    assert (
        orchestrator._turn.reality_eligibilities[initial_observation.id]
        is StateEligibility.ELIGIBLE_TERMINAL
    )
    orchestrator.run()
    assert next(
        state for state in orchestrator.canonical if state.dimension == "user.plan.calligraphy"
    ).status == "cancelled"


def test_terminal_key_with_incompatible_existing_lifecycle_fails_closed() -> None:
    runtime_scope = Scope(domain=ScopeDomain.USER, user_id="reality-user")
    _, orchestrator, _ = make_runtime()
    resolved = replace(
        make_plan_state("user.plan.calligraphy", state_scope=runtime_scope),
        status="resolved",
    )
    orchestrator._canonical = {resolved.state_id: resolved}

    run_turn(orchestrator, "incompatible-terminal", "书法我不去了")

    observation = next(
        item
        for item in orchestrator.fact_ingest.observations.all()
        if item.key == "user.plan.calligraphy.cancelled"
    )
    assert (
        orchestrator._turn.reality_eligibilities[observation.id]
        is StateEligibility.OBSERVATION_ONLY
    )
    assert next(
        state for state in orchestrator.canonical if state.dimension == "user.plan.calligraphy"
    ).status == "resolved"
    assert orchestrator._ingest_transitions == ()


@pytest.mark.parametrize(
    "plan_dimensions",
    [
        ("user.plan.calligraphy",),
        ("user.plan.calligraphy", "user.plan.painting"),
    ],
)
def test_terminal_without_exact_target_is_observation_only(
    plan_dimensions: tuple[str, ...],
) -> None:
    _, orchestrator = make_terminal_runtime(plan_dimensions)
    before = tuple(orchestrator._canonical.values())

    with patch("mind_runtime.pipeline.orchestrator.FactualReconciler") as reconciler:
        run_turn(orchestrator, "terminal-fail-closed", "我不去了")

    observation = next(
        item
        for item in orchestrator.fact_ingest.observations.all()
        if item.key == "user.plan.calligraphy.cancelled"
    )
    assert (
        orchestrator._turn.reality_eligibilities[observation.id]
        is StateEligibility.OBSERVATION_ONLY
    )
    assert tuple(
        state
        for state in orchestrator._canonical.values()
        if state.dimension.startswith("user.plan.")
    ) == before
    assert orchestrator._ingest_transitions == ()
    reconciler.assert_not_called()


def test_terminal_replay_stays_observation_only_after_state_universe_changes() -> None:
    _, orchestrator = make_terminal_runtime(("user.plan.calligraphy",))
    original = evidence("terminal-replay", "我不去了")
    run_turn(orchestrator, "terminal-replay", "我不去了")

    orchestrator._canonical = {
        state.state_id: state
        for state in (
            make_plan_state("user.plan.painting"),
            make_plan_state("user.plan.running"),
        )
    }
    orchestrator.begin_turn(interaction("terminal-replay-later"))
    orchestrator.ingest(original)

    observation_id = "reality-observation-evidence-terminal-replay-0"
    assert (
        orchestrator._turn.reality_eligibilities[observation_id]
        is StateEligibility.OBSERVATION_ONLY
    )
    assert orchestrator._ingest_transitions == ()


def test_terminal_restart_stays_observation_only_after_state_universe_changes(
    tmp_path: Path,
) -> None:
    fact_path = tmp_path / "facts.sqlite"
    state_path = tmp_path / "state.sqlite"
    fact_backend = SqliteFactBackend(fact_path)
    state_backend = SqliteStateBackend(state_path)
    original = evidence("terminal-restart", "我不去了")
    try:
        state_backend.save_state(make_plan_state("user.plan.calligraphy"))
        clock = FakeClock(NOW)
        first = TurnOrchestrator(
            clock=clock,
            trace=TraceRecorder(),
            runtime_id="runtime-reality",
            fact_ingest=FactIngestService(clock=clock, backend=fact_backend),
            definitions=StateDefinitionRegistry(),
            state_backend=state_backend,
            reality_input=RealityInputService(
                persistent=FakePersistent(
                    [
                        {
                            "type": "plan",
                            "key": "calligraphy",
                            "value": "cancelled",
                            "certainty": "confirmed",
                            "time_expression": "now",
                            "confidence": 1.0,
                        }
                    ]
                )
            ),
        )
        with patch("mind_runtime.pipeline.orchestrator.FactualReconciler") as reconciler:
            first.begin_turn(interaction("terminal-restart"))
            first.ingest(original)
            first.run()
            first.commit_turn()
        assert first._ingest_transitions == ()
        reconciler.assert_not_called()
        state_backend.save_state(make_plan_state("user.plan.painting"))
    finally:
        fact_backend.close()
        state_backend.close()

    fact_backend_b = SqliteFactBackend(fact_path)
    state_backend_b = SqliteStateBackend(state_path)
    try:
        clock_b = FakeClock(T2)
        restarted = TurnOrchestrator(
            clock=clock_b,
            trace=TraceRecorder(),
            runtime_id="runtime-reality",
            fact_ingest=FactIngestService(clock=clock_b, backend=fact_backend_b),
            definitions=StateDefinitionRegistry(),
            state_backend=state_backend_b,
            reality_input=RealityInputService(
                persistent=FakePersistent(
                    [
                        {
                            "type": "plan",
                            "key": "calligraphy",
                            "value": "cancelled",
                            "certainty": "confirmed",
                            "time_expression": "now",
                            "confidence": 1.0,
                        }
                    ]
                )
            ),
        )
        with patch("mind_runtime.pipeline.orchestrator.FactualReconciler") as reconciler_b:
            restarted.begin_turn(interaction("terminal-restart-later"))
            restarted.ingest(original)
            restarted.run()
            restarted.commit_turn()
        observation_id = "reality-observation-evidence-terminal-restart-0"
        assert (
            restarted._turn.reality_eligibilities[observation_id]
            is StateEligibility.OBSERVATION_ONLY
        )
        assert restarted._ingest_transitions == ()
        reconciler_b.assert_not_called()
    finally:
        fact_backend_b.close()
        state_backend_b.close()


def test_restart_rebuilds_same_eligibility_from_durable_observation(tmp_path: Path) -> None:
    t0 = T1 - timedelta(minutes=5)
    backend = SqliteFactBackend(tmp_path / "facts.sqlite")
    try:
        scope = SCOPE
        source = Evidence(
            id="evidence-replay-stability",
            source_type="user_message",
            source_id="source-replay-stability",
            authority_level=AuthorityLevel.ASSERTED,
            authority=Authority(scope, AuthorityLevel.ASSERTED, "source-replay-stability"),
            occurred_at=t0,
            received_at=T1,
            payload={"text": "我现在胃疼"},
            scope=scope,
            origin_runtime_id="runtime-reality",
            sync=SyncFields(
                scope,
                "runtime-reality",
                "evidence-replay-stability",
                1,
                "idem-evidence-replay-stability",
            ),
        )
        service_a = FactIngestService(clock=FakeClock(T1), backend=backend)
        service_a.admit(
            source,
            interaction_id="original-interaction",
            writing_runtime="runtime-reality",
            writing_persona_id=None,
        )
        reality = make_runtime()[2]
        admitted = reality.extract_and_admit(
            source,
            fact_ingest=service_a,
            interaction_id="retry-interaction",
            writing_runtime="runtime-reality",
        )
        observation = admitted[0]
        initial = evaluate_state_eligibility(observation, admission_anchor=observation.observed_at)
        assert observation.observed_at == T1
        assert observation.interaction_id == "original-interaction"
    finally:
        backend.close()

    backend_b = SqliteFactBackend(tmp_path / "facts.sqlite")
    try:
        service_b = FactIngestService(clock=FakeClock(T2), backend=backend_b)
        loaded = next(item for item in service_b.observations.all() if item.id == observation.id)
        replay = evaluate_state_eligibility(loaded, admission_anchor=loaded.observed_at)
        assert replay is initial is StateEligibility.ELIGIBLE_CURRENT
        assert loaded.observed_at == T1
        assert loaded.interaction_id == "original-interaction"
    finally:
        backend_b.close()


def test_future_plan_replay_preserves_c1_p0_isolation_after_window() -> None:
    persistent = FakePersistent(
        [
            {
                "type": "plan",
                "key": "calligraphy",
                "value": "write calligraphy",
                "certainty": "planned",
                "time_expression": "afternoon",
                "confidence": 0.95,
            }
        ]
    )
    clock, orchestrator, _ = make_runtime(persistent=persistent)
    original = evidence("stable-plan", "我明天下午去写书法")

    run_turn(orchestrator, "stable-plan", "我明天下午去写书法")
    initial = orchestrator._turn.reality_eligibilities[
        "reality-observation-evidence-stable-plan-0"
    ]
    clock.set(NOW + timedelta(days=2))
    orchestrator.begin_turn(interaction("stable-plan-replay"))
    orchestrator.ingest(original)
    replay = orchestrator._turn.reality_eligibilities[
        "reality-observation-evidence-stable-plan-0"
    ]

    assert initial is StateEligibility.OBSERVATION_ONLY
    assert replay is initial
    assert not any(state.dimension == "user.plan.calligraphy" for state in orchestrator.canonical)
    assert orchestrator._ingest_transitions == ()
    assert orchestrator.decision_context is None
