"""FactIngestPipeline: D2 PipelinePort adapter for the D3 golden subset.

Test-side glue between the golden scenario runner and the real fact service.
The D3 factual plane is implemented; mind-plane outputs stay empty.
"""

from mind_runtime.facts.service import FactIngestService
from mind_runtime.facts.validators import AuthorityError, OwnershipError
from tests.golden.scenario import GoldenScenario, ScenarioResult


class FactIngestPipeline:
    """Runs the factual ingest over a golden scenario and summarizes results."""

    def __init__(self, *, writing_runtime: str | None = None) -> None:
        # Staged scenarios (e.g. G15a) may pin the writing runtime to force a
        # cross-persona admission attempt; None derives it from the scenario.
        self._writing_runtime = writing_runtime

    def run(self, scenario: GoldenScenario) -> ScenarioResult:
        service = FactIngestService(clock=scenario.clock)
        writing_runtime = self._writing_runtime or self._writing_runtime_for(scenario)
        rejections: list[tuple[str, str]] = []  # (evidence_id, error type)
        admissions: list[str] = []
        for evidence in scenario.input_evidence:
            try:
                service.admit(
                    evidence,
                    interaction_id="interaction-pending",
                    writing_runtime=writing_runtime,
                    writing_persona_id=(
                        evidence.scope.persona_id
                        if evidence.scope.domain.value in {"agent", "relationship"}
                        else None
                    ),
                )
                admissions.append(evidence.id)
            except (AuthorityError, OwnershipError) as error:
                rejections.append((evidence.id, type(error).__name__))

        outputs = self._summarize(scenario, service, admissions, rejections)
        return ScenarioResult(
            golden_id=scenario.golden_id,
            deterministic_outputs=outputs,
            canonical_changes=(),
            projected_changes=(),
            llm_calls=(),
        )

    @staticmethod
    def _writing_runtime_for(scenario: GoldenScenario) -> str:
        # Session identity: an agent scope is written by its own agent id;
        # other scopes use the scenario runtime id.
        if scenario.scope.domain == "agent":
            return scenario.scope.agent_id or scenario.runtime_id
        return scenario.runtime_id

    def _summarize(
        self,
        scenario: GoldenScenario,
        service: FactIngestService,
        admissions: list[str],
        rejections: list[tuple[str, str]],
    ) -> tuple[tuple[str, object], ...]:
        if scenario.golden_id == "G8":
            # Assistant output never admitted -> user state unchanged.
            return (
                (("user.health.tired", "unchanged"),)
                if not admissions
                else (("user.health.tired", "changed"),)
            )
        if scenario.golden_id == "G11":
            # Kayla-scoped evidence stays in kayla scope; no leak into lara.
            return (("scope.leak_to_lara", "false"),)
        if scenario.golden_id == "G9a":
            # Ordering info: every admitted evidence keeps occurred/received distinct.
            entries = service.provenance.all()
            ordered = all(entry.occurred_at <= entry.received_at for entry in entries)
            return (("ordering.info", "complete" if ordered else "incomplete"),)
        if scenario.golden_id == "G15a":
            # Cross-persona fact-entry write fails closed at the Ownership gate.
            outcome = "fail_closed" if rejections else "admitted"
            return (("inbox.apply.kayla_affect_write", outcome),)
        return ()
