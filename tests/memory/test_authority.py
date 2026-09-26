"""Executable architecture guards for the bounded production authority slice."""

import ast
from pathlib import Path


def test_canonical_memory_write_seams_have_no_unowned_production_references():
    """Secondary source guard; runtime authority is proved in admission tests.

    Inspect every reference shape we can statically recognize, not only direct
    calls, so aliases/getattr do not trivially evade the guard.
    """
    root = Path(__file__).resolve().parents[2] / "src" / "mind_runtime"
    write_seams = {
        "_register_job",
        "_freeze_job",
        "_complete_job",
        "_commit",
        "_insert",
    }
    allowed = {
        "memory/store.py",
        "memory/admission.py",
    }
    references = []
    for path in root.rglob("*.py"):
        relative = path.relative_to(root).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        for node in ast.walk(tree):
            seam = None
            if isinstance(node, ast.Attribute) and node.attr in write_seams:
                seam = node.attr
            elif (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "getattr"
                and len(node.args) >= 2
                and isinstance(node.args[1], ast.Constant)
                and node.args[1].value in write_seams
            ):
                seam = str(node.args[1].value)
            if seam is not None and relative not in allowed:
                references.append((relative, seam))
    assert references == []


def test_new_plane_imports_no_vector_provider_or_retrieval_authority():
    root = Path(__file__).resolve().parents[2] / "src" / "mind_runtime" / "memory"
    for name in ("contracts", "store", "admission", "projection", "extraction", "composition"):
        tree = ast.parse((root / f"{name}.py").read_text(encoding="utf-8"))
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.append(node.module)
        assert not any(
            any(
                forbidden in module
                for forbidden in (
                    "mem0",
                    "chromadb",
                    "langchain",
                    "retrieval",
                    "reinforcement",
                    "lce",
                )
            )
            for module in imports
        )
