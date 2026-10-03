import ast
from pathlib import Path


def imports(path):
    modules = set()
    for item in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(item, ast.Import):
            modules.update(alias.name for alias in item.names)
        elif isinstance(item, ast.ImportFrom) and item.module:
            modules.add(item.module)
    return modules


def test_online_and_historical_dependency_separation():
    root = Path(__file__).resolve().parents[2]
    for directory in (root / "src", root / "xiyue"):
        for path in directory.rglob("*.py"):
            assert not any(name.startswith("historical") for name in imports(path)), path
    for path in (root / "historical").glob("*.py"):
        assert not any(
            name.startswith(("mind_runtime", "xiyue", "lce")) for name in imports(path)
        ), path
        defined = {
            item.name
            for item in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
            if isinstance(item, (ast.ClassDef, ast.FunctionDef))
        }
        assert not defined.intersection(
            {
                "SemanticDeltaV1",
                "DeltaSemanticPoint",
                "DeltaSemanticDependency",
                "validate_semantic_delta",
                "compile_semantic_delta",
            }
        ), path


def test_installed_online_package_excludes_offline_worker():
    import tomllib

    root = Path(__file__).resolve().parents[2]
    config = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    assert config["tool"]["setuptools"]["packages"]["find"]["where"] == ["src"]
