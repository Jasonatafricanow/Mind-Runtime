from __future__ import annotations

from datetime import UTC, datetime

from mind_runtime.contracts import Scope, SemanticEventCandidate
from mind_runtime.facts.service import FactIngestService
from tests.pipeline.test_fact_admission_turn import make_interaction, make_orchestrator
from tests.golden.fixtures.common import make_evidence
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
    ) -> tuple[object, ...]:
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
