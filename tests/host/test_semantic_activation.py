"""HERMES-SEMANTIC-PROVIDER-PRODUCTION-ACTIVATION — activation/negative tests.

Covers the frozen authority (2026-09-05):
  * semantic_provider.mode accepts exactly "disabled" | "enabled"; rejected otherwise.
  * mode=disabled -> provider absent by design (None).
  * mode=enabled  -> host MUST construct the existing provider via
                     create_semantic_provider(); missing selector/credential
                     FAILS CLOSED at composition (never silently downgrade).
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

from mind_runtime.validation.digest import canonical_json_bytes

REPO = Path(__file__).resolve().parents[2]
MANIFEST = REPO / "certification" / "d11s" / "inputs" / "runtime-config.json"
SEAM = REPO / "xiyue" / "mr_seam.py"


def _load_seam():
    spec = importlib.util.spec_from_file_location("mr_seam", str(SEAM))
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write_disabled_manifest(tmp_path: Path) -> Path:
    """Copy the production manifest but flip semantic_provider.mode to disabled."""
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    for component in data["components"]:
        if component["component_id"] == "semantic_provider":
            component["payload"]["mode"] = "disabled"
            component["payload_sha256"] = hashlib.sha256(
                canonical_json_bytes(component["payload"])
            ).hexdigest()
    target = tmp_path / "runtime-config.json"
    target.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return target


# ── Contract (decoder) ───────────────────────────────────────────────────────


def test_semantic_provider_mode_accepts_disabled_and_enabled() -> None:
    from mind_runtime.validation.contracts import _semantic

    disabled = _semantic({"mode": "disabled", "minimum_confidence": 0.75, "conflict_margin": 0.1})
    assert disabled.mode == "disabled"
    enabled = _semantic({"mode": "enabled", "minimum_confidence": 0.75, "conflict_margin": 0.1})
    assert enabled.mode == "enabled"


def test_semantic_provider_rejects_invalid_mode() -> None:
    from mind_runtime.validation.contracts import _semantic

    for bad in ("model_backed", "on", "true", "bogus", ""):
        with pytest.raises(ValueError):
            _semantic({"mode": bad, "minimum_confidence": 0.75, "conflict_margin": 0.1})


# ── Seam composition (activation / fail-closed) ──────────────────────────────


def test_mode_enabled_missing_provider_selection_fails_closed(monkeypatch) -> None:
    monkeypatch.delenv("MR_SEMANTIC_PROVIDER", raising=False)
    monkeypatch.delenv("GLM_API_KEY", raising=False)
    seam = _load_seam()
    with pytest.raises(RuntimeError):
        seam._load_production_composition()


def test_mode_enabled_missing_provider_credential_fails_closed(monkeypatch) -> None:
    monkeypatch.setenv("MR_SEMANTIC_PROVIDER", "glm")
    monkeypatch.delenv("GLM_API_KEY", raising=False)
    seam = _load_seam()
    with pytest.raises(RuntimeError):
        seam._load_production_composition()


def test_mode_enabled_constructs_provider(monkeypatch) -> None:
    monkeypatch.setenv("MR_SEMANTIC_PROVIDER", "glm")
    monkeypatch.setenv("GLM_API_KEY", "test-key")
    seam = _load_seam()
    composition = seam._load_production_composition()
    assert composition["semantic_provider"] is not None
    assert "glm" in type(composition["semantic_provider"]).__name__.lower()


def test_mode_disabled_provider_absent(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("MR_SEMANTIC_PROVIDER", raising=False)
    disabled_cfg = _write_disabled_manifest(tmp_path)
    monkeypatch.setenv("MR_RUNTIME_CONFIG", str(disabled_cfg))
    seam = _load_seam()
    composition = seam._load_production_composition()
    assert composition["semantic_provider"] is None