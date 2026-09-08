"""D11L shadow privacy pipeline (Evidence #7 executable).

Fail-closed redaction for shadow-learned content:
  * identity hashing (irreversible, deterministic)
  * sensitive plaintext redaction (phone/email/id-card/bank/amounts/tokens)
  * shadow store with 30-day rotation
  * pre-store leak validation (refuses to write if any sensitive plaintext
    pattern remains)
"""

from __future__ import annotations

import hashlib
import re
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

ID_HASH_LEN = 12
DEFAULT_RETENTION_DAYS = 30

_PHONE_RE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)|(?<!\d)1[3-9]\d[- ]?\d{4}[- ]?\d{4}(?!\d)")
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_IDCARD_RE = re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)")
_BANKCARD_RE = re.compile(
    r"(?<!\d)(?:62|60|58|55|54|53|52|51|35|34|30|48|49|40|43|36|37|38|39)[0-9]{12,17}(?!\d)"
)
# Amounts only when clearly marked: currency symbol, thousands separators,
# or explicit unit. Bare digit runs are never treated as amounts.
_AMOUNT_RE = re.compile(
    r"(?<!\d)(?:¥|￥)\s*\d[\d,]*(?:\.\d{1,2})?\s*(?:元|块|万|亿)?|"
    r"(?<!\d)\d{1,3}(?:,\d{3})+(?:\.\d{1,2})?\s*(?:元|块|万|亿)?|"
    r"(?<!\d)\d[\d,]*\.\d{1,2}\s*(?:元|块|万|亿)?"
)
# conservative: bare long digit runs that likely are ids/accounts
_LONG_DIGITS_RE = re.compile(r"(?<!\d)\d{9,}(?!\d)")
# 6-digit verification/PIN-like tokens: redaction leaves them (unsure what
# they are) but leak detection refuses them -> fail-closed store block.
_PIN_RE = re.compile(r"(?<!\d)\d{6}(?!\d)")
# API-key / bearer-style credential material. Conservative shapes only:
# explicit provider prefixes or explicit key/value assignment context.
# Generic high-entropy guessing is deliberately out of scope. Note: no
# leading \b on prefix shapes — \w includes CJK chars, so "\b" would never
# hold right after a Chinese character ("更新sk-proj…").
_TOKEN_RE = re.compile(
    r"(?:sk|pk)-[A-Za-z0-9_-]{16,}\b"
    r"|ghp_[A-Za-z0-9]{20,}"
    r"|github_pat_[A-Za-z0-9_]{20,}"
    r"|xox[baprs]-[A-Za-z0-9-]{10,}"
    r"|AKIA[0-9A-Z]{16}"
    r"|(?i:bearer)[\s:=]+[A-Za-z0-9._~-]{16,}"
    r"|(?i:(?:api[_-]?key|access[_-]?token|auth[_-]?token|secret[_-]?(?:key|token))"
    r"[\s:=]+)[A-Za-z0-9._~/+=-]{12,}"
)


def hash_id(plain: str) -> str:
    """Deterministic, irreversible identity hash (sha256 prefix)."""
    return hashlib.sha256(plain.encode("utf-8")).hexdigest()[:ID_HASH_LEN]


def sensitive_labels(text: str) -> tuple[str, ...]:
    """Labels of credential-class patterns present in text.

    Single truth source shared by ingestion redaction, the fail-closed leak
    gate, and egress provenance so they can never drift apart.
    """
    found: list[str] = []
    if _PHONE_RE.search(text):
        found.append("phone")
    if _EMAIL_RE.search(text):
        found.append("email")
    if _IDCARD_RE.search(text):
        found.append("id_card")
    if _BANKCARD_RE.search(text):
        found.append("bank_card")
    if _LONG_DIGITS_RE.search(text):
        found.append("long_digits")
    if _PIN_RE.search(text):
        found.append("pin")
    if _TOKEN_RE.search(text):
        found.append("token")
    return tuple(found)


def redact_text(text: str, known_names: tuple[str, ...] = ()) -> str:
    """Replace sensitive plaintext with redaction tokens.

    known_names: explicit person/place names to code (e.g. ("嘉森", "嘻嘻")).
    Order matters: longest/named replacements first to avoid golden-rule
    conflicts (a name inside an address should still be coded).
    """
    out = text
    # Named persons/places -> <person:N> codes (stable order from input tuple)
    for idx, name in enumerate(known_names, start=1):
        out = out.replace(name, f"<person:{idx}>")
    out = _PHONE_RE.sub("[PHONE]", out)
    out = _EMAIL_RE.sub("[EMAIL]", out)
    out = _IDCARD_RE.sub("[ID_CARD]", out)
    out = _BANKCARD_RE.sub("[BANK_CARD]", out)
    # token shapes must be consumed BEFORE the greedy digit-run rules,
    # otherwise keys like sk-...<digits> get mangled into [LONG_NUM]
    out = _TOKEN_RE.sub("[TOKEN]", out)
    out = _AMOUNT_RE.sub("[AMOUNT]", out)
    out = _LONG_DIGITS_RE.sub("[LONG_NUM]", out)
    return out


def has_sensitive_leak(text: str) -> bool:
    """True if any known sensitive plaintext pattern remains."""
    return bool(sensitive_labels(text))


# ── shadow store (SQLite) ──────────────────────────────────────────────────

_SCHEMA = """
CREATE TABLE IF NOT EXISTS shadow_events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    content_id INTEGER UNIQUE,
    ts TEXT NOT NULL,
    user_hash TEXT NOT NULL,
    session_hash TEXT NOT NULL,
    channel TEXT NOT NULL,
    sender TEXT NOT NULL,
    trigger TEXT NOT NULL,
    source_domain TEXT NOT NULL,
    redacted_text TEXT NOT NULL,
    event_ts TEXT
);
CREATE INDEX IF NOT EXISTS idx_shadow_events_ts ON shadow_events(ts);
"""


def _ensure_event_ts_column(con: sqlite3.Connection) -> None:
    """Lazy additive migration for DBs created before ADR-0012."""
    columns = {row[1] for row in con.execute("PRAGMA table_info(shadow_events)")}
    if "event_ts" not in columns:
        con.execute("ALTER TABLE shadow_events ADD COLUMN event_ts TEXT")


def init_store(db_path: str | Path) -> None:
    with sqlite3.connect(str(db_path)) as con:
        con.executescript(_SCHEMA)
        _ensure_event_ts_column(con)
        con.commit()


def store_record(
    db_path: str | Path,
    *,
    user_id: str,
    session_id: str,
    channel: str,
    sender: str,
    trigger: str,
    source_domain: str,
    text: str,
    known_names: tuple[str, ...] = (),
) -> str:
    """Redact then persist. Refuses (rolls back) if leak remains (fail-closed)."""
    redacted = redact_text(text, known_names)
    if has_sensitive_leak(redacted):
        raise ValueError("shadow store refused: sensitive plaintext remains")
    now = datetime.now(UTC).isoformat(timespec="seconds")
    with sqlite3.connect(str(db_path)) as con:
        con.execute(
            "INSERT INTO shadow_events "
            "(ts, user_hash, session_hash, channel, sender, trigger, source_domain, redacted_text) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (
                now,
                hash_id(user_id),
                hash_id(session_id),
                channel,
                sender,
                trigger,
                source_domain,
                redacted,
            ),
        )
    return redacted


def rotate_expired(db_path: str | Path, retention_days: int = DEFAULT_RETENTION_DAYS) -> int:
    """Delete shadow records older than retention; returns deleted count."""
    cutoff = (datetime.now(UTC) - timedelta(days=retention_days)).isoformat(timespec="seconds")
    with sqlite3.connect(str(db_path)) as con:
        cur = con.execute("DELETE FROM shadow_events WHERE ts < ?", (cutoff,))
        return cur.rowcount


def count_records(db_path: str | Path) -> int:
    with sqlite3.connect(str(db_path)) as con:
        row = con.execute("SELECT COUNT(*) FROM shadow_events").fetchone()
        return int(row[0]) if row else 0
