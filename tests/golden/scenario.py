"""Golden scenario schema: inputs and expectations for one G scenario."""

from dataclasses import dataclass

from mind_runtime.contracts import (
    AffectiveDimensionProfile,
    AppraisalPath,
    Evidence,
    HistoricalContextBundle,
    RuntimeState,
    Scope,
)
from tests.support.fake_clock import FakeClock


class _Unchanged:
    """Sentinel meaning "dimension must stay unchanged"."""


UNCHANGED = _Unchanged()


@dataclass(frozen=True)
class ExpectedChange:
    """One expected state change: dimension -> expected value (or UNCHANGED)."""

    dimension: str
    expected_value: object


@dataclass(frozen=True)
class LlmCall:
    """One recorded fake-LLM call."""

    prompt_type: str
    structured_response: object


@dataclass(frozen=True)
class ScenarioResult:
    """The deterministic result of running one golden scenario."""

    golden_id: str
    deterministic_outputs: tuple[tuple[str, object], ...]
    canonical_changes: tuple[ExpectedChange, ...]
    projected_changes: tuple[ExpectedChange, ...]
    llm_calls: tuple[LlmCall, ...]


@dataclass(frozen=True)
class GoldenScenario:
    """One fully specified golden scenario (D2 dispatch table)."""

    golden_id: str
    title: str
    owner: str
    clock: FakeClock
    runtime_id: str
    scope: Scope
    persona: tuple[AffectiveDimensionProfile, ...]
    initial_canonical_state: tuple[RuntimeState, ...]
    historical_context: HistoricalContextBundle | None
    input_evidence: tuple[Evidence, ...]
    expected_deterministic_outputs: tuple[tuple[str, object], ...]
    expected_allowed_llm_path: AppraisalPath | None
    expected_canonical_changes: tuple[ExpectedChange, ...]
    expected_projected_changes: tuple[ExpectedChange, ...]
