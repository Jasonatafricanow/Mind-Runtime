"""Comprehensive Host Tests for OW-MULTI-AGENT-BINDING-W2D-V1 and W2D-R1.

Normative authority:
- TICKET: OW-MULTI-AGENT-BINDING-W2D-V1
- TICKET: OW-MULTI-AGENT-BINDING-W2D-R1
- ADR-0021 (Multi-Binding Registry Authority)
- ADR-0020 (Runtime Identity Binding & Storage Isolation)
- docs/OW_MULTI_AGENT_BINDING_W2D_IMPL_REPORT.md

Covers:
- Binding ID grammar enforcement (ADR-0021): rejection of slash-bearing IDs
- Single URL path segment route identity: no slash decoding or multi-segment routing
- ObservationBindingCatalog authority, admission, and error handling
- Real A/B PRODUCTION + LAB registry fixture with valid public IDs (agent-a-prod, agent-b-prod)
- /api/runtime-bindings enumeration and descriptor privacy (no storage_namespace, no slashes)
- Scoped read endpoints: overview, trends, turns, head, detail, causal, human-causal, live-trace, states, ledger
- Same-turn isolation across distinct bindings with identical interaction_id
- Binding-aware cursor isolation (CURSOR_BINDING_MISMATCH)
- Scoped HTTP error translation (UNKNOWN_BINDING, BINDING_REGISTRY_UNAVAILABLE, BINDING_UNAVAILABLE)
- One registry resolution per request (instrumentation proof)
- No resolved context cache across requests (source failure proof)
- Component degradation proofs:
    A. Telemetry unavailable -> HTTP 200 -> TELEMETRY_UNAVAILABLE
    B. Assistant durable message unavailable -> HTTP 200 -> HOST_MESSAGE_UNAVAILABLE
    C. Live trace unavailable -> HTTP 200 -> CAPABILITY_UNAVAILABLE
- Real production startup reader seam wiring (reader factory zero-arg call proof)
- Source scan verifying generic OW authority boundaries
"""

from __future__ import annotations

import ast
import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from mind_runtime.binding_registry import (
    BindingDescriptor,
    BindingRegistry,
    BindingRegistryError,
    BindingRegistryReader,
    RegistryFailureCode,
    build_binding_registry,
)
from mind_runtime.runtime_binding import (
    RuntimeBinding,
    RuntimeEnvironment,
)
from observation_window.binding import (
    BindingResolver,
    ObservationBindingCatalog,
    ObservationBindingResolver,
    ObservationContext,
    ProductionObservationBindingResolver,
    ResolvedObservationBinding,
    ScopedBindingError,
    ScopedObservationBinding,
    StateSurface,
    TelemetrySource,
    AssistantMessageSource,
)
from observation_window.web.runtime import compose_ow_app


# ===========================================================================
# Helpers: Populating Real SQLite DBs
# ===========================================================================


def _init_sqlite_dbs(storage_dir: Path, *, interaction_id: str, value: float, prompt: str, reply: str) -> None:
    storage_dir.mkdir(parents=True, exist_ok=True)
    state_db = storage_dir / "cognition_state.sqlite"
    facts_db = storage_dir / "facts.sqlite"
    trace_db = storage_dir / "observation_trace.sqlite"
    hermes_db = storage_dir.parent / "state.db"

    now_str = "2026-09-07T03:00:00Z"
    user_payload = json.dumps({"text": prompt})

    # Cognition state DB
    with sqlite3.connect(state_db) as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS commit_markers (
                scope_domain TEXT NOT NULL,
                scope_user_id TEXT NOT NULL DEFAULT '',
                interaction_id TEXT NOT NULL,
                committed_at TEXT NOT NULL,
                projected_state_ids TEXT NOT NULL,
                PRIMARY KEY (scope_domain, scope_user_id, interaction_id)
            );
            CREATE TABLE IF NOT EXISTS states (
                scope_domain TEXT NOT NULL,
                scope_user_id TEXT NOT NULL DEFAULT '',
                scope_agent_id TEXT NOT NULL DEFAULT '',
                scope_persona_id TEXT NOT NULL DEFAULT '',
                scope_relationship_id TEXT NOT NULL DEFAULT '',
                scope_world_id TEXT NOT NULL DEFAULT '',
                scope_interaction_id TEXT NOT NULL DEFAULT '',
                state_id TEXT NOT NULL,
                dimension TEXT NOT NULL,
                status TEXT NOT NULL,
                value TEXT NOT NULL,
                valid_from TEXT NOT NULL,
                valid_until TEXT,
                relevant_until TEXT,
                last_observed_at TEXT NOT NULL,
                evidence_refs TEXT NOT NULL,
                transition_refs TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                origin_runtime_id TEXT NOT NULL,
                version INTEGER NOT NULL,
                sync_version INTEGER NOT NULL,
                sync_idem_key TEXT NOT NULL,
                PRIMARY KEY (
                    scope_domain, scope_user_id, scope_agent_id, scope_persona_id,
                    scope_relationship_id, scope_world_id, scope_interaction_id, state_id
                )
            );
            CREATE TABLE IF NOT EXISTS state_transitions (
                transition_id TEXT PRIMARY KEY,
                scope_domain TEXT NOT NULL,
                scope_user_id TEXT NOT NULL DEFAULT '',
                scope_agent_id TEXT NOT NULL DEFAULT '',
                scope_persona_id TEXT NOT NULL DEFAULT '',
                scope_relationship_id TEXT NOT NULL DEFAULT '',
                scope_world_id TEXT NOT NULL DEFAULT '',
                scope_interaction_id TEXT NOT NULL DEFAULT '',
                origin_runtime_id TEXT NOT NULL,
                intent_id TEXT NOT NULL,
                from_state_id TEXT NOT NULL,
                to_state_id TEXT NOT NULL,
                committed_at TEXT NOT NULL,
                sync_version INTEGER NOT NULL,
                sync_idem_key TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS slow_contribution_window (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                scope_domain TEXT NOT NULL,
                scope_user_id TEXT NOT NULL DEFAULT '',
                scope_agent_id TEXT NOT NULL DEFAULT '',
                scope_persona_id TEXT NOT NULL DEFAULT '',
                scope_relationship_id TEXT NOT NULL DEFAULT '',
                scope_world_id TEXT NOT NULL DEFAULT '',
                scope_interaction_id TEXT NOT NULL DEFAULT '',
                target_dimension TEXT NOT NULL,
                sequence INTEGER NOT NULL,
                accepted_at TEXT NOT NULL,
                proposed_value TEXT,
                salience REAL,
                evidence_refs TEXT,
                source_event_ref TEXT,
                source_decision_id TEXT
            );
        """)
        conn.execute(
            "INSERT OR REPLACE INTO commit_markers VALUES (?, ?, ?, ?, ?)",
            ("agent", "", interaction_id, now_str, json.dumps([f"st-{interaction_id}"])),
        )
        conn.execute(
            """INSERT OR REPLACE INTO states VALUES
               (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                "agent",
                "",
                "hermes-agent",
                "kayla_v0",
                "",
                "",
                "",
                f"st-{interaction_id}",
                "agent.affect.irritation",
                "active",
                str(value),
                now_str,
                None,
                None,
                now_str,
                "[]",
                "[]",
                now_str,
                "runtime",
                1,
                1,
                "sync-1",
            ),
        )
        conn.execute(
            """INSERT OR REPLACE INTO state_transitions VALUES
               (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                f"tr-{interaction_id}",
                "agent",
                "",
                "hermes-agent",
                "kayla_v0",
                "",
                "",
                "",
                "runtime",
                "intent-1",
                "st-prev",
                f"st-{interaction_id}",
                now_str,
                1,
                "sync-1",
            ),
        )

    # Facts DB
    with sqlite3.connect(facts_db) as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS evidence (
                scope_domain TEXT NOT NULL,
                scope_user_id TEXT NOT NULL DEFAULT '',
                scope_agent_id TEXT NOT NULL DEFAULT '',
                scope_persona_id TEXT NOT NULL DEFAULT '',
                scope_relationship_id TEXT NOT NULL DEFAULT '',
                scope_world_id TEXT NOT NULL DEFAULT '',
                scope_interaction_id TEXT NOT NULL DEFAULT '',
                id TEXT NOT NULL,
                origin_runtime_id TEXT NOT NULL,
                source_type TEXT NOT NULL,
                source_id TEXT NOT NULL,
                authority_level TEXT NOT NULL,
                occurred_at TEXT NOT NULL,
                received_at TEXT NOT NULL,
                payload TEXT NOT NULL,
                interaction_id TEXT NOT NULL,
                sync_version INTEGER NOT NULL,
                sync_idem_key TEXT NOT NULL,
                PRIMARY KEY (
                    scope_domain, scope_user_id, scope_agent_id, scope_persona_id,
                    scope_relationship_id, scope_world_id, scope_interaction_id, id
                )
            );
            CREATE TABLE IF NOT EXISTS observations (
                scope_domain TEXT NOT NULL,
                scope_user_id TEXT NOT NULL DEFAULT '',
                scope_agent_id TEXT NOT NULL DEFAULT '',
                scope_persona_id TEXT NOT NULL DEFAULT '',
                scope_relationship_id TEXT NOT NULL DEFAULT '',
                scope_world_id TEXT NOT NULL DEFAULT '',
                scope_interaction_id TEXT NOT NULL DEFAULT '',
                id TEXT NOT NULL,
                interaction_id TEXT NOT NULL,
                origin_runtime_id TEXT NOT NULL,
                type TEXT NOT NULL,
                key TEXT NOT NULL,
                value TEXT NOT NULL,
                confidence REAL NOT NULL,
                observed_at TEXT NOT NULL,
                evidence_refs TEXT NOT NULL,
                sync_version INTEGER NOT NULL,
                sync_idem_key TEXT NOT NULL,
                PRIMARY KEY (
                    scope_domain, scope_user_id, scope_agent_id, scope_persona_id,
                    scope_relationship_id, scope_world_id, scope_interaction_id, id
                )
            );
        """)
        conn.execute(
            """INSERT OR REPLACE INTO evidence VALUES
               (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                "interaction",
                "",
                "",
                "",
                "",
                "",
                interaction_id,
                f"ev-{interaction_id}",
                "runtime",
                "user_message",
                "user",
                "none",
                now_str,
                now_str,
                user_payload,
                interaction_id,
                1,
                "sync-1",
            ),
        )
        conn.execute(
            """INSERT OR REPLACE INTO evidence VALUES
               (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                "interaction",
                "",
                "",
                "",
                "",
                "",
                interaction_id,
                f"obs-{interaction_id}",
                "runtime",
                "user_message",
                "user",
                "none",
                now_str,
                now_str,
                user_payload,
                interaction_id,
                1,
                "sync-2",
            ),
        )
        reply_payload = json.dumps({"text": reply})
        conn.execute(
            """INSERT OR REPLACE INTO evidence VALUES
               (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                "interaction",
                "",
                "",
                "",
                "",
                "",
                interaction_id,
                f"ev-asst-{interaction_id}",
                "runtime",
                "assistant_message",
                "assistant",
                "none",
                now_str,
                now_str,
                reply_payload,
                interaction_id,
                1,
                "sync-3",
            ),
        )
        conn.execute(
            """INSERT OR REPLACE INTO observations VALUES
               (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                "interaction",
                "",
                "",
                "",
                "",
                "",
                interaction_id,
                f"obs-{interaction_id}",
                interaction_id,
                "runtime",
                "user_message",
                "user",
                user_payload,
                1.0,
                now_str,
                "[]",
                1,
                "sync-1",
            ),
        )

    # Hermes durable assistant DB
    hermes_db.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(hermes_db) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT,
                role TEXT,
                content TEXT,
                created_at TEXT
            )
        """)
        conn.execute(
            "INSERT INTO messages (session_id, role, content, created_at) VALUES (?, ?, ?, ?)",
            (interaction_id, "assistant", reply, now_str),
        )


# ===========================================================================
# Fixture: Real Multi-Binding Registry (agent-a-prod, agent-b-prod, experiment-1-lab)
# ===========================================================================


@pytest.fixture
def multi_binding_setup(tmp_path: Path):
    reg_dir = tmp_path / "registry"
    reg = build_binding_registry(reg_dir)
    reg.writer.initialize()

    prod_root = tmp_path / "prod_root"
    lab_root = tmp_path / "lab_root"

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
    binding_lab = RuntimeBinding(
        persona_id="kayla_v0",
        agent_id="hermes-agent-lab",
        runtime_id="runtime-lab",
        storage_namespace="lab/experiment-1",
        environment=RuntimeEnvironment.LAB,
    )

    reg.writer.register(binding_a, "agent-a-prod")
    reg.writer.register(binding_b, "agent-b-prod")
    reg.writer.register(binding_lab, "experiment-1-lab")

    # Storage paths
    paths_a = prod_root / "production" / "agent-a"
    paths_b = prod_root / "production" / "agent-b"
    paths_lab = lab_root / "lab" / "experiment-1"

    _init_sqlite_dbs(paths_a, interaction_id="same-turn", value=0.8, prompt="Hello A", reply="Reply from A")
    _init_sqlite_dbs(paths_b, interaction_id="same-turn", value=0.2, prompt="Hello B", reply="Reply from B")
    _init_sqlite_dbs(paths_lab, interaction_id="same-turn", value=0.5, prompt="Hello Lab", reply="Reply from Lab")

    class TestResolver:
        def resolve(self, b: RuntimeBinding) -> ResolvedObservationBinding:
            if b.environment == RuntimeEnvironment.PRODUCTION:
                root = prod_root / b.storage_namespace
            else:
                root = lab_root / b.storage_namespace
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

    return {
        "registry": reg,
        "resolver": TestResolver(),
        "prod_root": prod_root,
        "lab_root": lab_root,
        "paths_a": paths_a,
        "paths_b": paths_b,
        "paths_lab": paths_lab,
        "binding_a": binding_a,
        "binding_b": binding_b,
        "binding_lab": binding_lab,
    }


class _MockStatusProvider:
    def projection(self):
        from observation_window.binding import RuntimeStatusProjection
        return RuntimeStatusProjection(status="READY", summary_code="CORE_READY")


# ===========================================================================
# TASK 1: Public binding_id Grammar & Registry Validation (W2D-R1 §1, §2)
# ===========================================================================


class TestBindingIdValidation:
    def test_slash_bearing_binding_id_rejected_at_registration(self, multi_binding_setup):
        reg = multi_binding_setup["registry"]
        binding_a = multi_binding_setup["binding_a"]

        for invalid_id in ("production/agent-a", "lab/experiment-1", "agent/a/b", "/leading-slash", "trailing/"):
            with pytest.raises(BindingRegistryError) as exc_info:
                reg.writer.register(binding_a, invalid_id)
            assert exc_info.value.code == RegistryFailureCode.REGISTRY_CORRUPT

    def test_binding_descriptor_rejects_slash_id(self):
        with pytest.raises(BindingRegistryError) as exc_info:
            BindingDescriptor(
                binding_id="production/xiyue",
                environment=RuntimeEnvironment.PRODUCTION,
                agent_id="xiyue",
                runtime_id="mind-runtime-0.1.4",
            )
        assert exc_info.value.code == RegistryFailureCode.REGISTRY_CORRUPT

    def test_binding_id_is_distinct_from_storage_namespace(self, multi_binding_setup):
        reg = multi_binding_setup["registry"]
        resolved = reg.reader.resolve_binding("agent-a-prod", environment=RuntimeEnvironment.PRODUCTION)
        assert resolved.storage_namespace == "production/agent-a"
        assert "agent-a-prod" != resolved.storage_namespace


# ===========================================================================
# TASK 2: Single-Segment Route Path Identity (W2D-R1 §3)
# ===========================================================================


class TestSingleSegmentRouteIdentity:
    def test_single_segment_routing_accepts_valid_id(self, multi_binding_setup):
        reg = multi_binding_setup["registry"]
        resolver = multi_binding_setup["resolver"]
        catalog = ObservationBindingCatalog(
            reader=reg.reader,
            environment=RuntimeEnvironment.PRODUCTION,
            resolver=resolver,
        )
        resolved_a = resolver.resolve(multi_binding_setup["binding_a"])
        app, _ = compose_ow_app(resolved_a, catalog=catalog)
        client = TestClient(app)

        resp = client.get("/api/runtime-bindings/agent-a-prod/overview")
        assert resp.status_code == 200
        assert resp.json()["binding_id"] == "agent-a-prod"

    def test_slash_bearing_path_rejected_by_routing(self, multi_binding_setup):
        reg = multi_binding_setup["registry"]
        resolver = multi_binding_setup["resolver"]
        catalog = ObservationBindingCatalog(
            reader=reg.reader,
            environment=RuntimeEnvironment.PRODUCTION,
            resolver=resolver,
        )
        resolved_a = resolver.resolve(multi_binding_setup["binding_a"])
        app, _ = compose_ow_app(resolved_a, catalog=catalog)
        client = TestClient(app)

        resp = client.get("/api/runtime-bindings/production/agent-a/overview")
        assert resp.status_code == 404


# ===========================================================================
# TASK 3: Catalog Authority, Admission, and Error Tests
# ===========================================================================


class TestObservationBindingCatalog:
    def test_catalog_construction_is_narrow(self, multi_binding_setup):
        reg = multi_binding_setup["registry"]
        resolver = multi_binding_setup["resolver"]
        catalog = ObservationBindingCatalog(
            reader=reg.reader,
            environment=RuntimeEnvironment.PRODUCTION,
            resolver=resolver,
        )
        assert catalog.environment == RuntimeEnvironment.PRODUCTION
        assert not hasattr(catalog, "production_root")
        assert not hasattr(catalog, "lab_root")
        assert not hasattr(catalog, "runtime_dir")

    def test_catalog_admission_exact_equality(self, multi_binding_setup):
        reg = multi_binding_setup["registry"]
        resolver = multi_binding_setup["resolver"]
        prod_catalog = ObservationBindingCatalog(
            reader=reg.reader,
            environment=RuntimeEnvironment.PRODUCTION,
            resolver=resolver,
        )
        descriptors = prod_catalog.list_descriptors()
        desc_ids = [d.binding_id for d in descriptors]
        assert "agent-a-prod" in desc_ids
        assert "agent-b-prod" in desc_ids
        assert "experiment-1-lab" not in desc_ids

        lab_catalog = ObservationBindingCatalog(
            reader=reg.reader,
            environment=RuntimeEnvironment.LAB,
            resolver=resolver,
        )
        lab_descriptors = lab_catalog.list_descriptors()
        lab_ids = [d.binding_id for d in lab_descriptors]
        assert "experiment-1-lab" in lab_ids
        assert "agent-a-prod" not in lab_ids
        assert "agent-b-prod" not in lab_ids

    def test_catalog_resolve_known_binding(self, multi_binding_setup):
        reg = multi_binding_setup["registry"]
        resolver = multi_binding_setup["resolver"]
        catalog = ObservationBindingCatalog(
            reader=reg.reader,
            environment=RuntimeEnvironment.PRODUCTION,
            resolver=resolver,
        )
        scoped = catalog.resolve("agent-a-prod")
        assert isinstance(scoped, ScopedObservationBinding)
        assert scoped.binding_id == "agent-a-prod"
        assert scoped.context.binding_scope_key == "production:production/agent-a"
        assert scoped.sources is not None

    def test_catalog_resolve_unknown_binding_raises_404(self, multi_binding_setup):
        reg = multi_binding_setup["registry"]
        resolver = multi_binding_setup["resolver"]
        catalog = ObservationBindingCatalog(
            reader=reg.reader,
            environment=RuntimeEnvironment.PRODUCTION,
            resolver=resolver,
        )
        with pytest.raises(ScopedBindingError) as exc_info:
            catalog.resolve("not-a-real-binding")
        assert exc_info.value.status_code == 404
        assert exc_info.value.code == "UNKNOWN_BINDING"

    def test_catalog_resolve_lab_binding_via_production_raises_404(self, multi_binding_setup):
        reg = multi_binding_setup["registry"]
        resolver = multi_binding_setup["resolver"]
        catalog = ObservationBindingCatalog(
            reader=reg.reader,
            environment=RuntimeEnvironment.PRODUCTION,
            resolver=resolver,
        )
        with pytest.raises(ScopedBindingError) as exc_info:
            catalog.resolve("experiment-1-lab")
        assert exc_info.value.status_code == 404
        assert exc_info.value.code == "UNKNOWN_BINDING"
        assert "experiment-1-lab exists" not in exc_info.value.message

    def test_catalog_resolve_missing_sources_raises_503(self, multi_binding_setup, tmp_path: Path):
        reg = multi_binding_setup["registry"]

        class EmptyResolver:
            def resolve(self, b: RuntimeBinding) -> ResolvedObservationBinding:
                empty_dir = tmp_path / "empty_sources"
                return ResolvedObservationBinding(
                    runtime_binding=b,
                    binding_scope_key="test:empty",
                    state_surface=StateSurface(),
                    facts_db=empty_dir / "facts.sqlite",
                    state_db=empty_dir / "cognition_state.sqlite",
                    telemetry_source=TelemetrySource(db_path=None),
                    assistant_message_source=AssistantMessageSource(db_path=None),
                    runtime_status_provider=_MockStatusProvider(),
                    runtime_dir=empty_dir,
                )

        catalog = ObservationBindingCatalog(
            reader=reg.reader,
            environment=RuntimeEnvironment.PRODUCTION,
            resolver=EmptyResolver(),
        )
        with pytest.raises(ScopedBindingError) as exc_info:
            catalog.resolve("agent-a-prod")
        assert exc_info.value.status_code == 503
        assert exc_info.value.code == "BINDING_UNAVAILABLE"

    def test_catalog_resolve_registry_error_raises_503(self, tmp_path: Path):
        absent_dir = tmp_path / "absent_reg"
        reg = build_binding_registry(absent_dir)
        catalog = ObservationBindingCatalog(
            reader=reg.reader,
            environment=RuntimeEnvironment.PRODUCTION,
            resolver=BindingResolver(),
        )
        with pytest.raises(ScopedBindingError) as exc_info:
            catalog.resolve("agent-a-prod")
        assert exc_info.value.status_code == 503
        assert exc_info.value.code == "BINDING_REGISTRY_UNAVAILABLE"


# ===========================================================================
# TASK 4: One Registry Resolution Per Request & No Stale Cache (W2D-R1 §13, §14)
# ===========================================================================


class TestOneRegistryResolutionPerRequest:
    def test_resolution_count_per_request_is_exactly_one(self, multi_binding_setup):
        reg = multi_binding_setup["registry"]
        resolver = multi_binding_setup["resolver"]

        calls = []
        real_resolve_binding = reg.reader.resolve_binding

        def spy_resolve_binding(*args, **kwargs):
            calls.append((args, kwargs))
            return real_resolve_binding(*args, **kwargs)

        reg.reader.resolve_binding = spy_resolve_binding

        catalog = ObservationBindingCatalog(
            reader=reg.reader,
            environment=RuntimeEnvironment.PRODUCTION,
            resolver=resolver,
        )
        resolved_a = resolver.resolve(multi_binding_setup["binding_a"])
        app, _ = compose_ow_app(resolved_a, catalog=catalog)
        client = TestClient(app)

        # Overview endpoint
        calls.clear()
        resp = client.get("/api/runtime-bindings/agent-a-prod/overview")
        assert resp.status_code == 200
        assert len(calls) == 1

        # Turns endpoint
        calls.clear()
        resp = client.get("/api/runtime-bindings/agent-a-prod/turns")
        assert resp.status_code == 200
        assert len(calls) == 1

        # Causal endpoint
        calls.clear()
        resp = client.get("/api/runtime-bindings/agent-a-prod/turns/same-turn/causal")
        assert resp.status_code == 200
        assert len(calls) == 1

        # Human causal trace endpoint
        calls.clear()
        resp = client.get("/api/runtime-bindings/agent-a-prod/turns/same-turn/human-causal-trace")
        assert resp.status_code == 200
        assert len(calls) == 1

        # States endpoint
        calls.clear()
        resp = client.get("/api/runtime-bindings/agent-a-prod/states")
        assert resp.status_code == 200
        assert len(calls) == 1

    def test_enumeration_does_not_call_resolve_binding(self, multi_binding_setup):
        reg = multi_binding_setup["registry"]
        resolver = multi_binding_setup["resolver"]

        calls = []
        real_resolve_binding = reg.reader.resolve_binding

        def spy_resolve_binding(*args, **kwargs):
            calls.append((args, kwargs))
            return real_resolve_binding(*args, **kwargs)

        reg.reader.resolve_binding = spy_resolve_binding

        catalog = ObservationBindingCatalog(
            reader=reg.reader,
            environment=RuntimeEnvironment.PRODUCTION,
            resolver=resolver,
        )
        resolved_a = resolver.resolve(multi_binding_setup["binding_a"])
        app, _ = compose_ow_app(resolved_a, catalog=catalog)
        client = TestClient(app)

        calls.clear()
        resp = client.get("/api/runtime-bindings")
        assert resp.status_code == 200
        assert len(calls) == 0


class TestNoResolvedContextCache:
    def test_source_failure_after_healthy_request_fails_503(self, multi_binding_setup, tmp_path: Path):
        reg = multi_binding_setup["registry"]
        orig_resolver = multi_binding_setup["resolver"]

        class FlippableResolver:
            def __init__(self):
                self.broken = False

            def resolve(self, b: RuntimeBinding) -> ResolvedObservationBinding:
                if self.broken:
                    missing_dir = tmp_path / "nonexistent_sources"
                    return ResolvedObservationBinding(
                        runtime_binding=b,
                        binding_scope_key=f"{b.environment.value}:{b.storage_namespace}",
                        state_surface=StateSurface(fast_dimensions=("agent.affect.irritation",)),
                        facts_db=missing_dir / "facts.sqlite",
                        state_db=missing_dir / "cognition_state.sqlite",
                        telemetry_source=TelemetrySource(db_path=None),
                        assistant_message_source=AssistantMessageSource(db_path=None),
                        runtime_status_provider=_MockStatusProvider(),
                        runtime_dir=missing_dir,
                    )
                return orig_resolver.resolve(b)

        flippable = FlippableResolver()
        catalog = ObservationBindingCatalog(
            reader=reg.reader,
            environment=RuntimeEnvironment.PRODUCTION,
            resolver=flippable,
        )
        resolved_a = orig_resolver.resolve(multi_binding_setup["binding_a"])
        app, _ = compose_ow_app(resolved_a, catalog=catalog)
        client = TestClient(app)

        # 1. Healthy request succeeds
        resp1 = client.get("/api/runtime-bindings/agent-a-prod/overview")
        assert resp1.status_code == 200

        # 2. Break the physical sources via resolver
        flippable.broken = True

        # 3. Next request must NOT use stale cached context; must fail closed with 503
        resp2 = client.get("/api/runtime-bindings/agent-a-prod/overview")
        assert resp2.status_code == 503
        assert resp2.json()["code"] == "BINDING_UNAVAILABLE"

        # 4. Restoring source allows next request to succeed again
        flippable.broken = False
        resp3 = client.get("/api/runtime-bindings/agent-a-prod/overview")
        assert resp3.status_code == 200


# ===========================================================================
# TASK 5: Component Degradation Proofs (W2D-R1 §15)
# ===========================================================================


class TestComponentDegradationProofs:
    def test_telemetry_unavailable_returns_http_200_with_degradation(self, multi_binding_setup):
        reg = multi_binding_setup["registry"]
        binding_a = multi_binding_setup["binding_a"]

        class NoTelemetryResolver:
            def resolve(self, b: RuntimeBinding) -> ResolvedObservationBinding:
                root = multi_binding_setup["prod_root"] / b.storage_namespace
                return ResolvedObservationBinding(
                    runtime_binding=b,
                    binding_scope_key=f"{b.environment.value}:{b.storage_namespace}",
                    state_surface=StateSurface(fast_dimensions=("agent.affect.irritation",)),
                    facts_db=root / "facts.sqlite",
                    state_db=root / "cognition_state.sqlite",
                    telemetry_source=TelemetrySource(db_path=None),
                    assistant_message_source=AssistantMessageSource(db_path=root.parent / "state.db"),
                    runtime_status_provider=_MockStatusProvider(),
                    runtime_dir=root,
                )

        catalog = ObservationBindingCatalog(
            reader=reg.reader,
            environment=RuntimeEnvironment.PRODUCTION,
            resolver=NoTelemetryResolver(),
        )
        resolved_a = NoTelemetryResolver().resolve(binding_a)
        app, _ = compose_ow_app(resolved_a, catalog=catalog)
        client = TestClient(app)

        resp = client.get("/api/runtime-bindings/agent-a-prod/turns/same-turn/human-causal-trace")
        assert resp.status_code == 200
        data = resp.json()
        assert data["raw_linkage"]["telemetry_status"] == "TELEMETRY_UNAVAILABLE"

    def test_assistant_message_unavailable_returns_http_200_with_degradation(self, multi_binding_setup):
        reg = multi_binding_setup["registry"]
        binding_a = multi_binding_setup["binding_a"]
        paths_a = multi_binding_setup["paths_a"]

        # Seed turn with assistant message in telemetry journal, but NOT in facts.sqlite evidence
        trace_db = paths_a / "observation_trace.sqlite"
        now_str = "2026-09-07T03:00:00Z"
        with sqlite3.connect(trace_db) as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS trace_events (
                    event_id TEXT PRIMARY KEY,
                    interaction_id TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    sequence_no INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    source_refs_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
            """)
            asst_payload = json.dumps({
                "durable_message_id": "msg-unreachable",
                "timestamp": now_str,
            })
            conn.execute(
                """INSERT INTO trace_events
                   (event_id, interaction_id, stage, occurred_at, sequence_no, status, payload_json, source_refs_json, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                ("trc-degrade", "turn-degrade", "ASSISTANT_RESPONSE", now_str, 1, "RECORDED", asst_payload, "[]", now_str),
            )

        # Also add commit marker and user evidence for turn-degrade
        state_db = paths_a / "cognition_state.sqlite"
        facts_db = paths_a / "facts.sqlite"
        with sqlite3.connect(state_db) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO commit_markers VALUES (?, ?, ?, ?, ?)",
                ("agent", "", "turn-degrade", now_str, "[]"),
            )
        with sqlite3.connect(facts_db) as conn:
            conn.execute(
                """INSERT OR REPLACE INTO evidence VALUES
                   (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    "interaction", "", "", "", "", "", "turn-degrade",
                    "ev-turn-degrade", "runtime", "user_message", "user", "none",
                    now_str, now_str, json.dumps({"text": "User msg"}), "turn-degrade", 1, "sync-1",
                ),
            )

        class NoAssistantResolver:
            def resolve(self, b: RuntimeBinding) -> ResolvedObservationBinding:
                root = multi_binding_setup["prod_root"] / b.storage_namespace
                return ResolvedObservationBinding(
                    runtime_binding=b,
                    binding_scope_key=f"{b.environment.value}:{b.storage_namespace}",
                    state_surface=StateSurface(fast_dimensions=("agent.affect.irritation",)),
                    facts_db=root / "facts.sqlite",
                    state_db=root / "cognition_state.sqlite",
                    telemetry_source=TelemetrySource(db_path=root / "observation_trace.sqlite"),
                    assistant_message_source=AssistantMessageSource(db_path=None),  # capability absent
                    runtime_status_provider=_MockStatusProvider(),
                    runtime_dir=root,
                )

        catalog = ObservationBindingCatalog(
            reader=reg.reader,
            environment=RuntimeEnvironment.PRODUCTION,
            resolver=NoAssistantResolver(),
        )
        resolved_a = NoAssistantResolver().resolve(binding_a)
        app, _ = compose_ow_app(resolved_a, catalog=catalog)
        client = TestClient(app)

        resp = client.get("/api/runtime-bindings/agent-a-prod/turns/turn-degrade/human-causal-trace")
        assert resp.status_code == 200
        data = resp.json()
        assert data["assistant_response"]["status"] == "HOST_MESSAGE_UNAVAILABLE"

    def test_live_trace_unavailable_returns_http_200_with_degradation(self, multi_binding_setup):
        reg = multi_binding_setup["registry"]
        resolver = multi_binding_setup["resolver"]
        catalog = ObservationBindingCatalog(
            reader=reg.reader,
            environment=RuntimeEnvironment.PRODUCTION,
            resolver=resolver,
        )
        resolved_a = resolver.resolve(multi_binding_setup["binding_a"])
        app, _ = compose_ow_app(resolved_a, catalog=catalog, live_trace_provider=None)
        client = TestClient(app)

        resp = client.get("/api/runtime-bindings/agent-a-prod/live-trace")
        assert resp.status_code == 200
        data = resp.json()
        assert data["binding_id"] == "agent-a-prod"
        assert data["status"] == "CAPABILITY_UNAVAILABLE"


# ===========================================================================
# TASK 6: Enumeration and Descriptor Privacy Tests (W2D-R1 §16)
# ===========================================================================


class TestObservationBindingsEnumeration:
    def test_list_runtime_bindings_public_descriptor_privacy(self, multi_binding_setup):
        reg = multi_binding_setup["registry"]
        resolver = multi_binding_setup["resolver"]
        catalog = ObservationBindingCatalog(
            reader=reg.reader,
            environment=RuntimeEnvironment.PRODUCTION,
            resolver=resolver,
        )
        resolved_a = resolver.resolve(multi_binding_setup["binding_a"])
        app, _ = compose_ow_app(resolved_a, catalog=catalog)
        client = TestClient(app)

        resp = client.get("/api/runtime-bindings")
        assert resp.status_code == 200
        data = resp.json()
        assert "bindings" in data
        bindings = data["bindings"]
        assert len(bindings) == 2

        exact_keys = {"binding_id", "environment", "agent_id", "runtime_id"}
        binding_ids = set()
        for b in bindings:
            assert set(b.keys()) == exact_keys
            assert "storage_namespace" not in b
            assert "persona_id" not in b
            assert "facts_db" not in b
            assert "state_db" not in b
            assert "root" not in b
            assert "runtime_dir" not in b
            assert "binding_scope_key" not in b
            assert "readiness" not in b
            assert "/" not in b["binding_id"]
            binding_ids.add(b["binding_id"])

        assert binding_ids == {"agent-a-prod", "agent-b-prod"}
        assert "experiment-1-lab" not in binding_ids

    def test_list_runtime_bindings_503_when_no_catalog(self, multi_binding_setup):
        resolver = multi_binding_setup["resolver"]
        resolved_a = resolver.resolve(multi_binding_setup["binding_a"])
        app, _ = compose_ow_app(resolved_a, catalog=None)
        client = TestClient(app)

        resp = client.get("/api/runtime-bindings")
        assert resp.status_code == 503
        data = resp.json()
        assert data["code"] == "BINDING_REGISTRY_UNAVAILABLE"


# ===========================================================================
# TASK 7: Scoped Read Endpoints Isolation Tests (A/B Isolation)
# ===========================================================================


class TestScopedReadEndpointsIsolation:
    @pytest.fixture
    def test_client(self, multi_binding_setup):
        reg = multi_binding_setup["registry"]
        resolver = multi_binding_setup["resolver"]
        catalog = ObservationBindingCatalog(
            reader=reg.reader,
            environment=RuntimeEnvironment.PRODUCTION,
            resolver=resolver,
        )
        resolved_a = resolver.resolve(multi_binding_setup["binding_a"])
        app, _ = compose_ow_app(resolved_a, catalog=catalog)
        return TestClient(app)

    def test_scoped_overview_isolation(self, test_client):
        resp_a = test_client.get("/api/runtime-bindings/agent-a-prod/overview")
        assert resp_a.status_code == 200
        data_a = resp_a.json()
        assert data_a["binding_id"] == "agent-a-prod"
        assert data_a["turn_stats"]["persisted_committed_turns"] == 1
        st_a = next(s for s in data_a["current_states"] if s["dimension"] == "agent.affect.irritation")
        assert pytest.approx(st_a["value"]) == 0.8

        resp_b = test_client.get("/api/runtime-bindings/agent-b-prod/overview")
        assert resp_b.status_code == 200
        data_b = resp_b.json()
        assert data_b["binding_id"] == "agent-b-prod"
        assert data_b["turn_stats"]["persisted_committed_turns"] == 1
        st_b = next(s for s in data_b["current_states"] if s["dimension"] == "agent.affect.irritation")
        assert pytest.approx(st_b["value"]) == 0.2

    def test_scoped_trends_isolation(self, test_client):
        resp_a = test_client.get("/api/runtime-bindings/agent-a-prod/trends")
        assert resp_a.status_code == 200
        data_a = resp_a.json()
        assert data_a["binding_id"] == "agent-a-prod"

        resp_b = test_client.get("/api/runtime-bindings/agent-b-prod/trends")
        assert resp_b.status_code == 200
        data_b = resp_b.json()
        assert data_b["binding_id"] == "agent-b-prod"

    def test_scoped_states_and_history_isolation(self, test_client):
        # States list
        resp_a = test_client.get("/api/runtime-bindings/agent-a-prod/states")
        assert resp_a.status_code == 200
        data_a = resp_a.json()
        assert data_a["binding_id"] == "agent-a-prod"
        st_a = next(s for s in data_a["states"] if s["dimension"] == "agent.affect.irritation")
        assert pytest.approx(st_a["value"]) == 0.8

        resp_b = test_client.get("/api/runtime-bindings/agent-b-prod/states")
        assert resp_b.status_code == 200
        data_b = resp_b.json()
        assert data_b["binding_id"] == "agent-b-prod"
        st_b = next(s for s in data_b["states"] if s["dimension"] == "agent.affect.irritation")
        assert pytest.approx(st_b["value"]) == 0.2

        # Single state
        resp_single_a = test_client.get("/api/runtime-bindings/agent-a-prod/states/agent.affect.irritation")
        assert resp_single_a.status_code == 200
        assert resp_single_a.json()["binding_id"] == "agent-a-prod"
        assert pytest.approx(resp_single_a.json()["value"]) == 0.8

        resp_single_b = test_client.get("/api/runtime-bindings/agent-b-prod/states/agent.affect.irritation")
        assert resp_single_b.status_code == 200
        assert resp_single_b.json()["binding_id"] == "agent-b-prod"
        assert pytest.approx(resp_single_b.json()["value"]) == 0.2

        # History
        resp_hist_a = test_client.get("/api/runtime-bindings/agent-a-prod/states/agent.affect.irritation/history")
        assert resp_hist_a.status_code == 200
        assert resp_hist_a.json()["binding_id"] == "agent-a-prod"
        assert pytest.approx(resp_hist_a.json()["history"][0]["value"]) == 0.8

        resp_hist_b = test_client.get("/api/runtime-bindings/agent-b-prod/states/agent.affect.irritation/history")
        assert resp_hist_b.status_code == 200
        assert resp_hist_b.json()["binding_id"] == "agent-b-prod"
        assert pytest.approx(resp_hist_b.json()["history"][0]["value"]) == 0.2

    def test_scoped_turns_and_detail_isolation(self, test_client):
        # Head
        resp_head_a = test_client.get("/api/runtime-bindings/agent-a-prod/turns/head")
        assert resp_head_a.status_code == 200
        assert resp_head_a.json()["binding_id"] == "agent-a-prod"
        assert resp_head_a.json()["latest_interaction_id"] == "same-turn"

        resp_head_b = test_client.get("/api/runtime-bindings/agent-b-prod/turns/head")
        assert resp_head_b.status_code == 200
        assert resp_head_b.json()["binding_id"] == "agent-b-prod"
        assert resp_head_b.json()["latest_interaction_id"] == "same-turn"

        # List turns
        resp_turns_a = test_client.get("/api/runtime-bindings/agent-a-prod/turns")
        assert resp_turns_a.status_code == 200
        data_turns_a = resp_turns_a.json()
        assert data_turns_a["binding_id"] == "agent-a-prod"
        assert len(data_turns_a["turns"]) == 1
        assert data_turns_a["turns"][0]["interaction_id"] == "same-turn"
        assert data_turns_a["turns"][0]["user_preview"] == "Hello A"

        resp_turns_b = test_client.get("/api/runtime-bindings/agent-b-prod/turns")
        assert resp_turns_b.status_code == 200
        data_turns_b = resp_turns_b.json()
        assert data_turns_b["binding_id"] == "agent-b-prod"
        assert len(data_turns_b["turns"]) == 1
        assert data_turns_b["turns"][0]["interaction_id"] == "same-turn"
        assert data_turns_b["turns"][0]["user_preview"] == "Hello B"

        # Turn detail
        resp_dt_a = test_client.get("/api/runtime-bindings/agent-a-prod/turns/same-turn")
        assert resp_dt_a.status_code == 200
        data_dt_a = resp_dt_a.json()
        assert data_dt_a["binding_id"] == "agent-a-prod"
        assert "turn" in data_dt_a
        assert data_dt_a["turn"]["interaction_id"] == "same-turn"
        ht_a = data_dt_a["turn"]["human_trace"]
        assert ht_a["user_input"]["text"] == "Hello A"
        assert ht_a["assistant_response"]["text"] == "Reply from A"

        resp_dt_b = test_client.get("/api/runtime-bindings/agent-b-prod/turns/same-turn")
        assert resp_dt_b.status_code == 200
        data_dt_b = resp_dt_b.json()
        assert data_dt_b["binding_id"] == "agent-b-prod"
        assert "turn" in data_dt_b
        assert data_dt_b["turn"]["interaction_id"] == "same-turn"
        ht_b = data_dt_b["turn"]["human_trace"]
        assert ht_b["user_input"]["text"] == "Hello B"
        assert ht_b["assistant_response"]["text"] == "Reply from B"

    def test_scoped_causal_and_human_causal_trace(self, test_client):
        resp_causal_a = test_client.get("/api/runtime-bindings/agent-a-prod/turns/same-turn/causal")
        assert resp_causal_a.status_code == 200
        assert resp_causal_a.json()["binding_id"] == "agent-a-prod"

        resp_causal_b = test_client.get("/api/runtime-bindings/agent-b-prod/turns/same-turn/causal")
        assert resp_causal_b.status_code == 200
        assert resp_causal_b.json()["binding_id"] == "agent-b-prod"

        resp_ht_a = test_client.get("/api/runtime-bindings/agent-a-prod/turns/same-turn/human-causal-trace")
        assert resp_ht_a.status_code == 200
        assert resp_ht_a.json()["binding_id"] == "agent-a-prod"

        resp_ht_b = test_client.get("/api/runtime-bindings/agent-b-prod/turns/same-turn/human-causal-trace")
        assert resp_ht_b.status_code == 200
        assert resp_ht_b.json()["binding_id"] == "agent-b-prod"

    def test_scoped_live_trace_evidence_provenance(self, test_client):
        resp_live_a = test_client.get("/api/runtime-bindings/agent-a-prod/live-trace")
        assert resp_live_a.status_code == 200
        assert resp_live_a.json()["binding_id"] == "agent-a-prod"

        resp_live_b = test_client.get("/api/runtime-bindings/agent-b-prod/live-trace")
        assert resp_live_b.status_code == 200
        assert resp_live_b.json()["binding_id"] == "agent-b-prod"

        # Evidence
        resp_ev_a = test_client.get("/api/runtime-bindings/agent-a-prod/evidence/obs-same-turn")
        assert resp_ev_a.status_code == 200
        assert resp_ev_a.json()["binding_id"] == "agent-a-prod"
        assert resp_ev_a.json()["evidence_id"] == "obs-same-turn"

        resp_ev_b = test_client.get("/api/runtime-bindings/agent-b-prod/evidence/obs-same-turn")
        assert resp_ev_b.status_code == 200
        assert resp_ev_b.json()["binding_id"] == "agent-b-prod"
        assert resp_ev_b.json()["evidence_id"] == "obs-same-turn"

        # Provenance
        resp_prov_a = test_client.get("/api/runtime-bindings/agent-a-prod/provenance/obs-same-turn")
        assert resp_prov_a.status_code == 200
        assert resp_prov_a.json()["binding_id"] == "agent-a-prod"

        resp_prov_b = test_client.get("/api/runtime-bindings/agent-b-prod/provenance/obs-same-turn")
        assert resp_prov_b.status_code == 200
        assert resp_prov_b.json()["binding_id"] == "agent-b-prod"


# ===========================================================================
# TASK 8: Binding-Aware Cursor Isolation Tests (W2D-R1 §11)
# ===========================================================================


class TestCursorBindingIsolation:
    def test_cursor_binding_mismatch_rejected_with_400(self, multi_binding_setup):
        reg = multi_binding_setup["registry"]
        resolver = multi_binding_setup["resolver"]
        catalog = ObservationBindingCatalog(
            reader=reg.reader,
            environment=RuntimeEnvironment.PRODUCTION,
            resolver=resolver,
        )
        resolved_a = resolver.resolve(multi_binding_setup["binding_a"])
        app, _ = compose_ow_app(resolved_a, catalog=catalog)
        client = TestClient(app)

        # 1. Passing cursor with prefix of agent-a-prod to agent-b-prod -> 400 CURSOR_BINDING_MISMATCH
        cursor_a = "agent-a-prod:2026-09-07T03:00:00Z|same-turn"
        resp_mismatch = client.get(f"/api/runtime-bindings/agent-b-prod/turns?before={cursor_a}")
        assert resp_mismatch.status_code == 400
        data = resp_mismatch.json()
        assert data["code"] == "CURSOR_BINDING_MISMATCH"
        assert "cannot be used for 'agent-b-prod'" in data["message"]

        # 2. Passing un-prefixed cursor to scoped endpoint -> 400 CURSOR_BINDING_MISMATCH
        raw_cursor = "2026-09-07T03:00:00Z|same-turn"
        resp_unprefixed = client.get(f"/api/runtime-bindings/agent-a-prod/turns?before={raw_cursor}")
        assert resp_unprefixed.status_code == 400
        data_unprefixed = resp_unprefixed.json()
        assert data_unprefixed["code"] == "CURSOR_BINDING_MISMATCH"

        # 3. Passing matching cursor to agent-a-prod succeeds (200 OK)
        resp_matched = client.get(f"/api/runtime-bindings/agent-a-prod/turns?before={cursor_a}")
        assert resp_matched.status_code == 200
        assert resp_matched.json()["binding_id"] == "agent-a-prod"


# ===========================================================================
# TASK 9: Scoped Error Response Translation Tests
# ===========================================================================


class TestScopedErrorResponses:
    @pytest.fixture
    def test_client(self, multi_binding_setup):
        reg = multi_binding_setup["registry"]
        resolver = multi_binding_setup["resolver"]
        catalog = ObservationBindingCatalog(
            reader=reg.reader,
            environment=RuntimeEnvironment.PRODUCTION,
            resolver=resolver,
        )
        resolved_a = resolver.resolve(multi_binding_setup["binding_a"])
        app, _ = compose_ow_app(resolved_a, catalog=catalog)
        return TestClient(app)

    def test_unknown_binding_returns_404(self, test_client):
        resp = test_client.get("/api/runtime-bindings/unknown-id/overview")
        assert resp.status_code == 404
        data = resp.json()
        assert data["code"] == "UNKNOWN_BINDING"
        assert "unknown-id" in data["message"]

    def test_lab_binding_via_production_returns_404_no_disclosure(self, test_client):
        resp = test_client.get("/api/runtime-bindings/experiment-1-lab/overview")
        assert resp.status_code == 404
        data = resp.json()
        assert data["code"] == "UNKNOWN_BINDING"
        assert "admission" not in data["message"].lower()
        assert "lab environment" not in data["message"].lower()

    def test_missing_sources_returns_503(self, multi_binding_setup, tmp_path: Path):
        reg = multi_binding_setup["registry"]

        class MissingDbResolver:
            def resolve(self, b: RuntimeBinding) -> ResolvedObservationBinding:
                d = tmp_path / "missing_db"
                return ResolvedObservationBinding(
                    runtime_binding=b,
                    binding_scope_key="test:missing",
                    state_surface=StateSurface(),
                    facts_db=d / "facts.sqlite",
                    state_db=d / "cognition_state.sqlite",
                    telemetry_source=TelemetrySource(db_path=None),
                    assistant_message_source=AssistantMessageSource(db_path=None),
                    runtime_status_provider=_MockStatusProvider(),
                    runtime_dir=d,
                )

        catalog = ObservationBindingCatalog(
            reader=reg.reader,
            environment=RuntimeEnvironment.PRODUCTION,
            resolver=MissingDbResolver(),
        )
        resolved_a = multi_binding_setup["resolver"].resolve(multi_binding_setup["binding_a"])
        app, _ = compose_ow_app(resolved_a, catalog=catalog)
        client = TestClient(app)

        resp = client.get("/api/runtime-bindings/agent-a-prod/overview")
        assert resp.status_code == 503
        data = resp.json()
        assert data["code"] == "BINDING_UNAVAILABLE"

    def test_uninitialized_registry_returns_503(self, tmp_path: Path):
        absent_dir = tmp_path / "absent_reg"
        reg = build_binding_registry(absent_dir)
        catalog = ObservationBindingCatalog(
            reader=reg.reader,
            environment=RuntimeEnvironment.PRODUCTION,
            resolver=BindingResolver(),
        )
        dummy_dir = tmp_path / "dummy"
        dummy_dir.mkdir(parents=True)
        (dummy_dir / "cognition_state.sqlite").touch()
        (dummy_dir / "facts.sqlite").touch()
        dummy_binding = RuntimeBinding(
            persona_id="kayla_v0",
            agent_id="agent",
            runtime_id="runtime",
            storage_namespace="production/agent",
            environment=RuntimeEnvironment.PRODUCTION,
        )
        resolved = ResolvedObservationBinding(
            runtime_binding=dummy_binding,
            binding_scope_key="dummy",
            state_surface=StateSurface(),
            facts_db=dummy_dir / "facts.sqlite",
            state_db=dummy_dir / "cognition_state.sqlite",
            telemetry_source=TelemetrySource(db_path=None),
            assistant_message_source=AssistantMessageSource(db_path=None),
            runtime_status_provider=_MockStatusProvider(),
            runtime_dir=dummy_dir,
        )
        app, _ = compose_ow_app(resolved, catalog=catalog)
        client = TestClient(app)

        resp = client.get("/api/runtime-bindings/agent-a-prod/overview")
        assert resp.status_code == 503
        data = resp.json()
        assert data["code"] == "BINDING_REGISTRY_UNAVAILABLE"


# ===========================================================================
# TASK 10: Legacy Route Compatibility Tests
# ===========================================================================


class TestLegacyRouteCompatibility:
    def test_legacy_routes_work_unmodified(self, multi_binding_setup):
        reg = multi_binding_setup["registry"]
        resolver = multi_binding_setup["resolver"]
        reg.writer.set_default("agent-a-prod")
        catalog = ObservationBindingCatalog(
            reader=reg.reader,
            environment=RuntimeEnvironment.PRODUCTION,
            resolver=resolver,
        )
        resolved_a = resolver.resolve(multi_binding_setup["binding_a"])
        app, _ = compose_ow_app(resolved_a, catalog=catalog)
        client = TestClient(app)

        resp_overview = client.get("/api/overview")
        assert resp_overview.status_code == 200
        data_overview = resp_overview.json()
        assert "current_states" in data_overview
        assert "turn_stats" in data_overview

        resp_trends = client.get("/api/trends")
        assert resp_trends.status_code == 200

        resp_states = client.get("/api/states")
        assert resp_states.status_code == 200

        resp_turns = client.get("/api/turns")
        assert resp_turns.status_code == 200
        assert len(resp_turns.json()["turns"]) == 1


# ===========================================================================
# TASK 11: Real Production Startup Wiring Tests (W2D-R1 §4, §5, §6)
# ===========================================================================


class TestProductionStartupWiring:
    def test_runtime_main_calls_reader_factory_with_zero_args(self):
        """AST check: runtime.py must call open_production_binding_registry_reader() with NO arguments."""
        runtime_py = Path(__file__).resolve().parents[2] / "src" / "observation_window" / "web" / "runtime.py"
        assert runtime_py.is_file()

        tree = ast.parse(runtime_py.read_text(encoding="utf-8"))
        found_calls = 0
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func_name = None
                if isinstance(node.func, ast.Name):
                    func_name = node.func.id
                elif isinstance(node.func, ast.Attribute):
                    func_name = node.func.attr
                if func_name == "open_production_binding_registry_reader":
                    found_calls += 1
                    assert len(node.args) == 0, f"open_production_binding_registry_reader called with positional args: {node.args}"
                    assert len(node.keywords) == 0, f"open_production_binding_registry_reader called with keyword args: {node.keywords}"

        assert found_calls >= 1, "open_production_binding_registry_reader call not found in runtime.py"

    def test_production_resolver_and_catalog_seam(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ):
        store_dir = tmp_path / "prod_reg"
        monkeypatch.setenv("MR_BINDING_REGISTRY_DIR", str(store_dir))

        from mind_runtime.binding_registry_composition import (
            bootstrap_production_registry,
            open_production_binding_registry_reader,
        )

        desc = bootstrap_production_registry(
            binding_id="prod-bootstrapped-01",
            persona_id="kayla_v0",
        )
        assert desc.binding_id == "prod-bootstrapped-01"

        reader = open_production_binding_registry_reader()

        prod_root = tmp_path / "xiyue_root"
        prod_root.mkdir(parents=True, exist_ok=True)
        (prod_root / "cognition_state.sqlite").touch()
        (prod_root / "facts.sqlite").touch()

        resolver = ProductionObservationBindingResolver(production_root=prod_root)
        catalog = ObservationBindingCatalog(
            reader=reader,
            environment=RuntimeEnvironment.PRODUCTION,
            resolver=resolver,
        )

        descriptors = catalog.list_descriptors()
        assert len(descriptors) == 1
        assert descriptors[0].binding_id == "prod-bootstrapped-01"

        scoped = catalog.resolve("prod-bootstrapped-01")
        assert scoped.binding_id == "prod-bootstrapped-01"
        assert scoped.resolved_binding.runtime_binding.environment == RuntimeEnvironment.PRODUCTION


# ===========================================================================
# TASK 12: Generic OW Source Hygiene Tests (W2D-R1 §17)
# ===========================================================================


class TestGenericOWSourceHygiene:
    def test_no_forbidden_registry_calls_in_ow(self):
        ow_src = Path(__file__).resolve().parents[2] / "src" / "observation_window"
        assert ow_src.is_dir()

        forbidden_patterns = [
            "MR_BINDING_REGISTRY_DIR",
            "build_binding_registry(",
            "open_binding_registry_admin(",
            "bootstrap_production_registry(",
            "production_registry_location(",
            ".initialize(",
            ".set_default(",
            ".clear_default(",
        ]

        violations: list[str] = []
        for py_file in ow_src.rglob("*.py"):
            text = py_file.read_text(encoding="utf-8")
            for pattern in forbidden_patterns:
                if pattern in text:
                    violations.append(f"{py_file.name}: contains forbidden {pattern!r}")

        assert not violations, "Observation Window violates registry authority boundary:\n" + "\n".join(violations)
