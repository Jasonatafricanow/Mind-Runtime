from __future__ import annotations

import pytest

from mind_runtime.aml.contracts import AmlMessage
from mind_runtime.aml.providers import (
    OpenAICompatibleCompletion,
    OpenAICompatibleEmbedding,
    OpenAICompatibleThreadSemanticProvider,
    ThreadSemanticDecision,
)


def test_thread_semantic_decision_requires_bounded_action() -> None:
    with pytest.raises(ValueError):
        ThreadSemanticDecision("invent")
    with pytest.raises(ValueError):
        ThreadSemanticDecision("track")


def test_openai_thread_semantic_provider_parses_typed_hint(monkeypatch) -> None:
    provider = OpenAICompatibleThreadSemanticProvider(
        endpoint="https://example.com/v1/chat/completions",
        api_key="key",
        model="model",
    )
    monkeypatch.setattr(
        provider._transport,
        "post_json",
        lambda *_: {
            "choices": [
                {
                    "message": {
                        "content": (
                            '{"action":"track","question":"travel plan",'
                            '"summary":"still choosing","mature":false,'
                            '"confidence":0.8}'
                        )
                    }
                }
            ]
        },
    )
    result = provider.analyze(
        message=AmlMessage("user", "Maybe Lisbon."),
        context=(AmlMessage("user", "I am planning a trip."),),
    )
    assert result.action == "track"
    assert result.question == "travel plan"
    assert result.confidence == 0.8


def test_openai_completion_and_embedding_parse_provider_payloads(
    monkeypatch,
) -> None:
    completion = OpenAICompatibleCompletion(
        endpoint="https://example.com/v1/chat/completions",
        api_key="key",
        model="model",
    )
    monkeypatch.setattr(
        completion._transport,
        "post_json",
        lambda *_: {
            "choices": [{"message": {"content": "hypothetical memory"}}]
        },
    )
    assert completion("query") == "hypothetical memory"

    embedding = OpenAICompatibleEmbedding(
        endpoint="https://example.com/v1/embeddings",
        api_key="key",
        model="embed",
        dimension=3,
        revision="r1",
    )
    monkeypatch.setattr(
        embedding._transport,
        "post_json",
        lambda *_: {"data": [{"embedding": [1.0, 0.0, 0.0]}]},
    )
    assert embedding.embed("hello") == (1.0, 0.0, 0.0)
