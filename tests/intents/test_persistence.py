"""Durable restart-safe SQLite Intent lifecycle persistence."""

import sqlite3
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import pytest

from mind_runtime.contracts import (
    Intent,
    IntentStatus,
    IntentTransition,
    ReconsiderationPolicy,
    Scope,
    ScopeDomain,
    SyncFields,
)
from mind_runtime.intents.lifecycle import IntentLifecycleService
from mind_runtime.intents.persistence import (
    InMemoryIntentBackend,
    SqliteIntentBackend,
    _transition_from_row,
)

NOW = datetime(2026, 8, 22, 12, 0, tzinfo=UTC)
USER_SCOPE = Scope(domain=ScopeDomain.USER, user_id="user-1")
OTHER_SCOPE = Scope(domain=ScopeDomain.USER, user_id="user-2")


def candidate(intent_id: str = "intent-1", scope: Scope = USER_SCOPE) -> Intent:
    return Intent(
        intent_id=intent_id,
        scope=scope,
        origin_runtime_id="runtime-1",
        kind="scheduled_follow_up",
        strength=0.6,
        earliest_at=NOW,
        due_at=NOW + timedelta(hours=1),
        expires_at=NOW + timedelta(hours=5),
        reconsideration_policy=ReconsiderationPolicy.ON_DUE,
        cause_refs=("situation-1", "event-1"),
        state_refs=("projection-1",),
        status=IntentStatus.CANDIDATE,
        sync=SyncFields(scope, "runtime-1", intent_id, 1, f"admit-{intent_id}"),
    )


def transition(
    service: IntentLifecycleService,
    to_status: IntentStatus,
    *,
    scope: Scope = USER_SCOPE,
    intent_id: str = "intent-1",
    idempotency_key: str,
) -> Intent:
    return service.transition(
        scope,
        intent_id,
        to_status,
        (f"became_{to_status.value}",),
        NOW + timedelta(minutes=1),
        idempotency_key,
    )


def open_backend(path: Path) -> SqliteIntentBackend:
    return SqliteIntentBackend(path)


def test_sqlite_tables_and_append_only_version_history(tmp_path: Path) -> None:
    backend = open_backend(tmp_path / "intents.sqlite3")
    service = IntentLifecycleService(backend)
    initial = service.admit(candidate())
    deferred = transition(service, IntentStatus.DEFERRED, idempotency_key="defer-v2")
    reconsidered = transition(service, IntentStatus.CANDIDATE, idempotency_key="wake-v3")

    assert backend.table_names() == ("intent_transitions", "intents")
    assert backend.current(USER_SCOPE) == (reconsidered,)
    assert backend.history(USER_SCOPE, "intent-1") == (initial, deferred, reconsidered)
    assert [item.version for item in backend.transitions(USER_SCOPE, "intent-1")] == [2, 3]
    assert initial.status is IntentStatus.CANDIDATE
    assert deferred.status is IntentStatus.DEFERRED
    backend.close()


def test_restart_restores_same_current_history_and_aware_timestamps(tmp_path: Path) -> None:
    path = tmp_path / "restart.sqlite3"
    first_backend = open_backend(path)
    first_service = IntentLifecycleService(first_backend)
    initial = first_service.admit(candidate())
    deferred = transition(first_service, IntentStatus.DEFERRED, idempotency_key="defer-v2")
    first_backend.close()

    restarted = open_backend(path)

    assert restarted.current(USER_SCOPE) == (deferred,)
    assert restarted.history(USER_SCOPE, "intent-1") == (initial, deferred)
    restored_transition = restarted.transitions(USER_SCOPE, "intent-1")[0]
    assert restored_transition.occurred_at.tzinfo is not None
    assert restored_transition.occurred_at.utcoffset() == timedelta(0)
    assert restarted.history(USER_SCOPE, "intent-1")[0].due_at == NOW + timedelta(hours=1)
    restarted.close()


def test_sqlite_duplicate_replay_and_conflict_are_fail_closed(tmp_path: Path) -> None:
    backend = open_backend(tmp_path / "idempotency.sqlite3")
    service = IntentLifecycleService(backend)
    initial = candidate()
    assert service.admit(initial) == initial
    assert service.admit(initial) == initial
    deferred = transition(service, IntentStatus.DEFERRED, idempotency_key="same-operation")
    replay = transition(service, IntentStatus.DEFERRED, idempotency_key="same-operation")

    assert replay == deferred
    assert len(backend.history(USER_SCOPE, "intent-1")) == 2
    assert len(backend.transitions(USER_SCOPE, "intent-1")) == 1
    with pytest.raises(ValueError, match="conflicting"):
        service.admit(replace(initial, strength=0.9))
    with pytest.raises(ValueError, match="conflicting identity"):
        service.admit(
            replace(
                initial,
                sync=replace(initial.sync, idempotency_key="different-admission"),
            )
        )
    with pytest.raises(ValueError, match="conflicting"):
        transition(service, IntentStatus.EXPIRED, idempotency_key="same-operation")
    backend.close()


def test_sqlite_backend_rejects_invalid_initial_directly(tmp_path: Path) -> None:
    backend = open_backend(tmp_path / "invalid-initial.sqlite3")

    with pytest.raises(ValueError, match="version-one"):
        backend.append_initial(replace(candidate(), status=IntentStatus.DEFERRED))

    backend.close()


def test_scope_columns_isolate_current_history_and_transitions(tmp_path: Path) -> None:
    backend = open_backend(tmp_path / "scope.sqlite3")
    service = IntentLifecycleService(backend)
    user_intent = service.admit(candidate(scope=USER_SCOPE))
    other_intent = service.admit(candidate(scope=OTHER_SCOPE))

    assert backend.current(USER_SCOPE) == (user_intent,)
    assert backend.current(OTHER_SCOPE) == (other_intent,)
    with pytest.raises(KeyError, match="missing"):
        backend.history(OTHER_SCOPE, "not-present")
    with pytest.raises(KeyError, match="missing"):
        backend.transitions(OTHER_SCOPE, "not-present")
    backend.close()


def test_apply_transition_validates_transition_references_before_write(tmp_path: Path) -> None:
    initial = candidate()
    memory = InMemoryIntentBackend()
    memory_service = IntentLifecycleService(memory)
    memory_service.admit(initial)
    after = transition(memory_service, IntentStatus.DEFERRED, idempotency_key="defer-v2")
    recorded = memory.transitions(USER_SCOPE, "intent-1")[0]
    backend = open_backend(tmp_path / "references.sqlite3")
    backend.append_initial(initial)

    with pytest.raises(ValueError, match="describe"):
        backend.apply_transition(initial, after, replace(recorded, intent_id="other-intent"))

    assert backend.current(USER_SCOPE) == (initial,)
    assert backend.history(USER_SCOPE, "intent-1") == (initial,)
    assert backend.transitions(USER_SCOPE, "intent-1") == ()
    backend.close()


def test_transition_row_failure_rolls_back_new_intent_version(tmp_path: Path) -> None:
    path = tmp_path / "rollback.sqlite3"
    backend = open_backend(path)
    service = IntentLifecycleService(backend)
    initial = service.admit(candidate())
    with sqlite3.connect(path) as injector:
        injector.execute(
            """
            CREATE TRIGGER fail_intent_transition
            BEFORE INSERT ON intent_transitions
            BEGIN
                SELECT RAISE(ABORT, 'injected transition failure');
            END
            """
        )

    with pytest.raises(sqlite3.IntegrityError, match="injected"):
        transition(service, IntentStatus.DEFERRED, idempotency_key="must-rollback")

    assert backend.current(USER_SCOPE) == (initial,)
    assert backend.history(USER_SCOPE, "intent-1") == (initial,)
    assert backend.transitions(USER_SCOPE, "intent-1") == ()
    backend.close()


def _generated_transition() -> tuple[Intent, Intent, IntentTransition]:
    initial = candidate()
    memory = InMemoryIntentBackend()
    service = IntentLifecycleService(memory)
    service.admit(initial)
    after = transition(service, IntentStatus.DEFERRED, idempotency_key="generated-v2")
    return initial, after, memory.transitions(USER_SCOPE, "intent-1")[0]


def test_sqlite_direct_transition_replay_and_corruption_fail_closed(tmp_path: Path) -> None:
    initial, after, recorded = _generated_transition()
    path = tmp_path / "direct-replay.sqlite3"
    backend = open_backend(path)
    backend.append_initial(initial)
    assert backend.apply_transition(initial, after, recorded) == after
    assert backend.apply_transition(initial, after, recorded) == after
    with pytest.raises(ValueError, match="conflicting"):
        backend.apply_transition(
            initial,
            after,
            replace(recorded, reason_codes=("different",)),
        )
    with sqlite3.connect(path) as corruptor:
        corruptor.execute("DELETE FROM intent_transitions")
    with pytest.raises(ValueError, match="conflicting"):
        backend.apply_transition(initial, after, recorded)
    backend.close()


def test_sqlite_transition_shape_validation_catches_each_mutation(tmp_path: Path) -> None:
    initial, after, recorded = _generated_transition()

    empty = open_backend(tmp_path / "missing-current.sqlite3")
    with pytest.raises(ValueError, match="not current"):
        empty.apply_transition(initial, after, recorded)
    empty.close()

    backend = open_backend(tmp_path / "shape.sqlite3")
    backend.append_initial(initial)
    other_id = "other-intent"
    with pytest.raises(ValueError, match="identity"):
        backend.apply_transition(
            initial,
            replace(after, intent_id=other_id, sync=replace(after.sync, object_id=other_id)),
            recorded,
        )
    with pytest.raises(ValueError, match="origin"):
        backend.apply_transition(
            initial,
            replace(
                after,
                origin_runtime_id="other-runtime",
                sync=replace(after.sync, origin_runtime_id="other-runtime"),
            ),
            recorded,
        )
    with pytest.raises(ValueError, match="increment"):
        backend.apply_transition(
            initial,
            replace(after, sync=replace(after.sync, version=3)),
            recorded,
        )
    with pytest.raises(ValueError, match="immutable"):
        backend.apply_transition(initial, replace(after, strength=0.9), recorded)
    with pytest.raises(ValueError, match="idempotency"):
        backend.apply_transition(
            initial,
            after,
            replace(
                recorded,
                sync=replace(recorded.sync, idempotency_key="different-transition"),
            ),
        )
    backend.close()


def test_corrupt_sqlite_json_and_missing_transition_time_fail_closed(tmp_path: Path) -> None:
    path = tmp_path / "corrupt.sqlite3"
    backend = open_backend(path)
    backend.append_initial(candidate())
    with sqlite3.connect(path) as corruptor:
        corruptor.execute("UPDATE intents SET cause_refs = '{}' ")
    with pytest.raises(ValueError, match="reference list"):
        backend.history(USER_SCOPE, "intent-1")
    backend.close()

    row = {
        "scope_domain": "user",
        "scope_user_id": "user-1",
        "scope_agent_id": "",
        "scope_persona_id": "",
        "scope_relationship_id": "",
        "scope_world_id": "",
        "scope_interaction_id": "",
        "transition_id": "transition-1",
        "origin_runtime_id": "runtime-1",
        "version": 2,
        "occurred_at": None,
    }
    with pytest.raises(ValueError, match="occurred_at"):
        _transition_from_row(cast(sqlite3.Row, row))
