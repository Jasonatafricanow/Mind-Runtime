"""Phase 3 URL-authoritative runtime selector tests."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from urllib.parse import parse_qs

import pytest


_REPO_ROOT = Path(__file__).parents[2]
_STATIC_DIR = _REPO_ROOT / "src" / "observation_window" / "web" / "static"
_SELECTOR_JS = _STATIC_DIR / "runtime_selector.js"


def _run_node(js_code: str):
    wrapped = f"""
    const selector = require({json.dumps(str(_SELECTOR_JS).replace('\\', '/'))});
    (async () => {{
      {js_code}
    }})().catch(err => {{ console.error(err); process.exit(1); }});
    """
    result = subprocess.run(
        ["node", "-e", wrapped], capture_output=True, text=True, check=True
    )
    return json.loads(result.stdout.strip())


def test_switch_url_sets_runtime_and_clears_binding_dependent_state():
    result = _run_node(
        """
        const url = selector.switchUrl(
          '/moments?runtime=agent-a-prod&interaction_id=ix-a&turn_id=turn-a&dimension=irritation&limit=20&layout=compact#top',
          'agent-b-prod'
        );
        console.log(JSON.stringify(url));
        """
    )
    assert parse_qs(result.split("?", 1)[1].split("#", 1)[0]) == {
        "limit": ["20"],
        "layout": ["compact"],
        "runtime": ["agent-b-prod"],
    }
    assert result.endswith("#top")


def test_catalog_projection_uses_production_descriptors_and_binding_id():
    result = _run_node(
        """
        console.log(JSON.stringify(selector.projectCatalog({bindings: [
          {binding_id: 'agent-a-prod', environment: 'PRODUCTION'},
          {binding_id: 'experiment-1-lab', environment: 'LAB'},
          {binding_id: 'agent-b-prod', environment: 'PRODUCTION'}
        ]})));
        """
    )
    assert result == ["agent-a-prod", "agent-b-prod"]


def test_selector_options_keep_current_binding_selected():
    result = _run_node(
        """
        console.log(JSON.stringify(selector.optionModel(
          ['agent-a-prod', 'agent-b-prod'],
          {mode: 'SCOPED', bindingId: 'agent-b-prod'}
        )));
        """
    )
    assert result == [
        {"value": "agent-a-prod", "label": "agent-a-prod", "disabled": False, "selected": False},
        {"value": "agent-b-prod", "label": "agent-b-prod", "disabled": False, "selected": True},
    ]


def test_invalid_runtime_bootstrap_does_not_fetch_catalog():
    result = _run_node(
        """
        let calls = 0;
        global.fetch = () => { calls += 1; throw new Error('must not fetch'); };
        await selector.bootstrap({mode: 'INVALID', reason: 'EMPTY_RUNTIME_SELECTION'}, {
          container: null
        });
        console.log(JSON.stringify({calls}));
        """
    )
    assert result == {"calls": 0}


def test_selector_is_shared_by_all_five_canonical_pages():
    pages = ["state.html", "moments.html", "causal.html", "ledger.html", "live_trace.html"]
    for page in pages:
        html = (_STATIC_DIR / page).read_text(encoding="utf-8")
        assert '<script src="/static/runtime_selector.js"></script>' in html
        assert 'id="runtime-selector"' in html
        assert "OWRuntimeSelector.bootstrap(runtimeSelection)" in html


def test_selector_has_no_local_persistence_or_polling():
    source = _SELECTOR_JS.read_text(encoding="utf-8")
    assert "localStorage" not in source
    assert "sessionStorage" not in source
    assert "setInterval" not in source
    assert "runtimeFetch" not in source
    assert "location.assign" in source


def test_selector_label_uses_existing_i18n_seam():
    display = (_STATIC_DIR / "display_zh.js").read_text(encoding="utf-8")
    source = _SELECTOR_JS.read_text(encoding="utf-8")
    assert '"runtimeSelector": "Runtime / 运行时"' in display
    assert 'displayLabel("runtimeSelector")' in source
