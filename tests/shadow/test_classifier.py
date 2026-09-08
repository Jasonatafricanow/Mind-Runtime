"""Classifier classification-matrix tests (D11L Evidence #2 executable proof)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from mind_runtime.shadow.classifier import EventMeta, classify
from mind_runtime.shadow.redaction import count_records, hash_id, init_store
from mind_runtime.shadow.runner import handle_event


def _meta(**over: str) -> EventMeta:
    base = dict(
        channel="telegram",
        sender="user",
        session="session-1",
        trigger="message",
        source_domain="kayla_persona",
    )
    base.update(over)
    return EventMeta(**base)


# ── eligible ────────────────────────────────────────────────────────────────


def test_e1_real_private_chat_telegram() -> None:
    assert classify(_meta()) is True


def test_e1_real_private_chat_weixin() -> None:
    assert classify(_meta(channel="weixin")) is True


def test_e2_emotion_driven_proactive() -> None:
    assert classify(_meta(sender="agent", trigger="emotion")) is True


def test_agent_reply_in_chat_eligible() -> None:
    assert classify(_meta(sender="agent")) is True


# ── ineligible: traffic classes that must never be sampled ─────────────────


@pytest.mark.parametrize(
    "over",
    [
        {"channel": "unknown-channel"},
        {"channel": ""},
        {"sender": "system"},
        {"sender": ""},
        {"trigger": "cron"},  # cron 自动消息
        {"trigger": "schedule"},  # schedule 定时
        {"trigger": "heartbeat"},  # 心跳
        {"trigger": "task"},  # 任务
        {"trigger": "sync"},  # 同步
        {"trigger": "mirror"},  # 金屋镜像（trigger 级）
        {"trigger": "unknown"},
        {"session": "test/abc"},  # 测试 bot
        {"session": "test/sandbox-1"},
        {"source_domain": "xinchao"},  # 心潮
        {"source_domain": "ombre_brain"},  # OB
        {"source_domain": "garden"},  # 金屋
        {"source_domain": "test"},
        {"source_domain": "sandbox"},
    ],
)
def test_ineligible_matrix(over: dict[str, str]) -> None:
    assert classify(_meta(**over)) is False


# ── runner integration (fail-closed proof) ────────────────────────────────


def test_runner_refuses_when_gate_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MIND_RUNTIME_SHADOW_ENABLED", raising=False)
    assert handle_event(_meta()) == "refused-gate"


def test_runner_gate_on_skips_ineligible(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MIND_RUNTIME_SHADOW_ENABLED", "1")
    assert handle_event(_meta(trigger="cron")) == "ineligible"


def test_runner_gate_on_eligible_dry(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MIND_RUNTIME_SHADOW_ENABLED", "1")
    assert handle_event(_meta(), dry_run=True) == "eligible-dry"


def test_runner_real_store_path_records_private_semantics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """C1.5 behavior: the real store path persists private-mode semantics."""
    db = tmp_path / "shadow.db"
    monkeypatch.setenv("MIND_RUNTIME_SHADOW_ENABLED", "1")
    monkeypatch.setenv("MIND_RUNTIME_SHADOW_DB", str(db))
    status = handle_event(_meta(session="chat-9"), text="嘻嘻在吃饭")
    assert status == "eligible-recorded"
    with sqlite3.connect(str(db)) as con:
        row = con.execute("SELECT user_hash, redacted_text FROM shadow_events").fetchone()
    assert count_records(db) == 1
    # ADR-0011 private mode default: the person stays plaintext verbatim,
    # and identity fields are hashed
    assert str(row[0]) == hash_id("chat-9")
    assert str(row[1]) == "嘻嘻在吃饭"


def test_runner_store_refuses_secret_leak_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """C1.5 behavior: untokenizable OTP material never reaches the store."""
    db = tmp_path / "shadow.db"
    init_store(db)
    monkeypatch.setenv("MIND_RUNTIME_SHADOW_ENABLED", "1")
    monkeypatch.setenv("MIND_RUNTIME_SHADOW_DB", str(db))
    with pytest.raises(ValueError, match="sensitive plaintext"):
        handle_event(_meta(), text="验证码123456请查收")
    assert count_records(db) == 0
