"""Targeted tests for MR Fast Function V1 product-level fast-state lock.

Verifies requirements A through L:
A. FAST_FUNCTION_V1 contains exactly 8 entries.
B. All eight canonical keys are unique.
C. Every state has exactly one primary function (bijective mapping).
D. Existing restlessness key remains unchanged.
E. restlessness product semantics are activation/excitation.
F. diligence_pressure maps to FOLLOW_UP_PERSISTENCE, not a frequency/cooldown modifier.
G. fatigue has no outbound-action consumer.
H. fatigue is associated only with cognitive-rest mode ownership.
I. legacy states are not deleted and stay outside V1 lock.
J. module has no dependency on provider / Body / LLM.
K. no numeric psychological calibration is introduced.
L. existing Surface/Intent tests remain green (checked in regression run).
"""

import ast
import json
from pathlib import Path

import pytest

from mind_runtime.dynamics.fast_functions import (
    FAST_FUNCTION_V1_REGISTRY,
    FAST_FUNCTION_V1_SPECS,
    FOLLOW_UP_PERSISTENCE_NOT_FREQUENCY_INVARIANT,
    FastFunctionKind,
    FastFunctionRegistry,
    FastStateFunctionSpec,
    FastStateStatus,
    validate_diligence_anti_spam_invariant,
)
from mind_runtime.dynamics.kayla_v0 import kayla_v0_profile


def test_a_fast_function_v1_contains_exactly_eight_entries() -> None:
    """A. FAST_FUNCTION_V1 contains exactly 8 entries."""
    assert len(FAST_FUNCTION_V1_SPECS) == 8
    assert len(FAST_FUNCTION_V1_REGISTRY) == 8


def test_b_all_eight_canonical_keys_are_unique() -> None:
    """B. All eight canonical keys are unique."""
    keys = [spec.state_key for spec in FAST_FUNCTION_V1_SPECS]
    assert len(keys) == 8
    assert len(set(keys)) == 8
    for key in keys:
        assert key.startswith("agent.affect.")
        assert FAST_FUNCTION_V1_REGISTRY.get(key) is not None
        assert FAST_FUNCTION_V1_REGISTRY.require(key).state_key == key


def test_c_every_state_has_exactly_one_primary_function() -> None:
    """C. Every state has exactly one primary function."""
    kinds = [spec.function_kind for spec in FAST_FUNCTION_V1_SPECS]
    assert len(kinds) == 8
    assert len(set(kinds)) == 8

    # Verify each FastFunctionKind is represented exactly once
    for kind in FastFunctionKind:
        spec = FAST_FUNCTION_V1_REGISTRY.get_by_function(kind)
        assert spec is not None
        assert spec.function_kind == kind
        assert FAST_FUNCTION_V1_REGISTRY.require_by_function(kind) == spec


def test_d_existing_restlessness_key_remains_unchanged() -> None:
    """D. Existing restlessness key remains unchanged."""
    assert "agent.affect.restlessness" in FAST_FUNCTION_V1_REGISTRY
    spec = FAST_FUNCTION_V1_REGISTRY["agent.affect.restlessness"]
    assert spec.state_key == "agent.affect.restlessness"
    # Must NOT rename to activation or excitation
    assert "agent.affect.activation" not in FAST_FUNCTION_V1_REGISTRY
    assert "agent.affect.excitation" not in FAST_FUNCTION_V1_REGISTRY


def test_e_restlessness_product_semantics_are_activation_excitation() -> None:
    """E. restlessness product semantics are activation/excitation."""
    spec = FAST_FUNCTION_V1_REGISTRY["agent.affect.restlessness"]
    assert spec.product_label is not None
    assert "activation" in spec.product_label.lower()
    assert "excitation" in spec.product_label.lower()
    assert spec.function_kind == FastFunctionKind.ACTIVITY_WAKE
    assert spec.primary_consumer == "CognitiveTicker / wake-reconsider path"
    assert spec.external_action_capable is False


def test_f_diligence_pressure_maps_to_follow_up_persistence_not_frequency() -> None:
    """F. diligence_pressure maps to FOLLOW_UP_PERSISTENCE, not a frequency/cooldown modifier."""
    spec = FAST_FUNCTION_V1_REGISTRY["agent.affect.diligence_pressure"]
    assert spec.function_kind == FastFunctionKind.FOLLOW_UP_PERSISTENCE
    assert spec.function_kind != "FOLLOW_UP_FREQUENCY"
    assert "frequency" not in spec.function_kind.value.lower()
    assert "cooldown" not in spec.function_kind.value.lower()

    # Executable invariant constant
    assert (
        FOLLOW_UP_PERSISTENCE_NOT_FREQUENCY_INVARIANT
        == "FOLLOW_UP_PERSISTENCE != FOLLOW_UP_FREQUENCY"
    )

    # Executable anti-spam invariant check: higher diligence must NOT shorten cooldown
    assert validate_diligence_anti_spam_invariant(
        diligence_pressure=0.9,
        base_cooldown_seconds=300.0,
        effective_cooldown_seconds=300.0,
    )
    with pytest.raises(ValueError, match="Diligence anti-spam violation"):
        validate_diligence_anti_spam_invariant(
            diligence_pressure=0.9,
            base_cooldown_seconds=300.0,
            effective_cooldown_seconds=120.0,
        )


def test_g_fatigue_has_no_outbound_action_consumer() -> None:
    """G. fatigue has no outbound-action consumer."""
    spec = FAST_FUNCTION_V1_REGISTRY["agent.affect.fatigue"]
    assert spec.external_action_capable is False

    consumer_lower = spec.primary_consumer.lower()
    for forbidden in ("outbound", "message", "send", "proactive", "share", "expression"):
        assert forbidden not in consumer_lower, f"Forbidden term {forbidden!r} in fatigue consumer"


def test_h_fatigue_is_associated_only_with_cognitive_rest_mode_ownership() -> None:
    """H. fatigue is associated only with cognitive-rest mode ownership."""
    spec = FAST_FUNCTION_V1_REGISTRY["agent.affect.fatigue"]
    assert spec.function_kind == FastFunctionKind.COGNITIVE_REST_PRESSURE
    assert spec.status == FastStateStatus.REGISTERED_ONLY
    assert "cognitive-mode" in spec.primary_consumer or "homeostasis" in spec.primary_consumer


def test_i_legacy_states_are_not_deleted() -> None:
    """I. legacy states are not deleted and remain outside FAST_FUNCTION_V1."""
    legacy_keys = [
        "agent.affect.closeness_craving",
        "agent.affect.social_pull",
        "agent.affect.introspective_pull",
        "agent.affect.anxiety",
    ]
    # None of these legacy states are members of FAST_FUNCTION_V1_REGISTRY
    for key in legacy_keys:
        assert key not in FAST_FUNCTION_V1_REGISTRY

    # But they exist in persona definitions / configurations
    kayla_json_path = Path(__file__).resolve().parents[2] / "configs" / "personas" / "kayla.json"
    assert kayla_json_path.exists()
    with open(kayla_json_path, encoding="utf-8") as f:
        kayla_data = json.load(f)
    kayla_dims = {d["dimension"] for d in kayla_data["dimensions"]}

    for key in (
        "agent.affect.closeness_craving",
        "agent.affect.social_pull",
        "agent.affect.introspective_pull",
    ):
        assert key in kayla_dims, f"Legacy state {key} missing from kayla.json"

    # anxiety exists in kayla_v0 test profile
    v0_dims = {d.dimension for d in kayla_v0_profile().dimensions}
    assert "agent.affect.anxiety" in v0_dims

    # introspective_pull is NOT the authority for fatigue / sleep
    fatigue_spec = FAST_FUNCTION_V1_REGISTRY["agent.affect.fatigue"]
    assert fatigue_spec.state_key != "agent.affect.introspective_pull"


def test_j_module_has_no_dependency_on_provider_body_llm() -> None:
    """J. module has no dependency on provider / Body / LLM."""
    module_path = (
        Path(__file__).resolve().parents[2]
        / "src"
        / "mind_runtime"
        / "dynamics"
        / "fast_functions.py"
    )
    assert module_path.exists()

    with open(module_path, encoding="utf-8") as f:
        tree = ast.parse(f.read(), filename=str(module_path))

    imported_names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported_names.append(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_names.append(node.module)

    forbidden_roots = ("provider", "body", "llm", "openai", "anthropic", "langchain")
    for imported in imported_names:
        for forbidden in forbidden_roots:
            assert forbidden not in imported.lower(), (
                f"Forbidden dependency {forbidden!r} detected in "
                f"fast_functions.py import: {imported}"
            )


def test_k_no_numeric_psychological_calibration_is_introduced() -> None:
    """K. no numeric psychological calibration is introduced."""
    # Ensure FastStateFunctionSpec does not define psychological numeric fields
    spec_fields = set(FastStateFunctionSpec.__dataclass_fields__.keys())
    psychological_fields = {
        "baseline",
        "sensitivity",
        "recovery_rate",
        "ceiling",
        "floor",
        "decay_rate",
    }
    assert not (spec_fields & psychological_fields)

    # Fatigue must be REGISTERED_ONLY without provisional numeric parameters
    fatigue_spec = FAST_FUNCTION_V1_REGISTRY["agent.affect.fatigue"]
    assert fatigue_spec.status == FastStateStatus.REGISTERED_ONLY


def test_registry_immutability_and_lookup() -> None:
    """Registry enforces immutability, uniqueness, and closed lookup."""
    registry = FAST_FUNCTION_V1_REGISTRY

    with pytest.raises(KeyError, match="no fast function registered"):
        registry.require("agent.affect.unknown_dimension")

    assert registry.get("agent.affect.unknown_dimension") is None

    # Cannot construct registry with duplicate state keys
    spec = FAST_FUNCTION_V1_SPECS[0]
    with pytest.raises(ValueError, match="duplicate state key"):
        FastFunctionRegistry((spec, spec))

    # Cannot construct registry with duplicate function kinds
    duplicate_kind_spec = FastStateFunctionSpec(
        state_key="agent.affect.custom_contact",
        semantic_label="custom contact",
        function_kind=FastFunctionKind.PROACTIVE_CONTACT,
        primary_consumer="Intent / proactive message path",
        external_action_capable=True,
    )
    with pytest.raises(ValueError, match="duplicate function kind"):
        FastFunctionRegistry((spec, duplicate_kind_spec))
