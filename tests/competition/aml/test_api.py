from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from mind_runtime.competition.aml.api import create_app
from mind_runtime.competition.aml.contracts import AmlRuntimeConfig
from mind_runtime.competition.aml.runtime import AmlCompetitionRuntime


def test_http_contract_and_auth(tmp_path: Path) -> None:
    runtime = AmlCompetitionRuntime(
        tmp_path,
        run_id="http",
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
    assert set(data[0]) == {
        "id",
        "content",
        "score",
        "created_at",
    }
    assert "blue notebook" in data[0]["content"]
