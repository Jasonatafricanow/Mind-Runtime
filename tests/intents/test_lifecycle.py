"""Append-only legal Intent lifecycle behavior."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest

from mind_runtime.contracts import (
    Intent,
    IntentStatus,
    ReconsiderationPolicy,
    Scope,
    ScopeDomain,
    SyncFields,
)
from mind_runtime.intents.lifecycle import IntentLifecycleService
from mind_runtime.intents.persistence import InMemoryIntentBackend, IntentBackend

NOW = datetime(2026, 8, 22, 12, 0, tzinfo=UTC)
USER_SCOPE = Scope(domain=ScopeDomain.USER, user_id="user-1")
OTHER_SCOPE = Scope(domain=ScopeDomain.USER, user_id="user-2")


def candidate(intent_id: str = "intent-1") -> Intent:
    return Intent(
        intent_id=intent_id,
        scope=USER_SCOPE,
        origin_runtime_id="runtime-1",
        kind="contact_user",
        strength=0.7,
        earliest_at=NOW,
        due_at=None,
        expires_at=NOW + timedelta(hours=2),
        reconsideration_policy=ReconsiderationPolicy.ON_CONTEXT_CHANGE,
        cause_refs=("situation-1",),
        state_refs=("projection-1",),
        status=IntentStatus.CANDIDATE,
        sync=SyncFields(USER_SCOPE, "runtime-1", intent_id, 1, f"admit-{intent_id}"),
    )


def transition(
    service: IntentLifecycleService,
    to_status: IntentStatus,
    *,
    intent_id: str = "intent-1",
    reason_codes: tuple[str, ...] = ("test_reason",),
    occurred_at: datetime = NOW + timedelta(minutes=1),
    idempotency_key: str | None = None,
) -> Intent:
    return service.transition(
        USER_SCOPE,
        intent_id,
        to_status,
        reason_codes,
        occurred_at,
        idempotency_key or f"transition-{intent_id}-{to_status.value}",
    )


def service_with_candidate(
    backend: InMemoryIntentBackend | None = None,
) -> tuple[IntentLifecycleService, InMemoryIntentBackend]:
    selected_backend = backend or InMemoryIntentBackend()
    service = IntentLifecycleService(selected_backend)
    service.admit(candidate())
    return service, selected_backend


def test_backend_protocol_and_candidate_admission_are_exactly_idempotent() -> None:
    backend = InMemoryIntentBackend()
    service = IntentLifecycleService(backend)
    initial = candidate()

    assert isinstance(backend, IntentBackend)
    assert service.admit(initial) == initial
    assert service.admit(initial) == initial
    assert backend.current(USER_SCOPE) == (initial,)
    assert backend.history(USER_SCOPE, initial.intent_id) == (initial,)
    assert backend.transitions(USER_SCOPE, initial.intent_id) == ()

    with pytest.raises(ValueError, match="conflicting"):
        service.admit(replace(initial, strength=0.8))
    with pytest.raises(ValueError, match="conflicting identity"):
        service.admit(
            replace(
                initial,
                sync=replace(initial.sync, idempotency_key="different-admission"),
            )
        )
    with pytest.raises(ValueError, match="candidate"):
        service.admit(replace(initial, status=IntentStatus.DEFERRED))
    with pytest.raises(ValueError, match="version-one"):
        backend.append_initial(replace(initial, status=IntentStatus.DEFERRED))


def test_lifecycle_rejects_non_backend_and_invalid_status_type() -> None:
    with pytest.raises(ValueError, match="IntentBackend"):
        IntentLifecycleService(cast(IntentBackend, object()))
    service, _backend = service_with_candidate()
    with pytest.raises(ValueError, match="IntentStatus"):
        service.transition(
            USER_SCOPE,
            "intent-1",
            cast(IntentStatus, "deferred"),
            ("invalid",),
            NOW,
            "invalid-status",
        )


@pytest.mark.parametrize(
    ("from_status", "to_status"),
    [
        (IntentStatus.CANDIDATE, IntentStatus.ALLOWED),
        (IntentStatus.CANDIDATE, IntentStatus.DEFERRED),
        (IntentStatus.CANDIDATE, IntentStatus.BLOCKED),
        (IntentStatus.CANDIDATE, IntentStatus.EXPIRED),
        (IntentStatus.CANDIDATE, IntentStatus.SUPERSEDED),
        (IntentStatus.DEFERRED, IntentStatus.CANDIDATE),
        (IntentStatus.DEFERRED, IntentStatus.EXPIRED),
        (IntentStatus.DEFERRED, IntentStatus.SUPERSEDED),
        (IntentStatus.ALLOWED, IntentStatus.COMPLETED),
        (IntentStatus.ALLOWED, IntentStatus.SUPERSEDED),
    ],
)
def test_legal_transition_matrix_appends_one_version_and_preserves_intent_facts(
    from_status: IntentStatus, to_status: IntentStatus
) -> None:
    service, backend = service_with_candidate()
    if from_status is IntentStatus.DEFERRED:
        before = transition(service, IntentStatus.DEFERRED, idempotency_key="prepare-deferred")
    elif from_status is IntentStatus.ALLOWED:
        before = transition(service, IntentStatus.ALLOWED, idempotency_key="prepare-allowed")
    else:
        before = candidate()

    after = transition(
        service,
        to_status,
        occurred_at=NOW + timedelta(minutes=2),
        idempotency_key=f"legal-{from_status.value}-{to_status.value}",
    )

    assert after.status is to_status
    assert after.sync.version == before.sync.version + 1
    assert after.earliest_at == before.earliest_at
    assert after.due_at == before.due_at
    assert after.expires_at == before.expires_at
    assert after.cause_refs == before.cause_refs
    assert after.state_refs == before.state_refs
    history = backend.history(USER_SCOPE, after.intent_id)
    assert history[-2:] == (before, after)
    assert history[-2].status is from_status
    recorded = backend.transitions(USER_SCOPE, after.intent_id)[-1]
    assert recorded.from_status is from_status
    assert recorded.to_status is to_status
    assert recorded.version == after.sync.version


@pytest.mark.parametrize(
    "terminal",
    [
        IntentStatus.BLOCKED,
        IntentStatus.EXPIRED,
        IntentStatus.COMPLETED,
        IntentStatus.SUPERSEDED,
    ],
)
def test_terminal_status_history_cannot_be_rewritten(terminal: IntentStatus) -> None:
    service, backend = service_with_candidate()
    if terminal is IntentStatus.COMPLETED:
        transition(service, IntentStatus.ALLOWED, idempotency_key="prepare-allowed")
    final = transition(service, terminal, idempotency_key=f"make-{terminal.value}")
    before_history = backend.history(USER_SCOPE, final.intent_id)
    before_transitions = backend.transitions(USER_SCOPE, final.intent_id)

    with pytest.raises(ValueError, match="illegal"):
        transition(
            service,
            IntentStatus.CANDIDATE,
            idempotency_key=f"rewrite-{terminal.value}",
        )

    assert backend.current(USER_SCOPE) == (final,)
    assert backend.history(USER_SCOPE, final.intent_id) == before_history
    assert backend.transitions(USER_SCOPE, final.intent_id) == before_transitions


def test_same_status_absent_intent_and_cross_scope_fail_closed() -> None:
    service, backend = service_with_candidate()
    before = backend.current(USER_SCOPE)

    with pytest.raises(ValueError, match="illegal"):
        transition(service, IntentStatus.CANDIDATE, idempotency_key="same-status")
    with pytest.raises(KeyError, match="missing"):
        transition(service, IntentStatus.ALLOWED, intent_id="missing")
    with pytest.raises(KeyError, match="missing"):
        service.transition(
            OTHER_SCOPE,
            "intent-1",
            IntentStatus.ALLOWED,
            ("wrong_scope",),
            NOW,
            "cross-scope",
        )

    assert backend.current(USER_SCOPE) == before
    assert backend.current(OTHER_SCOPE) == ()


def test_transition_replay_is_idempotent_and_conflicting_reuse_fails() -> None:
    service, backend = service_with_candidate()
    first = transition(
        service,
        IntentStatus.DEFERRED,
        reason_codes=("cooldown_active",),
        idempotency_key="policy-defer-1",
    )
    replay = transition(
        service,
        IntentStatus.DEFERRED,
        reason_codes=("cooldown_active",),
        occurred_at=NOW + timedelta(hours=1),
        idempotency_key="policy-defer-1",
    )

    assert replay == first
    assert len(backend.history(USER_SCOPE, "intent-1")) == 2
    assert len(backend.transitions(USER_SCOPE, "intent-1")) == 1
    with pytest.raises(ValueError, match="conflicting"):
        transition(
            service,
            IntentStatus.EXPIRED,
            reason_codes=("expired",),
            idempotency_key="policy-defer-1",
        )

    initial = backend.history(USER_SCOPE, "intent-1")[0]
    recorded = backend.transitions(USER_SCOPE, "intent-1")[0]
    assert backend.apply_transition(initial, first, recorded) == first
    with pytest.raises(ValueError, match="conflicting"):
        backend.apply_transition(
            initial,
            first,
            replace(recorded, reason_codes=("different",)),
        )


def test_in_memory_backend_direct_missing_reads_and_transition_fail_closed() -> None:
    populated_service, populated = service_with_candidate()
    after = transition(
        populated_service,
        IntentStatus.DEFERRED,
        idempotency_key="generated-transition",
    )
    initial = populated.history(USER_SCOPE, "intent-1")[0]
    recorded = populated.transitions(USER_SCOPE, "intent-1")[0]
    empty = InMemoryIntentBackend()

    with pytest.raises(KeyError, match="missing"):
        empty.history(USER_SCOPE, "intent-1")
    with pytest.raises(KeyError, match="missing"):
        empty.transitions(USER_SCOPE, "intent-1")
    with pytest.raises(KeyError, match="missing"):
        empty.apply_transition(initial, after, recorded)


class FailingCommitBackend(InMemoryIntentBackend):
    """Test double that fails at the backend's atomic commit boundary."""

    fail_commit = False

    def _commit(self, snapshot: Any) -> None:
        if self.fail_commit:
            raise RuntimeError("injected commit failure")
        super()._commit(snapshot)


def test_backend_commit_failure_changes_neither_current_nor_history() -> None:
    backend = FailingCommitBackend()
    service, _ = service_with_candidate(backend)
    before_current = backend.current(USER_SCOPE)
    before_history = backend.history(USER_SCOPE, "intent-1")
    before_transitions = backend.transitions(USER_SCOPE, "intent-1")
    backend.fail_commit = True

    with pytest.raises(RuntimeError, match="injected"):
        transition(service, IntentStatus.DEFERRED, idempotency_key="fail-transition")

    assert backend.current(USER_SCOPE) == before_current
    assert backend.history(USER_SCOPE, "intent-1") == before_history
    assert backend.transitions(USER_SCOPE, "intent-1") == before_transitions
