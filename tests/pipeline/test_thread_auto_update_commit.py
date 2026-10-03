from __future__ import annotations

from datetime import UTC, datetime

from mind_runtime.contracts import Scope, SemanticEventCandidate
from mind_runtime.facts.service import FactIngestService
from mind_runtime.memory.product import MemoryThread
from tests.golden.fixtures.common import make_evidence
from tests.pipeline.test_fact_admission_turn import make_interaction, make_orchestrator
from tests.support.fake_clock import FakeClock

NOW = datetime(2026, 9, 25, tzinfo=UTC)


class RecordingThreadUpdates:
    def __init__(self) -> None:
        self.calls: list[tuple[Scope, tuple[SemanticEventCandidate, ...]]] = []

    def apply(
        self,
        *,
        scope: Scope,
        accepted_events: tuple[SemanticEventCandidate, ...],
        at: datetime,
    ) -> tuple[MemoryThread, ...]:
        assert at.tzinfo is UTC
        self.calls.append((scope, accepted_events))
        return ()


def test_thread_updates_run_only_after_turn_commit() -> None:
    updates = RecordingThreadUpdates()
    orchestrator = make_orchestrator(
        FactIngestService(clock=FakeClock(NOW)),
        thread_updates=updates,
    )
    orchestrator.begin_turn(make_interaction())
    orchestrator.ingest(make_evidence(text="I am considering a new laptop."))
    orchestrator.run()
    assert updates.calls == []

    orchestrator.commit_turn()
    assert len(updates.calls) == 1
    assert updates.calls[0][0] == make_interaction().scope


def test_aborted_turn_does_not_publish_thread_updates() -> None:
    updates = RecordingThreadUpdates()
    orchestrator = make_orchestrator(
        FactIngestService(clock=FakeClock(NOW)),
        thread_updates=updates,
    )
    orchestrator.begin_turn(make_interaction())
    orchestrator.ingest(make_evidence(text="I am considering a new laptop."))
    orchestrator.run()
    orchestrator.abort_turn()
    assert updates.calls == []


class RecordingPostCommitProjection:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[tuple[Scope, str]] = []

    def project_interaction(
        self,
        *,
        scope: Scope,
        interaction_id: str,
    ) -> int:
        self.calls.append((scope, interaction_id))
        if self.fail:
            raise RuntimeError("derived projection unavailable")
        return 1


def test_memory_projection_runs_only_after_durable_turn_commit() -> None:
    projector = RecordingPostCommitProjection()
    orchestrator = make_orchestrator(
        FactIngestService(clock=FakeClock(NOW)),
        memory_post_commit_projection=projector,
    )
    interaction = make_interaction()
    orchestrator.begin_turn(interaction)
    orchestrator.ingest(make_evidence(text="A durable memory source."))
    orchestrator.run()
    assert projector.calls == []

    orchestrator.commit_turn()
    assert projector.calls == [
        (interaction.scope, interaction.interaction_id)
    ]


def test_memory_projection_failure_cannot_rollback_committed_turn() -> None:
    projector = RecordingPostCommitProjection(fail=True)
    orchestrator = make_orchestrator(
        FactIngestService(clock=FakeClock(NOW)),
        memory_post_commit_projection=projector,
    )
    interaction = make_interaction()
    orchestrator.begin_turn(interaction)
    orchestrator.ingest(make_evidence(text="Commit remains authoritative."))
    orchestrator.run()
    orchestrator.commit_turn()

    assert orchestrator.state.value == "committed"
    assert projector.calls == [
        (interaction.scope, interaction.interaction_id)
    ]


def test_aborted_turn_projects_durable_memory_but_not_thread_state() -> None:
    projector = RecordingPostCommitProjection()
    updates = RecordingThreadUpdates()
    orchestrator = make_orchestrator(
        FactIngestService(clock=FakeClock(NOW)),
        memory_post_commit_projection=projector,
        thread_updates=updates,
    )
    interaction = make_interaction()
    orchestrator.begin_turn(interaction)
    orchestrator.ingest(
        make_evidence(text="Durable factual input survives response abort.")
    )
    orchestrator.run()
    orchestrator.abort_turn()

    assert orchestrator.state.value == "aborted"
    assert projector.calls == [
        (interaction.scope, interaction.interaction_id)
    ]
    assert updates.calls == []
