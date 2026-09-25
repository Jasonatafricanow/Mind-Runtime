"""Lock the fixed cross-module import direction of the contracts package."""

import ast
import importlib.util
from pathlib import Path

import pytest

# Every contract module may import only itself's lower layers plus its own
# module; importing a later-layer module is a direction violation. The root
# re-export module (__init__) is allowed to import everything and is not
# listed here.
_ALLOWED_IMPORTS: dict[str, set[str]] = {
    "scope": set(),
    "common": {"scope"},
    "interaction": {"scope"},
    "evidence": {"common", "scope"},
    "reality": {"common", "scope"},
    "observation": {"common", "reality", "scope"},
    "state": {"common", "scope"},
    "transition": {"common", "scope", "state"},
    "projection": {"common", "observation", "scope", "state", "transition"},
    "checkpoint": {"common", "scope"},
    "pattern": {"common", "scope"},
    "historical": {"common", "pattern", "scope"},
    "situation": {"common", "historical", "scope"},
    "appraisal": {"common", "scope"},
    "affect": {"common", "scope"},
    "dynamics": {"affect", "common", "scope"},
    "intent": {"common", "scope"},
    "emotional_transition": {
        "affect",
        "appraisal",
        "common",
        "historical",
        "intent",
        "late_projection",
        "observation",
        "projection",
        "scope",
        "situation",
        "state",
    },
    "action": {"common", "scope"},
    "behavior": {
        "appraisal",
        "common",
        "intent",
        "projection",
        "scope",
        "situation",
    },
    "trace": {"common", "scope"},
    "governance": {"common", "scope"},
    "expression": {"common", "scope"},
    "decision": {"common", "scope"},
    "replication": {
        "common",
        "evidence",
        "observation",
        "projection",
        "scope",
        "state",
        "transition",
    },
}


def _contracts_dir() -> Path:
    spec = importlib.util.find_spec("mind_runtime.contracts")
    assert spec is not None
    assert spec.submodule_search_locations is not None
    return Path(next(iter(spec.submodule_search_locations)))


def _imported_contract_modules(tree: ast.Module) -> set[str]:
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module
            if module is not None and module.startswith("mind_runtime.contracts."):
                imports.add(module.split(".")[2])
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("mind_runtime.contracts."):
                    imports.add(alias.name.split(".")[2])
    return imports


def test_cross_module_import_direction_is_fixed() -> None:
    for module_name, allowed in _ALLOWED_IMPORTS.items():
        source = (_contracts_dir() / f"{module_name}.py").read_text(encoding="utf-8")
        found = _imported_contract_modules(ast.parse(source))
        assert found <= allowed, (
            f"{module_name} imports later-layer or unknown contract modules: "
            f"{sorted(found - allowed)}"
        )


def _expression_dir() -> Path:
    spec = importlib.util.find_spec("mind_runtime.expression")
    assert spec is not None
    assert spec.submodule_search_locations is not None
    return Path(next(iter(spec.submodule_search_locations)))


def test_expression_package_imports_only_stdlib_contracts_and_siblings() -> None:
    """The bounded D10 expression package never imports pipeline or later layers."""
    allowed_prefixes = ("mind_runtime.contracts", "mind_runtime.expression")
    for module_path in sorted(_expression_dir().glob("*.py")):
        tree = ast.parse(module_path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            imported: list[str] = []
            if isinstance(node, ast.ImportFrom):
                if node.module is not None:
                    imported.append(node.module)
            elif isinstance(node, ast.Import):
                imported.extend(alias.name for alias in node.names)
            for name in imported:
                if name.startswith("mind_runtime.") and not name.startswith(allowed_prefixes):
                    raise AssertionError(f"{module_path.name} imports forbidden package {name}")


def test_package_reexports_all_26_d1_contract_groups() -> None:
    from mind_runtime import contracts

    expected_groups = {
        "Interaction",
        "Scope",
        "Authority",
        "Ownership",
        "Evidence",
        "Observation",
        "StateDefinition",
        "TransitionIntent",
        "ProjectedMindState",
        "Situation",
        "SemanticAppraisal",
        "EmotionalTransitionResult",
        "AffectiveDimensionProfile",
        "DynamicsPolicy",
        "Intent",
        "ActionIntent",
        "ActionPolicyResult",
        "ExpressionGuardResult",
        "DecisionContext",
        "ReplicationEnvelope",
        "TraceRef",
        "AppraisalRouteDecision",
        "HistoricalContextQuery",
        "PatternQuery",
        "TurnCheckpoint",
        "DataSensitivity",
    }
    missing = sorted(name for name in expected_groups if not hasattr(contracts, name))
    assert not missing, f"missing D1 contract exports: {missing}"


def test_validation_is_the_final_import_layer() -> None:
    """No production domain may depend on certification validation."""
    package_root = _contracts_dir().parent
    for module_path in sorted(package_root.rglob("*.py")):
        if "validation" in module_path.parts:
            continue
        tree = ast.parse(module_path.read_text(encoding="utf-8"))
        assert not _imports_validation(tree), (
            f"{module_path.relative_to(package_root)} imports validation"
        )


def _imports_validation(tree: ast.Module) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module.startswith("mind_runtime.validation"):
                return True
            if module == "mind_runtime" and any(alias.name == "validation" for alias in node.names):
                return True
            if node.level and (
                module == "validation"
                or module.startswith("validation.")
                or (not module and any(alias.name == "validation" for alias in node.names))
            ):
                return True
        elif isinstance(node, ast.Import) and any(
            alias.name.startswith("mind_runtime.validation") for alias in node.names
        ):
            return True
    return False


@pytest.mark.parametrize(
    "source",
    [
        "from mind_runtime import validation",
        "from mind_runtime import validation as certification",
        "from . import validation",
        "from .. import validation as certification",
        "from .validation import schedule",
        "from ..validation.schedule import SimulationClock",
    ],
)
def test_validation_import_lock_covers_root_alias_and_relative_forms(source: str) -> None:
    assert _imports_validation(ast.parse(source))
