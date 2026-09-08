"""Golden scenario runner: run once / replay / restart / compare."""

from dataclasses import replace
from typing import Protocol, runtime_checkable

from tests.golden.scenario import GoldenScenario, ScenarioResult


@runtime_checkable
class PipelinePort(Protocol):
    """A pipeline that turns one golden scenario into a deterministic result."""

    def run(self, scenario: GoldenScenario) -> ScenarioResult:
        """Execute the scenario and return its result."""
        ...


class UnimplementedPipeline:
    """Placeholder until a real D3+ pipeline lands; raises for xfail entries."""

    def run(self, scenario: GoldenScenario) -> ScenarioResult:
        raise NotImplementedError(f"{scenario.owner}")


@runtime_checkable
class PersistencePort(Protocol):
    """Snapshot/restore of scenario inputs across a simulated restart."""

    def snapshot(self, scenario: GoldenScenario) -> object:
        """Return a serializable snapshot of the scenario."""
        ...

    def restore(self, snapshot: object) -> GoldenScenario:
        """Rebuild the scenario from a snapshot."""
        ...


class NullPersistence:
    """Round-trips the scenario object unchanged (no real persistence yet)."""

    def snapshot(self, scenario: GoldenScenario) -> object:
        return scenario

    def restore(self, snapshot: object) -> GoldenScenario:
        assert isinstance(snapshot, GoldenScenario)
        return snapshot


class ScenarioRunner:
    """Executes scenarios through a PipelinePort with replay/restart/compare."""

    def __init__(
        self,
        pipeline: PipelinePort,
        *,
        persistence: PersistencePort | None = None,
    ) -> None:
        self._pipeline = pipeline
        self._persistence = persistence or NullPersistence()

    def run_once(self, scenario: GoldenScenario) -> ScenarioResult:
        return self._pipeline.run(scenario)

    def replay(self, scenario: GoldenScenario, *, times: int = 2) -> tuple[ScenarioResult, ...]:
        if times < 1:
            raise ValueError("times must be at least 1")
        results = tuple(self._pipeline.run(scenario) for _ in range(times))
        self.compare(results)
        return results

    def restart_from_persistence(self, scenario: GoldenScenario) -> ScenarioResult:
        snapshot = self._persistence.snapshot(scenario)
        restored = self._persistence.restore(snapshot)
        return self._pipeline.run(restored)

    def compare(self, results: tuple[ScenarioResult, ...]) -> None:
        if not results:
            raise ValueError("compare requires at least one result")
        reference = results[0]
        for result in results[1:]:
            assert result.deterministic_outputs == reference.deterministic_outputs, (
                f"deterministic outputs diverged for {result.golden_id}"
            )
            assert result.canonical_changes == reference.canonical_changes, (
                f"canonical changes diverged for {result.golden_id}"
            )
            assert result.projected_changes == reference.projected_changes, (
                f"projected changes diverged for {result.golden_id}"
            )

    @staticmethod
    def restore_from_snapshot(snapshot: object) -> GoldenScenario:
        assert isinstance(snapshot, GoldenScenario)
        return replace(snapshot)
