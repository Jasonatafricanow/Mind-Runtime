"""Host-driven due/expiry processing that never executes an action."""

from datetime import UTC, datetime

from mind_runtime.contracts import (
    Intent,
    IntentStatus,
    IntentWake,
    ReconsiderationPolicy,
    Scope,
)
from mind_runtime.contracts.common import require_aware_utc
from mind_runtime.intents.lifecycle import IntentLifecycleService

_EXPIRABLE = frozenset({IntentStatus.CANDIDATE, IntentStatus.DEFERRED})


class IntentScheduler:
    """Expire stale Intents and wake due deferred Intents for reconsideration."""

    def __init__(self, lifecycle: IntentLifecycleService) -> None:
        self._lifecycle = lifecycle

    def tick(self, scope: Scope, now: datetime) -> tuple[IntentWake, ...]:
        require_aware_utc(now, "scheduler now")
        intents = tuple(sorted(self._lifecycle.backend.current(scope), key=_sort_key))
        expired_ids: set[str] = set()
        for intent in intents:
            if (
                intent.status in _EXPIRABLE
                and intent.expires_at is not None
                and intent.expires_at <= now
            ):
                self._lifecycle.transition(
                    scope,
                    intent.intent_id,
                    IntentStatus.EXPIRED,
                    ("scheduler_expired",),
                    now,
                    f"scheduler-expire-{intent.intent_id}-v{intent.sync.version}",
                )
                expired_ids.add(intent.intent_id)

        wakes: list[IntentWake] = []
        for intent in intents:
            if intent.intent_id in expired_ids or not _is_due(intent, now):
                continue
            reconsidered = self._lifecycle.transition(
                scope,
                intent.intent_id,
                IntentStatus.CANDIDATE,
                ("scheduler_due",),
                now,
                f"scheduler-due-{intent.intent_id}-v{intent.sync.version}",
            )
            wakes.append(
                IntentWake(
                    wake_id=f"wake-{intent.intent_id}-v{reconsidered.sync.version}",
                    scope=scope,
                    intent_id=intent.intent_id,
                    reason="due_reconsideration",
                    woken_at=now,
                    intent_version=reconsidered.sync.version,
                )
            )
        return tuple(wakes)


def _sort_key(intent: Intent) -> tuple[datetime, str]:
    return (intent.due_at or datetime.max.replace(tzinfo=UTC), intent.intent_id)


def _is_due(intent: Intent, now: datetime) -> bool:
    return (
        intent.status is IntentStatus.DEFERRED
        and intent.reconsideration_policy is ReconsiderationPolicy.ON_DUE
        and intent.due_at is not None
        and intent.due_at <= now
    )
