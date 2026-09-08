"""D7R architecture authority and supersession audit."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ADR = ROOT / "docs" / "adr" / "0004-compress-cognitive-topology.md"
DESIGN = (
    ROOT
    / "docs"
    / "superpowers"
    / "specs"
    / "2026-08-22-d7r-compressed-runtime-and-agent-onboarding-design.md"
)
BASELINES = (
    ROOT / "docs" / "Mind%20Runtime%20V0.1.4%20开发总纲和需求基线.md",
    ROOT / "docs" / "Mind%20Runtime%20V0.1.4%20分步开发与分布派单总纲.md",
    ROOT / "docs" / "MindRuntimeV0.1.4完整版_开发总纲_需求基线_分布派单.md",
)
AGENTS = ROOT / "AGENTS.md"
README = ROOT / "README.md"
D9_ADR = ROOT / "docs" / "adr" / "0006-separate-intent-authority.md"
D9_REPORT = ROOT / "docs" / "superpowers" / "plans" / "2026-08-22-d9-integration-report.md"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_adr_0004_accepts_the_compressed_runtime_design() -> None:
    text = _read(ADR)
    assert "# ADR-0004: Compress the cognitive topology" in text
    assert "- **Status:** Accepted" in text
    assert DESIGN.name in text
    assert "ResolvedAppraisal" in text
    assert "D11P" in text
    assert "no D8 production implementation" in text


def test_all_v014_baselines_declare_the_d7r_authority_overlay() -> None:
    for path in BASELINES:
        first_lines = "\n".join(_read(path).splitlines()[:18])
        assert "ADR-0004" in first_lines, path.name
        assert DESIGN.name in first_lines, path.name
        assert "supersedes conflicting topology clauses" in first_lines, path.name


def test_agents_declares_the_d7r_overlay_and_protected_boundaries() -> None:
    text = _read(AGENTS)
    assert DESIGN.name in text
    assert "D7R is closed" in text
    assert "D8 is closed" in text
    assert "D9 is closed" in text
    assert "D10 is closed" in text
    assert "D11S is closed" in text
    assert "D11L is blocked by the external environment" in text
    assert "D11P, MR-4, and MR-5 remain blocked" in text
    assert "EmotionalTransition and Assessment/Contribution Trace" in text
    assert "Intent lifecycle and scheduling" in text
    assert "History facts cannot become Persona" in text


def test_readme_exposes_only_the_compressed_product_slice() -> None:
    text = _read(README)
    assert "-> Factual Context" in text
    assert "-> Deterministic Emotional Transition" in text
    assert "-> Intent / Scheduler" in text
    assert "D7 -> D7R -> D8 -> D9 -> D10 -> D11S -> D11L -> D11 completion -> D11P" in text
    assert "| D7R | Complete" in text
    assert "| D8 | Complete" in text
    assert "| D9 | Complete" in text
    assert "| D10 | Complete" in text
    assert "| D11S | Complete" in text
    assert "| D11L | Blocked" in text
    assert "| D11 | Incomplete" in text
    assert "| D11P | Blocked" in text
    assert "Appraisal Resolution\n-> Affective Dynamics\n-> Motivation" not in text


def test_d9_authority_and_integration_report_close_only_d9() -> None:
    adr = _read(D9_ADR)
    report = _read(D9_REPORT)
    assert "# ADR-0006: Separate Intent authority from emotional transition" in adr
    assert "- **Status:** Accepted" in adr
    assert "READY FOR D10: YES" in report
    assert "857 passed, 5 xfailed" in report
    assert "100%" in report
    assert "D10 behavior is not implemented" in report
    assert "No LLM" in report


D10_ADR = ROOT / "docs" / "adr" / "0007-bound-expression-authority.md"
D10_REPORT = ROOT / "docs" / "superpowers" / "plans" / "2026-08-23-d10-integration-report.md"


def test_d10_authority_and_report_close_only_d10() -> None:
    adr = _read(D10_ADR)
    report = _read(D10_REPORT)
    assert "Accepted for D10 implementation" in adr
    assert "D10: COMPLETE" in report
    assert "READY FOR D11: YES" in report
    assert "LLM" in report and "prose" in report
    assert "D11 behavior is not implemented" in report


def test_gate_state_closes_only_d11s_and_keeps_d11_incomplete() -> None:
    agents = _read(AGENTS)
    readme = _read(README)
    assert "D10 is closed" in agents
    assert "D11S is closed" in agents
    assert "D11L is blocked by the external environment" in agents
    assert "D11P, MR-4, and MR-5 remain blocked" in agents
    assert "| D10 | Complete" in readme
    assert "| D11S | Complete" in readme
    assert "| D11L | Blocked" in readme
    assert "| D11 | Incomplete" in readme
    assert "| D11P | Blocked" in readme
