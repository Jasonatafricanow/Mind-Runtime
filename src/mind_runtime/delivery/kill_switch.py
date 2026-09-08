"""Durable fail-closed kill switch (C7B STEP 5).

The kill switch lives in the same SQLite file as the delivery
backend, so an OFF decision survives process death. Three levels:

  global OFF     (no outbound anywhere)
  per-channel OFF (no outbound on channel X)
  per-target OFF  (no outbound to target Y)

Default is ON (delivery allowed). OFF is explicit.

The kill switch is consulted BEFORE the carrier is invoked. The
switch is NOT allowed to rewrite persisted ACCEPTED rows — the
ACCEPTED state is monotonic truth and survives a later switch
flip.

The C7A in-memory backend keeps its own (volatile) kill switch
behaviour via the ``fail_after`` flag; that is unchanged. The
durable kill switch in this module is independent and is what the
C7B tests exercise.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass(frozen=True, slots=True)
class KillSwitchDecision:
    """A pure answer to "may we deliver this outbound request?".

    ``allowed`` is the boolean answer. ``reason_code`` is a generic,
    non-secret string suitable for trace events. It MUST NOT contain
    the payload or any private expression text.
    """

    allowed: bool
    reason_code: str


class KillSwitchLevel:
    """Operational levels for the durable kill switch."""

    ON = "on"  # delivery allowed
    OFF = "off"  # global block
    OFF_CHANNEL = "off_channel"  # per-channel block
    OFF_TARGET = "off_target"  # per-target block

    @classmethod
    def all_levels(cls) -> tuple[str, ...]:
        return (cls.ON, cls.OFF, cls.OFF_CHANNEL, cls.OFF_TARGET)


_KILL_SWITCH_ROW_ID = 1  # single-row table; idempotent reopen


def _ensure_kill_switch_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS delivery_kill_switch (
            row_id INTEGER PRIMARY KEY,
            state TEXT NOT NULL,
            channel_blocks TEXT NOT NULL DEFAULT '{}',
            target_blocks TEXT NOT NULL DEFAULT '{}',
            updated_at TEXT NOT NULL
        );
        """
    )
    row = conn.execute(
        "SELECT row_id FROM delivery_kill_switch WHERE row_id = ?",
        (_KILL_SWITCH_ROW_ID,),
    ).fetchone()
    if row is None:
        now = datetime.now(tz=UTC)
        conn.execute(
            "INSERT INTO delivery_kill_switch "
            "(row_id, state, channel_blocks, target_blocks, updated_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (
                _KILL_SWITCH_ROW_ID,
                KillSwitchLevel.ON,
                "{}",
                "{}",
                now.isoformat(),
            ),
        )
        conn.commit()


def _validate_state(state: str) -> str:
    if state not in KillSwitchLevel.all_levels():
        raise ValueError(
            f"kill_switch state must be one of {KillSwitchLevel.all_levels()!r}: {state!r}"
        )
    return state


def _validate_block_map(raw: str, field_name: str) -> dict[str, str]:
    if not isinstance(raw, str):
        raise ValueError(f"{field_name} must be a JSON object string")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ValueError(
            f"{field_name} must be a valid JSON object: {error}"
        ) from error
    if not isinstance(parsed, dict):
        raise ValueError(f"{field_name} must be a JSON object")
    out: dict[str, str] = {}
    for key, value in parsed.items():
        if not isinstance(key, str) or not key:
            raise ValueError(f"{field_name} keys must be non-empty strings")
        if not isinstance(value, str):
            raise ValueError(f"{field_name} values must be strings")
        out[key] = value
    return out


def _compute_state(
    current: str, channel_blocks: dict[str, str], target_blocks: dict[str, str],
) -> str:
    """Derive the persistent state label from the two block maps.

    Precedence: global OFF > per-target OFF > per-channel OFF > ON.
    A global OFF is only set/cleared by ``set_global``; the
    block maps never override it directly, but the labels must
    agree with the maps so a reopen can answer "is X blocked?"
    without a separate check.
    """
    if current == KillSwitchLevel.OFF:
        return KillSwitchLevel.OFF
    if target_blocks:
        return KillSwitchLevel.OFF_TARGET
    if channel_blocks:
        return KillSwitchLevel.OFF_CHANNEL
    return KillSwitchLevel.ON


@dataclass
class DeliveryKillSwitch:
    """Durable, fail-closed kill switch consulted before every carrier call.

    The switch is a single-row table. Reopening the same SQLite file
    restores the persisted state; an OFF set before a crash remains
    OFF after restart. An ACCEPTED row persisted before the OFF is
    untouched (the switch MUST NOT rewrite history).
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        _ensure_kill_switch_schema(self._conn)

    def close(self) -> None:
        # The switch may share a connection with the delivery backend;
        # we never close a connection we did not create in this module.
        # The standalone constructor (below) is what callers use to
        # open a connection owned by the switch.
        if getattr(self, "_owns_conn", False):
            self._conn.close()

    # --- mutate ---

    def set_global(self, *, on: bool, updated_at: datetime) -> None:
        new_state = KillSwitchLevel.ON if on else KillSwitchLevel.OFF
        with self._conn:
            self._conn.execute(
                "UPDATE delivery_kill_switch"
                " SET state = ?, updated_at = ?"
                " WHERE row_id = ?",
                (new_state, updated_at.isoformat(), _KILL_SWITCH_ROW_ID),
            )

    def block_channel(self, channel: str, *, reason: str, updated_at: datetime) -> None:
        if not channel:
            raise ValueError("channel must be non-empty")
        if not reason:
            raise ValueError("reason must be non-empty")
        self._set_block("channel_blocks", channel, reason, updated_at)

    def unblock_channel(self, channel: str, *, updated_at: datetime) -> None:
        self._unset_block("channel_blocks", channel, updated_at)

    def block_target(self, target: str, *, reason: str, updated_at: datetime) -> None:
        if not target:
            raise ValueError("target must be non-empty")
        if not reason:
            raise ValueError("reason must be non-empty")
        self._set_block("target_blocks", target, reason, updated_at)

    def unblock_target(self, target: str, *, updated_at: datetime) -> None:
        self._unset_block("target_blocks", target, updated_at)

    def _read_row(self) -> tuple[str, dict[str, str], dict[str, str]]:
        row = self._conn.execute(
            "SELECT state, channel_blocks, target_blocks FROM delivery_kill_switch"
            " WHERE row_id = ?",
            (_KILL_SWITCH_ROW_ID,),
        ).fetchone()
        if row is None:
            raise ValueError(  # pragma: no cover
                "kill switch row missing — schema not initialised"
            )
        return (
            _validate_state(row["state"]),
            _validate_block_map(row["channel_blocks"], "channel_blocks"),
            _validate_block_map(row["target_blocks"], "target_blocks"),
        )

    def _set_block(
        self, column: str, key: str, reason: str, updated_at: datetime
    ) -> None:
        state, channel_blocks, target_blocks = self._read_row()
        if column == "channel_blocks":
            channel_blocks = {**channel_blocks, key: reason}
        else:
            target_blocks = {**target_blocks, key: reason}
        new_state = _compute_state(state, channel_blocks, target_blocks)
        with self._conn:
            self._conn.execute(
                "UPDATE delivery_kill_switch SET"
                " channel_blocks = ?, target_blocks = ?,"
                " state = ?, updated_at = ?"
                " WHERE row_id = ?",
                (
                    json.dumps(channel_blocks, sort_keys=True),
                    json.dumps(target_blocks, sort_keys=True),
                    new_state,
                    updated_at.isoformat(),
                    _KILL_SWITCH_ROW_ID,
                ),
            )

    def _unset_block(self, column: str, key: str, updated_at: datetime) -> None:
        state, channel_blocks, target_blocks = self._read_row()
        if column == "channel_blocks":
            channel_blocks = {k: v for k, v in channel_blocks.items() if k != key}
        else:
            target_blocks = {k: v for k, v in target_blocks.items() if k != key}
        new_state = _compute_state(state, channel_blocks, target_blocks)
        with self._conn:
            self._conn.execute(
                "UPDATE delivery_kill_switch SET"
                " channel_blocks = ?, target_blocks = ?,"
                " state = ?, updated_at = ?"
                " WHERE row_id = ?",
                (
                    json.dumps(channel_blocks, sort_keys=True),
                    json.dumps(target_blocks, sort_keys=True),
                    new_state,
                    updated_at.isoformat(),
                    _KILL_SWITCH_ROW_ID,
                ),
            )

    # --- inspect ---

    def state(self) -> str:
        state, channel_blocks, target_blocks = self._read_row()
        return state

    def channel_blocks(self) -> dict[str, str]:
        _, channel_blocks, _ = self._read_row()
        return channel_blocks

    def target_blocks(self) -> dict[str, str]:
        _, _, target_blocks = self._read_row()
        return target_blocks

    def decide(self, *, channel: str, target: str) -> KillSwitchDecision:
        """Pure consult: may this (channel, target) be delivered now?

        Order of precedence: global OFF > per-channel OFF >
        per-target OFF > ON. Reasons are generic (no payload).
        """

        if not channel:
            raise ValueError("channel must be non-empty")
        if not target:
            raise ValueError("target must be non-empty")
        state, channel_blocks, target_blocks = self._read_row()
        if state == KillSwitchLevel.OFF:
            return KillSwitchDecision(allowed=False, reason_code="global_off")
        if channel in channel_blocks:
            return KillSwitchDecision(
                allowed=False, reason_code=f"channel_off:{channel}",
            )
        if target in target_blocks:
            return KillSwitchDecision(
                allowed=False, reason_code=f"target_off:{target}",
            )
        return KillSwitchDecision(allowed=True, reason_code="on")


def open_kill_switch(path: str) -> DeliveryKillSwitch:
    """Open a standalone kill switch on its own SQLite file.

    The shared-connection constructor in ``DeliveryKillSwitch``
    is what production code uses (the delivery backend owns the
    connection and the switch shares it). This standalone
    constructor is for tests that exercise the kill switch in
    isolation.
    """

    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    switch = DeliveryKillSwitch(conn)
    switch._owns_conn = True  # type: ignore[attr-defined]
    return switch
