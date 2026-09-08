"""ActionReceipt / DeliveryReceipt idempotency and reconcile (D5.5).

Receipts distinguish not-sent, sent, and unknown send state. The reconcile
rules frozen by the baseline:

- all receipts SENT -> the action is considered delivered (reconciled);
- any UNKNOWN -> delivery state stays explicit, never silently resolved;
- otherwise (UNSENT only, or mixed without UNKNOWN) -> not sent.
"""

from dataclasses import dataclass

from mind_runtime.contracts import ActionReceipt, DeliveryStatus


@dataclass(frozen=True)
class ReceiptOutcome:
    """The reconciled delivery verdict for one action intent."""

    action_intent_id: str
    delivery_status: DeliveryStatus
    reconciled: bool
    reason: str


def reconcile_delivery(statuses: tuple[DeliveryStatus, ...]) -> tuple[DeliveryStatus, bool, str]:
    """Aggregate delivery statuses into one verdict (pure, D5.5)."""
    if not statuses:
        return DeliveryStatus.UNSENT, False, "no_receipts"
    unique = set(statuses)
    if DeliveryStatus.UNKNOWN in unique:
        return DeliveryStatus.UNKNOWN, False, "delivery_unknown"
    if unique == {DeliveryStatus.SENT}:
        return DeliveryStatus.SENT, True, "delivered"
    return DeliveryStatus.UNSENT, False, "not_sent"


def reconcile_receipts(receipts: tuple[ActionReceipt, ...]) -> ReceiptOutcome:
    """Reconcile every receipt recorded for one action intent."""
    status, reconciled, reason = reconcile_delivery(
        tuple(receipt.delivery_status for receipt in receipts)
    )
    intent_id = receipts[0].action_intent_id if receipts else ""
    return ReceiptOutcome(
        action_intent_id=intent_id,
        delivery_status=status,
        reconciled=reconciled,
        reason=reason,
    )


class ReceiptRegistry:
    """Idempotent receipt records keyed by receipt_id (D5.5)."""

    def __init__(self) -> None:
        self._receipts: dict[str, ActionReceipt] = {}

    def record(self, receipt: ActionReceipt) -> None:
        # Idempotent: re-recording the same receipt_id never duplicates.
        self._receipts[receipt.receipt_id] = receipt

    def receipts_for(self, action_intent_id: str) -> tuple[ActionReceipt, ...]:
        return tuple(
            receipt
            for receipt in self._receipts.values()
            if receipt.action_intent_id == action_intent_id
        )

    def reconcile(self, action_intent_id: str) -> ReceiptOutcome:
        return reconcile_receipts(self.receipts_for(action_intent_id))

    def all(self) -> tuple[ActionReceipt, ...]:
        return tuple(self._receipts.values())

    def count(self) -> int:
        return len(self._receipts)
