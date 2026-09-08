"""Shadow privacy pipeline tests (D11L Evidence #7 executable proof)."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from mind_runtime.shadow.redaction import (
    count_records,
    has_sensitive_leak,
    hash_id,
    init_store,
    redact_text,
    rotate_expired,
    sensitive_labels,
    store_record,
)

# ── identity hashing ───────────────────────────────────────────────────────


def test_hash_id_deterministic_and_irreversible() -> None:
    h1 = hash_id("session-1")
    assert h1 == hash_id("session-1")
    assert len(h1) == 12
    assert h1 != "session-1"  # not the plaintext
    assert h1 != hash_id("session-2")  # distinct inputs differ


# ── redaction patterns ─────────────────────────────────────────────────────


def test_phone_redacted() -> None:
    out = redact_text("电话 13812345678 联系")
    assert "[PHONE]" in out
    assert "13812345678" not in out


def test_email_redacted() -> None:
    out = redact_text("邮箱 abc.def@example.com 谢谢")
    assert "[EMAIL]" in out
    assert "abc.def@example.com" not in out


def test_id_card_redacted() -> None:
    out = redact_text("身份证 110101199001011234")
    assert "[ID_CARD]" in out


def test_bank_card_redacted() -> None:
    out = redact_text("卡号 6222020200112233445 已转")
    assert "[BANK_CARD]" in out


def test_amount_redacted() -> None:
    out = redact_text("付了 ¥12,800.50 元")
    assert "[AMOUNT]" in out
    assert "12,800" not in out


def test_long_digit_run_redacted() -> None:
    out = redact_text("订单号 20260826123456789 处理中")
    assert "[LONG_NUM]" in out


def test_known_name_coded() -> None:
    out = redact_text("嘉森和嘻嘻去公园", known_names=("嘉森", "嘻嘻"))
    assert "嘉森" not in out
    assert "嘻嘻" not in out
    assert "<person:1>" in out and "<person:2>" in out


def test_clean_text_untouched() -> None:
    text = "今天天气不错，我们聊了聊股票"
    assert redact_text(text) == text


# ── leak detection (fail-closed) ───────────────────────────────────────────


def test_leak_detection_true_on_plaintext() -> None:
    assert has_sensitive_leak("手机 13900001111")
    assert has_sensitive_leak("邮箱 a@b.co")
    assert has_sensitive_leak("1234567890123456789A")
    assert has_sensitive_leak("6222020200112233445")


def test_leak_detection_false_after_redaction() -> None:
    out = redact_text("电话 13812345678 卡号 6222020200112233445 付 ¥800")
    assert has_sensitive_leak(out) is False


# ── store + rotation ───────────────────────────────────────────────────────


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    p = tmp_path / "shadow.db"
    init_store(p)
    return p


def test_store_record_redacts_and_hashes(db_path: Path) -> None:
    redacted = store_record(
        db_path,
        user_id="user-jason",
        session_id="session-abc",
        channel="telegram",
        sender="user",
        trigger="message",
        source_domain="kayla_persona",
        text="我号码 13812345678，转你 ¥500",
    )
    assert "[PHONE]" in redacted and "[AMOUNT]" in redacted
    with sqlite3.connect(str(db_path)) as con:
        row = con.execute("SELECT user_hash, session_hash FROM shadow_events").fetchone()
    assert row[0] == hash_id("user-jason")
    assert row[1] == hash_id("session-abc")
    assert count_records(db_path) == 1


def test_store_refuses_on_leak(db_path: Path) -> None:
    # Verification-code-like plaintext survives redaction (not classified),
    # so the fail-closed store must refuse to persist it.
    with pytest.raises(ValueError):
        store_record(
            db_path,
            user_id="u",
            session_id="s",
            channel="telegram",
            sender="user",
            trigger="message",
            source_domain="kayla_persona",
            text="验证码 123456 请发我手机 13800001111",
        )
    assert count_records(db_path) == 0  # rolled back, nothing written


def test_rotate_expired_deletes_only_old(db_path: Path) -> None:
    store_record(
        db_path,
        user_id="u",
        session_id="s1",
        channel="telegram",
        sender="user",
        trigger="message",
        source_domain="kayla_persona",
        text="今天的内容",
    )
    # Inject an expired record manually (31 days old)
    old_ts = (datetime.now(UTC) - timedelta(days=31)).isoformat(timespec="seconds")
    with sqlite3.connect(str(db_path)) as con:
        con.execute(
            "INSERT INTO shadow_events "
            "(ts, user_hash, session_hash, channel, sender, trigger, source_domain, redacted_text) "
            "VALUES (?, 'oldhash', 'oldhash', 'telegram', "
            "'user', 'message', 'kayla_persona', 'old')",
            (old_ts,),
        )
    assert count_records(db_path) == 2
    deleted = rotate_expired(db_path, retention_days=30)
    assert deleted == 1
    assert count_records(db_path) == 1  # only the fresh one remains


def test_id_card_is_detected_and_tokenized() -> None:
    """C1.5 behavior: 18-digit resident-id shapes flag and redact."""
    text = "身份证11010519491231002X丢了要补办"
    # the bare digit run also raises the generic long-digit tripwire
    assert sensitive_labels(text) == ("id_card", "long_digits")
    out = redact_text(text)
    assert "[ID_CARD]" in out
    assert "11010519491231002X" not in out


def test_init_store_migrates_legacy_schema_additively(tmp_path: Path) -> None:
    """ADR-0012 §2: pre-event_ts stores gain the column lazily, rows kept."""
    import sqlite3

    db = tmp_path / "legacy.db"
    with sqlite3.connect(str(db)) as con:
        con.execute(
            "CREATE TABLE shadow_events ("
            "event_id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "content_id INTEGER UNIQUE,"
            "ts TEXT NOT NULL,"
            "user_hash TEXT NOT NULL,"
            "session_hash TEXT NOT NULL,"
            "channel TEXT NOT NULL,"
            "sender TEXT NOT NULL,"
            "trigger TEXT NOT NULL,"
            "source_domain TEXT NOT NULL,"
            "redacted_text TEXT NOT NULL)"
        )
        con.execute(
            "INSERT INTO shadow_events (content_id, ts, user_hash, session_hash, "
            "channel, sender, trigger, source_domain, redacted_text) "
            "VALUES (1,'2026-01-01T00:00:00+00:00','u','s','telegram','user',"
            "'message','kayla_persona','旧数据')"
        )
    init_store(db)
    with sqlite3.connect(str(db)) as con:
        columns = {row[1] for row in con.execute("PRAGMA table_info(shadow_events)")}
        row = con.execute("SELECT redacted_text, event_ts FROM shadow_events").fetchone()
    assert "event_ts" in columns
    assert row == ("旧数据", None)
