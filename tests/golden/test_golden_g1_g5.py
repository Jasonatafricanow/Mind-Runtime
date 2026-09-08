"""G1~G5 golden acceptance entries (xfail until owner pipelines land)."""

from tests.golden.fixtures.g1_g5 import make_g1, make_g2, make_g3, make_g4, make_g5
from tests.golden.runner import ScenarioRunner
from tests.pipeline.golden_pipeline import D9IntentPolicyPipeline, OrchestratorPipeline
from tests.state.pipeline import StateReconcilePipeline


def test_golden_g1() -> None:
    """G1 (D6): 凌晨刚醒 — awake, conversation active, sleep norm suppressed."""
    scenario = make_g1()
    result = ScenarioRunner(OrchestratorPipeline()).run_once(scenario)
    assert result.deterministic_outputs == scenario.expected_deterministic_outputs


def test_golden_g2() -> None:
    """G2 state reaffirm: headache stays active after reaffirm (D4.3)."""
    scenario = make_g2()
    result = ScenarioRunner(StateReconcilePipeline()).run_once(scenario)
    assert result.deterministic_outputs == scenario.expected_deterministic_outputs


def test_golden_g3() -> None:
    """G3 cancelled is not expired: cancelled stays context (D4.6)."""
    scenario = make_g3()
    result = ScenarioRunner(StateReconcilePipeline()).run_once(scenario)
    assert result.deterministic_outputs == scenario.expected_deterministic_outputs


def test_golden_g4() -> None:
    scenario = make_g4()
    result = ScenarioRunner(D9IntentPolicyPipeline()).run_once(scenario)
    assert result.deterministic_outputs == scenario.expected_deterministic_outputs


def test_golden_g5() -> None:
    scenario = make_g5()
    result = ScenarioRunner(D9IntentPolicyPipeline()).run_once(scenario)
    assert result.deterministic_outputs == scenario.expected_deterministic_outputs
