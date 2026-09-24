"""Targeted tests for CognitiveMode v0 concept layer (MR-COGNITIVE-MODES-V0-CONTRACT-01)."""

import ast
import json
from pathlib import Path

import pytest

from mind_runtime.cognition.modes import (
    BACKGROUND_LCE_STATUS,
    COGNITIVE_MODE_AUTHORITY_INVARIANTS,
    COGNITIVE_MODE_V0_REGISTRY,
    LEGACY_INTROSPECTIVE_PULL_KEY,
    MODE_CONTROLLER_STATUS,
    PLANNED_FATIGUE_STATE_KEY,
    TRANSITION_POLICY_STATUS,
    CognitiveMode,
    CognitiveModeSpec,
    get_cognitive_mode_spec,
)


def test_registry_contains_exactly_five_modes() -> None:
    """Registry must contain exactly the 5 frozen cognitive modes."""
    expected_modes = {
        CognitiveMode.ACTIVE,
        CognitiveMode.INTROSPECTIVE,
        CognitiveMode.DAYDREAM,
        CognitiveMode.SLEEP,
        CognitiveMode.DREAM,
    }
    assert len(CognitiveMode) == 5
    assert len(COGNITIVE_MODE_V0_REGISTRY) == 5
    assert set(COGNITIVE_MODE_V0_REGISTRY.keys()) == expected_modes
    assert {m.name for m in CognitiveMode} == {
        "ACTIVE",
        "INTROSPECTIVE",
        "DAYDREAM",
        "SLEEP",
        "DREAM",
    }


def test_all_mode_ids_unique() -> None:
    """All mode identifiers must be unique."""
    enum_values = [m.value for m in CognitiveMode]
    assert len(enum_values) == len(set(enum_values)) == 5

    spec_mode_values = [spec.mode.value for spec in COGNITIVE_MODE_V0_REGISTRY.values()]
    assert len(spec_mode_values) == len(set(spec_mode_values)) == 5


def test_dream_is_sleep_associated() -> None:
    """DREAM is logically sleep-associated with SLEEP as parent_mode."""
    dream_spec = COGNITIVE_MODE_V0_REGISTRY[CognitiveMode.DREAM]
    assert dream_spec.parent_mode == CognitiveMode.SLEEP

    # Verify other modes do not claim SLEEP as parent
    for mode, spec in COGNITIVE_MODE_V0_REGISTRY.items():
        if mode != CognitiveMode.DREAM:
            assert spec.parent_mode is None


def test_daydream_is_interruptible() -> None:
    """DAYDREAM is immediately interruptible."""
    daydream_spec = COGNITIVE_MODE_V0_REGISTRY[CognitiveMode.DAYDREAM]
    assert daydream_spec.interruptible is True


def test_introspective_is_internal_background() -> None:
    """INTROSPECTIVE is internal background reflection."""
    intro_spec = COGNITIVE_MODE_V0_REGISTRY[CognitiveMode.INTROSPECTIVE]
    assert intro_spec.background_processing is True
    assert intro_spec.interactive is False


def test_sleep_does_not_authorize_outbound_action() -> None:
    """SLEEP mode does not authorize outbound action directly."""
    sleep_spec = COGNITIVE_MODE_V0_REGISTRY[CognitiveMode.SLEEP]
    assert sleep_spec.outbound_allowed_by_mode is False


def test_dream_does_not_authorize_outbound_action() -> None:
    """DREAM mode does not authorize outbound action directly."""
    dream_spec = COGNITIVE_MODE_V0_REGISTRY[CognitiveMode.DREAM]
    assert dream_spec.outbound_allowed_by_mode is False


def test_candidate_only_outputs_for_non_active_modes() -> None:
    """Dream, daydream, and introspection outputs must be candidate-only."""
    for mode in (
        CognitiveMode.DREAM,
        CognitiveMode.DAYDREAM,
        CognitiveMode.INTROSPECTIVE,
        CognitiveMode.SLEEP,
    ):
        spec = COGNITIVE_MODE_V0_REGISTRY[mode]
        assert spec.candidate_output_only is True, f"{mode} must be candidate_output_only"

    # ACTIVE is normal turn execution
    assert COGNITIVE_MODE_V0_REGISTRY[CognitiveMode.ACTIVE].candidate_output_only is False


def test_cognitive_mode_module_does_not_import_body_provider_or_llm() -> None:
    """modes.py must not import Body, provider, LLM, or network libraries."""
    module_path = (
        Path(__file__).resolve().parent.parent.parent
        / "src"
        / "mind_runtime"
        / "cognition"
        / "modes.py"
    )
    assert module_path.is_file(), f"modes.py not found at {module_path}"

    tree = ast.parse(module_path.read_text(encoding="utf-8"))

    forbidden_tokens = {
        "body",
        "provider",
        "llm",
        "openai",
        "anthropic",
        "google",
        "litellm",
        "langchain",
        "requests",
        "urllib",
        "http",
        "socket",
    }

    imported_modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported_modules.add(alias.name.lower())
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imported_modules.add(node.module.lower())

    for mod in imported_modules:
        for token in forbidden_tokens:
            assert token not in mod, f"Forbidden import '{mod}' found in modes.py"


def test_no_numeric_thresholds_exist_in_module() -> None:
    """No numeric thresholds, durations, probabilities, or rates exist in modes.py."""
    module_path = (
        Path(__file__).resolve().parent.parent.parent
        / "src"
        / "mind_runtime"
        / "cognition"
        / "modes.py"
    )
    tree = ast.parse(module_path.read_text(encoding="utf-8"))

    # Verify no numeric literal constants exist in the AST of modes.py
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant):
            assert not (
                isinstance(node.value, (int, float))
                and not isinstance(node.value, bool)
            ), (
                f"Numeric literal constant {node.value} found in modes.py"
            )

    # Verify all specs in the registry contain zero numeric values
    for spec in COGNITIVE_MODE_V0_REGISTRY.values():
        for field_name in (
            "mode",
            "purpose",
            "interactive",
            "background_processing",
            "outbound_allowed_by_mode",
            "interruptible",
            "parent_mode",
            "candidate_output_only",
            "future_consumers",
        ):
            val = getattr(spec, field_name)
            assert not (isinstance(val, (int, float)) and not isinstance(val, bool)), (
                f"Field {field_name} in {spec.mode} has numeric value: {val}"
            )



def test_legacy_introspective_pull_is_not_renamed() -> None:
    """Legacy agent.affect.introspective_pull remains untouched in persona config."""
    config_path = (
        Path(__file__).resolve().parent.parent.parent
        / "configs"
        / "personas"
        / "kayla.json"
    )
    assert config_path.is_file(), f"kayla.json not found at {config_path}"

    kayla_raw = json.loads(config_path.read_text(encoding="utf-8"))
    dimensions = [d["dimension"] for d in kayla_raw.get("dimensions", [])]

    assert "agent.affect.introspective_pull" in dimensions, (
        "agent.affect.introspective_pull must remain in persona configuration"
    )
    assert LEGACY_INTROSPECTIVE_PULL_KEY == "agent.affect.introspective_pull"

    # Explicit boundary check: dimension key is not equal to CognitiveMode.INTROSPECTIVE
    assert LEGACY_INTROSPECTIVE_PULL_KEY != CognitiveMode.INTROSPECTIVE
    assert LEGACY_INTROSPECTIVE_PULL_KEY != CognitiveMode.INTROSPECTIVE.value


def test_fatigue_boundary() -> None:
    """Fatigue is a planned affect key, not a CognitiveMode or threshold."""
    assert PLANNED_FATIGUE_STATE_KEY == "agent.affect.fatigue"
    assert PLANNED_FATIGUE_STATE_KEY not in [m.value for m in CognitiveMode]


def test_authority_invariants_and_status_markers() -> None:
    """Verify non-negotiable authority invariants and non-implemented status markers."""
    assert len(COGNITIVE_MODE_AUTHORITY_INVARIANTS) == 10
    for inv in COGNITIVE_MODE_AUTHORITY_INVARIANTS:
        assert isinstance(inv, str) and len(inv) > 0

    assert MODE_CONTROLLER_STATUS == "NOT_IMPLEMENTED"
    assert TRANSITION_POLICY_STATUS == "NOT_IMPLEMENTED"
    assert BACKGROUND_LCE_STATUS == "NOT_IMPLEMENTED"


def test_get_cognitive_mode_spec_lookup() -> None:
    """get_cognitive_mode_spec must support enum and string lookups case-insensitively."""
    assert (
        get_cognitive_mode_spec(CognitiveMode.ACTIVE)
        == COGNITIVE_MODE_V0_REGISTRY[CognitiveMode.ACTIVE]
    )
    assert get_cognitive_mode_spec("active") == COGNITIVE_MODE_V0_REGISTRY[CognitiveMode.ACTIVE]
    assert get_cognitive_mode_spec("ACTIVE") == COGNITIVE_MODE_V0_REGISTRY[CognitiveMode.ACTIVE]
    assert get_cognitive_mode_spec("dream") == COGNITIVE_MODE_V0_REGISTRY[CognitiveMode.DREAM]
    assert get_cognitive_mode_spec("DREAM") == COGNITIVE_MODE_V0_REGISTRY[CognitiveMode.DREAM]

    with pytest.raises(KeyError):
        get_cognitive_mode_spec("unknown_mode")


def test_spec_immutability_and_validation() -> None:
    """CognitiveModeSpec and registry must be immutable and fail closed on invalid inputs."""
    spec = COGNITIVE_MODE_V0_REGISTRY[CognitiveMode.ACTIVE]
    with pytest.raises(AttributeError):
        spec.interactive = False  # type: ignore[misc]

    with pytest.raises(TypeError):
        COGNITIVE_MODE_V0_REGISTRY[CognitiveMode.ACTIVE] = spec  # type: ignore[index]

    # Dream must have sleep as parent
    with pytest.raises(ValueError, match="DREAM mode must have SLEEP as parent_mode"):
        CognitiveModeSpec(
            mode=CognitiveMode.DREAM,
            purpose="test",
            interactive=False,
            background_processing=True,
            outbound_allowed_by_mode=False,
            interruptible=True,
            parent_mode=None,
            candidate_output_only=True,
        )

    # Sleep must not allow outbound
    with pytest.raises(ValueError, match="sleep must not authorize outbound action"):
        CognitiveModeSpec(
            mode=CognitiveMode.SLEEP,
            purpose="test",
            interactive=False,
            background_processing=True,
            outbound_allowed_by_mode=True,
            interruptible=True,
            parent_mode=None,
            candidate_output_only=True,
        )
