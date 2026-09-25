"""Offline contract checks for the current Memory Body adapter during migration."""

from typing import Any

import pytest

from mind_runtime.contracts import ProviderExpressionContext, Scope, ScopeDomain
from mind_runtime.emotional_transition.provider import ProviderUnavailableError
from mind_runtime.memory.real_body_agent import LLMUnavailable, RealLLMBodyAgent


def context() -> ProviderExpressionContext:
    return ProviderExpressionContext(
        "render-1", "context-1", Scope(ScopeDomain.USER, user_id="u1"),
        "runtime-1", "The approved context", (), (),
    )


class StubTransport:
    def __init__(self, response: dict[str, Any] | Exception) -> None:
        self.response = response
        self.requests: list[tuple[str, dict[str, object], float]] = []

    def post_json(
        self, url: str, framed: dict[str, object], timeout_s: float
    ) -> dict[str, Any]:
        self.requests.append((url, framed, timeout_s))
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def make_agent(*, gemini: bool = False) -> RealLLMBodyAgent:
    host = "generativelanguage.googleapis.com" if gemini else "provider.example"
    path = "/v1beta/models/test:generateContent" if gemini else "/v1/chat/completions"
    return RealLLMBodyAgent(
        endpoint_url=f"https://{host}{path}", model="test-model", api_key="a b",
        user_question="What should you say?", allowed_hosts=(host,), timeout_s=7,
        extra_body={"seed": 123},
    )


def test_openai_body_uses_only_provided_context_and_records_success() -> None:
    agent = make_agent()
    transport = StubTransport({"choices": [{"message": {"content": "Reply"}}]})
    agent._transport = transport
    provided = context()

    assert agent.respond(provided) == "Reply"
    assert agent.calls == (provided,)
    assert agent.responses == ("Reply",)
    url, framed, timeout = transport.requests[0]
    assert url == "https://provider.example/v1/chat/completions"
    assert timeout == 7
    assert framed["model"] == "test-model"
    assert framed["temperature"] == 0.0
    assert framed["max_tokens"] == 800
    assert framed["seed"] == 123
    assert framed["_headers"] == {"Authorization": "Bearer a b"}
    assert framed["messages"] == [{
        "role": "user",
        "content": "Context the agent has been given:\nThe approved context\n\n"
        "User question: What should you say?\n\nReply as the agent. Be brief.",
    }]


def test_gemini_body_uses_native_frame_and_quoted_key() -> None:
    agent = make_agent(gemini=True)
    transport = StubTransport({"candidates": [{"content": {"parts": [{"text": "Native reply"}]}}]})
    agent._transport = transport

    assert agent.respond(context()) == "Native reply"
    url, framed, timeout = transport.requests[0]
    assert url.endswith(":generateContent?key=a%20b")
    assert timeout == 7
    assert framed["generationConfig"] == {"temperature": 0.0, "maxOutputTokens": 800}
    assert framed["contents"][0]["parts"][0]["text"].startswith(
        "Context the agent has been given:\nThe approved context"
    )
    assert "_headers" not in framed


def test_gemini_request_preserves_existing_query_and_openai_custom_auth() -> None:
    gemini = make_agent(gemini=True)
    gemini._endpoint_url += "?alt=json"
    url, _, _ = gemini._build_request("approved")
    assert url.endswith("?alt=json&key=a%20b")

    openai = make_agent()
    openai._api_key_header = "X-API-Key"
    openai._api_key_prefix = "Token "
    _, framed, _ = openai._build_request("approved")
    assert framed["_headers"] == {"X-API-Key": "Token a b"}


def test_gemini_ignores_empty_part_before_usable_text() -> None:
    agent = make_agent(gemini=True)
    agent._transport = StubTransport({
        "candidates": [{"content": {"parts": [{"text": ""}, {"text": "Usable"}]}}]
    })
    assert agent.respond(context()) == "Usable"
    assert agent.responses == ("Usable",)


@pytest.mark.parametrize(
    "response",
    [
        {"choices": []},
        {"choices": [{}]},
        {"choices": [{"message": {"content": " "}}]},
        {"candidates": []},
    ],
)
def test_missing_openai_body_response_is_inconclusive(response: dict[str, Any]) -> None:
    agent = make_agent()
    agent._transport = StubTransport(response)
    with pytest.raises(LLMUnavailable, match="empty content"):
        agent.respond(context())
    assert agent.calls == (context(),)
    assert agent.responses == ()


@pytest.mark.parametrize(
    "response",
    [
        {"candidates": []},
        {"candidates": 123},
        {"candidates": [{}]},
        {"candidates": [{"content": {"parts": []}}]},
        {"candidates": [{"content": {"parts": [{"text": ""}]}}]},
    ],
)
def test_missing_gemini_body_response_is_inconclusive(response: dict[str, Any]) -> None:
    agent = make_agent(gemini=True)
    agent._transport = StubTransport(response)
    with pytest.raises(LLMUnavailable, match="empty content"):
        agent.respond(context())
    assert agent.responses == ()


def test_transport_failure_is_inconclusive_without_false_response() -> None:
    agent = make_agent()
    agent._transport = StubTransport(OSError("offline"))
    with pytest.raises(LLMUnavailable, match="body llm call failed"):
        agent.respond(context())
    assert agent.calls == (context(),)
    assert agent.responses == ()


def test_body_endpoint_rejects_insecure_or_unlisted_host() -> None:
    with pytest.raises(ProviderUnavailableError, match="https"):
        RealLLMBodyAgent(
            endpoint_url="http://provider.example/chat", model="m", api_key="k",
            user_question="q", allowed_hosts=("provider.example",),
        )
    with pytest.raises(ProviderUnavailableError, match="allowlist"):
        RealLLMBodyAgent(
            endpoint_url="https://different.example/chat", model="m", api_key="k",
            user_question="q", allowed_hosts=("provider.example",),
        )
