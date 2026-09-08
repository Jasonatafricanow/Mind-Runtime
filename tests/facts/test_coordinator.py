"""D3.1 InteractionCoordinator lifecycle tests."""

from datetime import UTC, datetime

import pytest

from mind_runtime.contracts import Interaction, InteractionStatus
from mind_runtime.facts.coordinator import InteractionCoordinator
from tests.golden.fixtures.common import make_scope
from tests.support.fake_clock import FakeClock

NOW = datetime(2026, 8, 20, 19, 0, tzinfo=UTC)


def make_coordinator() -> InteractionCoordinator:
    return InteractionCoordinator(clock=FakeClock(NOW))


def test_begin_interaction_creates_open_interaction() -> None:
    coordinator = make_coordinator()
    interaction = coordinator.begin_interaction(
        interaction_id="interaction-1",
        scope=make_scope(),
        channel="chat",
        session_id="session-1",
        turn_id="turn-1",
    )
    assert interaction.interaction_id == "interaction-1"
    assert interaction.status is InteractionStatus.OPEN
    assert interaction.started_at == NOW
    assert interaction.committed_at is None


def test_processing_marks_in_flight() -> None:
    coordinator = make_coordinator()
    interaction = coordinator.begin_interaction(
        interaction_id="i-1",
        scope=make_scope(),
        channel="chat",
        session_id="s-1",
        turn_id="t-1",
    )
    coordinator.processing(interaction)
    assert coordinator.is_processing(interaction.interaction_id)


def test_commit_interaction_sets_committed() -> None:
    coordinator = make_coordinator()
    interaction = coordinator.begin_interaction(
        interaction_id="i-1",
        scope=make_scope(),
        channel="chat",
        session_id="s-1",
        turn_id="t-1",
    )
    coordinator.processing(interaction)
    committed = coordinator.commit_interaction(interaction)
    assert committed.status is InteractionStatus.COMMITTED
    assert committed.committed_at == NOW
    assert not coordinator.is_processing("i-1")


def test_abort_interaction_sets_aborted_without_committed_at() -> None:
    coordinator = make_coordinator()
    interaction = coordinator.begin_interaction(
        interaction_id="i-1",
        scope=make_scope(),
        channel="chat",
        session_id="s-1",
        turn_id="t-1",
    )
    coordinator.processing(interaction)
    aborted = coordinator.abort_interaction(interaction)
    assert aborted.status is InteractionStatus.ABORTED
    assert aborted.committed_at is None
    assert not coordinator.is_processing("i-1")


def test_commit_without_begin_rejected() -> None:
    coordinator = make_coordinator()
    with pytest.raises(ValueError, match="unknown"):
        coordinator.commit_interaction(
            Interaction(
                interaction_id="ghost",
                scope=make_scope(),
                channel="chat",
                session_id="s-1",
                turn_id="t-1",
                started_at=NOW,
                committed_at=None,
                status=InteractionStatus.OPEN,
            )
        )


def test_double_commit_rejected() -> None:
    coordinator = make_coordinator()
    interaction = coordinator.begin_interaction(
        interaction_id="i-1",
        scope=make_scope(),
        channel="chat",
        session_id="s-1",
        turn_id="t-1",
    )
    coordinator.commit_interaction(interaction)
    with pytest.raises(ValueError, match="already"):
        coordinator.commit_interaction(interaction)


def test_abort_after_commit_rejected() -> None:
    coordinator = make_coordinator()
    interaction = coordinator.begin_interaction(
        interaction_id="i-1",
        scope=make_scope(),
        channel="chat",
        session_id="s-1",
        turn_id="t-1",
    )
    coordinator.commit_interaction(interaction)
    with pytest.raises(ValueError, match="already"):
        coordinator.abort_interaction(interaction)


def test_begin_duplicate_interaction_rejected() -> None:
    coordinator = make_coordinator()
    coordinator.begin_interaction(
        interaction_id="i-1",
        scope=make_scope(),
        channel="chat",
        session_id="s-1",
        turn_id="t-1",
    )
    with pytest.raises(ValueError, match="already exists"):
        coordinator.begin_interaction(
            interaction_id="i-1",
            scope=make_scope(),
            channel="chat",
            session_id="s-1",
            turn_id="t-1",
        )


def test_commit_requires_aware_utc_clock() -> None:
    coordinator = InteractionCoordinator(clock=FakeClock(NOW))
    interaction = coordinator.begin_interaction(
        interaction_id="i-1",
        scope=make_scope(),
        channel="chat",
        session_id="s-1",
        turn_id="t-1",
    )
    committed = coordinator.commit_interaction(interaction)
    assert committed.committed_at is not None
    assert committed.committed_at.tzinfo is not None
    assert committed.committed_at.utcoffset() == datetime.now(UTC).utcoffset()
