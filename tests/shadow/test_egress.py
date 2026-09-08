"""C1 fail-closed egress tests (P1-P6 seams).

Contract under test: PrivateRecord -> EgressPolicy -> SanitizedProjection
(ADR-0011). The canonical store is read-only to this boundary and never
mutated by sanitization.
"""

from __future__ import annotations

import dataclasses
import json
import sqlite3
from pathlib import Path

import pytest

from mind_runtime.shadow.egress import (
    POLICY_VERSION,
    EgressLeakError,
    sanitize_record,
)
from mind_runtime.shadow.redaction import hash_id, init_store

KNOWN_NAMES = ("嘉森", "嘻嘻", "老婆")

# Shape-valid but obviously synthetic fixtures; never real credentials.
_AWS_LIKE = "AKIA" + "Q" * 16
_GH_LIKE = "ghp_" + "a1B" * 8
_SK_LIKE = "sk-proj-abcdef1234567890ab"


def _seed_event(db: Path, content_id: int, text: str) -> None:
    init_store(db)
    with sqlite3.connect(str(db)) as con:
        con.execute(
            "INSERT INTO shadow_events "
            "(content_id, ts, user_hash, session_hash, channel, sender, "
            "trigger, source_domain, redacted_text) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (
                content_id,
                "2026-08-27T10:00:00+00:00",
                hash_id("u"),
                hash_id("s"),
                "telegram",
                "user",
                "message",
                "kayla_persona",
                text,
            ),
        )


def _read_row(db: Path, content_id: int) -> str:
    with sqlite3.connect(str(db)) as con:
        row = con.execute(
            "SELECT redacted_text FROM shadow_events WHERE content_id=?", (content_id,)
        ).fetchone()
    assert row is not None
    return str(row[0])


def test_p2_otp_like_pin_refuses_egress_entirely() -> None:
    """Ambiguous OTP material can never be emitted under the policy."""
    with pytest.raises(EgressLeakError) as leaked:
        sanitize_record("验证码123456已过期", record_id="x", source_type="shadow_event")
    assert leaked.value.labels == ("pin",)


@pytest.mark.parametrize(
    ("secret", "label"),
    [
        pytest.param("13812345678", "phone", id="phone"),
        pytest.param(_SK_LIKE, "token", id="openai-shape"),
        pytest.param(_GH_LIKE, "token", id="github-pat"),
        pytest.param(_AWS_LIKE, "token", id="aws-key"),
        pytest.param(f"apikey: {_GH_LIKE[4:]}x9", "token", id="assignment"),
    ],
)
def test_p4_no_secret_crosses_the_boundary(secret: str, label: str) -> None:
    message = f"老婆提醒我更新{secret}"
    projection = sanitize_record(
        message, record_id="p4", source_type="shadow_event", known_names=KNOWN_NAMES
    )
    payload = json.dumps(dataclasses.asdict(projection), ensure_ascii=False)
    # neither the secret nor the protected person terms appear anywhere
    assert secret not in payload
    assert "老婆" not in payload
    assert label in projection.redactions


def test_p3_export_copy_does_not_mutate_canonical_source(tmp_path: Path) -> None:
    db = tmp_path / "shadow.db"
    _seed_event(db, 11, "嘉森的电话13812345678")
    before = _read_row(db, 11)

    projection = sanitize_record(
        before,
        record_id="11",
        source_type="shadow_event",
        scope="telegram",
        known_names=KNOWN_NAMES,
    )
    assert "<person:" in projection.text
    assert "[PHONE]" in projection.text

    # canonical row re-read after export: unchanged, still private-canonical
    assert _read_row(db, 11) == before == "嘉森的电话13812345678"


def test_p5_sanitization_is_idempotent() -> None:
    raw = f"嘻嘻找嘉森拿了{_SK_LIKE}登录13812345678"
    once = sanitize_record(raw, record_id="r", source_type="t", known_names=KNOWN_NAMES)
    twice = sanitize_record(once.text, record_id="r", source_type="t", known_names=KNOWN_NAMES)
    # re-projecting a sanitized copy neither changes the artifact nor finds
    # anything new to destroy: text/tokens are stable and the audit trail of
    # the FIRST pass is the authoritative one
    assert twice.text == once.text
    assert twice.redactions == ()
    assert twice.policy_version == POLICY_VERSION


def test_p6_provenance_locates_source_without_leaking(tmp_path: Path) -> None:
    db = tmp_path / "shadow.db"
    _seed_event(db, 77, "老婆的手机13812345678")
    canonical = _read_row(db, 77)

    projection = sanitize_record(
        canonical,
        record_id="77",
        source_type="shadow_event",
        source_ts="2026-08-27T10:00:00+00:00",
        scope="telegram",
        known_names=KNOWN_NAMES,
    )
    payload = json.dumps(dataclasses.asdict(projection), ensure_ascii=False)
    # auditable: source record id/type/ts/scope + policy version travel along,
    # and the auditor can still find THIS canonical row by record id
    assert projection.record_id == "77"
    assert projection.source_type == "shadow_event"
    assert projection.source_ts == "2026-08-27T10:00:00+00:00"
    assert projection.scope == "telegram"
    assert projection.policy_version == POLICY_VERSION
    assert _read_row(db, 77) == canonical
    # ...but not reversible leaking: no secret values, no person semantics
    for forbidden in ("老婆", "嘉森", "13812345678"):
        assert forbidden not in payload
    assert "person" in projection.redactions
    assert "phone" in projection.redactions
