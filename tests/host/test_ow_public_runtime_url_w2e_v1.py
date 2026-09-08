"""Comprehensive Host and Presentation Contract Tests for OW-MULTI-AGENT-BINDING-W2E-V1.

Normative authority:
- TICKET: OW-MULTI-AGENT-BINDING-W2E-V1
- Execution Delta: Central fetch seam, full document reload navigation model,
  fail-closed zero-fetch verification, and A/B isolation.
- ADR-0021 (Multi-Binding Registry Authority)
- ADR-0020 (Runtime Identity Binding & Storage Isolation)
- docs/OW_MULTI_AGENT_BINDING_W2E_IMPL_REPORT.md
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from mind_runtime.binding_registry import (
    BindingDescriptor,
    BindingRegistry,
    BindingRegistryError,
    RegistryFailureCode,
    build_binding_registry,
)
from mind_runtime.runtime_binding import (
    RuntimeBinding,
    RuntimeEnvironment,
)
from observation_window.binding import (
    AssistantMessageSource,
    ObservationBindingCatalog,
    ObservationBindingResolver,
    ObservationContext,
    ProductionObservationBindingResolver,
    ResolvedObservationBinding,
    ScopedBindingError,
    StateSurface,
    TelemetrySource,
)
from observation_window.web.api import build_router
from observation_window.web.runtime import (
    build_ow_app_from_db_dir,
    compose_ow_app,
)

_REPO_ROOT = Path(__file__).parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from tests.host.test_ow_binding_scoped_api_w2d_v1 import (
    _MockStatusProvider,
    _init_sqlite_dbs,
)

_STATIC_DIR = _REPO_ROOT / "src" / "observation_window" / "web" / "static"
_RUNTIME_SCOPE_JS = _STATIC_DIR / "runtime_scope.js"


def _run_node_script(js_code: str) -> dict[str, Any]:
    """Execute a snippet in Node.js requiring runtime_scope.js and return JSON."""
    wrapped = f"""
    const runtimeScope = require({json.dumps(str(_RUNTIME_SCOPE_JS).replace('\\', '/'))});
    (async () => {{
        {js_code}
    }})().catch(err => {{
        console.error(err);
        process.exit(1);
    }});
    """
    proc = subprocess.run(
        ["node", "-e", wrapped],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(proc.stdout.strip())


# ===========================================================================
# 1. PARSER UNIT TESTS (via Node.js)
# ===========================================================================

class TestPageRuntimeParser:
    """Validate parsePageRuntime across all required query cardinality and grammar cases."""

    def test_absent_runtime_returns_legacy(self):
        code = """
        const res = runtimeScope.parsePageRuntime('');
        console.log(JSON.stringify(res));
        """
        res = _run_node_script(code)
        assert res == {"mode": "LEGACY", "bindingId": None}

    def test_absent_runtime_with_other_params_returns_legacy(self):
        code = """
        const res = runtimeScope.parsePageRuntime('?turn_id=123&dim=val');
        console.log(JSON.stringify(res));
        """
        res = _run_node_script(code)
        assert res == {"mode": "LEGACY", "bindingId": None}

    def test_valid_runtime_returns_scoped(self):
        for valid_id in ("agent-a-prod", "agent-b-prod", "experiment-1-lab", "xiyue-prod", "a", "k-1"):
            code = f"""
            const res = runtimeScope.parsePageRuntime('?runtime={valid_id}');
            console.log(JSON.stringify(res));
            """
            res = _run_node_script(code)
            assert res == {"mode": "SCOPED", "bindingId": valid_id}

    def test_empty_runtime_fails_closed_with_empty_reason(self):
        code = """
        const res = runtimeScope.parsePageRuntime('?runtime=');
        console.log(JSON.stringify(res));
        """
        res = _run_node_script(code)
        assert res["mode"] == "INVALID"
        assert res["reason"] == "EMPTY_RUNTIME_SELECTION"

    def test_duplicate_runtime_fails_closed_with_ambiguous_reason(self):
        code = """
        const res = runtimeScope.parsePageRuntime('?runtime=agent-a-prod&runtime=agent-b-prod');
        console.log(JSON.stringify(res));
        """
        res = _run_node_script(code)
        assert res["mode"] == "INVALID"
        assert res["reason"] == "AMBIGUOUS_RUNTIME_SELECTION"

    def test_slash_bearing_runtime_fails_closed(self):
        for slash_id in ("production/agent-a", "lab/experiment-1", "a/b/c"):
            code = f"""
            const res = runtimeScope.parsePageRuntime('?runtime={slash_id}');
            console.log(JSON.stringify(res));
            """
            res = _run_node_script(code)
            assert res["mode"] == "INVALID"
            assert res["reason"] == "MALFORMED_RUNTIME_SELECTION"

    def test_uppercase_and_malformed_grammar_fails_closed(self):
        for bad in ("AgentA", "AGENT-A", "-leading-dash", "bad_underscore", "with space", "a" * 65):
            code = f"""
            const res = runtimeScope.parsePageRuntime('?runtime=' + encodeURIComponent('{bad}'));
            console.log(JSON.stringify(res));
            """
            res = _run_node_script(code)
            assert res["mode"] == "INVALID"
            assert res["reason"] == "MALFORMED_RUNTIME_SELECTION"


# ===========================================================================
# 2. API PATH BUILDER & WITH_RUNTIME TESTS
# ===========================================================================

class TestApiPathAndWithRuntime:
    """Validate apiPath and withRuntime behavior for legacy and scoped modes."""

    def test_api_path_legacy_returns_unmodified(self):
        code = """
        const sel = { mode: 'LEGACY', bindingId: null };
        const p1 = runtimeScope.apiPath(sel, '/api/overview');
        const p2 = runtimeScope.apiPath(sel, '/api/trends?limit=30');
        const p3 = runtimeScope.apiPath(sel, '/api/turns/turn-1/causal');
        console.log(JSON.stringify({ p1, p2, p3 }));
        """
        res = _run_node_script(code)
        assert res["p1"] == "/api/overview"
        assert res["p2"] == "/api/trends?limit=30"
        assert res["p3"] == "/api/turns/turn-1/causal"

    def test_api_path_scoped_maps_to_runtime_bindings(self):
        code = """
        const sel = { mode: 'SCOPED', bindingId: 'agent-a-prod' };
        const p1 = runtimeScope.apiPath(sel, '/api/overview');
        const p2 = runtimeScope.apiPath(sel, '/api/trends?limit=30');
        const p3 = runtimeScope.apiPath(sel, '/api/turns/turn-1/causal');
        const p4 = runtimeScope.apiPath(sel, '/api/live-trace');
        const p5 = runtimeScope.apiPath(sel, '/api/states');
        console.log(JSON.stringify({ p1, p2, p3, p4, p5 }));
        """
        res = _run_node_script(code)
        assert res["p1"] == "/api/runtime-bindings/agent-a-prod/overview"
        assert res["p2"] == "/api/runtime-bindings/agent-a-prod/trends?limit=30"
        assert res["p3"] == "/api/runtime-bindings/agent-a-prod/turns/turn-1/causal"
        assert res["p4"] == "/api/runtime-bindings/agent-a-prod/live-trace"
        assert res["p5"] == "/api/runtime-bindings/agent-a-prod/states"

    def test_api_path_invalid_throws(self):
        code = """
        const sel = { mode: 'INVALID', reason: 'AMBIGUOUS_RUNTIME_SELECTION' };
        let threw = false;
        try {
            runtimeScope.apiPath(sel, '/api/overview');
        } catch (e) {
            threw = true;
        }
        console.log(JSON.stringify({ threw }));
        """
        res = _run_node_script(code)
        assert res["threw"] is True

    def test_with_runtime_preserves_existing_query_params(self):
        code = """
        const sel = { mode: 'SCOPED', bindingId: 'agent-a-prod' };
        const u1 = runtimeScope.withRuntime('/debug/causal?turn_id=123', sel);
        const u2 = runtimeScope.withRuntime('/moments?before=cursor456&limit=20', sel);
        const u3 = runtimeScope.withRuntime('/#section', sel);
        console.log(JSON.stringify({ u1, u2, u3 }));
        """
        res = _run_node_script(code)
        assert "runtime=agent-a-prod" in res["u1"]
        assert "turn_id=123" in res["u1"]
        assert "runtime=agent-a-prod" in res["u2"]
        assert "before=cursor456" in res["u2"]
        assert "runtime=agent-a-prod" in res["u3"]
        assert "#section" in res["u3"]

    def test_with_runtime_legacy_returns_unmodified(self):
        code = """
        const sel = { mode: 'LEGACY', bindingId: null };
        const u1 = runtimeScope.withRuntime('/debug/causal?turn_id=123', sel);
        console.log(JSON.stringify({ u1 }));
        """
        res = _run_node_script(code)
        assert res["u1"] == "/debug/causal?turn_id=123"


# ===========================================================================
# 3. CENTRAL FETCH SEAM & RESPONSE ASSERTION TESTS
# ===========================================================================

class TestRuntimeFetchSeam:
    """Validate central runtimeFetch behavior, zero-fetch on invalid, and identity mismatch."""

    def test_invalid_selection_issues_zero_fetches(self):
        code = """
        let fetchCount = 0;
        global.fetch = async () => { fetchCount++; return { ok: true }; };
        const sel = { mode: 'INVALID', reason: 'EMPTY_RUNTIME_SELECTION', detail: 'Empty' };
        let threw = false;
        let code = '';
        try {
            await runtimeScope.runtimeFetch(sel, '/api/overview');
        } catch (e) {
            threw = true;
            code = e.code;
        }
        console.log(JSON.stringify({ threw, code, fetchCount }));
        """
        res = _run_node_script(code)
        assert res["threw"] is True
        assert res["code"] == "INVALID_RUNTIME_SELECTION"
        assert res["fetchCount"] == 0, "MUST issue zero fetches on INVALID selection!"

    def test_response_binding_id_match_succeeds(self):
        code = """
        const sel = { mode: 'SCOPED', bindingId: 'agent-a-prod' };
        global.fetch = async (url) => {
            return {
                ok: true,
                status: 200,
                json: async () => ({ binding_id: 'agent-a-prod', payload: 'ok' })
            };
        };
        const data = await runtimeScope.runtimeFetch(sel, '/api/overview');
        console.log(JSON.stringify({ ok: true, data }));
        """
        res = _run_node_script(code)
        assert res["ok"] is True
        assert res["data"]["binding_id"] == "agent-a-prod"

    def test_response_binding_id_mismatch_fails_closed(self):
        code = """
        const sel = { mode: 'SCOPED', bindingId: 'agent-a-prod' };
        global.fetch = async (url) => {
            return {
                ok: true,
                status: 200,
                json: async () => ({ binding_id: 'agent-b-prod', payload: 'wrong' })
            };
        };
        let threw = false;
        let errCode = '';
        try {
            await runtimeScope.runtimeFetch(sel, '/api/overview');
        } catch (e) {
            threw = true;
            errCode = e.code;
        }
        console.log(JSON.stringify({ threw, errCode }));
        """
        res = _run_node_script(code)
        assert res["threw"] is True
        assert res["errCode"] == "RUNTIME_IDENTITY_MISMATCH"

    def test_http_404_translated_to_unknown_binding(self):
        code = """
        const sel = { mode: 'SCOPED', bindingId: 'not-real' };
        global.fetch = async () => ({
            ok: false,
            status: 404,
            json: async () => ({ detail: 'UNKNOWN_BINDING' })
        });
        let threw = false;
        let errCode = '';
        try {
            await runtimeScope.runtimeFetch(sel, '/api/overview');
        } catch (e) {
            threw = true;
            errCode = e.code;
        }
        console.log(JSON.stringify({ threw, errCode }));
        """
        res = _run_node_script(code)
        assert res["threw"] is True
        assert res["errCode"] == "UNKNOWN_BINDING"

    def test_http_503_translated_to_registry_or_binding_unavailable(self):
        code = """
        const sel = { mode: 'SCOPED', bindingId: 'agent-a-prod' };
        global.fetch = async () => ({
            ok: false,
            status: 503,
            json: async () => ({ detail: 'BINDING_REGISTRY_UNAVAILABLE' })
        });
        let threw = false;
        let errCode = '';
        try {
            await runtimeScope.runtimeFetch(sel, '/api/overview');
        } catch (e) {
            threw = true;
            errCode = e.code;
        }
        console.log(JSON.stringify({ threw, errCode }));
        """
        res = _run_node_script(code)
        assert res["threw"] is True
        assert res["errCode"] == "BINDING_REGISTRY_UNAVAILABLE"


# ===========================================================================
# 4. PUBLIC PAGE ROUTE CONTRACT & DOM BOOTSTRAP (TestClient)
# ===========================================================================

class TestPublicPageRoutesContract:
    """Validate that all public product routes return HTML containing runtime_scope.js and indicator."""

    @pytest.fixture
    def client(self, tmp_path: Path) -> TestClient:
        app, _ = build_ow_app_from_db_dir(tmp_path)
        return TestClient(app)

    @pytest.mark.parametrize("route", [
        "/",
        "/overview",
        "/state",
        "/moments",
        "/timeline",
        "/debug/causal",
        "/causal",
        "/debug/ledger",
        "/history",
        "/debug/live-trace",
        "/debug/runtime",
        "/live-trace",
        "/live",
    ])
    def test_all_public_page_routes_serve_html_with_runtime_scope_script(self, client: TestClient, route: str):
        res = client.get(route)
        assert res.status_code == 200
        assert "text/html" in res.headers["content-type"]
        html = res.text
        assert '<script src="/static/runtime_scope.js"></script>' in html, f"Missing runtime_scope.js in {route}"
        assert 'id="runtime-indicator"' in html, f"Missing #runtime-indicator in {route}"

    def test_static_runtime_scope_js_is_served(self, client: TestClient):
        res = client.get("/static/runtime_scope.js")
        assert res.status_code == 200
        assert "parsePageRuntime" in res.text
        assert "runtimeFetch" in res.text
        assert "withRuntime" in res.text
        assert "assertResponseBinding" in res.text


# ===========================================================================
# 5. A/B DATA ISOLATION & ZERO UNSCOPED CALLS
# ===========================================================================

class TestABVisualDataIsolation:
    """Prove that agent-a-prod and agent-b-prod load distinct data with zero cross-leakage."""

    @pytest.fixture
    def multi_binding_client(self, tmp_path: Path) -> tuple[TestClient, str, str]:
        reg_dir = tmp_path / "registry"
        reg = build_binding_registry(reg_dir)
        reg.writer.initialize()

        prod_root = tmp_path / "prod_root"

        binding_a = RuntimeBinding(
            persona_id="kayla_v0",
            agent_id="hermes-agent-a",
            runtime_id="runtime-a",
            storage_namespace="production/agent-a",
            environment=RuntimeEnvironment.PRODUCTION,
        )
        binding_b = RuntimeBinding(
            persona_id="kayla_v0",
            agent_id="hermes-agent-b",
            runtime_id="runtime-b",
            storage_namespace="production/agent-b",
            environment=RuntimeEnvironment.PRODUCTION,
        )
        reg.writer.register(binding_a, "agent-a-prod")
        reg.writer.register(binding_b, "agent-b-prod")

        paths_a = prod_root / "production" / "agent-a"
        paths_b = prod_root / "production" / "agent-b"

        _init_sqlite_dbs(paths_a, interaction_id="turn-a", value=0.85, prompt="Hello A", reply="Reply from A")
        _init_sqlite_dbs(paths_b, interaction_id="turn-b", value=0.20, prompt="Hello B", reply="Reply from B")

        class TestResolver:
            def resolve(self, b: RuntimeBinding) -> ResolvedObservationBinding:
                root = prod_root / b.storage_namespace
                return ResolvedObservationBinding(
                    runtime_binding=b,
                    binding_scope_key=f"{b.environment.value}:{b.storage_namespace}",
                    state_surface=StateSurface(fast_dimensions=("agent.affect.irritation",)),
                    facts_db=root / "facts.sqlite",
                    state_db=root / "cognition_state.sqlite",
                    telemetry_source=TelemetrySource(db_path=root / "observation_trace.sqlite"),
                    assistant_message_source=AssistantMessageSource(db_path=root.parent / "state.db"),
                    runtime_status_provider=_MockStatusProvider(),
                    runtime_dir=root,
                )

        resolver = TestResolver()
        catalog = ObservationBindingCatalog(
            reader=reg.reader,
            environment=RuntimeEnvironment.PRODUCTION,
            resolver=resolver,
        )
        resolved_a = resolver.resolve(binding_a)
        app, _ = compose_ow_app(resolved_a, catalog=catalog)
        return TestClient(app), "agent-a-prod", "agent-b-prod"

    def test_ab_overview_isolation(self, multi_binding_client):
        client, id_a, id_b = multi_binding_client

        res_a = client.get(f"/api/runtime-bindings/{id_a}/overview")
        assert res_a.status_code == 200
        data_a = res_a.json()
        assert data_a["binding_id"] == id_a

        res_b = client.get(f"/api/runtime-bindings/{id_b}/overview")
        assert res_b.status_code == 200
        data_b = res_b.json()
        assert data_b["binding_id"] == id_b

        assert data_a["binding_id"] != data_b["binding_id"]

    def test_ab_states_isolation(self, multi_binding_client):
        client, id_a, id_b = multi_binding_client

        res_a = client.get(f"/api/runtime-bindings/{id_a}/states")
        assert res_a.status_code == 200
        states_a = {s["dimension"]: float(s["value"]) for s in res_a.json()["states"]}

        res_b = client.get(f"/api/runtime-bindings/{id_b}/states")
        assert res_b.status_code == 200
        states_b = {s["dimension"]: float(s["value"]) for s in res_b.json()["states"]}

        assert states_a.get("agent.affect.irritation") == 0.85
        assert states_b.get("agent.affect.irritation") == 0.20

    def test_unknown_runtime_returns_404_no_fallback(self, multi_binding_client):
        client, _, _ = multi_binding_client
        res = client.get("/api/runtime-bindings/not-real/overview")
        assert res.status_code == 404
        assert res.json()["code"] == "UNKNOWN_BINDING"


# ===========================================================================
# 6. SOURCE SCAN & HYGIENE
# ===========================================================================

class TestSourceHygieneW2E:
    """Verify clean presentation boundary, zero hardcoded Xiyue defaults, and no storage_namespace in URL logic."""

    def test_no_storage_namespace_as_public_identity(self):
        js_text = _RUNTIME_SCOPE_JS.read_text(encoding="utf-8")
        assert "storage_namespace" not in js_text
        assert "production/" not in js_text
        assert "lab/" not in js_text

    def test_no_hardcoded_xiyue_default(self):
        js_text = _RUNTIME_SCOPE_JS.read_text(encoding="utf-8")
        assert "xiyue" not in js_text.lower()
        assert "hermes" not in js_text.lower()

    def test_no_localstorage_or_sessionstorage_authority(self):
        js_text = _RUNTIME_SCOPE_JS.read_text(encoding="utf-8")
        assert "localStorage" not in js_text
        assert "sessionStorage" not in js_text

    def test_all_five_html_pages_include_runtime_scope_and_indicator(self):
        pages = ["state.html", "moments.html", "causal.html", "ledger.html", "live_trace.html"]
        for page in pages:
            text = (_STATIC_DIR / page).read_text(encoding="utf-8")
            assert '<script src="/static/runtime_scope.js"></script>' in text, f"{page} missing runtime_scope.js"
            assert 'id="runtime-indicator"' in text, f"{page} missing runtime-indicator"
            assert "OWRuntimeScope.parsePageRuntime" in text, f"{page} missing parsePageRuntime"
            assert "OWRuntimeScope.runtimeFetch" in text, f"{page} missing runtimeFetch"
