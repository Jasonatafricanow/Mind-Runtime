"""MR-RUNTIME-02: Hermes RuntimeBinding discovery / restart reconstruction.

Contract under test (MR-RUNTIME-02, on top of ADR-0020):
  * a single discovery authority resolves the Hermes production binding:
    explicit ``binding`` param > ``MR_RUNTIME_BINDING`` reference file > the
    ONE legacy compat default (ADR-0020 §5) — never a directory scan or
    newest-file heuristic;
  * restart resolves a byte-identical durable identity and recovers durable
    state (process death != runtime identity loss);
  * a new Hermes session never creates a new MR runtime;
  * fail-closed: manifest mismatch, LAB reference, partial/ambiguous/invalid
    reference, persona conflict — all reject MR startup, no silent fallback.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from tests.golden.fixtures.common import make_state

from mind_runtime.contracts import Scope, ScopeDomain
from mind_runtime.host.xiyue_adapter import default_adapter
from mind_runtime.runtime_binding import (
    PRODUCTION_COMPAT_NAMESPACE,
    BindingDiscoveryError,
    BindingManifestMismatchError,
    RuntimeBindingError,
    RuntimeEnvironment,
    discover_production_binding,
    production_binding,
)
from mind_runtime.state.persistence import SqliteCommitMarkerStore, SqliteStateBackend


def _relocate_production(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Relocate the production compat namespace into tmp (MR_FACTS_DB/MR_STATE_DB)."""
    monkeypatch.setenv("MR_FACTS_DB", str(tmp_path / "facts.sqlite"))
    monkeypatch.setenv("MR_STATE_DB", str(tmp_path / "cognition_state.sqlite"))
    return tmp_path


def _manifest(root: Path) -> dict[str, str]:
    return json.loads((root / "binding.json").read_text(encoding="utf-8"))


def _write_ref(tmp_path: Path, data: Any, name: str = "binding-ref.json") -> str:
    ref = tmp_path / name
    ref.write_text(json.dumps(data), encoding="utf-8")
    return str(ref)


def _production_ref(**overrides: str) -> dict[str, str]:
    data = {
        "environment": "production",
        "persona_id": "kayla_v0",
        "agent_id": "hermes-xiyue",
        "runtime_id": "xiyue",
        "storage_namespace": PRODUCTION_COMPAT_NAMESPACE,
    }
    data.update(overrides)
    return data


# ---------------------------------------------------------------------------
# discovery authority (pure)
# ---------------------------------------------------------------------------


class TestDiscoveryAuthority:
    def test_no_reference_resolves_legacy_compat_default(self) -> None:
        binding = discover_production_binding(persona_id="kayla_v0")
        assert binding == production_binding("kayla_v0")
        assert binding.environment is RuntimeEnvironment.PRODUCTION
        assert binding.runtime_id == "xiyue"
        assert binding.agent_id == "hermes-xiyue"
        assert binding.storage_namespace == PRODUCTION_COMPAT_NAMESPACE

    def test_explicit_reference_file_is_honored(self, tmp_path: Path) -> None:
        ref = _write_ref(tmp_path, _production_ref())
        binding = discover_production_binding(persona_id="kayla_v0", binding_ref=ref)
        assert binding.runtime_id == "xiyue"
        assert binding.agent_id == "hermes-xiyue"

    def test_env_var_reference_is_honored(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ref = _write_ref(tmp_path, _production_ref())
        monkeypatch.setenv("MR_RUNTIME_BINDING", ref)
        binding = discover_production_binding(persona_id="kayla_v0")
        assert binding.storage_namespace == PRODUCTION_COMPAT_NAMESPACE

    def test_explicit_arg_beats_env_var(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        env_ref = _write_ref(tmp_path, _production_ref(), name="env-ref.json")
        arg_ref = _write_ref(
            tmp_path, _production_ref(agent_id="explicit-agent"), name="arg-ref.json"
        )
        monkeypatch.setenv("MR_RUNTIME_BINDING", env_ref)
        binding = discover_production_binding(persona_id="kayla_v0", binding_ref=arg_ref)
        assert binding.agent_id == "explicit-agent"

    def test_partial_reference_rejected_no_second_fallback(self, tmp_path: Path) -> None:
        partial = {
            "environment": "production",
            "agent_id": "hermes-xiyue",
            "storage_namespace": PRODUCTION_COMPAT_NAMESPACE,
            # runtime_id missing
        }
        ref = _write_ref(tmp_path, partial)
        with pytest.raises(BindingDiscoveryError):
            discover_production_binding(persona_id="kayla_v0", binding_ref=ref)

    def test_ambiguous_reference_rejected_not_newest_wins(self, tmp_path: Path) -> None:
        ref = _write_ref(
            tmp_path,
            [
                _production_ref(),
                _production_ref(agent_id="other-agent"),
            ],
        )
        with pytest.raises(BindingDiscoveryError):
            discover_production_binding(persona_id="kayla_v0", binding_ref=ref)

    def test_empty_reference_rejected(self, tmp_path: Path) -> None:
        ref = _write_ref(tmp_path, [])
        with pytest.raises(BindingDiscoveryError):
            discover_production_binding(persona_id="kayla_v0", binding_ref=ref)

    def test_lab_reference_rejected_by_production_bootstrap(self, tmp_path: Path) -> None:
        ref = _write_ref(tmp_path, _production_ref(environment="lab"))
        with pytest.raises(BindingDiscoveryError):
            discover_production_binding(persona_id="kayla_v0", binding_ref=ref)

    def test_persona_conflict_rejected(self, tmp_path: Path) -> None:
        ref = _write_ref(tmp_path, _production_ref(persona_id="someone-else"))
        with pytest.raises(BindingDiscoveryError):
            discover_production_binding(persona_id="kayla_v0", binding_ref=ref)

    def test_invalid_namespace_rejected(self, tmp_path: Path) -> None:
        ref = _write_ref(tmp_path, _production_ref(storage_namespace="../escape"))
        with pytest.raises(RuntimeBindingError):
            discover_production_binding(persona_id="kayla_v0", binding_ref=ref)

    def test_unknown_fields_rejected(self, tmp_path: Path) -> None:
        ref = _write_ref(tmp_path, _production_ref(surprise_field="x"))
        with pytest.raises(BindingDiscoveryError):
            discover_production_binding(persona_id="kayla_v0", binding_ref=ref)

    def test_no_directory_scanning_newest_file_heuristic(self, tmp_path: Path) -> None:
        """Decoy binding files anywhere in the tree must not influence discovery."""
        decoys = tmp_path / "decoys"
        decoys.mkdir()
        (decoys / "binding.json").write_text(
            json.dumps(_production_ref(agent_id="newest-decoy")), encoding="utf-8"
        )
        (tmp_path / "production").mkdir()
        (tmp_path / "production" / "runtime.json").write_text(
            json.dumps(_production_ref(runtime_id="runtime-decoy")), encoding="utf-8"
        )
        binding = discover_production_binding(persona_id="kayla_v0")
        assert binding == production_binding("kayla_v0")


# ---------------------------------------------------------------------------
# production boot / restart reconstruction
# ---------------------------------------------------------------------------


class TestProductionBoot:
    def test_boot_resolves_expected_binding(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _relocate_production(tmp_path, monkeypatch)
        adapter = default_adapter()
        assert adapter._runtime_id == "xiyue"
        manifest = _manifest(tmp_path)
        assert manifest == {
            "environment": "production",
            "persona_id": "kayla_v0",
            "agent_id": "hermes-xiyue",
            "runtime_id": "xiyue",
            "storage_namespace": PRODUCTION_COMPAT_NAMESPACE,
        }

    def test_boot_with_env_reference_uses_it(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _relocate_production(tmp_path, monkeypatch)
        ref = _write_ref(tmp_path, _production_ref())
        monkeypatch.setenv("MR_RUNTIME_BINDING", ref)
        default_adapter()
        assert _manifest(tmp_path)["agent_id"] == "hermes-xiyue"

    def test_explicit_binding_param_beats_env_reference(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _relocate_production(tmp_path, monkeypatch)
        ref = _write_ref(tmp_path, _production_ref(agent_id="env-agent"))
        monkeypatch.setenv("MR_RUNTIME_BINDING", ref)
        default_adapter(binding=production_binding("kayla_v0"))
        assert _manifest(tmp_path)["agent_id"] == "hermes-xiyue"

    def test_wrong_manifest_fails_closed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        root = _relocate_production(tmp_path, monkeypatch)
        stale = {
            "environment": "production",
            "persona_id": "kayla_v0",
            "agent_id": "hermes-xiyue",
            "runtime_id": "another-runtime",  # configured boot says "xiyue"
            "storage_namespace": PRODUCTION_COMPAT_NAMESPACE,
        }
        (root / "binding.json").write_text(json.dumps(stale), encoding="utf-8")
        with pytest.raises(BindingManifestMismatchError):
            default_adapter()

    def test_state_survives_process_reconstruction(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        root = _relocate_production(tmp_path, monkeypatch)
        # boot #1: durable write, then the process dies
        boot1 = default_adapter()
        assert boot1 is not None
        writer = SqliteStateBackend(root / "cognition_state.sqlite")
        writer.save_state(make_state(dimension="user.sleep.phase", value="awake"))
        writer.close()
        # boot #2: same discovery chain, existing manifest verified, state recovered
        boot2 = default_adapter()
        canonical = {
            s.dimension: s.value for s in boot2._port.orchestrator._canonical.values()
        }
        assert canonical.get("user.sleep.phase") == "awake"


class TestNoSessionCoupling:
    def test_new_hermes_session_does_not_create_new_runtime(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        root = _relocate_production(tmp_path, monkeypatch)
        monkeypatch.setenv("MR_ENABLED", "true")
        adapter = default_adapter()
        manifest_before = (root / "binding.json").read_bytes()

        h1 = adapter.begin_turn(
            message="hello", channel="chat", session_id="session-A", message_id="m-1"
        )
        assert h1 is not None
        assert adapter.commit_turn(h1)
        # a second, unrelated Hermes conversation — same runtime, new session id
        h2 = adapter.begin_turn(
            message="different conversation",
            channel="chat",
            session_id="session-B",
            message_id="m-2",
        )
        assert h2 is not None
        assert h1.interaction_id != h2.interaction_id
        assert adapter.commit_turn(h2)

        # a reconstructed "process" (new adapter object) serves a brand-new session
        # on the SAME durable runtime — not a fresh MR
        boot2 = default_adapter()
        h3 = boot2.begin_turn(
            message="after restart", channel="chat", session_id="session-C", message_id="m-3"
        )
        assert h3 is not None
        assert boot2.commit_turn(h3)

        # all three sessions landed in the ONE namespace; binding identity unchanged
        assert (root / "binding.json").read_bytes() == manifest_before
        markers = SqliteCommitMarkerStore(root / "cognition_state.sqlite")
        scope = Scope(domain=ScopeDomain.USER, user_id="user")
        assert markers.has_commit(interaction_id=h1.interaction_id, scope=scope)
        assert markers.has_commit(interaction_id=h2.interaction_id, scope=scope)
        assert markers.has_commit(interaction_id=h3.interaction_id, scope=scope)
