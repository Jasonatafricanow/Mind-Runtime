"""D11S closure vocabulary, evidence, and strict-xfail governance gate."""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
AGENTS = ROOT / "AGENTS.md"
README = ROOT / "README.md"
REPORT = ROOT / "docs" / "superpowers" / "plans" / "2026-08-23-d11s-integration-report.md"
D11L_ENTRY = ROOT / "docs" / "superpowers" / "plans" / "2026-08-23-d11l-entry-requirements.md"
D11S_DESIGN = (
    ROOT
    / "docs"
    / "superpowers"
    / "specs"
    / "2026-08-23-d11s-deterministic-certification-and-d11l-entry-design.md"
)
GOLDEN_TESTS = ROOT / "tests" / "golden"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _strict_xfail_ids() -> set[str]:
    ids: set[str] = set()
    for path in sorted(GOLDEN_TESTS.glob("test_golden_*.py")):
        tree = ast.parse(_read(path), filename=str(path))
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
                keywords = {keyword.arg: keyword.value for keyword in decorator.keywords}
                strict = keywords.get("strict")
                reason = keywords.get("reason")
                if not (
                    isinstance(strict, ast.Constant)
                    and strict.value is True
                    and isinstance(reason, ast.Constant)
                    and reason.value == "MR-D11P not implemented"
                ):
                    continue
                ids.add("G28" if "g28" in node.name else node.name)
    return ids


def test_d11s_status_never_claims_live_d11_completion() -> None:
    agents = _read(AGENTS)
    readme = _read(README)
    report = _read(REPORT)

    assert "D11S is closed" in agents
    assert "D11L is blocked by the external environment" in agents
    assert "| D11S | Complete" in readme
    assert "| D11L | Blocked" in readme
    assert "| D11 | Incomplete" in readme
    assert "| D11P | Blocked" in readme
    assert "LIVE SHADOW VALIDATION: NOT PERFORMED" in report
    assert "D11: INCOMPLETE" in report
    assert "READY FOR D11L: YES" in report
    assert "READY FOR D11P: NO" in report
    assert "D11 COMPLETE" not in report


def test_only_g28_remains_strict_xfail() -> None:
    assert _strict_xfail_ids() == {"G28"}


def test_d11l_entry_keeps_all_external_requirements_unavailable() -> None:
    entry = _read(D11L_ENTRY)

    assert entry.count("| **Unavailable.**") == 11
    assert "D11L: BLOCKED_BY_EXTERNAL_ENVIRONMENT" in entry
    assert "LIVE SHADOW VALIDATION: NOT PERFORMED" in entry
    assert "READY FOR D11P: NO" in entry


def test_active_authority_and_delivery_order_include_the_d11_split() -> None:
    agents = _read(AGENTS)
    readme = _read(README)
    design = _read(D11S_DESIGN)
    split = "D10 -> D11S -> D11L -> D11 completion -> D11P"

    assert "**Status:** Approved after independent architecture-entry review" in design
    assert "0007-bound-expression-authority.md" in agents
    assert "0008-split-d11-certification-and-live-shadow.md" in agents
    assert D11S_DESIGN.name in agents
    assert split in agents
    assert split in readme
    assert "D10 -> D11 -> D11P" not in agents
    assert "D10 -> D11 -> D11P" not in readme
