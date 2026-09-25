"""STATEBAR-MR-REUSE-01 tests for the trimmed Reality input seam and frozen contract C1+P0."""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from tests.support.fake_clock import FakeClock

from mind_runtime.contracts import (
    Authority,
    AuthorityLevel,
    Evidence,
    Interaction,
    InteractionStatus,
    Observation,
    ObservationModality,
    Scope,
    ScopeDomain,
    SyncFields,
)
from mind_runtime.facts.ports import (
    FactAdmissionDisposition,
    FactAdmissionResult,
    RealityAdmissionRequest,
)
from mind_runtime.facts.service import FactIngestService
from mind_runtime.pipeline.orchestrator import TurnOrchestrator
from mind_runtime.pipeline.trace import TraceRecorder
from mind_runtime.reality.eligibility import StateEligibility
from mind_runtime.state.definitions import StateDefinitionRegistry

NOW = datetime(2026, 9, 9, 14, 0, tzinfo=UTC)


def scope() -> Scope:
    return Scope(domain=ScopeDomain.USER, user_id="reality-user")


def evidence(interaction_id: str, text: str, *, source_type: str = "user_message") -> Evidence:
    current_scope = scope()
    evidence_id = f"evidence-{interaction_id}"
    return Evidence(
        id=evidence_id,
        source_type=source_type,
        source_id=f"source-{interaction_id}",
        authority_level=AuthorityLevel.ASSERTED,
        occurred_at=NOW,
        received_at=NOW,
        payload={"text": text},
        scope=current_scope,
        origin_runtime_id="runtime-reality",
        authority=Authority(
            scope=current_scope,
            level=AuthorityLevel.ASSERTED,
            source_id=f"source-{interaction_id}",
        ),
        sync=SyncFields(
            current_scope,
            "runtime-reality",
            evidence_id,
            1,
            f"idem-{evidence_id}",
        ),
    )


def interaction(interaction_id: str) -> Interaction:
    return Interaction(
        interaction_id=interaction_id,
        scope=scope(),
        channel="test",
        session_id="reality-session",
        turn_id=f"turn-{interaction_id}",
        started_at=NOW,
        committed_at=None,
        status=InteractionStatus.OPEN,
    )


class FakePersistent:
    def __init__(self, payload: object) -> None:
        self.payload = payload
        self.calls = 0

    def extract(self, text: str) -> object:
        self.calls += 1
        return self.payload


def make_runtime(
    *, persistent: Any = None, reality_admission: Any = None
) -> tuple[FakeClock, TurnOrchestrator, Any]:
    from mind_runtime.reality import RealityInputService

    clock = FakeClock(NOW)
    fact_ingest = FactIngestService(clock=clock)
    reality = RealityInputService(persistent=persistent)
    orchestrator = TurnOrchestrator(
        clock=clock,
        trace=TraceRecorder(),
        runtime_id="runtime-reality",
        fact_ingest=fact_ingest,
        reality_admission=reality_admission,
        definitions=StateDefinitionRegistry(),
        reality_input=reality,
    )
    return clock, orchestrator, reality


def run_turn(orchestrator: TurnOrchestrator, interaction_id: str, text: str) -> None:
    orchestrator.begin_turn(interaction(interaction_id))
    orchestrator.ingest(evidence(interaction_id, text))
    orchestrator.run()
    orchestrator.commit_turn()


# ============================================================================
# Core tests updated for canonical key user.sleep.phase and C1+P0 eligibility
# ============================================================================


def test_fast_overlay_extracts_immediate_high_confidence_state_into_current_turn() -> None:
    """Scenario A: '我刚睡醒' is ELIGIBLE_CURRENT with canonical key user.sleep.phase."""
    _, orchestrator, _ = make_runtime()

    run_turn(orchestrator, "awake-1", "我刚睡醒")

    state = next(item for item in orchestrator.canonical if item.dimension == "user.sleep.phase")
    assert state.value == "awake"
    assert state.status == "active"
    assert state.evidence_refs == ("evidence-awake-1",)


def test_complex_state_uses_structured_persistent_extraction() -> None:
    """Under C1+P0, PLANNED propositions persist into the fact plane as OBSERVATION_ONLY.

    They do not write into canonical state or Situation.
    """
    persistent = FakePersistent(
        [
            {
                "type": "plan",
                "category": "planning",
                "key": "calligraphy",
                "value": "practice calligraphy after dinner",
                "certainty": "planned",
                "time_expression": "tonight",
                "confidence": 0.93,
            }
        ]
    )
    _, orchestrator, _ = make_runtime(persistent=persistent)

    run_turn(orchestrator, "plan-1", "晚点去写书法，吃完饭以后")

    # Frozen P0 policy: prospective observation is NOT admitted to canonical state
    assert not any(item.dimension == "user.plan.calligraphy" for item in orchestrator.canonical)
    assert persistent.calls == 1

    # But it IS durably admitted into the fact plane
    obs_store = getattr(orchestrator.fact_ingest, "observations", None)
    assert obs_store is not None
    obs = next(
        item
        for item in obs_store.all()
        if item.key == "user.plan.calligraphy.observed"
    )
    assert obs.modality is ObservationModality.PLANNED
    assert obs.value == "practice calligraphy after dinner"


def test_malformed_structured_extraction_is_rejected_deterministically() -> None:
    persistent = FakePersistent([{"type": "not-a-state", "key": "user.secret", "value": "x"}])
    _, orchestrator, _ = make_runtime(persistent=persistent)

    run_turn(orchestrator, "bad-1", "这是一个复杂但无法确认的说法")

    assert not any(item.dimension == "user.secret" for item in orchestrator.canonical)


def test_new_reality_supersedes_old_state_through_mr_reconciler() -> None:
    """Scenario C: '我准备睡了' then '我刚睡醒' supersedes user.sleep.phase."""
    _, orchestrator, _ = make_runtime()
    run_turn(orchestrator, "sleep-1", "我准备睡了")
    run_turn(orchestrator, "sleep-2", "我刚睡醒")

    current = next(item for item in orchestrator.canonical if item.dimension == "user.sleep.phase")
    assert current.value == "awake"
    # Supersession records both the terminal predecessor and the fresh
    # current record, so the current version advances by two.
    assert current.version == 3
    assert any(
        transition.from_state.value == "preparing_sleep"
        and transition.to_state.status == "superseded"
        for transition in orchestrator._ingest_transitions
    )


def test_semantic_lifecycle_resolves_exact_observation_dimension() -> None:
    """A concrete terminal Observation resolves only its exact dimension."""
    _, orchestrator, _ = make_runtime()
    run_turn(orchestrator, "symptom-1", "胃有点疼")
    run_turn(orchestrator, "symptom-2", "胃好多了")

    state = next(
        item for item in orchestrator.canonical if item.dimension == "user.health.stomach_pain"
    )
    assert state.status == "resolved"
    assert orchestrator._ingest_transitions
    observation = next(
        item
        for item in orchestrator.fact_ingest.observations.all()
        if item.key == "user.health.stomach_pain.resolved"
    )
    assert (
        orchestrator._turn.reality_eligibilities[observation.id]
        is StateEligibility.ELIGIBLE_TERMINAL
    )


def test_assistant_only_evidence_cannot_create_user_reality() -> None:
    _, _, reality = make_runtime()
    assistant = evidence("assistant-1", "你可能胃疼", source_type="assistant_message")

    assert reality.extract_and_admit(assistant, interaction_id="assistant-1") == ()


def test_retry_is_idempotent_and_does_not_duplicate_reality_state() -> None:
    persistent = FakePersistent(
        [{"type": "activity", "key": "swimming", "value": "completed", "confidence": 1.0}]
    )
    _, orchestrator, _ = make_runtime(persistent=persistent)
    first = evidence("retry-1", "今天去游泳了")
    orchestrator.begin_turn(interaction("retry-1"))
    orchestrator.ingest(first)
    orchestrator.run()
    orchestrator.commit_turn()
    first_states = tuple(orchestrator.canonical)

    orchestrator.begin_turn(interaction("retry-2"))
    orchestrator.ingest(first)

    assert tuple(orchestrator.canonical) == first_states
    assert persistent.calls == 1


def test_no_provider_keeps_fast_path_and_has_explicit_degradation() -> None:
    _, orchestrator, reality = make_runtime()

    run_turn(orchestrator, "fallback-1", "我刚睡醒")

    assert reality.persistent_available is False
    assert any(item.dimension == "user.sleep.phase" for item in orchestrator.canonical)


def test_llm_provider_is_explicit_opt_in_and_requires_endpoint_and_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mind_runtime.reality import build_reality_input
    from mind_runtime.reality.extraction import OpenAICompatRealityExtractor

    monkeypatch.delenv("MR_REALITY_LLM_ENABLED", raising=False)
    monkeypatch.delenv("MR_REALITY_LLM_BASE_URL", raising=False)
    monkeypatch.delenv("MR_REALITY_LLM_MODEL", raising=False)
    assert build_reality_input().persistent_available is False

    monkeypatch.setenv("MR_REALITY_LLM_ENABLED", "1")
    monkeypatch.setenv("MR_REALITY_LLM_BASE_URL", "https://example.invalid/v1")
    monkeypatch.setenv("MR_REALITY_LLM_MODEL", "reality-test")
    configured = build_reality_input()
    assert configured.persistent_available is True
    assert isinstance(configured.persistent, OpenAICompatRealityExtractor)
    assert configured.persistent.model == "reality-test"


def test_trimmed_seam_has_no_statebar_runtime_dependency() -> None:
    import sys

    assert not any(
        name == "statebar_mcp" or name.startswith("statebar_mcp.") for name in sys.modules
    )


def test_restart_uses_mr_state_backend_for_reality_state(tmp_path: Path) -> None:
    from mind_runtime.facts.persistence import SqliteFactBackend
    from mind_runtime.reality import RealityInputService
    from mind_runtime.state.persistence import SqliteStateBackend

    clock = FakeClock(NOW)
    fact_backend = SqliteFactBackend(tmp_path / "facts.sqlite")
    state_backend = SqliteStateBackend(tmp_path / "state.sqlite")
    first = TurnOrchestrator(
        clock=clock,
        trace=TraceRecorder(),
        runtime_id="runtime-reality",
        fact_ingest=FactIngestService(clock=clock, backend=fact_backend),
        definitions=StateDefinitionRegistry(),
        state_backend=state_backend,
        reality_input=RealityInputService(),
    )
    run_turn(first, "restart-1", "我刚睡醒")

    restarted = TurnOrchestrator(
        clock=clock,
        trace=TraceRecorder(),
        runtime_id="runtime-reality",
        fact_ingest=FactIngestService(clock=clock, backend=fact_backend),
        definitions=StateDefinitionRegistry(),
        state_backend=state_backend,
        reality_input=RealityInputService(),
    )
    assert any(item.dimension == "user.sleep.phase" for item in restarted.canonical)
    fact_backend.close()
    state_backend.close()


def test_replay_recovers_typed_observation_when_state_write_was_interrupted(tmp_path: Path) -> None:
    from mind_runtime.facts.persistence import SqliteFactBackend
    from mind_runtime.reality import RealityInputService
    from mind_runtime.state.persistence import SqliteStateBackend

    clock = FakeClock(NOW)
    fact_backend = SqliteFactBackend(tmp_path / "facts.sqlite")
    state_backend = SqliteStateBackend(tmp_path / "state.sqlite")
    first = TurnOrchestrator(
        clock=clock,
        trace=TraceRecorder(),
        runtime_id="runtime-reality",
        fact_ingest=FactIngestService(clock=clock, backend=fact_backend),
        definitions=StateDefinitionRegistry(),
        reality_input=RealityInputService(),
    )
    first.begin_turn(interaction("crash-window-1"))
    first.ingest(evidence("crash-window-1", "我刚睡醒"))
    # Simulate interruption after fact/typed-observation admission but before
    # the canonical state reconciliation/commit stage.
    first.abort_turn()

    restarted = TurnOrchestrator(
        clock=clock,
        trace=TraceRecorder(),
        runtime_id="runtime-reality",
        fact_ingest=FactIngestService(clock=clock, backend=fact_backend),
        definitions=StateDefinitionRegistry(),
        state_backend=state_backend,
        reality_input=RealityInputService(),
    )
    restarted.begin_turn(interaction("crash-window-2"))
    restarted.ingest(evidence("crash-window-1", "我刚睡醒"))
    restarted.run()
    restarted.commit_turn()

    assert any(item.dimension == "user.sleep.phase" for item in restarted.canonical)
    fact_backend.close()
    state_backend.close()


# ============================================================================
# Scenarios E, F, G, H, I from Section 15 of MR_REALITY_OBSERVATION_CONTRACT_01
# ============================================================================


def test_scenario_f_past_assertion_without_target_is_observation_only() -> None:
    """Scenario F: '我昨晚没睡好' persists as Observation but does not become canonical state."""
    _, orchestrator, _ = make_runtime()
    run_turn(orchestrator, "past-sleep-1", "我昨晚没睡好")

    # Canonical state is untouched: past assertion without target is Observation-only
    assert not any(item.dimension == "user.sleep.phase" for item in orchestrator.canonical)

    obs_store = getattr(orchestrator.fact_ingest, "observations", None)
    assert obs_store is not None
    obs = next(
        item
        for item in obs_store.all()
        if item.key == "user.sleep.phase.observed"
    )
    assert obs.modality is ObservationModality.ASSERTED
    assert obs.semantic_time.relation.value == "past"
    assert obs.semantic_time.daypart.value == "night"


def test_scenario_g_future_planned_is_observation_only() -> None:
    """Scenario G: '我明天下午去写书法' persists as PLANNED Observation-only."""
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
    _, orchestrator, _ = make_runtime(persistent=persistent)
    run_turn(orchestrator, "plan-calligraphy", "我明天下午去写书法")

    assert not any(item.dimension == "user.plan.calligraphy" for item in orchestrator.canonical)
    obs_store = getattr(orchestrator.fact_ingest, "observations", None)
    assert obs_store is not None
    obs = next(
        item
        for item in obs_store.all()
        if item.key == "user.plan.calligraphy.observed"
    )
    assert obs.modality is ObservationModality.PLANNED


def test_scenario_h_future_tentative_is_observation_only() -> None:
    """Scenario H: '我明天下午可能去写书法' persists as TENTATIVE Observation-only."""
    persistent = FakePersistent(
        [
            {
                "type": "plan",
                "key": "calligraphy",
                "value": "write calligraphy",
                "certainty": "tentative",
                "time_expression": "afternoon",
                "confidence": 0.95,
            }
        ]
    )
    _, orchestrator, _ = make_runtime(persistent=persistent)
    run_turn(orchestrator, "tentative-calligraphy", "我明天下午可能去写书法")

    assert not any(item.dimension == "user.plan.calligraphy" for item in orchestrator.canonical)
    obs_store = getattr(orchestrator.fact_ingest, "observations", None)
    assert obs_store is not None
    obs = next(
        item
        for item in obs_store.all()
        if item.key == "user.plan.calligraphy.observed"
    )
    assert obs.modality is ObservationModality.TENTATIVE


def test_scenario_i_unresolved_future_is_observation_only() -> None:
    """Scenario I: '我可能换工作' persists as TENTATIVE Observation-only with null window."""
    persistent = FakePersistent(
        [
            {
                "type": "plan",
                "key": "job",
                "value": "change job",
                "certainty": "tentative",
                "time_expression": "unspecified",
                "confidence": 0.9,
            }
        ]
    )
    _, orchestrator, _ = make_runtime(persistent=persistent)
    run_turn(orchestrator, "change-job-1", "我可能换工作")

    assert not any(item.dimension == "user.plan.job" for item in orchestrator.canonical)
    obs_store = getattr(orchestrator.fact_ingest, "observations", None)
    assert obs_store is not None
    obs = next(
        item
        for item in obs_store.all()
        if item.key == "user.plan.job.observed"
    )
    assert obs.modality is ObservationModality.TENTATIVE
    assert obs.effective_window is None


# ============================================================================
# Scenario J: Decoupled narrow RealityAdmissionPort (Blocker #4)
# ============================================================================


class StandaloneRealityAdmissionPort:
    """A pure RealityAdmissionPort that does NOT implement FactIngestPort."""

    def __init__(self) -> None:
        self.admitted: list[Observation] = []

    def admit_reality(self, request: RealityAdmissionRequest) -> FactAdmissionResult:
        obs = Observation(
            id=request.observation_id,
            interaction_id=request.interaction_id,
            scope=request.source_evidence.scope,
            origin_runtime_id=request.source_evidence.origin_runtime_id,
            type="factual",
            key=request.key,
            value=request.value,
            confidence=request.confidence,
            observed_at=request.source_evidence.received_at,
            evidence_refs=(request.source_evidence.id,),
            modality=request.modality,
            semantic_time=request.semantic_time,
            effective_window=request.effective_window,
            sync=SyncFields(
                request.source_evidence.scope,
                request.source_evidence.origin_runtime_id,
                request.observation_id,
                1,
                f"idem-{request.observation_id}",
            ),
        )
        self.admitted.append(obs)
        return FactAdmissionResult(obs, FactAdmissionDisposition.NEW)


def test_scenario_j_decoupled_narrow_reality_admission_port() -> None:
    """Scenario J: Proves that RealityInputService and TurnOrchestrator consume
    a narrow RealityAdmissionPort without relying on FactIngestPort or concrete FactIngestService.
    """
    standalone_port = StandaloneRealityAdmissionPort()
    # Confirm it does NOT implement FactIngestPort
    assert not hasattr(standalone_port, "admit")

    _, orchestrator, _ = make_runtime(reality_admission=standalone_port)

    run_turn(orchestrator, "awake-narrow", "我刚睡醒")

    # Standalone port admitted the reality observation
    assert len(standalone_port.admitted) == 1
    assert standalone_port.admitted[0].key == "user.sleep.phase.observed"
    assert standalone_port.admitted[0].modality is ObservationModality.ASSERTED

    # And TurnOrchestrator reconciled it to canonical state
    state = next(item for item in orchestrator.canonical if item.dimension == "user.sleep.phase")
    assert state.value == "awake"
