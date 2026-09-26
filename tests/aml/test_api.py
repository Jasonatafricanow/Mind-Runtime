from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from mind_runtime.aml.api import build_runtime_from_env, create_app
from mind_runtime.aml.contracts import AmlRuntimeConfig
from mind_runtime.aml.runtime import AmlMemoryRuntime


def test_http_contract_echoes_add_ids_and_returns_declared_search_fields(
    tmp_path: Path,
) -> None:
    runtime = AmlMemoryRuntime(
        tmp_path,
        config=AmlRuntimeConfig(
            result_cap=1,
            thread_enabled=False,
            lce_enabled=False,
        ),
    )
    client = TestClient(create_app(runtime, auth_token="secret"))

    assert client.get("/health").status_code == 200
    body = {
        "request_id": "req-1",
        "messages": [
            {
                "role": "user",
                "timestamp": 1704067200000,
                "content": "The blue notebook was selected.",
            }
        ],
        "user_id": "user-1",
        "session_id": "session-1",
    }
    assert client.post("/aml/add", json=body).status_code == 401

    added = client.post(
        "/aml/add",
        json=body,
        headers={"Authorization": "Bearer secret"},
    )
    assert added.status_code == 200
    assert added.json() == {
        "success": True,
        "request_id": "req-1",
        "user_id": "user-1",
        "session_id": "session-1",
    }

    searched = client.post(
        "/aml/search",
        json={
            "query": "Which notebook?",
            "options": ["A. red", "B. blue"],
            "user_id": "user-1",
            "top_k": 100,
        },
        headers={"X-Api-Key": "secret"},
    )
    assert searched.status_code == 200
    data = searched.json()["data"]
    assert len(data) == 1
    assert set(data[0]) == {"id", "content", "score", "created_at"}
    assert "blue notebook" in data[0]["content"]


def test_env_factory_keeps_competition_policy_outside_core(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("AML_DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("AML_RESULT_CAP", "7")
    monkeypatch.setenv("AML_LCE_ENABLED", "0")
    monkeypatch.setenv("AML_THREAD_ENABLED", "0")
    monkeypatch.setenv("AML_DECISION_BACKEND", "none")
    for prefix in ("AML_EMBED", "AML_HYDE", "AML_THREAD"):
        monkeypatch.delenv(f"{prefix}_ENDPOINT", raising=False)
        monkeypatch.delenv(f"{prefix}_API_KEY", raising=False)
        monkeypatch.delenv(f"{prefix}_MODEL", raising=False)

    runtime = build_runtime_from_env()
    assert runtime.config.result_cap == 7
    assert runtime.config.lce_enabled is False
    assert runtime.config.thread_enabled is False
