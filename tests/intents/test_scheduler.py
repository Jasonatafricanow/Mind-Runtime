"""Host-driven Scheduler wakes due Intent for reconsideration only."""

from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

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
from mind_runtime.intents.persistence import InMemoryIntentBackend, SqliteIntentBackend
from mind_runtime.intents.scheduler import IntentScheduler

NOW = datetime(2026, 8, 22, 12, 0, tzinfo=UTC)
USER_SCOPE = Scope(domain=ScopeDomain.USER, user_id="user-1")


def candidate(
    intent_id: str,
    *,
    due_at: datetime | None,
    expires_at: datetime | None,
    reconsideration: ReconsiderationPolicy = ReconsiderationPolicy.ON_DUE,
) -> Intent:
    earliest_at = due_at if due_at is not None else NOW - timedelta(hours=2)
    return Intent(
        intent_id=intent_id,
        scope=USER_SCOPE,
        origin_runtime_id="runtime-1",
        kind="scheduled_follow_up",
        strength=0.6,
        earliest_at=earliest_at,
        due_at=due_at,
        expires_at=expires_at,
        reconsideration_policy=reconsideration,
        cause_refs=("situation-1",),
        state_refs=("projection-1",),
        status=IntentStatus.CANDIDATE,
        sync=SyncFields(USER_SCOPE, "runtime-1", intent_id, 1, f"admit-{intent_id}"),
    )


def defer(service: IntentLifecycleService, intent: Intent) -> Intent:
    service.admit(intent)
    return service.transition(
        USER_SCOPE,
        intent.intent_id,
        IntentStatus.DEFERRED,
        ("waiting_until_due",),
        NOW - timedelta(hours=2),
        f"prepare-deferred-{intent.intent_id}",
    )


def test_expiry_wins_over_due_wake_and_creates_no_executable_work() -> None:
    backend = InMemoryIntentBackend()
    lifecycle = IntentLifecycleService(backend)
    expired_due = defer(
        lifecycle,
        candidate(
            "expired-due",
            due_at=NOW - timedelta(hours=1),
            expires_at=NOW,
        ),
    )

    wakes = IntentScheduler(lifecycle).tick(USER_SCOPE, NOW)

    assert wakes == ()
    current = backend.current(USER_SCOPE)[0]
    assert current.status is IntentStatus.EXPIRED
    assert current.sync.version == expired_due.sync.version + 1
    assert backend.transitions(USER_SCOPE, "expired-due")[-1].reason_codes == ("scheduler_expired",)


def test_due_deferred_intent_wakes_to_candidate_with_version_lineage() -> None:
    backend = InMemoryIntentBackend()
    lifecycle = IntentLifecycleService(backend)
    deferred = defer(
        lifecycle,
        candidate(
            "due-now",
            due_at=NOW,
            expires_at=NOW + timedelta(hours=4),
        ),
    )

    wakes = IntentScheduler(lifecycle).tick(USER_SCOPE, NOW)

    assert len(wakes) == 1
    wake = wakes[0]
    current = backend.current(USER_SCOPE)[0]
    assert wake.wake_id == "wake-due-now-v3"
    assert wake.scope == USER_SCOPE
    assert wake.intent_id == "due-now"
    assert wake.reason == "due_reconsideration"
    assert wake.woken_at == NOW
    assert wake.intent_version == deferred.sync.version + 1
    assert current.status is IntentStatus.CANDIDATE
    assert current.sync.version == wake.intent_version


def test_future_context_manual_and_terminal_intents_do_not_wake() -> None:
    backend = InMemoryIntentBackend()
    lifecycle = IntentLifecycleService(backend)
    future = defer(
        lifecycle,
        candidate(
            "future",
            due_at=NOW + timedelta(minutes=1),
            expires_at=NOW + timedelta(hours=2),
        ),
    )
    context_change = defer(
        lifecycle,
        candidate(
            "context",
            due_at=NOW - timedelta(minutes=1),
            expires_at=NOW + timedelta(hours=2),
            reconsideration=ReconsiderationPolicy.ON_CONTEXT_CHANGE,
        ),
    )
    manual = defer(
        lifecycle,
        candidate(
            "manual",
            due_at=NOW - timedelta(minutes=1),
            expires_at=NOW + timedelta(hours=2),
            reconsideration=ReconsiderationPolicy.MANUAL,
        ),
    )
    blocked_candidate = candidate(
        "blocked",
        due_at=NOW - timedelta(minutes=1),
        expires_at=NOW + timedelta(hours=2),
    )
    lifecycle.admit(blocked_candidate)
    blocked = lifecycle.transition(
        USER_SCOPE,
        "blocked",
        IntentStatus.BLOCKED,
        ("unsupported",),
        NOW - timedelta(minutes=1),
        "prepare-blocked",
    )
    before = backend.current(USER_SCOPE)

    assert IntentScheduler(lifecycle).tick(USER_SCOPE, NOW) == ()
    assert backend.current(USER_SCOPE) == before
    assert future.status is IntentStatus.DEFERRED
    assert context_change.status is IntentStatus.DEFERRED
    assert manual.status is IntentStatus.DEFERRED
    assert blocked.status is IntentStatus.BLOCKED


def test_repeated_tick_emits_no_duplicate_transition_or_wake() -> None:
    backend = InMemoryIntentBackend()
    lifecycle = IntentLifecycleService(backend)
    defer(
        lifecycle,
        candidate(
            "due-once",
            due_at=NOW,
            expires_at=NOW + timedelta(hours=2),
        ),
    )
    scheduler = IntentScheduler(lifecycle)

    first = scheduler.tick(USER_SCOPE, NOW)
    second = scheduler.tick(USER_SCOPE, NOW)

    assert len(first) == 1
    assert second == ()
    assert len(backend.history(USER_SCOPE, "due-once")) == 3
    assert len(backend.transitions(USER_SCOPE, "due-once")) == 2


def test_sqlite_restart_discovers_and_wakes_same_due_work(tmp_path: Path) -> None:
    path = tmp_path / "scheduler.sqlite3"
    first_backend = SqliteIntentBackend(path)
    first_lifecycle = IntentLifecycleService(first_backend)
    defer(
        first_lifecycle,
        candidate(
            "restart-due",
            due_at=NOW,
            expires_at=NOW + timedelta(hours=2),
        ),
    )
    first_backend.close()

    restarted_backend = SqliteIntentBackend(path)
    restarted_lifecycle = IntentLifecycleService(restarted_backend)
    wakes = IntentScheduler(restarted_lifecycle).tick(USER_SCOPE, NOW)

    assert [(wake.intent_id, wake.intent_version) for wake in wakes] == [("restart-due", 3)]
    assert restarted_backend.current(USER_SCOPE)[0].status is IntentStatus.CANDIDATE
    restarted_backend.close()


def test_scheduler_requires_aware_utc_now() -> None:
    scheduler = IntentScheduler(IntentLifecycleService(InMemoryIntentBackend()))

    with pytest.raises(ValueError, match="aware UTC"):
        scheduler.tick(USER_SCOPE, NOW.replace(tzinfo=None))
    with pytest.raises(ValueError, match="aware UTC"):
        scheduler.tick(USER_SCOPE, NOW.astimezone(timezone(timedelta(hours=2))))
