"""MR-RUNTIME-01: Runtime identity / binding / storage namespace isolation.

Contract under test (ADR-0020):
  * the four identity dimensions (persona_id, agent_id, runtime_id,
    storage_namespace) remain distinct and all four are required;
  * two bindings construct independent, non-communicating runtimes over the
    SAME MR Core implementation;
  * namespace A and namespace B cannot read or write each other's durable
    state (filesystem/SQLite level, not a query filter);
  * restart with the same durable binding restores the same durable state;
  * absent/invalid namespace fails closed; LAB never falls back to
    production storage;
  * the existing production single-runtime path stays compatible
    (MR_FACTS_DB / MR_STATE_DB env relocation still honored).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import pytest
from tests.golden.fixtures.common import make_state
from tests.support.fake_clock import FakeClock

import mind_runtime.runtime_binding as rb
from mind_runtime.runtime_binding import (
    DEFAULT_LAB_ROOT,
    DEFAULT_PRODUCTION_ROOT,
    PRODUCTION_COMPAT_NAMESPACE,
    BindingManifestMismatchError,
    NamespaceIsolationError,
    RuntimeBinding,
    RuntimeBindingError,
    RuntimeEnvironment,
    bind_storage,
    production_binding,
    resolve_storage_paths,
)
from mind_runtime.shadow.runtime_loop import build_runtime_stack
from mind_runtime.state.persistence import SqliteStateBackend

NOW = datetime(2026, 9, 6, 11, 0, tzinfo=UTC)


def lab_binding(
    namespace: str,
    *,
    persona_id: str = "kayla_v0",
    agent_id: str = "mr-lab",
    runtime_id: str | None = None,
) -> RuntimeBinding:
    return RuntimeBinding(
        persona_id=persona_id,
        agent_id=agent_id,
        runtime_id=runtime_id or f"lab-{namespace}",
        storage_namespace=namespace,
        environment=RuntimeEnvironment.LAB,
    )


def build_stack_for(binding: RuntimeBinding, lab_root: Any = None):
    paths = bind_storage(binding, lab_root=lab_root)
    orchestrator, _bridge = build_runtime_stack(
        clock=FakeClock(NOW),
        facts_db=paths.facts_db,
        state_db=paths.state_db,
        origin_runtime_id=binding.runtime_id,
        user_id="user",
    )
    return paths, orchestrator


# ---------------------------------------------------------------------------
# 1. identity dimensions remain distinct
# ---------------------------------------------------------------------------


class TestIdentityDimensionsDistinct:
    def test_all_four_fields_required_no_defaults(self) -> None:
        with pytest.raises(TypeError):
            RuntimeBinding(  # type: ignore[call-arg]
                persona_id="kayla_v0",
                agent_id="mr-lab",
                runtime_id="lab-x",
            )

    @pytest.mark.parametrize(
        "field", ["persona_id", "agent_id", "runtime_id", "storage_namespace"]
    )
    def test_empty_identity_field_fails_closed(self, field: str) -> None:
        values: dict[str, str] = {
            "persona_id": "kayla_v0",
            "agent_id": "mr-lab",
            "runtime_id": "lab-x",
            "storage_namespace": "exp-x",
        }
        values[field] = ""
        with pytest.raises(RuntimeBindingError):
            RuntimeBinding(environment=RuntimeEnvironment.LAB, **values)

    def test_same_persona_different_bindings_are_distinct(self) -> None:
        a = lab_binding("exp-a")
        b = lab_binding("exp-b")
        assert a.persona_id == b.persona_id  # same MR persona ...
        assert a.agent_id == b.agent_id  # ... same consuming agent ...
        assert a.runtime_id != b.runtime_id  # ... different logical runtimes ...
        assert a.storage_namespace != b.storage_namespace  # ... different namespaces.
        assert a != b

    def test_binding_is_not_a_scope_and_seeds_no_cognition(self, tmp_path: Any) -> None:
        binding = lab_binding("exp-no-leak")
        assert not hasattr(binding, "scope")  # never a canonical-state identity
        _paths, orchestrator = build_stack_for(binding, lab_root=tmp_path)
        # Composition alone must seed zero canonical cognition state.
        assert orchestrator.canonical == ()
        assert orchestrator._runtime_id == binding.runtime_id


# ---------------------------------------------------------------------------
# 2/3. two bindings construct independently; namespaces cannot cross-read/write
# ---------------------------------------------------------------------------


class TestNamespaceIsolation:
    def test_two_lab_bindings_get_disjoint_physical_storage(self, tmp_path: Any) -> None:
        paths_a, orch_a = build_stack_for(lab_binding("exp-a"), lab_root=tmp_path)
        paths_b, orch_b = build_stack_for(lab_binding("exp-b"), lab_root=tmp_path)
        assert paths_a.root != paths_b.root
        assert paths_a.state_db != paths_b.state_db
        assert paths_a.facts_db != paths_b.facts_db
        assert orch_a._runtime_id != orch_b._runtime_id

    def test_namespace_a_and_b_cannot_read_each_other(self, tmp_path: Any) -> None:
        paths_a, _ = build_stack_for(lab_binding("exp-a"), lab_root=tmp_path)
        paths_b, _ = build_stack_for(lab_binding("exp-b"), lab_root=tmp_path)

        writer_a = SqliteStateBackend(paths_a.state_db)
        writer_a.save_state(
            make_state(dimension="user.isolation.note", value="A-ONLY")
        )
        writer_a.close()
        writer_b = SqliteStateBackend(paths_b.state_db)
        writer_b.save_state(
            make_state(dimension="user.isolation.note", value="B-ONLY")
        )
        writer_b.close()

        # Independent reconstruction of each runtime sees only its own state.
        _pa, orch_a = build_stack_for(lab_binding("exp-a"), lab_root=tmp_path)
        _pb, orch_b = build_stack_for(lab_binding("exp-b"), lab_root=tmp_path)

        values_a = {s.dimension: s.value for s in orch_a.canonical}
        values_b = {s.dimension: s.value for s in orch_b.canonical}
        assert values_a.get("user.isolation.note") == "A-ONLY"
        assert values_a.get("user.isolation.note") != "B-ONLY"
        assert values_b.get("user.isolation.note") == "B-ONLY"
        assert values_b.get("user.isolation.note") != "A-ONLY"


# ---------------------------------------------------------------------------
# 4. restart with same durable binding restores same state
# ---------------------------------------------------------------------------


class TestRestartStability:
    def test_same_binding_reconnects_to_same_namespace(self, tmp_path: Any) -> None:
        binding = lab_binding("restart-1")
        paths_1 = bind_storage(binding, lab_root=tmp_path)
        paths_2 = bind_storage(binding, lab_root=tmp_path)
        assert paths_1.state_db == paths_2.state_db
        assert paths_1.facts_db == paths_2.facts_db

    def test_process_death_restores_durable_state_via_binding(self, tmp_path: Any) -> None:
        binding = lab_binding("restart-2")
        paths = bind_storage(binding, lab_root=tmp_path)
        writer = SqliteStateBackend(paths.state_db)
        writer.save_state(make_state(dimension="user.sleep.phase", value="awake"))
        writer.close()
        # process exits; a new process re-supplies the same binding
        paths_after = bind_storage(binding, lab_root=tmp_path)
        _p, orchestrator = build_stack_for(binding, lab_root=tmp_path)
        assert paths_after.state_db == paths.state_db
        assert any(
            s.dimension == "user.sleep.phase" and s.value == "awake"
            for s in orchestrator.canonical
        )

    def test_different_binding_into_occupied_namespace_fails_closed(
        self, tmp_path: Any
    ) -> None:
        bind_storage(lab_binding("occupied"), lab_root=tmp_path)
        intruder = lab_binding("occupied", agent_id="some-other-agent")
        with pytest.raises(BindingManifestMismatchError):
            bind_storage(intruder, lab_root=tmp_path)


# ---------------------------------------------------------------------------
# 5/6. fail-closed namespace validation; LAB never defaults to production
# ---------------------------------------------------------------------------


class TestFailClosedNamespace:
    @pytest.mark.parametrize(
        "namespace",
        [
            "",
            "   ",
            "../escape",
            "/absolute",
            "a/../b",
            "trailing/",
            "double//slash",
            "back\\slash",
            "colon:name",
            "..",
        ],
    )
    def test_invalid_namespace_labels_rejected(self, namespace: str) -> None:
        with pytest.raises(RuntimeBindingError):
            lab_binding(namespace)

    def test_lab_binding_may_not_use_production_namespace(self, tmp_path: Any) -> None:
        binding = lab_binding(PRODUCTION_COMPAT_NAMESPACE)
        with pytest.raises(NamespaceIsolationError):
            resolve_storage_paths(binding, lab_root=tmp_path)

    def test_lab_resolution_ignores_production_env_relocation(
        self, tmp_path: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("MR_STATE_DB", str(tmp_path / "ambient-prod.sqlite"))
        monkeypatch.setenv("MR_FACTS_DB", str(tmp_path / "ambient-facts.sqlite"))
        paths = resolve_storage_paths(lab_binding("exp-env"), lab_root=tmp_path / "lab")
        assert paths.state_db == tmp_path / "lab" / "exp-env" / "cognition_state.sqlite"
        assert paths.facts_db == tmp_path / "lab" / "exp-env" / "facts.sqlite"
        assert "ambient" not in str(paths.state_db)

    def test_lab_root_inside_production_root_fails_closed(self, tmp_path: Any) -> None:
        prod = tmp_path / "prod"
        with pytest.raises(NamespaceIsolationError):
            resolve_storage_paths(
                lab_binding("exp-x"), production_root=prod, lab_root=prod / "lab"
            )

    def test_production_root_inside_lab_root_fails_closed(self, tmp_path: Any) -> None:
        lab = tmp_path / "lab"
        with pytest.raises(NamespaceIsolationError):
            resolve_storage_paths(
                lab_binding("exp-x"), production_root=lab / "prod", lab_root=lab
            )

    def test_production_env_override_into_lab_root_fails_closed(
        self, tmp_path: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        lab = tmp_path / "lab"
        monkeypatch.setenv(
            "MR_STATE_DB", str(lab / "smuggled" / "cognition_state.sqlite")
        )
        with pytest.raises(NamespaceIsolationError):
            resolve_storage_paths(
                production_binding("kayla_v0"),
                production_root=tmp_path / "prod",
                lab_root=lab,
            )


# ---------------------------------------------------------------------------
# 7. existing production single-runtime path remains compatible
# ---------------------------------------------------------------------------


class TestProductionCompat:
    def test_production_compat_namespace_resolves_to_default_root(self) -> None:
        paths = resolve_storage_paths(production_binding("kayla_v0"))
        assert paths.root == DEFAULT_PRODUCTION_ROOT
        assert paths.facts_db == DEFAULT_PRODUCTION_ROOT / "facts.sqlite"
        assert paths.state_db == DEFAULT_PRODUCTION_ROOT / "cognition_state.sqlite"

    def test_production_env_relocation_still_honored(
        self, tmp_path: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("MR_FACTS_DB", str(tmp_path / "facts.sqlite"))
        monkeypatch.setenv("MR_STATE_DB", str(tmp_path / "cognition_state.sqlite"))
        paths = resolve_storage_paths(production_binding("kayla_v0"))
        assert paths.facts_db == tmp_path / "facts.sqlite"
        assert paths.state_db == tmp_path / "cognition_state.sqlite"

    def test_explicit_production_namespace_resolves_as_isolated_binding(
        self, tmp_path: Any
    ) -> None:
        production_root = tmp_path / "production"
        paths = resolve_storage_paths(
            RuntimeBinding(
                persona_id="kayla_v0",
                agent_id="hermes-agent-a",
                runtime_id="agent-a",
                storage_namespace="production/other",
                environment=RuntimeEnvironment.PRODUCTION,
            ),
            production_root=production_root,
        )

        assert paths.root == production_root / "production" / "other"
        assert paths.facts_db == paths.root / "facts.sqlite"
        assert paths.state_db == paths.root / "cognition_state.sqlite"
        assert paths.root != DEFAULT_PRODUCTION_ROOT

    def test_default_adapter_wires_production_binding_without_env(
        self, tmp_path: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No env, no explicit binding → production-compat binding to default root."""
        from mind_runtime.host import xiyue_adapter as xa

        monkeypatch.delenv("MR_FACTS_DB", raising=False)
        monkeypatch.delenv("MR_STATE_DB", raising=False)
        monkeypatch.setattr(rb, "DEFAULT_PRODUCTION_ROOT", tmp_path / "prod")
        adapter = xa.default_adapter()
        assert adapter._runtime_id == "xiyue"
        assert (tmp_path / "prod" / "cognition_state.sqlite").exists()
        assert (tmp_path / "prod" / "binding.json").exists()

    def test_default_adapter_rejects_lab_binding(self) -> None:
        from mind_runtime.host import xiyue_adapter as xa

        with pytest.raises(RuntimeBindingError):
            xa.default_adapter(binding=lab_binding("exp-lab"))


# ---------------------------------------------------------------------------
# defaults + manifest identity
# ---------------------------------------------------------------------------


class TestDefaultsAndManifest:
    def test_default_roots_are_disjoint(self) -> None:
        prod = DEFAULT_PRODUCTION_ROOT.resolve()
        lab = DEFAULT_LAB_ROOT.resolve()
        assert prod != lab
        assert prod not in lab.parents
        assert lab not in prod.parents

    def test_manifest_records_full_binding_identity(self, tmp_path: Any) -> None:
        binding = lab_binding("manifest-1", persona_id="kayla_v0")
        paths = bind_storage(binding, lab_root=tmp_path)
        manifest = json.loads(paths.binding_manifest.read_text(encoding="utf-8"))
        assert manifest == {
            "environment": "lab",
            "persona_id": "kayla_v0",
            "agent_id": "mr-lab",
            "runtime_id": "lab-manifest-1",
            "storage_namespace": "manifest-1",
        }

    def test_production_binding_uses_compat_defaults(self) -> None:
        binding = production_binding("kayla_v0")
        assert binding.environment is RuntimeEnvironment.PRODUCTION
        assert binding.storage_namespace == PRODUCTION_COMPAT_NAMESPACE
        assert binding.runtime_id == "xiyue"
        assert binding.agent_id == "hermes-xiyue"
