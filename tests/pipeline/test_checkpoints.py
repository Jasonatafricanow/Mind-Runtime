"""D5.4 TurnCheckpoint tests: recoverable stages and restart decisions."""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from mind_runtime.contracts import (
    DeliveryStatus,
    Interaction,
    InteractionStatus,
    SyncFields,
    TurnCheckpoint,
    TurnStage,
)
from mind_runtime.pipeline.checkpoints import (
    InMemoryCheckpointStore,
    RecoveryDecision,
    SqliteCheckpointStore,
    recovery_decision,
)
from mind_runtime.pipeline.orchestrator import TurnOrchestrator
from mind_runtime.pipeline.trace import TraceRecorder
from tests.golden.fixtures.common import make_evidence, make_scope
from tests.support.fake_clock import FakeClock

NOW = datetime(2026, 8, 22, 12, 0, tzinfo=UTC)


def make_interaction() -> Interaction:
    return Interaction(
        interaction_id="interaction-1",
        scope=make_scope(),
        channel="chat",
        session_id="session-1",
        turn_id="turn-1",
        started_at=NOW,
        committed_at=None,
        status=InteractionStatus.OPEN,
    )


def make_orchestrator(**kwargs: Any) -> TurnOrchestrator:
    return TurnOrchestrator(clock=FakeClock(NOW), trace=TraceRecorder(), **kwargs)


def make_checkpoint(
    *,
    stage: TurnStage,
    delivery: DeliveryStatus = DeliveryStatus.SENT,
    interaction_id: str = "interaction-1",
) -> TurnCheckpoint:
    scope = make_scope()
    return TurnCheckpoint(
        checkpoint_id=f"checkpoint-{interaction_id}",
        interaction_id=interaction_id,
        scope=scope,
        origin_runtime_id="runtime-1",
        stage=stage,
        base_state_version=1,
        projection_ref="projection-interaction-1",
        action_id="intent-stub",
        delivery_status=delivery,
        checkpointed_at=NOW,
        sync=SyncFields(scope, "runtime-1", f"checkpoint-{interaction_id}", 1, "idem"),
    )


# --- stores ---


def test_in_memory_store_round_trip() -> None:
    store = InMemoryCheckpointStore()
    checkpoint = make_checkpoint(stage=TurnStage.DISPATCHING)
    store.save(checkpoint)
    assert store.load("interaction-1") == checkpoint
    store.remove("interaction-1")
    assert store.load("interaction-1") is None


def test_in_memory_store_replace_same_interaction() -> None:
    store = InMemoryCheckpointStore()
    store.save(make_checkpoint(stage=TurnStage.DISPATCHING))
    store.save(make_checkpoint(stage=TurnStage.AWAITING_COMMIT))
    loaded = store.load("interaction-1")
    assert loaded is not None
    assert loaded.stage is TurnStage.AWAITING_COMMIT
    assert len(store.all()) == 1


def test_sqlite_store_survives_restart(tmp_path: Path) -> None:
    path = tmp_path / "checkpoints.db"
    store = SqliteCheckpointStore(path)
    checkpoint = make_checkpoint(stage=TurnStage.AWAITING_COMMIT)
    store.save(checkpoint)
    store.close()
    # Simulated restart: a fresh store over the same file.
    restarted = SqliteCheckpointStore(path)
    assert restarted.load("interaction-1") == checkpoint
    restarted.remove("interaction-1")
    assert restarted.load("interaction-1") is None


def test_sqlite_store_table_name() -> None:
    store = SqliteCheckpointStore(":memory:")
    assert store.table_names() == ("checkpoints",)


# --- recovery decisions ---


@pytest.mark.parametrize(
    ("stage", "delivery", "expected_action"),
    [
        (TurnStage.AWAITING_COMMIT, DeliveryStatus.SENT, "not_committed"),
        (TurnStage.DISPATCHING, DeliveryStatus.SENT, "reconcile_complete"),
        (TurnStage.DISPATCHING, DeliveryStatus.UNKNOWN, "delivery_unknown"),
        (TurnStage.DISPATCHING, DeliveryStatus.UNSENT, "safe_abort"),
        (TurnStage.PROCESSING, DeliveryStatus.UNSENT, "processing_incomplete"),
    ],
)
def test_recovery_decision_matrix(
    stage: TurnStage, delivery: DeliveryStatus, expected_action: str
) -> None:
    decision = recovery_decision(make_checkpoint(stage=stage, delivery=delivery))
    assert isinstance(decision, RecoveryDecision)
    assert decision.action == expected_action
    assert decision.stage is stage
    assert decision.delivery_status is delivery


def test_recovery_decision_no_checkpoint() -> None:
    decision = recovery_decision(None)
    assert decision.action == "no_checkpoint"


# --- orchestrator integration ---


def test_run_checkpoints_dispatching_stage() -> None:
    store = InMemoryCheckpointStore()
    orchestrator = make_orchestrator(checkpoints=store)
    orchestrator.begin_turn(make_interaction())
    orchestrator.ingest(make_evidence(text="hello"))
    orchestrator.run()
    checkpoint = store.load("interaction-1")
    assert checkpoint is not None
    assert checkpoint.stage is TurnStage.DISPATCHING
    assert checkpoint.delivery_status is DeliveryStatus.SENT
    assert checkpoint.action_id == "intent-interaction-1"
    assert checkpoint.projection_ref == "projection-interaction-1"


def test_commit_removes_checkpoint() -> None:
    store = InMemoryCheckpointStore()
    orchestrator = make_orchestrator(checkpoints=store)
    orchestrator.begin_turn(make_interaction())
    orchestrator.ingest(make_evidence(text="hello"))
    orchestrator.run()
    assert store.load("interaction-1") is not None
    orchestrator.commit_turn()
    assert store.load("interaction-1") is None


def test_abort_removes_checkpoint() -> None:
    store = InMemoryCheckpointStore()
    orchestrator = make_orchestrator(checkpoints=store)
    orchestrator.begin_turn(make_interaction())
    orchestrator.ingest(make_evidence(text="hello"))
    orchestrator.run()
    orchestrator.abort_turn()
    assert store.load("interaction-1") is None


def test_recover_after_restart_never_treats_uncommitted_as_committed() -> None:
    """D5.4: an awaiting_commit checkpoint must not become 'committed'."""
    store = InMemoryCheckpointStore()
    orchestrator = make_orchestrator(checkpoints=store)
    orchestrator.begin_turn(make_interaction())
    orchestrator.ingest(make_evidence(text="hello"))
    orchestrator.run()
    orchestrator.commit_turn()
    assert store.load("interaction-1") is None  # committed -> dropped
    # Now simulate a crash BEFORE commit: checkpoint stays awaiting_commit.
    store.save(make_checkpoint(stage=TurnStage.AWAITING_COMMIT))
    restarted = make_orchestrator(checkpoints=store)
    decision = restarted.recover("interaction-1")
    assert decision.action == "not_committed"
    # The restarted orchestrator never has the projection in canonical.
    assert restarted.canonical == ()


def test_recover_dispatch_sent_reconciles_not_silent_abort() -> None:
    store = InMemoryCheckpointStore()
    store.save(make_checkpoint(stage=TurnStage.DISPATCHING, delivery=DeliveryStatus.SENT))
    restarted = make_orchestrator(checkpoints=store)
    assert restarted.recover("interaction-1").action == "reconcile_complete"


def test_recover_dispatch_unknown_never_silent_abort() -> None:
    store = InMemoryCheckpointStore()
    store.save(make_checkpoint(stage=TurnStage.DISPATCHING, delivery=DeliveryStatus.UNKNOWN))
    restarted = make_orchestrator(checkpoints=store)
    assert restarted.recover("interaction-1").action == "delivery_unknown"


def test_recover_no_checkpoint() -> None:
    orchestrator = make_orchestrator(checkpoints=InMemoryCheckpointStore())
    assert orchestrator.recover("interaction-1").action == "no_checkpoint"


def test_recover_without_store() -> None:
    orchestrator = make_orchestrator()
    assert orchestrator.recover("interaction-1").action == "no_checkpoint"


def test_sqlite_store_recovery_across_orchestrator_instances(tmp_path: Path) -> None:
    path = tmp_path / "cp.db"
    first = make_orchestrator(checkpoints=SqliteCheckpointStore(path))
    first.begin_turn(make_interaction())
    first.ingest(make_evidence(text="hello"))
    first.run()
    # Crash before commit; a fresh orchestrator over the same file.
    second = make_orchestrator(checkpoints=SqliteCheckpointStore(path))
    decision = second.recover("interaction-1")
    assert decision.action == "reconcile_complete"
    assert decision.stage is TurnStage.DISPATCHING
