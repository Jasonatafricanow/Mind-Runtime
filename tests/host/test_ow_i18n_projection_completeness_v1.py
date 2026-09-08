"""Tests for OW-I18N-PROJECTION-COMPLETENESS-V1.

Guarantees every user-visible non-raw value flows through the central
zh-CN display projection:

1. Reason projection (displayReason): known reasons map to Chinese primary,
   unknown reasons fail safe to the raw value.
2. Provenance projection (displayProvenance): CANONICAL/OBSERVER/UNAVAILABLE
   map to 权威/观察遥测/不可用 with DB filenames untranslated.
3. Status vocabulary covers the live status set (§7).
4. Banned primary-display strings (§11) do not leak into page markup outside
   explicitly-allowed contexts (raw secondary via title=, canonical keys,
   comparisons, dictionaries, comments).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from observation_window.web.runtime import build_ow_app_from_db_dir

_STATIC_DIR = Path(__file__).parents[2] / "src" / "observation_window" / "web" / "static"
_PAGES = ("state.html", "moments.html", "causal.html", "ledger.html", "live_trace.html")


@pytest.fixture
def proj_test_client(tmp_path: Path) -> TestClient:
    app, _ = build_ow_app_from_db_dir(tmp_path)
    return TestClient(app)


def _display_js() -> str:
    return (_STATIC_DIR / "display_zh.js").read_text(encoding="utf-8")


def test_reason_projection_exists_and_fail_safe():
    js = _display_js()
    assert "displayReason" in js
    assert "语义结果未持久化到可回溯存储" in js
    assert "评估详情未持久化到可回溯存储" in js
    assert "历史轮次" in js
    # Unknown reasons must fall back to the raw value (never guessed).
    lookup_body = js[js.find("function lookup"):js.find("function lookup") + 300]
    assert "? map[key] : value" in lookup_body


def test_provenance_projection_exists():
    js = _display_js()
    assert "displayProvenance" in js
    assert "权威事实 · facts.sqlite" in js
    assert "权威状态 · cognition_state.sqlite" in js
    assert "观察遥测" in js


def test_status_vocabulary_covers_live_set():
    status_block = _display_js()[_display_js().find("var STATUS"):_display_js().find("var STAGES")]
    for raw, zh in (
        ("AVAILABLE", "可用"), ("UNAVAILABLE", "不可用"), ("NOT PERSISTED", "未持久化"),
        ("ACCEPTED", "已接受"), ("PROPOSED", "已提议"), ("EXECUTED", "已执行"),
        ("COMMITTED", "已提交"), ("ABORTED", "已中止"), ("REJECTED", "已拒绝"),
        ("ABSTAINED", "已弃权"), ("UNKNOWN", "未知"),
        ("PASS", "通过"), ("PRESENT", "已持久化"), ("ON", "开启"), ("OFF", "关闭"),
    ):
        assert f'"{raw}": "{zh}"' in status_block, raw


def test_no_banned_primary_display_strings_in_pages():
    """§11 audit: banned English must not appear as primary visible copy.

    Allowed contexts per occurrence line:
    - raw secondary: title= / title' / title" attributes
    - canonical keys: agent.affect. / longitudinal
    - non-display code: comparisons (===, !==), dictionary lookups, .slice/.split
    - secondary raw styling span (mono dim), HTML comments, <title> tag
    """
    banned = [
        "irritation", "no delta", "UNAVAILABLE / NOT PERSISTED", "not established",
        "BEFORE", "PROPOSED TARGET", "HOMEOSTASIS DISPOSITION", "AFTER",
        "Human Causal Trace",
    ]
    allow_tokens = (
        "title=", "title'", 'title"',
        "agent.affect.", "longitudinal",
        "=== '", "!== '", "indexOf(", "startsWith(",
        "displayStatus(", "displayReason(", "displayProvenance(", "displayDimension",
        "reasonPair", ".slice(", ".split(",
        "mono dim",
        "REASONS", "STATUS:", "DIMENSIONS",
    )
    for page in _PAGES:
        raw = (_STATIC_DIR / page).read_text(encoding="utf-8")
        raw = re.sub(r"<title>.*?</title>", "", raw, flags=re.S)
        for line_no, line in enumerate(raw.splitlines(), 1):
            if "<!--" in line or "//" in line or "/*" in line:
                continue
            for banned_str in banned:
                if banned_str in line:
                    assert any(tok in line for tok in allow_tokens), (
                        f"{page}:{line_no} leaks banned primary display string "
                        f"{banned_str!r}: {line.strip()[:120]}"
                    )


def test_causal_renders_chinese_stage_badges(proj_test_client: TestClient):
    """Causal page carries the zh-primary pattern with raw kept as title."""
    res = proj_test_client.get("/debug/causal")
    assert res.status_code == 200
    html = res.text
    assert "1. 用户输入" in html
    assert 'title="USER INPUT"' in html
    assert "不可用 / 未持久化" in html
    assert ">BEFORE<" not in html and "变化前" in html
    assert ">AFTER<" not in html and "变化后" in html


def test_state_uses_frozen_authoritative_vocabulary(proj_test_client: TestClient):
    """Product surfaces use 权威 as the single frozen word for canonical."""
    res = proj_test_client.get("/")
    assert res.status_code == 200
    assert "权威快状态" in res.text
    assert "权威慢状态" in res.text
    assert "关系安全感" in res.text
    assert "Canonical Fast Affect" not in res.text
    assert "Relationship Security" not in res.text
