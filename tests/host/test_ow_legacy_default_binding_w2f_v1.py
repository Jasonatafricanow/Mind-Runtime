"""W2-F legacy/default-binding compatibility tests."""

from __future__ import annotations

import ast
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient

from mind_runtime.binding_registry import build_binding_registry
from mind_runtime.runtime_binding import RuntimeBinding, RuntimeEnvironment
from observation_window.binding import ObservationBindingCatalog
from observation_window.web.runtime import compose_ow_app
from tests.host.test_ow_binding_scoped_api_w2d_v1 import multi_binding_setup


def _catalog(setup):
    return ObservationBindingCatalog(
        reader=setup["registry"].reader,
        environment=RuntimeEnvironment.PRODUCTION,
        resolver=setup["resolver"],
    )


def _client(setup):
    catalog = _catalog(setup)
    resolved = setup["resolver"].resolve(setup["binding_a"])
    app, _ = compose_ow_app(resolved, catalog=catalog)
    return TestClient(app)


def test_legacy_page_redirects_to_explicit_production_default(multi_binding_setup):
    setup = multi_binding_setup
    setup["registry"].writer.set_default("agent-a-prod")

    response = _client(setup).get("/state?dimension=irritation", follow_redirects=False)

    assert response.status_code == 307
    location = urlsplit(response.headers["location"])
    assert location.path == "/state"
    assert parse_qs(location.query) == {
        "dimension": ["irritation"],
        "runtime": ["agent-a-prod"],
    }


def test_legacy_api_uses_explicit_production_default(multi_binding_setup):
    setup = multi_binding_setup
    setup["registry"].writer.set_default("agent-a-prod")

    response = _client(setup).get("/api/overview")

    assert response.status_code == 200
    assert response.json()["binding_id"] == "agent-a-prod"


def test_missing_default_projects_to_conflict(multi_binding_setup):
    response = _client(multi_binding_setup).get("/state", follow_redirects=False)

    assert response.status_code == 409
    assert response.json()["code"] == "DEFAULT_BINDING_UNDECLARED"


def test_legacy_cursor_rejects_cursor_from_previous_default(multi_binding_setup):
    setup = multi_binding_setup
    registry = setup["registry"]
    registry.writer.set_default("agent-a-prod")
    client = _client(setup)

    first = client.get("/api/turns?limit=1")
    cursor_a = first.json()["next_cursor"]
    assert cursor_a.startswith("agent-a-prod:")

    registry.writer.set_default("agent-b-prod")
    response = client.get(f"/api/turns?before={cursor_a}")

    assert response.status_code == 400
    assert response.json()["code"] == "CURSOR_BINDING_MISMATCH"


def test_explicit_runtime_never_redirects_or_consults_default(multi_binding_setup):
    setup = multi_binding_setup
    setup["registry"].writer.set_default("agent-a-prod")

    response = _client(setup).get("/state?runtime=agent-b-prod", follow_redirects=False)

    assert response.status_code == 200


def test_explicit_runtime_api_wins_without_a_default(multi_binding_setup):
    client = _client(multi_binding_setup)

    response = client.get("/api/overview?runtime=agent-b-prod")

    assert response.status_code == 200
    assert response.json()["binding_id"] == "agent-b-prod"


def test_invalid_explicit_runtime_does_not_fallback_to_default(multi_binding_setup):
    setup = multi_binding_setup
    setup["registry"].writer.set_default("agent-a-prod")

    response = _client(setup).get("/api/overview?runtime=", follow_redirects=False)

    assert response.status_code == 400
    assert response.json()["code"] == "INVALID_RUNTIME_SELECTION"


def test_production_catalog_excludes_lab_binding(multi_binding_setup):
    response = _client(multi_binding_setup).get("/api/runtime-bindings")

    assert response.status_code == 200
    assert [b["binding_id"] for b in response.json()["bindings"]] == [
        "agent-a-prod",
        "agent-b-prod",
    ]


@pytest.mark.parametrize("path", ["/", "/overview", "/state", "/moments", "/causal", "/history", "/live-trace"])
def test_all_product_page_aliases_redirect_to_default(multi_binding_setup, path):
    setup = multi_binding_setup
    setup["registry"].writer.set_default("agent-b-prod")

    response = _client(setup).get(path, follow_redirects=False)

    assert response.status_code == 307
    assert parse_qs(urlsplit(response.headers["location"]).query)["runtime"] == ["agent-b-prod"]


@pytest.mark.parametrize(
    "path",
    [
        "/api/overview",
        "/api/trends",
        "/api/states",
        "/api/turns",
        "/api/live-trace",
    ],
)
def test_legacy_read_apis_are_default_aliases(multi_binding_setup, path):
    setup = multi_binding_setup
    setup["registry"].writer.set_default("agent-b-prod")

    response = _client(setup).get(path)

    assert response.status_code == 200
    assert response.json()["binding_id"] == "agent-b-prod"


def test_default_switch_changes_only_new_legacy_aliases(multi_binding_setup):
    setup = multi_binding_setup
    registry = setup["registry"]
    registry.writer.set_default("agent-a-prod")
    client = _client(setup)

    assert parse_qs(urlsplit(client.get("/state", follow_redirects=False).headers["location"]).query)["runtime"] == [
        "agent-a-prod"
    ]
    registry.writer.set_default("agent-b-prod")

    switched = client.get("/state", follow_redirects=False)
    explicit_a = client.get("/state?runtime=agent-a-prod", follow_redirects=False)
    assert parse_qs(urlsplit(switched.headers["location"]).query)["runtime"] == ["agent-b-prod"]
    assert explicit_a.status_code == 200


def test_empty_production_registry_projects_to_no_bindings(multi_binding_setup, tmp_path):
    empty = build_binding_registry(tmp_path / "empty-registry")
    empty.writer.initialize()
    catalog = ObservationBindingCatalog(
        reader=empty.reader,
        environment=RuntimeEnvironment.PRODUCTION,
        resolver=multi_binding_setup["resolver"],
    )
    resolved = multi_binding_setup["resolver"].resolve(multi_binding_setup["binding_a"])
    app, _ = compose_ow_app(resolved, catalog=catalog)

    response = TestClient(app).get("/state", follow_redirects=False)

    assert response.status_code == 503
    assert response.json()["code"] == "NO_BINDINGS_AVAILABLE"


def test_corrupt_registry_projects_to_registry_unavailable(multi_binding_setup, tmp_path):
    corrupt_dir = tmp_path / "corrupt-registry"
    corrupt_dir.mkdir()
    (corrupt_dir / "registry.json").write_text("not-json", encoding="utf-8")
    corrupt = build_binding_registry(corrupt_dir)
    catalog = ObservationBindingCatalog(
        reader=corrupt.reader,
        environment=RuntimeEnvironment.PRODUCTION,
        resolver=multi_binding_setup["resolver"],
    )
    resolved = multi_binding_setup["resolver"].resolve(multi_binding_setup["binding_a"])
    app, _ = compose_ow_app(resolved, catalog=catalog)

    response = TestClient(app).get("/state", follow_redirects=False)

    assert response.status_code == 503
    assert response.json()["code"] == "BINDING_REGISTRY_UNAVAILABLE"


def test_production_runtime_composition_has_no_xiyue_singleton_fallback():
    source_path = Path(__file__).parents[2] / "src" / "observation_window" / "web" / "runtime.py"
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "resolve_xiyue_observation_binding"
    ]
    assert not calls


def test_production_runtime_fails_closed_before_opening_missing_canonical_sources(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    """Startup must not let SQLite create missing production source files."""
    from mind_runtime.binding_registry_composition import bootstrap_production_registry
    import observation_window.web.runtime as runtime_module

    registry_dir = tmp_path / "registry"
    production_root = tmp_path / "production"
    production_root.mkdir()
    (production_root / "agent-missing-source").mkdir()
    binding = RuntimeBinding(
        persona_id="persona-missing-source",
        agent_id="agent-missing-source",
        runtime_id="runtime-missing-source",
        storage_namespace="agent-missing-source",
        environment=RuntimeEnvironment.PRODUCTION,
    )
    bootstrap_production_registry(
        binding_id="agent-missing-source",
        binding=binding,
        registry_dir=registry_dir,
    )
    monkeypatch.setenv("MR_BINDING_REGISTRY_DIR", str(registry_dir))
    monkeypatch.setattr(runtime_module.uvicorn, "run", lambda *args, **kwargs: None)

    with pytest.raises(RuntimeError, match="production BindingRegistry is unavailable"):
        runtime_module.main(["--runtime-dir", str(production_root)])

    namespace_root = production_root / "agent-missing-source"
    assert not (namespace_root / "cognition_state.sqlite").exists()
    assert not (namespace_root / "facts.sqlite").exists()
