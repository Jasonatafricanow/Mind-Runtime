"""D3.C2/C3 InteractionCoordinator persistence: lifecycle survives restart."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from mind_runtime.contracts import Interaction, InteractionStatus
from mind_runtime.facts.coordinator import InteractionCoordinator
from mind_runtime.facts.persistence import SqliteFactBackend
from tests.golden.fixtures.common import make_scope
from tests.support.fake_clock import FakeClock

NOW = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)


def make_coordinator(path: str | Path | None = None) -> InteractionCoordinator:
    backend = SqliteFactBackend(path) if path is not None else None
    return InteractionCoordinator(clock=FakeClock(NOW), backend=backend)


def begin(
    coordinator: InteractionCoordinator, interaction_id: str = "interaction-1"
) -> Interaction:
    return coordinator.begin_interaction(
        interaction_id=interaction_id,
        scope=make_scope(),
        channel="chat",
        session_id="session-1",
        turn_id="turn-1",
    )


def test_open_interaction_survives_restart(tmp_path: Path) -> None:
    path = tmp_path / "facts.db"
    coordinator = make_coordinator(path)
    begin(coordinator)
    restarted = make_coordinator(path)
    interaction = restarted.get_interaction("interaction-1")
    assert interaction is not None
    assert interaction.status is InteractionStatus.OPEN
    assert interaction.started_at == NOW


def test_committed_state_survives_restart_and_recommit_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "facts.db"
    coordinator = make_coordinator(path)
    interaction = begin(coordinator)
    coordinator.commit_interaction(interaction)
    restarted = make_coordinator(path)
    loaded = restarted.get_interaction("interaction-1")
    assert loaded is not None
    assert loaded.status is InteractionStatus.COMMITTED
    assert loaded.committed_at == NOW
    # Lifecycle stays fail-closed after restart: no second commit.
    with pytest.raises(ValueError, match="already"):
        restarted.commit_interaction(loaded)


def test_aborted_state_survives_restart(tmp_path: Path) -> None:
    path = tmp_path / "facts.db"
    coordinator = make_coordinator(path)
    interaction = begin(coordinator)
    coordinator.abort_interaction(interaction)
    restarted = make_coordinator(path)
    loaded = restarted.get_interaction("interaction-1")
    assert loaded is not None
    assert loaded.status is InteractionStatus.ABORTED
    assert loaded.committed_at is None
    with pytest.raises(ValueError, match="already"):
        restarted.abort_interaction(loaded)


def test_begin_duplicate_after_restart_rejected(tmp_path: Path) -> None:
    path = tmp_path / "facts.db"
    coordinator = make_coordinator(path)
    begin(coordinator)
    restarted = make_coordinator(path)
    with pytest.raises(ValueError, match="already exists"):
        begin(restarted)


def test_get_interaction_unknown_returns_none(tmp_path: Path) -> None:
    coordinator = make_coordinator(tmp_path / "facts.db")
    assert coordinator.get_interaction("ghost") is None


def test_processing_marker_is_runtime_state_not_durable(tmp_path: Path) -> None:
    path = tmp_path / "facts.db"
    coordinator = make_coordinator(path)
    interaction = begin(coordinator)
    coordinator.processing(interaction)
    restarted = make_coordinator(path)
    assert not restarted.is_processing("interaction-1")
    # The interaction itself is still known and OPEN after restart.
    loaded = restarted.get_interaction("interaction-1")
    assert loaded is not None
    assert loaded.status is InteractionStatus.OPEN
