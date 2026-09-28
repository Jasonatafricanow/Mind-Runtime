"""Production online semantics are Body/Host-owned.

The certified manifest keeps the legacy semantic-provider config fields for
backward-compatible decoding, but production composition must not construct an
MR-local semantic or appraisal model and must not require model credentials.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SEAM = REPO / "xiyue" / "mr_seam.py"


def _load_seam():
    spec = importlib.util.spec_from_file_location("mr_seam", str(SEAM))
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_legacy_semantic_provider_modes_still_decode() -> None:
    from mind_runtime.validation.contracts import _semantic

    disabled = _semantic(
        {"mode": "disabled", "minimum_confidence": 0.75, "conflict_margin": 0.1}
    )
    enabled = _semantic(
        {"mode": "enabled", "minimum_confidence": 0.75, "conflict_margin": 0.1}
    )
    assert disabled.mode == "disabled"
    assert enabled.mode == "enabled"


def test_legacy_semantic_provider_rejects_unknown_mode() -> None:
    from mind_runtime.validation.contracts import _semantic

    for bad in ("model_backed", "on", "true", "bogus", ""):
        with pytest.raises(ValueError):
            _semantic(
                {"mode": bad, "minimum_confidence": 0.75, "conflict_margin": 0.1}
            )


def test_production_composition_never_constructs_local_semantic_provider(
    monkeypatch,
) -> None:
    monkeypatch.setenv("MR_SEMANTIC_PROVIDER", "glm")
    monkeypatch.setenv("GLM_API_KEY", "must-not-be-consumed")
    seam = _load_seam()
    composition = seam._load_production_composition()
    assert composition["semantic_provider"] is None


def test_production_composition_never_constructs_local_appraisal_provider(
    monkeypatch,
) -> None:
    monkeypatch.setenv("APPRAISAL_API_KEY", "must-not-be-consumed")
    seam = _load_seam()
    composition = seam._load_production_composition()
    assert composition["appraisal_producer"] is None


def test_production_composition_requires_no_model_credentials(monkeypatch) -> None:
    monkeypatch.delenv("MR_SEMANTIC_PROVIDER", raising=False)
    monkeypatch.delenv("GLM_API_KEY", raising=False)
    monkeypatch.delenv("APPRAISAL_API_KEY", raising=False)
    seam = _load_seam()
    composition = seam._load_production_composition()
    assert composition["semantic_provider"] is None
    assert composition["appraisal_producer"] is None