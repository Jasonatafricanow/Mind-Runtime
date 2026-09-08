"""G11~G16 golden acceptance entries (xfail until owner pipelines land)."""

from tests.facts.pipeline import FactIngestPipeline
from tests.golden.fixtures.g11_g16 import (
    make_g11,
    make_g12,
    make_g12a,
    make_g13,
    make_g14,
    make_g15,
    make_g15a,
    make_g16,
    make_g16a,
)
from tests.golden.runner import ScenarioRunner
from tests.pipeline.d11s_pipeline import D11SRestartPipeline
from tests.pipeline.golden_pipeline import (
    D8TransitionPipeline,
    D9IntentPolicyPipeline,
    FailingAgent,
    OrchestratorPipeline,
    ReplicationHarnessPipeline,
    StateBackendPipeline,
)


def test_golden_g11() -> None:
    """G11 scope isolation: green since D3 (ingest-level)."""
    scenario = make_g11()
    result = ScenarioRunner(FactIngestPipeline()).run_once(scenario)
    assert result.deterministic_outputs == scenario.expected_deterministic_outputs


def test_golden_g12a() -> None:
    """G12a (D5.8): committed canonical state survives restart through the
    durable StateBackend (the D5-owned staged part of G12)."""
    scenario = make_g12a()
    result = ScenarioRunner(StateBackendPipeline()).run_once(scenario)
    assert result.deterministic_outputs == scenario.expected_deterministic_outputs


def test_golden_g12() -> None:
    """G12 (ADR-0008): fresh composition restores every existing durable
    Product Slice plane plus recovery semantics and unchanged read-only history."""
    scenario = make_g12()
    result = ScenarioRunner(D11SRestartPipeline()).run_once(scenario)
    assert result.deterministic_outputs == scenario.expected_deterministic_outputs


def test_golden_g13() -> None:
    """G13 (D5): projection failure never pollutes canonical state."""
    scenario = make_g13()
    result = ScenarioRunner(OrchestratorPipeline(commit=False, agent=FailingAgent())).run_once(
        scenario
    )
    assert result.deterministic_outputs == scenario.expected_deterministic_outputs


def test_golden_g14() -> None:
    scenario = make_g14()
    result = ScenarioRunner(D9IntentPolicyPipeline()).run_once(scenario)
    assert result.deterministic_outputs == scenario.expected_deterministic_outputs


def test_golden_g15a() -> None:
    """G15a (D3): Lara writing the Kayla agent scope fails closed at ingest."""
    scenario = make_g15a()
    result = ScenarioRunner(FactIngestPipeline(writing_runtime="lara")).run_once(scenario)
    assert result.deterministic_outputs == scenario.expected_deterministic_outputs


def test_golden_g15b() -> None:
    """G15b (D5): replication ownership + projected reject via the harness."""
    scenario = make_g15()
    result = ScenarioRunner(ReplicationHarnessPipeline()).run_once(scenario)
    assert result.deterministic_outputs == scenario.expected_deterministic_outputs


def test_golden_g16a() -> None:
    """G16a: proactive cooldown permission moved from Situation to D9 Policy."""
    scenario = make_g16a()
    result = ScenarioRunner(D9IntentPolicyPipeline()).run_once(scenario)
    assert result.deterministic_outputs == scenario.expected_deterministic_outputs


def test_golden_g16() -> None:
    scenario = make_g16()
    result = ScenarioRunner(D8TransitionPipeline()).run_once(scenario)
    assert result.deterministic_outputs == scenario.expected_deterministic_outputs
