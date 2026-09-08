"""Tests for OW-RESPONSIVE-I18N-ZH-V1.

Chinese display layer + multi-screen responsive contracts:
1. Central display dictionary exists with the canonical vocabulary.
2. Mapping is display-only: canonical keys remain in product pages.
3. Unknown canonical values fail safe (fallback-to-raw pattern).
4. Product UI primary labels are Chinese.
5. Five-tier mobile breakpoints exist in the shared stylesheet.
6. No page-level fixed minimum width forcing desktop layout.
7. Causal mobile recomposition breakpoint exists.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from observation_window.web.runtime import build_ow_app_from_db_dir

_STATIC_DIR = Path(__file__).parents[2] / "src" / "observation_window" / "web" / "static"


@pytest.fixture
def i18n_test_client(tmp_path: Path) -> TestClient:
    app, _ = build_ow_app_from_db_dir(tmp_path)
    return TestClient(app)


def _display_js() -> str:
    return (_STATIC_DIR / "display_zh.js").read_text(encoding="utf-8")


def test_zh_display_dictionary_exists():
    js = _display_js()
    assert "OWDisplay" in js
    for fn in ("displayDimension", "displayOrigin", "displayStatus", "displayStage",
               "displayDisposition", "displayScope", "displayEventKind", "displayLabel",
               "fmtTime"):
        assert fn in js


def test_canonical_dimension_mapping_present_and_display_only():
    js = _display_js()
    for canonical, zh in (
        ("agent.affect.irritation", "烦躁"),
        ("agent.affect.anxiety", "焦虑"),
        ("agent.affect.excitement", "兴奋"),
        ("agent.affect.longing", "思念"),
        ("agent.longitudinal.relationship_security", "关系安全感"),
    ):
        assert f'"{canonical}": "{zh}"' in js
    # Origin vocabulary
    assert '"DYNAMICS / RECOVERY": "动态恢复"' in js
    assert '"EVENT EFFECT": "事件效应"' in js
    assert '"UNCHANGED": "未变化"' in js
    # Canonical keys live in the dictionary (display) and the Xiyue binding
    # adapter's declared state_surface (membership) — NOT in generic pages
    # (OW-MULTI-AGENT-BINDING-PHASE01-V1: descriptor-driven State UI).
    for canonical in ("agent.affect.irritation", "agent.affect.anxiety",
                      "agent.affect.excitement", "agent.affect.longing",
                      "agent.longitudinal.relationship_security"):
        assert canonical in js
    xiyue_adapter = (_STATIC_DIR.parent.parent / "binding_xiyue.py").read_text(encoding="utf-8")
    for canonical in ("agent.affect.irritation", "agent.longitudinal.relationship_security"):
        assert canonical in xiyue_adapter
    state_html = (_STATIC_DIR / "state.html").read_text(encoding="utf-8")
    for canonical in ("agent.affect.irritation", "agent.affect.anxiety",
                      "agent.affect.excitement", "agent.affect.longing",
                      "agent.longitudinal.relationship_security"):
        assert canonical not in state_html


def test_unknown_canonical_value_falls_back_to_raw():
    js = _display_js()
    # Every display function routes through lookup(), which returns the raw
    # value when the key is absent from the map.
    assert "function lookup(map, value)" in js
    assert "hasOwnProperty.call(map, key) ? map[key] : value" in js
    # No display function can return blank for unknown input.
    assert "return ''" not in js.split("function lookup")[1].split("}")[0]


def test_product_ui_primary_labels_chinese():
    state_html = (_STATIC_DIR / "state.html").read_text(encoding="utf-8")
    assert "状态" in state_html
    assert "动态时序" in state_html
    assert "关键轮次" in state_html
    assert "长期状态" in state_html
    assert "已提交轮次" in state_html
    assert "最近轮次" in state_html
    assert "单维度" in state_html
    assert "对比" in state_html
    assert "查看因果链" in state_html
    assert "尚未建立" in state_html
    # Product page includes the shared display vocabulary module.
    assert '/static/display_zh.js' in state_html
    moments_html = (_STATIC_DIR / "moments.html").read_text(encoding="utf-8")
    assert "交互记录" in moments_html
    assert "已中止" in moments_html


def test_mobile_breakpoints_exist():
    css = (_STATIC_DIR / "style.css").read_text(encoding="utf-8")
    # §9 tiers: laptop/tablet boundary 1023, phone boundary 767, small phone 480
    assert "max-width: 1439px" in css
    assert "max-width: 1023px" in css
    assert "max-width: 767px" in css
    assert "max-width: 480px" in css
    # §12: phone chart height bounded 200-220px
    assert "--chart-height: 210px" in css


def test_no_page_level_fixed_minimum_width():
    css = (_STATIC_DIR / "style.css").read_text(encoding="utf-8")
    # Any min-width at or above ~700px would force a desktop layout on phone.
    for match in re.finditer(r"min-width:\s*(\d+)px", css):
        assert int(match.group(1)) < 700, match.group(0)


def test_causal_mobile_layout_breakpoint_exists():
    causal_html = (_STATIC_DIR / "causal.html").read_text(encoding="utf-8")
    assert "max-width: 767px" in causal_html
    assert "flex-direction: column" in causal_html


def test_product_routes_serve_zh_pages(i18n_test_client: TestClient):
    for route, expected in (("/", "动态时序"), ("/moments", "交互记录"), ("/debug/causal", "因果检查器")):
        res = i18n_test_client.get(route)
        assert res.status_code == 200, route
        assert expected in res.text, route
