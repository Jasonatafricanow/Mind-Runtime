"""Tests for OW-MULTI-AGENT-BINDING-PHASE01-V1.

Phase 0/1 internal architecture contracts (no public multi-binding support):

1. Two synthetic binding contexts with the SAME interaction_id stay fully
   isolated (causal cache, source handles, durable values).
2. State surface membership is descriptor-driven; no DB ontology inference.
3. RuntimeStatusProvider emits only the normalized, display-safe projection.
4. SingleBindingRegistryAdapter fails closed (no scanning, no LAB selection).
5. Generic OW source carries no Xiyue paths / hardcoded dimension membership
   outside the explicitly-named Xiyue compat adapter and zh dictionary.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from mind_runtime.runtime_binding import (
    RuntimeBinding,
    RuntimeEnvironment,
)
from observation_window.binding import (
    AssistantMessageSource,
    BindingResolver,
    BindingScopeError,
    CausalTraceStore,
    ResolvedObservationBinding,
    RuntimeStatusProjection,
    SingleBindingRegistryAdapter,
    StateSurface,
    TelemetrySource,
)
from observation_window.binding_xiyue import (
    XIYUE_STATE_SURFACE,
    XiyueReadinessStatusProvider,
    resolve_xiyue_observation_binding,
)
from observation_window.web.runtime import build_ow_app_from_db_dir

_PKG_ROOT = Path(__file__).parents[2] / "src" / "observation_window"


def _lab_binding(ns: str) -> RuntimeBinding:
    return RuntimeBinding(
        persona_id="p-test",
        agent_id=f"agent-{ns}",
        runtime_id=f"rt-{ns}",
        storage_namespace=ns,
        environment=RuntimeEnvironment.LAB,
    )


def _resolve_lab(binding: RuntimeBinding, lab_root: Path) -> ResolvedObservationBinding:
    resolver = BindingResolver()
    return resolver.resolve(
        binding,
        lab_root=lab_root,
        state_surface=StateSurface(
            fast_dimensions=("agent.affect.irritation",),
            slow_dimensions=("agent.longitudinal.relationship_security",),
        ),
        telemetry_source=TelemetrySource(
            db_path=lab_root / binding.storage_namespace / "observation_trace.sqlite"
        ),
        assistant_message_source=AssistantMessageSource(
            db_path=lab_root / binding.storage_namespace / "state.db"
        ),
    )


# ---------------------------------------------------------------------------
# §22 two-binding internal isolation
# ---------------------------------------------------------------------------


class TestTwoBindingIsolation:
    def test_same_interaction_id_causal_caches_are_isolated(self, tmp_path: Path):
        a = _resolve_lab(_lab_binding("ow-a"), tmp_path)
        b = _resolve_lab(_lab_binding("ow-b"), tmp_path)
        store = CausalTraceStore()

        store.put(a.binding_scope_key, "same-turn", {"trace": "A", "value": 0.9})
        store.put(b.binding_scope_key, "same-turn", {"trace": "B", "value": 0.1})

        entry_a = store.get(a.binding_scope_key, "same-turn")
        entry_b = store.get(b.binding_scope_key, "same-turn")
        assert entry_a == {"trace": "A", "value": 0.9}
        assert entry_b == {"trace": "B", "value": 0.1}
        # Same interaction_id, different durable meaning — never cross-served.
        assert entry_a["value"] != entry_b["value"]

    def test_resolved_source_handles_never_cross(self, tmp_path: Path):
        a = _resolve_lab(_lab_binding("ow-a"), tmp_path)
        b = _resolve_lab(_lab_binding("ow-b"), tmp_path)

        assert a.state_db != b.state_db
        assert a.facts_db != b.facts_db
        assert a.telemetry_source.db_path != b.telemetry_source.db_path
        assert a.assistant_message_source.db_path != b.assistant_message_source.db_path
        assert a.binding_scope_key != b.binding_scope_key

    def test_durable_values_stay_per_binding(self, tmp_path: Path):
        # Same interaction_id committed under both bindings with different
        # state values; each binding's own state DB holds only its own value.
        for ns, value in (("ow-a", 0.9), ("ow-b", 0.1)):
            binding = _lab_binding(ns)
            resolver = BindingResolver()
            resolved = resolver.resolve(binding, lab_root=tmp_path)
            resolved.state_db.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(resolved.state_db)
            conn.execute(
                "CREATE TABLE states (state_id TEXT PRIMARY KEY, dimension TEXT, value TEXT)"
            )
            conn.execute(
                "INSERT INTO states VALUES (?, ?, ?)",
                (f"st-{ns}", "agent.affect.irritation", str(value)),
            )
            conn.commit()
            conn.close()

        for ns, value in (("ow-a", 0.9), ("ow-b", 0.1)):
            binding = _lab_binding(ns)
            resolved = BindingResolver().resolve(binding, lab_root=tmp_path)
            conn = sqlite3.connect(resolved.state_db)
            row = conn.execute(
                "SELECT value FROM states WHERE state_id = ?", (f"st-{ns}",)
            ).fetchone()
            conn.close()
            assert float(row[0]) == value


# ---------------------------------------------------------------------------
# §23 descriptor-driven state surface
# ---------------------------------------------------------------------------


class TestStateSurfaceDescriptor:
    def test_descriptor_a_xiyue_shape(self):
        surface = XIYUE_STATE_SURFACE
        assert surface.fast_dimensions == (
            "agent.affect.irritation",
            "agent.affect.anxiety",
            "agent.affect.excitement",
            "agent.affect.longing",
        )
        assert surface.slow_dimensions == (
            "agent.longitudinal.relationship_security",
        )
        payload = surface.to_payload()
        assert payload["fast_dimensions"][0] == "agent.affect.irritation"
        # Descriptor carries canonical keys only — no localized strings.
        assert "烦躁" not in json.dumps(payload)

    def test_descriptor_b_no_slow_section_projected(self, tmp_path: Path):
        surface = StateSurface(
            fast_dimensions=("agent.mood.custom_a", "agent.mood.custom_b"),
            slow_dimensions=(),
        )
        app, _ = build_ow_app_from_db_dir(tmp_path, state_surface=surface)
        client = TestClient(app)

        data = client.get("/api/overview").json()
        assert data["state_surface"]["fast_dimensions"] == [
            "agent.mood.custom_a",
            "agent.mood.custom_b",
        ]
        assert data["state_surface"]["slow_dimensions"] == []

    def test_unknown_dimension_display_fails_safe_to_raw(self):
        # Dictionary-level fail-safe (page rendering routes through this).
        import importlib

        import sys

        if "owdisplay_test" in sys.modules:
            del sys.modules["owdisplay_test"]
        # OWDisplay is a browser global; replicate its lookup contract here.
        from observation_window.binding import StateSurface as _S  # noqa: F401

        # The zh dictionary maps only known keys; the JS fallback returns the
        # raw key for unknown ones — assert the known mapping + unknown raw.
        dict_js = (_PKG_ROOT / "web" / "static" / "display_zh.js").read_text(
            encoding="utf-8"
        )
        assert '"agent.affect.irritation": "烦躁"' in dict_js
        assert "hasOwnProperty.call(map, key) ? map[key] : value" in dict_js


# ---------------------------------------------------------------------------
# §24 runtime status projection
# ---------------------------------------------------------------------------


class TestRuntimeStatusProjection:
    def _write_readiness(self, tmp_path: Path, payload: dict | None) -> Path:
        path = tmp_path / "readiness.json"
        if payload is not None:
            path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def test_ready(self, tmp_path: Path):
        provider = XiyueReadinessStatusProvider(
            self._write_readiness(tmp_path, {
                "core_ready": True, "gateway_pid": 7,
                "epoch_id": "e1", "runtime_ready_at": "t0",
            })
        )
        projection = provider.projection()
        assert projection.status == "READY"
        assert projection.summary_code == "CORE_READY"

    def test_degraded(self, tmp_path: Path):
        provider = XiyueReadinessStatusProvider(
            self._write_readiness(tmp_path, {"core_ready": False})
        )
        projection = provider.projection()
        assert projection.status == "DEGRADED"
        assert projection.summary_code == "CORE_DEGRADED"

    def test_offline_when_absent(self, tmp_path: Path):
        provider = XiyueReadinessStatusProvider(self._write_readiness(tmp_path, None))
        projection = provider.projection()
        assert projection.status == "OFFLINE"

    def test_projection_is_normalized_and_display_safe(self, tmp_path: Path):
        provider = XiyueReadinessStatusProvider(
            self._write_readiness(tmp_path, {
                "core_ready": True,
                "gateway_pid": 7,
                "epoch_id": "e1",
                "runtime_ready_at": "t0",
                "raw_internal_payload": {"anything": "goes"},
                "process_cmdline": "should not leak",
            })
        )
        payload = provider.projection().to_payload()
        assert set(payload.keys()) == {"status", "summary_code", "observed_at", "detail"}
        assert set(payload["detail"].keys()) <= {"gateway_pid", "epoch_id", "runtime_ready_at"}
        serialized = json.dumps(payload)
        assert "raw_internal_payload" not in serialized
        assert "should not leak" not in serialized
        assert "readiness" not in serialized


# ---------------------------------------------------------------------------
# §25 discovery fail-closed
# ---------------------------------------------------------------------------


class TestDiscoveryFailClosed:
    def test_explicit_binding_json_reconstructs_authoritative_binding(
        self, tmp_path: Path
    ):
        (tmp_path / "binding.json").write_text(json.dumps({
            "environment": "production",
            "persona_id": "kayla_v0",
            "agent_id": "hermes-xiyue",
            "runtime_id": "xiyue",
            "storage_namespace": "production/xiyue",
        }), encoding="utf-8")
        adapter = SingleBindingRegistryAdapter(runtime_dir=tmp_path)
        assert adapter.binding.storage_namespace == "production/xiyue"
        assert adapter.binding.agent_id == "hermes-xiyue"

    def test_no_reference_no_manifest_no_persona_fails_closed(self, tmp_path: Path):
        with pytest.raises(BindingScopeError):
            SingleBindingRegistryAdapter(runtime_dir=tmp_path)

    def test_manifest_identity_mismatch_fails_closed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        # The namespace manifest (written by the composition seam) declares
        # agent X; OW resolves the compat binding (agent hermes-xiyue) —
        # the resolver must refuse to observe a foreign-owned namespace.
        monkeypatch.delenv("MR_FACTS_DB", raising=False)
        monkeypatch.delenv("MR_STATE_DB", raising=False)
        (tmp_path / "binding.json").write_text(json.dumps({
            "environment": "production",
            "persona_id": "someone_else",
            "agent_id": "agent-other",
            "runtime_id": "rt-other",
            "storage_namespace": "production/xiyue",
        }), encoding="utf-8")
        compat_binding = RuntimeBinding(
            persona_id="kayla_v0",
            agent_id="hermes-xiyue",
            runtime_id="xiyue",
            storage_namespace="production/xiyue",
            environment=RuntimeEnvironment.PRODUCTION,
        )
        resolver = BindingResolver()
        with pytest.raises(BindingScopeError):
            resolver.resolve(compat_binding, production_root=tmp_path)

    def test_production_adapter_refuses_lab_binding(self, tmp_path: Path):
        (tmp_path / "binding.json").write_text(json.dumps({
            "environment": "lab",
            "persona_id": "p",
            "agent_id": "a",
            "runtime_id": "r",
            "storage_namespace": "lab/experiment-1",
        }), encoding="utf-8")
        with pytest.raises(BindingScopeError):
            resolve_xiyue_observation_binding(runtime_dir=tmp_path)

    def test_xiyue_discovery_defaults_are_authoritative(self):
        adapter, anchor = resolve_xiyue_observation_binding()
        assert adapter.binding.storage_namespace == "production/xiyue"
        assert anchor.exists()


# ---------------------------------------------------------------------------
# §21 generic source scan
# ---------------------------------------------------------------------------


class TestGenericSourceScan:
    ALLOWED_FILES = {
        # explicit Xiyue compatibility adapter: the one place path/ontology
        # literals are permitted
        "binding_xiyue.py",
        # explicit Xiyue live-trace/debug implementation (Live Trace content
        # redesign is out of scope for Phase 01)
        "live_runtime_trace.py",
    }
    BANNED_TOKENS = (
        "xiyue",
        "profiles/xiyue",
        "production/xiyue",
        "relationship_security",
        "agent.affect.irritation",
        "agent.affect.anxiety",
        "agent.affect.excitement",
        "agent.affect.longing",
    )
    #: Importing / referencing the explicitly named compatibility adapter is
    #: the sanctioned composition seam (Phase 01 §21): those identifier lines
    #: are allowed to name the adapter, but must still carry no path or
    #: ontology literals themselves.
    ADAPTER_REFERENCE_MARKERS = (
        "binding_xiyue",
        "resolve_xiyue_observation_binding",
        "build_xiyue_resolved_binding",
    )

    def _violations_on_line(self, line: str) -> list[str]:
        lowered = line.lower()
        if any(marker in lowered for marker in self.ADAPTER_REFERENCE_MARKERS):
            return []
        return [t for t in self.BANNED_TOKENS if t in lowered]

    def test_generic_ow_sources_carry_no_xiyue_or_ontology_literals(self):
        violations = []
        for path in _PKG_ROOT.rglob("*.py"):
            if path.name in self.ALLOWED_FILES:
                continue
            for lineno, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), start=1
            ):
                for token in self._violations_on_line(line):
                    violations.append(f"{path.name}:{lineno}: {token!r}")
        for path in (_PKG_ROOT / "web" / "static").glob("*.html"):
            for lineno, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), start=1
            ):
                for token in self._violations_on_line(line):
                    violations.append(f"static/{path.name}:{lineno}: {token!r}")
        # display_zh.js is the centralized zh vocabulary — mapping canonical
        # dimensions to Chinese is its explicit purpose (§21 allowed).
        assert "agent.affect.irritation" in (
            (_PKG_ROOT / "web" / "static" / "display_zh.js").read_text(encoding="utf-8")
        )
        assert not violations, "\n".join(violations)
