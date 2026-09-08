"""G6~G10 golden acceptance entries (xfail until owner pipelines land)."""

from tests.facts.pipeline import FactIngestPipeline
from tests.golden.fixtures.g6_g10 import (
    make_g6,
    make_g7,
    make_g8,
    make_g9,
    make_g9a,
    make_g10,
)
from tests.golden.runner import ScenarioRunner
from tests.pipeline.golden_pipeline import (
    D8TransitionPipeline,
    DynamicsPipeline,
    OrchestratorPipeline,
)
from tests.state.pipeline import StateReconcilePipeline


def test_golden_g6() -> None:
    scenario = make_g6()
    result = ScenarioRunner(D8TransitionPipeline()).run_once(scenario)
    assert result.deterministic_outputs == scenario.expected_deterministic_outputs


def test_golden_g7() -> None:
    """G7 (D7): same impulse, different persona sensitivity -> small vs large."""
    scenario = make_g7()
    result = ScenarioRunner(DynamicsPipeline()).run_once(scenario)
    assert result.deterministic_outputs == scenario.expected_deterministic_outputs


def test_golden_g8() -> None:
    """G8 assistant self-pollution guard: green since D3."""
    scenario = make_g8()
    result = ScenarioRunner(FactIngestPipeline()).run_once(scenario)
    assert result.deterministic_outputs == scenario.expected_deterministic_outputs


def test_golden_g9a() -> None:
    """G9a (D3): delayed event keeps complete ordering information in provenance."""
    scenario = make_g9a()
    result = ScenarioRunner(FactIngestPipeline()).run_once(scenario)
    assert result.deterministic_outputs == scenario.expected_deterministic_outputs


def test_golden_g9b() -> None:
    """G9b (D4): delayed observation must not roll back Effective State."""
    scenario = make_g9()
    result = ScenarioRunner(StateReconcilePipeline()).run_once(scenario)
    assert result.deterministic_outputs == scenario.expected_deterministic_outputs


def test_golden_g10() -> None:
    """G10 (D5) replay: same evidence/clock yields the same outputs."""
    scenario = make_g10()
    runner = ScenarioRunner(OrchestratorPipeline())
    results = runner.replay(scenario, times=2)
    assert results[0].deterministic_outputs == scenario.expected_deterministic_outputs
