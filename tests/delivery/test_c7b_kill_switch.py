"""C7B STEP 5 — kill switch tests.

Three levels (operational):
  global OFF  (no outbound anywhere)
  per-channel OFF (no outbound on channel X)
  per-target OFF (no outbound to target Y)

Default is ON (delivery allowed). OFF is explicit.

Invariants:
  * OFF before carrier invocation: zero transport.send calls happen.
  * OFF after request is persisted but before delivery: the
    request stays PENDING / IN_FLIGHT; the carrier is never invoked.
  * OFF after provider ACCEPTED: the persisted ACCEPTED truth is
    preserved; the orchestrator MUST NOT rewrite history.
"""

from __future__ import annotations

import gc
from datetime import UTC, datetime
from pathlib import Path

import pytest

from mind_runtime.contracts import (
    Scope,
    ScopeDomain,
    SyncFields,
)
from mind_runtime.delivery import (
    DeliveryLifecycleState,
    DeliveryRequest,
    KillSwitchLevel,
    SqliteDeliveryBackend,
    make_message_id,
    make_request_id,
)

NOW = datetime(2026, 1, 1, tzinfo=UTC)
SCOPE = Scope(domain=ScopeDomain.USER, user_id="u1")
RUNTIME_ID = "xiyue"


def _request(
    *, request_id: str, body: bytes = b"hello",
    channel: str = "weixin", target: str = "user-1",
) -> DeliveryRequest:
    return DeliveryRequest(
        request_id=request_id,
        message_id=make_message_id(request_id),
        scope=SCOPE, origin_runtime_id=RUNTIME_ID,
        channel=channel, target=target, action_type="proactive_message", payload_bytes=body,
        created_at=NOW,
        sync=SyncFields(SCOPE, RUNTIME_ID, request_id, 1, f"idem-{request_id}"),
    )


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "c7b_ks.db"


# ----------------------------------------------------------- defaults


def test_default_state_is_on(db_path: Path) -> None:
    """The default kill-switch state is ON (delivery allowed)."""

    backend = SqliteDeliveryBackend(db_path)
    try:
        assert backend.kill_switch().state() == KillSwitchLevel.ON
    finally:
        backend.close()


# ----------------------------------------------------------- global OFF


def test_global_off_blocks_all_outbound(db_path: Path) -> None:
    """Global OFF refuses every (channel, target)."""

    backend = SqliteDeliveryBackend(db_path)
    try:
        ks = backend.kill_switch()
        ks.set_global(on=False, updated_at=datetime.now(tz=UTC))
        decision = ks.decide(channel="weixin", target="user-1")
        assert decision.allowed is False
        assert decision.reason_code == "global_off"
    finally:
        backend.close()


def test_global_off_survives_reopen(db_path: Path) -> None:
    """Global OFF persists across process restart."""

    backend = SqliteDeliveryBackend(db_path)
    ks = backend.kill_switch()
    ks.set_global(on=False, updated_at=datetime.now(tz=UTC))
    backend.close()
    del backend, ks
    gc.collect()

    fresh = SqliteDeliveryBackend(db_path)
    try:
        assert fresh.kill_switch().state() == KillSwitchLevel.OFF
        decision = fresh.kill_switch().decide(channel="x", target="y")
        assert decision.allowed is False
        assert decision.reason_code == "global_off"
    finally:
        fresh.close()


# ----------------------------------------------------------- per-channel OFF


def test_per_channel_off_blocks_only_that_channel(db_path: Path) -> None:
    """per-channel OFF blocks one channel; other channels are allowed."""

    backend = SqliteDeliveryBackend(db_path)
    try:
        ks = backend.kill_switch()
        ks.block_channel("weixin", reason="maintenance", updated_at=datetime.now(tz=UTC))
        assert ks.state() == KillSwitchLevel.OFF_CHANNEL
        blocked = ks.decide(channel="weixin", target="user-1")
        assert blocked.allowed is False
        assert "channel_off" in blocked.reason_code
        allowed = ks.decide(channel="email", target="user-1")
        assert allowed.allowed is True
    finally:
        backend.close()


def test_per_channel_off_survives_reopen(db_path: Path) -> None:
    """per-channel OFF persists across restart."""

    backend = SqliteDeliveryBackend(db_path)
    ks = backend.kill_switch()
    ks.block_channel("weixin", reason="maintenance", updated_at=datetime.now(tz=UTC))
    backend.close()
    del backend, ks
    gc.collect()

    fresh = SqliteDeliveryBackend(db_path)
    try:
        assert fresh.kill_switch().state() == KillSwitchLevel.OFF_CHANNEL
        assert "weixin" in fresh.kill_switch().channel_blocks()
        decision = fresh.kill_switch().decide(channel="weixin", target="x")
        assert decision.allowed is False
    finally:
        fresh.close()


# ----------------------------------------------------------- per-target OFF


def test_per_target_off_blocks_only_that_target(db_path: Path) -> None:
    """per-target OFF blocks one target; other targets are allowed."""

    backend = SqliteDeliveryBackend(db_path)
    try:
        ks = backend.kill_switch()
        ks.block_target("user-1", reason="opt_out", updated_at=datetime.now(tz=UTC))
        assert ks.state() == KillSwitchLevel.OFF_TARGET
        blocked = ks.decide(channel="weixin", target="user-1")
        assert blocked.allowed is False
        assert "target_off" in blocked.reason_code
        allowed = ks.decide(channel="weixin", target="user-2")
        assert allowed.allowed is True
    finally:
        backend.close()


def test_per_target_off_survives_reopen(db_path: Path) -> None:
    """per-target OFF persists across restart."""

    backend = SqliteDeliveryBackend(db_path)
    ks = backend.kill_switch()
    ks.block_target("user-1", reason="opt_out", updated_at=datetime.now(tz=UTC))
    backend.close()
    del backend, ks
    gc.collect()

    fresh = SqliteDeliveryBackend(db_path)
    try:
        assert fresh.kill_switch().state() == KillSwitchLevel.OFF_TARGET
        assert "user-1" in fresh.kill_switch().target_blocks()
    finally:
        fresh.close()


# ----------------------------------------------------------- accept preserved


def test_off_after_accepted_does_not_rewrite_history(
    db_path: Path,
) -> None:
    """Turning the kill switch OFF does NOT rewrite persisted
    ACCEPTED rows. ACCEPTED is monotonic truth.
    """

    request = _request(request_id=make_request_id(SCOPE, "intent-1", "k1"))
    backend = SqliteDeliveryBackend(db_path)
    backend.record_request(
        request, lifecycle_state=DeliveryLifecycleState.PENDING,
    )
    backend.set_lifecycle_state(
        request.request_id, DeliveryLifecycleState.IN_FLIGHT, at=NOW,
    )
    backend.set_lifecycle_state(
        request.request_id, DeliveryLifecycleState.ACCEPTED, at=NOW,
    )
    # Now flip the kill switch OFF.
    backend.kill_switch().set_global(
        on=False, updated_at=datetime.now(tz=UTC),
    )
    # The persisted ACCEPTED row is untouched.
    row = backend.get_durable_request(request.request_id)
    assert row is not None
    assert row.lifecycle_state is DeliveryLifecycleState.ACCEPTED
    # An attempt to rewrite the state as REJECTED must fail closed.
    with pytest.raises(ValueError, match="illegal delivery lifecycle"):
        backend.set_lifecycle_state(
            request.request_id, DeliveryLifecycleState.REJECTED,
            at=datetime.now(tz=UTC),
        )
    backend.close()


# ----------------------------------------------------------- unblock


def test_unblock_channel_returns_to_on_when_no_others_blocked(
    db_path: Path,
) -> None:
    """Unblocking the only channel block returns the switch to ON."""

    backend = SqliteDeliveryBackend(db_path)
    try:
        ks = backend.kill_switch()
        ks.block_channel("weixin", reason="x", updated_at=datetime.now(tz=UTC))
        assert ks.state() == KillSwitchLevel.OFF_CHANNEL
        ks.unblock_channel("weixin", updated_at=datetime.now(tz=UTC))
        assert ks.state() == KillSwitchLevel.ON
    finally:
        backend.close()


def test_unblock_target_with_channel_blocks_remaining_off_channel(
    db_path: Path,
) -> None:
    """If both blocks exist, unblocking a target leaves channel
    block in effect: state is OFF_CHANNEL.
    """

    backend = SqliteDeliveryBackend(db_path)
    try:
        ks = backend.kill_switch()
        now = datetime.now(tz=UTC)
        ks.block_channel("weixin", reason="x", updated_at=now)
        ks.block_target("user-1", reason="y", updated_at=now)
        # Both blocks: the higher-priority label is OFF_TARGET.
        assert ks.state() == KillSwitchLevel.OFF_TARGET
        ks.unblock_target("user-1", updated_at=now)
        # Channel block remains: state is OFF_CHANNEL.
        assert ks.state() == KillSwitchLevel.OFF_CHANNEL
    finally:
        backend.close()


# ----------------------------------------------------------- bad input


@pytest.mark.parametrize(
    ("operation", "kwargs", "message"),
    (
        ("decide", {"channel": "", "target": "user-1"}, "channel"),
        ("decide", {"channel": "weixin", "target": ""}, "target"),
        (
            "block_channel",
            {"channel": "", "reason": "x", "updated_at": NOW},
            "channel",
        ),
        (
            "block_channel",
            {"channel": "weixin", "reason": "", "updated_at": NOW},
            "reason",
        ),
        (
            "block_target",
            {"target": "", "reason": "x", "updated_at": NOW},
            "target",
        ),
        (
            "block_target",
            {"target": "user-1", "reason": "", "updated_at": NOW},
            "reason",
        ),
    ),
)
def test_kill_switch_rejects_empty_inputs(
    db_path: Path,
    operation: str,
    kwargs: dict[str, object],
    message: str,
) -> None:
    backend = SqliteDeliveryBackend(db_path)
    try:
        with pytest.raises(ValueError, match=message):
            getattr(backend.kill_switch(), operation)(**kwargs)
    finally:
        backend.close()

