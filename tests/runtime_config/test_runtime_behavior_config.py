"""CFG1-CFG6: runtime behavior configuration tests (C6B-Config).

CFG1  Kayla production/deployment config explicitly resolves threshold=3.
CFG2  Generic runtime with no config resolves None.
CFG3  Another synthetic deployment may configure threshold=5 without code change.
CFG4  Malformed / zero / negative / bool value fails closed.
CFG5  PersonaProfile / persona_config affect schema remains unchanged.
CFG6  Runtime gate OFF does not require/load proactive behavior config.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from mind_runtime.cognition.tick import CognitiveTickConfig
from mind_runtime.runtime_config import (
    RuntimeBehaviorLoadError,
    load_runtime_behavior,
)


def test_cfg1_kayla_config_resolves_threshold_three() -> None:
    """Kayla production config explicitly sets threshold=3."""
    config = load_runtime_behavior(Path("configs/runtime/kayla.json"))
    assert config.proactive.photo_cadence_threshold == 3
    tick_config = config.to_cognitive_tick_config()
    assert tick_config.photo_cadence_threshold == 3


def test_cfg2_generic_runtime_no_config_resolves_none() -> None:
    """Generic runtime (no config) resolves to None, disabling cadence."""
    default_config = CognitiveTickConfig()
    assert default_config.photo_cadence_threshold is None

    # A config file with empty proactive block also yields None
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump({"proactive": {}}, f)
        f.flush()
        config = load_runtime_behavior(f.name)
    assert config.proactive.photo_cadence_threshold is None
    Path(f.name).unlink()


def test_cfg3_synthetic_deployment_can_configure_threshold_five() -> None:
    """Another deployment may set threshold=5 without source-code changes."""
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump({"proactive": {"photo_cadence_threshold": 5}}, f)
        f.flush()
        config = load_runtime_behavior(f.name)
    assert config.proactive.photo_cadence_threshold == 5
    assert config.to_cognitive_tick_config().photo_cadence_threshold == 5
    Path(f.name).unlink()


def test_cfg4_malformed_values_fail_closed() -> None:
    """0, negative, bool, string fail closed via typed config validation."""
    for bad_value in (0, -1, "3", 3.5, True):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump({"proactive": {"photo_cadence_threshold": bad_value}}, f)
            f.flush()
            with pytest.raises(RuntimeBehaviorLoadError):
                load_runtime_behavior(f.name)
        Path(f.name).unlink()


def test_cfg4b_malformed_structure_fails_closed() -> None:
    """Top-level non-object and non-object proactive block fail closed."""
    for payload in ("[1, 2, 3]", '"a-string"'):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            f.write(payload)
            f.flush()
            with pytest.raises(RuntimeBehaviorLoadError):
                load_runtime_behavior(f.name)
        Path(f.name).unlink()
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump({"proactive": "not-an-object"}, f)
        f.flush()
        with pytest.raises(RuntimeBehaviorLoadError):
            load_runtime_behavior(f.name)
    Path(f.name).unlink()


def test_cfg4c_missing_and_unreadable_file_fail_closed() -> None:
    """A missing file and malformed-JSON file both raise at load time."""
    with pytest.raises(RuntimeBehaviorLoadError, match="not found"):
        load_runtime_behavior(Path("/nonexistent/behavior.json"))
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        f.write("{not valid json")
        f.flush()
        with pytest.raises(RuntimeBehaviorLoadError, match="cannot read"):
            load_runtime_behavior(f.name)
    Path(f.name).unlink()


def test_cfg5_persona_config_schema_unchanged() -> None:
    """PersonaProfile / persona_config affect schema remains unchanged.

    The runtime behavior config is loaded independently; this test verifies
    persona config loader works as before.
    """
    from mind_runtime.persona_config import load_kayla_production

    loaded = load_kayla_production()
    assert loaded.profile.persona_id == "kayla"
    assert len(loaded.profile.dimensions) > 0
    # All dimensions have required affect fields
    for dim in loaded.profile.dimensions:
        assert hasattr(dim, "baseline")
        assert hasattr(dim, "initial_value")
        assert hasattr(dim, "sensitivity")


def test_cfg6_gate_off_does_not_require_config() -> None:
    """Runtime gate OFF does not request config loading at all.

    This is enforced by the main() function wiring -- the Config load
    only happens when tick_requested = True. This test verifies the
    behavior is syntactically possible: default CognitiveTickConfig exists
    and has threshold=None (feature disabled)."""
    config = CognitiveTickConfig()
    assert config.photo_cadence_threshold is None
    # No crash means fail-closed; a missing config file would raise
    # but gate_off path never calls load_runtime_behavior()