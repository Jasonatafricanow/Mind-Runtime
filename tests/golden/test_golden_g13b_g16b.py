"""G13b/G16b golden acceptance entries (xfail until owner pipelines land)."""

from tests.golden.fixtures.g13b_g16b import make_g13b, make_g16b
from tests.golden.runner import ScenarioRunner
from tests.pipeline.golden_pipeline import D8TransitionPipeline, OrchestratorPipeline


def test_golden_g13b() -> None:
    """G13b (D5): ingested facts survive a cognitive abort; projection dies."""
    scenario = make_g13b()
    result = ScenarioRunner(OrchestratorPipeline(commit=False)).run_once(scenario)
    assert result.deterministic_outputs == scenario.expected_deterministic_outputs


def test_golden_g16b() -> None:
    scenario = make_g16b()
    result = ScenarioRunner(D8TransitionPipeline()).run_once(scenario)
    assert result.deterministic_outputs == scenario.expected_deterministic_outputs
