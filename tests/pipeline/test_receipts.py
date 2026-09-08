"""D5.5 ActionReceipt/DeliveryReceipt reconcile tests."""

from datetime import UTC, datetime

from mind_runtime.contracts import (
    ActionReceipt,
    DeliveryStatus,
    Interaction,
    InteractionStatus,
    SyncFields,
)
from mind_runtime.pipeline.orchestrator import TurnOrchestrator
from mind_runtime.pipeline.receipts import ReceiptRegistry, reconcile_delivery, reconcile_receipts
from mind_runtime.pipeline.trace import TraceRecorder
from tests.golden.fixtures.common import make_evidence, make_scope
from tests.support.fake_clock import FakeClock

NOW = datetime(2026, 8, 22, 13, 0, tzinfo=UTC)


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


def make_receipt(
    receipt_id: str,
    *,
    status: DeliveryStatus,
    action_intent_id: str = "intent-1",
) -> ActionReceipt:
    scope = make_scope()
    return ActionReceipt(
        receipt_id=receipt_id,
        scope=scope,
        origin_runtime_id="runtime-1",
        action_intent_id=action_intent_id,
        delivery_status=status,
        outcome="hello" if status is DeliveryStatus.SENT else None,
        received_at=NOW,
        sync=SyncFields(scope, "runtime-1", receipt_id, 1, f"idem-{receipt_id}"),
    )


def test_reconcile_delivery_all_sent() -> None:
    status, reconciled, reason = reconcile_delivery((DeliveryStatus.SENT, DeliveryStatus.SENT))
    assert status is DeliveryStatus.SENT
    assert reconciled is True
    assert reason == "delivered"


def test_reconcile_delivery_empty() -> None:
    status, reconciled, reason = reconcile_delivery(())
    assert status is DeliveryStatus.UNSENT
    assert reconciled is False
    assert reason == "no_receipts"


def test_reconcile_delivery_unknown_never_silent() -> None:
    status, reconciled, reason = reconcile_delivery((DeliveryStatus.SENT, DeliveryStatus.UNKNOWN))
    assert status is DeliveryStatus.UNKNOWN
    assert reconciled is False
    assert reason == "delivery_unknown"


def test_reconcile_delivery_not_sent() -> None:
    status, reconciled, reason = reconcile_delivery((DeliveryStatus.UNSENT, DeliveryStatus.UNSENT))
    assert status is DeliveryStatus.UNSENT
    assert reconciled is False
    assert reason == "not_sent"


def test_reconcile_delivery_mixed_without_unknown_is_not_sent() -> None:
    status, _, reason = reconcile_delivery((DeliveryStatus.SENT, DeliveryStatus.UNSENT))
    assert status is DeliveryStatus.UNSENT
    assert reason == "not_sent"


def test_reconcile_receipts_aggregates_one_intent() -> None:
    outcome = reconcile_receipts(
        (
            make_receipt("r-1", status=DeliveryStatus.SENT),
            make_receipt("r-2", status=DeliveryStatus.SENT),
        )
    )
    assert outcome.action_intent_id == "intent-1"
    assert outcome.reconciled is True
    assert outcome.delivery_status is DeliveryStatus.SENT


def test_reconcile_receipts_empty() -> None:
    outcome = reconcile_receipts(())
    assert outcome.action_intent_id == ""
    assert outcome.reconciled is False
    assert outcome.reason == "no_receipts"


def test_registry_record_is_idempotent() -> None:
    registry = ReceiptRegistry()
    registry.record(make_receipt("r-1", status=DeliveryStatus.SENT))
    registry.record(make_receipt("r-1", status=DeliveryStatus.SENT))
    assert registry.count() == 1
    assert registry.all() == (make_receipt("r-1", status=DeliveryStatus.SENT),)


def test_registry_reconcile_by_intent() -> None:
    registry = ReceiptRegistry()
    registry.record(make_receipt("r-1", status=DeliveryStatus.SENT, action_intent_id="a-1"))
    registry.record(make_receipt("r-2", status=DeliveryStatus.UNSENT, action_intent_id="a-1"))
    registry.record(make_receipt("r-3", status=DeliveryStatus.UNKNOWN, action_intent_id="a-2"))
    assert registry.reconcile("a-1").reason == "not_sent"
    assert registry.reconcile("a-2").reason == "delivery_unknown"
    assert registry.reconcile("a-3").reason == "no_receipts"


def test_orchestrator_records_and_reconciles_receipt() -> None:
    registry = ReceiptRegistry()
    orchestrator = TurnOrchestrator(clock=FakeClock(NOW), trace=TraceRecorder(), receipts=registry)
    orchestrator.begin_turn(make_interaction())
    orchestrator.ingest(make_evidence(text="hello"))
    orchestrator.run()
    assert registry.count() == 1
    outcome = orchestrator.reconcile("intent-interaction-1")
    assert outcome.reconciled is True
    assert outcome.delivery_status is DeliveryStatus.SENT


def test_orchestrator_reconcile_without_registry() -> None:
    orchestrator = TurnOrchestrator(clock=FakeClock(NOW), trace=TraceRecorder())
    outcome = orchestrator.reconcile("intent-stub")
    assert outcome.reason == "no_registry"
    assert outcome.reconciled is False
