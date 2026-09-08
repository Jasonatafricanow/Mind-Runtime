"""StateReconcilePipeline: D2 PipelinePort adapter for the D4 golden subset.

Test-side glue that runs the real D4 FactualReconciler over a golden
scenario: scenario evidence is admitted through the D3 factual plane, then
mapped (per-scenario, no LLM) to typed state intents, reconciled, and
summarized into deterministic outputs.
"""

from mind_runtime.contracts import StateDefinition, StateDomain, StateValueType
from mind_runtime.facts.service import FactIngestService
from mind_runtime.state.definitions import StateDefinitionRegistry
from mind_runtime.state.reconciler import FactualReconciler, ReconcileResult, StateIntent
from mind_runtime.state.relevance import evaluate_relevance
from tests.golden.scenario import GoldenScenario, ScenarioResult

# Test-side definitions for the D4 golden dimensions. The policies mirror
# the baseline lifecycle kinds: ttl_lifecycle for transient discomfort,
# indefinite/categorical for phase, event_only for explicit plans.
_GOLDEN_DEFINITIONS = (
    StateDefinition(
        key="user.health.headache",
        domain=StateDomain.USER,
        value_type=StateValueType.CATEGORICAL,
        dynamics_policy="ttl_lifecycle",
        default_validity_policy="ttl:12h",
        bounds=None,
    ),
    StateDefinition(
        key="user.sleep.phase",
        domain=StateDomain.USER,
        value_type=StateValueType.CATEGORICAL,
        dynamics_policy="categorical_lifecycle",
        default_validity_policy=None,
        bounds=None,
    ),
    StateDefinition(
        key="user.planning.calligraphy",
        domain=StateDomain.USER,
        value_type=StateValueType.CATEGORICAL,
        dynamics_policy="event_only",
        default_validity_policy="event_only",
        bounds=None,
    ),
)


class StateReconcilePipeline:
    """Runs the D4 state reconciler over a golden scenario."""

    def __init__(self, *, writing_runtime: str | None = None) -> None:
        self._writing_runtime = writing_runtime
        self._definitions = StateDefinitionRegistry(_GOLDEN_DEFINITIONS)

    def run(self, scenario: GoldenScenario) -> ScenarioResult:
        service = FactIngestService(clock=scenario.clock)
        writing_runtime = self._writing_runtime or scenario.runtime_id
        for evidence in scenario.input_evidence:
            service.admit(
                evidence,
                interaction_id="interaction-pending",
                writing_runtime=writing_runtime,
                writing_persona_id=None,
            )
        intents = self._intents_for(scenario)
        reconciler = FactualReconciler(clock=scenario.clock, definitions=self._definitions)
        result = reconciler.apply(scenario.initial_canonical_state, intents)
        outputs = self._summarize(scenario, result)
        return ScenarioResult(
            golden_id=scenario.golden_id,
            deterministic_outputs=outputs,
            canonical_changes=(),
            projected_changes=(),
            llm_calls=(),
        )

    def _intents_for(self, scenario: GoldenScenario) -> tuple[StateIntent, ...]:
        # Per-scenario typed mapping (D4 has no semantic extraction; the
        # scenario fixtures define the dimension/value by construction).
        if scenario.golden_id == "G2":
            return (
                StateIntent(
                    dimension="user.health.headache",
                    value="active",
                    observed_at=scenario.clock.now(),
                    scope=scenario.scope,
                    origin_runtime_id=scenario.runtime_id,
                    evidence_refs=self._evidence_ids(scenario),
                ),
            )
        if scenario.golden_id == "G9":
            # Delayed event: the intent carries the evidence's occurred_at
            # (13:50), which is older than the current state's observation.
            evidence = scenario.input_evidence[0]
            return (
                StateIntent(
                    dimension="user.sleep.phase",
                    value="sleeping",
                    observed_at=evidence.occurred_at,
                    scope=scenario.scope,
                    origin_runtime_id=scenario.runtime_id,
                    evidence_refs=(evidence.id,),
                ),
            )
        return ()

    @staticmethod
    def _evidence_ids(scenario: GoldenScenario) -> tuple[str, ...]:
        return tuple(evidence.id for evidence in scenario.input_evidence)

    def _summarize(
        self, scenario: GoldenScenario, result: ReconcileResult
    ) -> tuple[tuple[str, object], ...]:
        if scenario.golden_id == "G2":
            state = result.effective_for("user.health.headache", scenario.scope)
            if state is None:
                return (("user.health.headache", "missing"),)
            return (("user.health.headache", state.value),)
        if scenario.golden_id == "G9":
            state = result.effective_for("user.sleep.phase", scenario.scope)
            if state is None:
                return (("user.sleep.phase", "missing"),)
            # The delayed observation must not roll back the newer state.
            return (("user.sleep.phase", state.value),)
        if scenario.golden_id == "G3":
            state = result.effective_for("user.planning.calligraphy", scenario.scope)
            if state is None:
                return (("context.recently_cancelled", "missing"),)
            outcome = evaluate_relevance(state, now=scenario.clock.now())
            return (
                (
                    "context.recently_cancelled",
                    "true" if outcome.recently_cancelled else "false",
                ),
            )
        return ()
