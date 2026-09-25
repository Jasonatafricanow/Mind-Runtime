"""Audit only the currently unresolved Golden scenario.

Historical G->phase ownership belonged to the development plan and is not a
runtime regression contract. The executable Golden scenarios themselves cover
the implemented pipelines; this audit only prevents unresolved cases from
silently multiplying.
"""

import ast
from pathlib import Path

GOLDEN_TESTS = Path(__file__).parent


def _strict_xfails() -> dict[tuple[str, str], str]:
    found: dict[tuple[str, str], str] = {}
    for path in sorted(GOLDEN_TESTS.glob("test_golden_*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for decorator in node.decorator_list:
                if not isinstance(decorator, ast.Call):
                    continue
                marker = decorator.func
                if not (
                    isinstance(marker, ast.Attribute)
                    and marker.attr == "xfail"
                    and isinstance(marker.value, ast.Attribute)
                    and marker.value.attr == "mark"
                    and isinstance(marker.value.value, ast.Name)
                    and marker.value.value.id == "pytest"
                ):
                    continue
                keywords = {item.arg: item.value for item in decorator.keywords}
                strict = keywords.get("strict")
                reason = keywords.get("reason")
                if (
                    isinstance(strict, ast.Constant)
                    and strict.value is True
                    and isinstance(reason, ast.Constant)
                    and isinstance(reason.value, str)
                ):
                    found[(path.name, node.name)] = reason.value
    return found


def test_only_g28_remains_strict_xfail() -> None:
    assert _strict_xfails() == {
        (
            "test_golden_g24_g28.py",
            "test_golden_g28_onboarding_llm_is_one_time_and_user_activated",
        ): "MR-D11P not implemented"
    }
