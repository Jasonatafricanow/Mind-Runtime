"""Compressed Product Slice acceptance entries (strict xfail by owner)."""

from collections.abc import Callable

import pytest

from tests.golden.fixtures.g24_g28 import (
    make_g24,
    make_g25,
    make_g26,
    make_g27,
    make_g28,
)
from tests.golden.runner import ScenarioRunner, UnimplementedPipeline
from tests.golden.scenario import GoldenScenario
from tests.pipeline.d11s_pipeline import (
    D11SHistoryPipeline,
    D11SLongHorizonPipeline,
    D11SModelSwapPipeline,
)
from tests.pipeline.golden_pipeline import D9IntentPolicyPipeline


def _run(factory: Callable[[], GoldenScenario]) -> None:
    scenario = factory()
    result = ScenarioRunner(UnimplementedPipeline()).run_once(scenario)
    assert result.deterministic_outputs == scenario.expected_deterministic_outputs


def test_golden_g24_due_intent_wakes_for_reconsideration() -> None:
    scenario = make_g24()
    result = ScenarioRunner(D9IntentPolicyPipeline()).run_once(scenario)
    assert result.deterministic_outputs == scenario.expected_deterministic_outputs


def test_golden_g25_model_swap_preserves_internal_decision() -> None:
    scenario = make_g25()
    result = ScenarioRunner(D11SModelSwapPipeline()).run_once(scenario)
    assert result.deterministic_outputs == scenario.expected_deterministic_outputs


def test_golden_g26_long_horizon_state_remains_bounded() -> None:
    scenario = make_g26()
    result = ScenarioRunner(D11SLongHorizonPipeline()).run_once(scenario)
    assert result.deterministic_outputs == scenario.expected_deterministic_outputs


def test_golden_g27_repeated_history_surface_does_not_amplify() -> None:
    scenario = make_g27()
    result = ScenarioRunner(D11SHistoryPipeline()).run_once(scenario)
    assert result.deterministic_outputs == scenario.expected_deterministic_outputs


@pytest.mark.xfail(reason="MR-D11P not implemented", strict=True)
def test_golden_g28_onboarding_llm_is_one_time_and_user_activated() -> None:
    _run(make_g28)
