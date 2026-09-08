"""D2.1 runner tests: run once / replay / restart / compare."""

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime

import pytest

from mind_runtime.contracts import (
    AffectiveDimensionProfile,
    AppraisalPath,
    Authority,
    AuthorityLevel,
    Evidence,
    HistoricalContextBundle,
    HistoricalContextItem,
    HistoricalContextQuery,
    RuntimeState,
    Scope,
    ScopeDomain,
    SyncFields,
)
from tests.golden.fake_history import FakeHistoricalProvider
from tests.golden.fake_llm import FakeLLM
from tests.golden.runner import (
    NullPersistence,
    ScenarioRunner,
    UnimplementedPipeline,
)
from tests.golden.scenario import (
    UNCHANGED,
    ExpectedChange,
    GoldenScenario,
    LlmCall,
    ScenarioResult,
)
from tests.support.fake_clock import FakeClock

NOW = datetime(2026, 8, 20, 14, 0, tzinfo=UTC)


def make_scope() -> Scope:
    return Scope(domain=ScopeDomain.USER, user_id="user-1")


def make_sync(scope: Scope, object_id: str) -> SyncFields:
    return SyncFields(scope, "runtime-1", object_id, 1, f"idem-{object_id}")


def make_state(dimension: str = "user.sleep.phase", value: object = "awake") -> RuntimeState:
    scope = make_scope()
    return RuntimeState(
        state_id=f"state-{dimension}",
        scope=scope,
        origin_runtime_id="runtime-1",
        dimension=dimension,
        value=value,
        status="active",
        valid_from=NOW,
        valid_until=None,
        relevant_until=None,
        last_observed_at=NOW,
        evidence_refs=(),
        transition_refs=(),
        updated_at=NOW,
        version=1,
        sync=make_sync(scope, f"state-{dimension}"),
    )


def make_persona() -> tuple[AffectiveDimensionProfile, ...]:
    return (
        AffectiveDimensionProfile(
            dimension="agent.affect.longing",
            baseline=0.3,
            initial_value=0.3,
            sensitivity=0.6,
            recovery_rate=0.2,
            ceiling=1.0,
            floor=0.0,
            growth_profile=(("growth", 0.05),),
            coupling_profile=(),
        ),
    )


def make_evidence() -> Evidence:
    scope = make_scope()
    return Evidence(
        id="evidence-1",
        scope=scope,
        origin_runtime_id="runtime-1",
        source_type="user_message",
        source_id="message-1",
        authority_level=AuthorityLevel.ASSERTED,
        authority=Authority(scope, AuthorityLevel.ASSERTED, "message-1"),
        occurred_at=NOW,
        received_at=NOW,
        payload={"text": "hello"},
        sync=make_sync(scope, "evidence-1"),
    )


def make_scenario(golden_id: str = "G1") -> GoldenScenario:
    return GoldenScenario(
        golden_id=golden_id,
        title=f"{golden_id} scenario",
        owner="MR-D6.2 not implemented",
        clock=FakeClock(NOW),
        runtime_id="runtime-1",
        scope=make_scope(),
        persona=make_persona(),
        initial_canonical_state=(make_state(),),
        historical_context=None,
        input_evidence=(make_evidence(),),
        expected_deterministic_outputs=(("user_activity", "awake_and_engaged"),),
        expected_allowed_llm_path=None,
        expected_canonical_changes=(ExpectedChange("user.sleep.phase", "awake"),),
        expected_projected_changes=(),
    )


class RecordingPipeline:
    """Test double: records calls, returns a fixed ScenarioResult."""

    def __init__(self) -> None:
        self.calls: list[GoldenScenario] = []

    def run(self, scenario: GoldenScenario) -> ScenarioResult:
        self.calls.append(scenario)
        return ScenarioResult(
            golden_id=scenario.golden_id,
            deterministic_outputs=scenario.expected_deterministic_outputs,
            canonical_changes=scenario.expected_canonical_changes,
            projected_changes=scenario.expected_projected_changes,
            llm_calls=(),
        )


def test_run_once_calls_pipeline_exactly_once() -> None:
    pipeline = RecordingPipeline()
    runner = ScenarioRunner(pipeline)
    scenario = make_scenario()

    result = runner.run_once(scenario)

    assert len(pipeline.calls) == 1
    assert pipeline.calls[0] is scenario
    assert result.golden_id == "G1"


def test_replay_same_input_is_deterministic() -> None:
    pipeline = RecordingPipeline()
    runner = ScenarioRunner(pipeline)
    scenario = make_scenario()

    results = runner.replay(scenario, times=3)

    assert len(results) == 3
    assert len(pipeline.calls) == 3
    assert results[0] == results[1] == results[2]


def test_restart_from_persistence_round_trips() -> None:
    pipeline = RecordingPipeline()
    runner = ScenarioRunner(pipeline, persistence=NullPersistence())
    scenario = make_scenario()

    result = runner.restart_from_persistence(scenario)

    assert len(pipeline.calls) == 1
    assert result.golden_id == "G1"


def test_compare_equal_results_pass() -> None:
    runner = ScenarioRunner(RecordingPipeline())
    scenario = make_scenario()
    results = runner.replay(scenario, times=2)

    runner.compare(results)  # no raise


def test_compare_mismatched_results_raise() -> None:
    runner = ScenarioRunner(RecordingPipeline())
    a = ScenarioResult(
        golden_id="G1",
        deterministic_outputs=(("user_activity", "awake"),),
        canonical_changes=(),
        projected_changes=(),
        llm_calls=(),
    )
    b = ScenarioResult(
        golden_id="G1",
        deterministic_outputs=(("user_activity", "sleeping"),),
        canonical_changes=(),
        projected_changes=(),
        llm_calls=(),
    )
    with pytest.raises(AssertionError):
        runner.compare((a, b))


def test_unimplemented_pipeline_raises_with_owner() -> None:
    pipeline = UnimplementedPipeline()
    scenario = make_scenario()
    with pytest.raises(NotImplementedError, match="MR-D6.2"):
        pipeline.run(scenario)


def test_scenario_result_is_immutable() -> None:
    result = ScenarioResult(
        golden_id="G1",
        deterministic_outputs=(),
        canonical_changes=(),
        projected_changes=(),
        llm_calls=(),
    )
    with pytest.raises(FrozenInstanceError):
        result.golden_id = "G2"  # type: ignore[misc]


def test_unchanged_sentinel_is_distinct() -> None:
    assert UNCHANGED is not None
    change = ExpectedChange("user.sleep.phase", UNCHANGED)
    assert change.expected_value is UNCHANGED


def test_llm_call_is_frozen_record() -> None:
    call = LlmCall(prompt_type="semantic_appraisal", structured_response={"meaning": "x"})
    assert call.prompt_type == "semantic_appraisal"
    assert call.structured_response == {"meaning": "x"}
    with pytest.raises(FrozenInstanceError):
        call.prompt_type = "other"  # type: ignore[misc]


# --- FakeLLM ---


def test_fake_llm_records_call_count_prompt_type_response() -> None:
    llm = FakeLLM({"semantic_appraisal": {"meaning": "possible_rejection"}})

    response = llm.complete("semantic_appraisal")

    assert response == {"meaning": "possible_rejection"}
    assert llm.call_count == 1
    assert llm.prompt_types == ["semantic_appraisal"]
    assert llm.calls == (LlmCall("semantic_appraisal", {"meaning": "possible_rejection"}),)


def test_fake_llm_rejects_unscripted_prompt() -> None:
    llm = FakeLLM({})
    with pytest.raises(KeyError):
        llm.complete("unknown_prompt")


# --- FakeHistoricalProvider ---


def test_fake_history_serves_by_key() -> None:
    scope = make_scope()
    item = HistoricalContextItem(
        item_id="hc-1",
        scope=scope,
        external_id="ext-1",
        kind="episode",
        proposition="user cancelled a plan last week",
        source_refs=(),
        confidence=0.8,
        relevance_hint=0.6,
    )
    bundle = HistoricalContextBundle(
        bundle_id="hb-1",
        scope=scope,
        origin_runtime_id="runtime-1",
        episodes=(item,),
        stable_facts=(),
        relationship_events=(),
        pattern_summaries=(),
        source_refs=(),
        provider_trace="fixture",
    )
    provider = FakeHistoricalProvider({("sig-1",): bundle})
    query = HistoricalContextQuery(
        query_id="hq-1",
        scope=scope,
        origin_runtime_id="runtime-1",
        situation_hint=None,
        query_text=None,
        pattern_queries=(),
        budget=10,
    )

    assert provider.query(query, signature="sig-1") is bundle
    with pytest.raises(KeyError):
        provider.query(query, signature="sig-unknown")


def test_appraisal_path_enum_available_for_scenarios() -> None:
    assert AppraisalPath.LLM.value == "llm"
