"""Executable architecture guards for the bounded production authority slice."""

import ast
from pathlib import Path


def test_admission_is_only_production_caller_of_job_completion():
    root = Path(__file__).resolve().parents[2] / "src" / "mind_runtime"
    callers = []
    for path in root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "_complete_job"
            ):
                callers.append(path.relative_to(root).as_posix())
    assert callers == ["memory/admission.py"]


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
