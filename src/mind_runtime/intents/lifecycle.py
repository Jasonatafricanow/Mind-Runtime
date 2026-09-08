"""Legal append-only Intent lifecycle service."""

from dataclasses import replace
from datetime import datetime

from mind_runtime.contracts import Intent, IntentStatus, IntentTransition, Scope, SyncFields
from mind_runtime.contracts.common import require_non_empty
from mind_runtime.intents.persistence import IntentBackend

_LEGAL_TRANSITIONS: dict[IntentStatus, frozenset[IntentStatus]] = {
    IntentStatus.CANDIDATE: frozenset(
        {
            IntentStatus.ALLOWED,
            IntentStatus.DEFERRED,
            IntentStatus.BLOCKED,
            IntentStatus.EXPIRED,
            IntentStatus.SUPERSEDED,
        }
    ),
    IntentStatus.DEFERRED: frozenset(
        {IntentStatus.CANDIDATE, IntentStatus.EXPIRED, IntentStatus.SUPERSEDED}
    ),
    IntentStatus.ALLOWED: frozenset({IntentStatus.COMPLETED, IntentStatus.SUPERSEDED}),
}


class IntentLifecycleService:
    """Own lifecycle legality while delegating atomic storage to a backend."""

    def __init__(self, backend: IntentBackend) -> None:
        if not isinstance(backend, IntentBackend):
            raise ValueError("backend must implement IntentBackend")
        self.backend = backend

    def admit(self, intent: Intent) -> Intent:
        if intent.status is not IntentStatus.CANDIDATE or intent.sync.version != 1:
            raise ValueError("admit requires a version-one candidate Intent")
        return self.backend.append_initial(intent)

    @staticmethod
    def is_initial_candidate(intent: Intent) -> bool:
        """Return whether an engine output is admissible as lifecycle version one."""

        return intent.status is IntentStatus.CANDIDATE and intent.sync.version == 1

    @staticmethod
    def has_status(intent: Intent, status: IntentStatus) -> bool:
        """Keep Intent lifecycle-state inspection inside its authority module."""

        return intent.status is status

    def transition(
        self,
        scope: Scope,
        intent_id: str,
        to_status: IntentStatus,
        reason_codes: tuple[str, ...],
        occurred_at: datetime,
        idempotency_key: str,
    ) -> Intent:
        require_non_empty(intent_id, "intent_id")
        require_non_empty(idempotency_key, "idempotency_key")
        if not isinstance(to_status, IntentStatus):
            raise ValueError("to_status must be an IntentStatus")
        try:
            history = self.backend.history(scope, intent_id)
        except KeyError as error:
            raise KeyError(f"missing Intent {intent_id}") from error

        for existing in history[1:]:
            if existing.sync.idempotency_key != idempotency_key:
                continue
            existing_transition = next(
                item
                for item in self.backend.transitions(scope, intent_id)
                if item.version == existing.sync.version
            )
            if (
                existing_transition.to_status is to_status
                and existing_transition.reason_codes == reason_codes
            ):
                return existing
            raise ValueError("conflicting transition idempotency replay")

        before = history[-1]
        if to_status not in _LEGAL_TRANSITIONS.get(before.status, frozenset()):
            raise ValueError(
                f"illegal Intent transition {before.status.value} -> {to_status.value}"
            )
        next_version = before.sync.version + 1
        next_sync = SyncFields(
            scope=scope,
            origin_runtime_id=before.origin_runtime_id,
            object_id=intent_id,
            version=next_version,
            idempotency_key=idempotency_key,
        )
        after = replace(before, status=to_status, sync=next_sync)
        transition_id = f"intent-transition-{intent_id}-v{next_version}"
        recorded = IntentTransition(
            transition_id=transition_id,
            scope=scope,
            origin_runtime_id=before.origin_runtime_id,
            intent_id=intent_id,
            from_status=before.status,
            to_status=to_status,
            reason_codes=reason_codes,
            occurred_at=occurred_at,
            version=next_version,
            sync=SyncFields(
                scope=scope,
                origin_runtime_id=before.origin_runtime_id,
                object_id=transition_id,
                version=next_version,
                idempotency_key=idempotency_key,
            ),
        )
        return self.backend.apply_transition(before, after, recorded)
