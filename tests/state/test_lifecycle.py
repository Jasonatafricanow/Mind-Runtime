"""D4.1 lifecycle vocabulary tests: current-like/terminal definitions frozen."""

import pytest

from mind_runtime.state.lifecycle import (
    CURRENT_LIKE_LIFECYCLES,
    TERMINAL_LIFECYCLES,
    StateLifecycle,
    is_current_like,
    is_known_lifecycle,
    is_terminal,
)


def test_seven_frozen_lifecycle_statuses() -> None:
    assert {member.value for member in StateLifecycle} == {
        "active",
        "improving",
        "expired",
        "resolved",
        "completed",
        "cancelled",
        "superseded",
    }


def test_current_like_is_active_and_improving_only() -> None:
    assert CURRENT_LIKE_LIFECYCLES == frozenset({StateLifecycle.ACTIVE, StateLifecycle.IMPROVING})


def test_terminal_set_matches_baseline() -> None:
    assert TERMINAL_LIFECYCLES == frozenset(
        {
            StateLifecycle.RESOLVED,
            StateLifecycle.COMPLETED,
            StateLifecycle.CANCELLED,
            StateLifecycle.SUPERSEDED,
        }
    )


def test_expired_is_neither_current_like_nor_terminal() -> None:
    assert StateLifecycle.EXPIRED not in CURRENT_LIKE_LIFECYCLES
    assert StateLifecycle.EXPIRED not in TERMINAL_LIFECYCLES


@pytest.mark.parametrize(
    "status",
    [StateLifecycle.ACTIVE, StateLifecycle.IMPROVING, "active", "improving"],
)
def test_current_like_classification(status: str | StateLifecycle) -> None:
    assert is_current_like(status)
    assert not is_terminal(status)


@pytest.mark.parametrize(
    "status",
    [
        StateLifecycle.RESOLVED,
        StateLifecycle.COMPLETED,
        StateLifecycle.CANCELLED,
        StateLifecycle.SUPERSEDED,
        "resolved",
        "completed",
        "cancelled",
        "superseded",
    ],
)
def test_terminal_classification(status: str | StateLifecycle) -> None:
    assert is_terminal(status)
    assert not is_current_like(status)


def test_unknown_statuses_fail_safe() -> None:
    for unknown in ("current", "open", "whatever", ""):
        assert not is_current_like(unknown)
        assert not is_terminal(unknown)
        assert not is_known_lifecycle(unknown)


def test_expired_is_known_lifecycle_but_neither_class() -> None:
    assert is_known_lifecycle("expired")
    assert is_known_lifecycle(StateLifecycle.EXPIRED)
    assert not is_current_like(StateLifecycle.EXPIRED)
    assert not is_terminal(StateLifecycle.EXPIRED)
