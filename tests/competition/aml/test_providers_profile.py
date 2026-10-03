from __future__ import annotations

from pathlib import Path

import pytest

from mind_runtime.competition.aml.contracts import AmlMessage
from mind_runtime.competition.aml.profile import build_runtime_from_env
from mind_runtime.competition.aml.providers import (
    OpenAICompatibleAmlHostSemanticProvider,
    OpenAICompatibleCompletion,
    OpenAICompatibleEmbedding,
)
from mind_runtime.contracts import Scope, ScopeDomain


def _chat_payload(content: str) -> dict[str, object]:
    return {
        "choices": [
            {
                "message": {
                    "content": content,
                }
            }
        ]
    }


def test_completion_and_embedding_parse_openai_compatible_payloads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    completion = OpenAICompatibleCompletion(
        endpoint="https://example.com/v1/chat/completions",
        api_key="key",
        model="model",
    )
    monkeypatch.setattr(
        completion._chat.transport,
        "post_json",
        lambda *_: _chat_payload("hypothetical memory"),
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
        embedding._chat.transport,
        "post_json",
        lambda *_: {
            "data": [{"embedding": [1.0, 0.0, 0.0]}]
        },
    )
    assert embedding.embed("hello") == (1.0, 0.0, 0.0)
    with pytest.raises(ValueError, match="nonempty"):
        embedding.embed(" ")


def test_body_semantic_provider_binds_system_authority_and_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = OpenAICompatibleAmlHostSemanticProvider(
        endpoint="https://example.com/v1/chat/completions",
        api_key="key",
        model="body",
    )
    scope = Scope(ScopeDomain.USER, user_id="u")
    responses = iter(
        (
            _chat_payload(
                '{"action":"none","question":null,'
                '"summary":null,"mature":false,"confidence":0.8}'
            ),
            _chat_payload(
                '{"action":"track","question":"travel plan",'
                '"summary":"still choosing","mature":true,'
                '"confidence":0.9}'
            ),
        )
    )
    monkeypatch.setattr(
        provider._chat.transport,
        "post_json",
        lambda *_: next(responses),
    )
    message = AmlMessage("user", "Maybe Lisbon.")
    assert provider.events(
        message=message,
        visible_messages=(message,),
        active_threads=(),
        scope=scope,
        origin_runtime_id="runtime",
        evidence_ref="e1",
    ) == ()

    events = provider.events(
        message=message,
        visible_messages=(message,),
        active_threads=(),
        scope=scope,
        origin_runtime_id="runtime",
        evidence_ref="e1",
    )
    assert len(events) == 1
    event = events[0]
    assert event.scope == scope
    assert event.origin_runtime_id == "runtime"
    assert event.evidence_refs == ("e1",)
    attrs = dict(event.attributes)
    assert attrs["thread_action"] == "track"
    assert attrs["thread_question"] == "travel plan"
    assert attrs["thread_mature"] == "true"


def test_body_semantic_provider_rejects_unbounded_model_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = OpenAICompatibleAmlHostSemanticProvider(
        endpoint="https://example.com/v1/chat/completions",
        api_key="key",
        model="body",
    )
    monkeypatch.setattr(
        provider._chat.transport,
        "post_json",
        lambda *_: _chat_payload(
            '{"action":"invent","question":"q",'
            '"summary":"s","mature":false,"confidence":0.8}'
        ),
    )
    with pytest.raises(ValueError, match="bounded"):
        provider.events(
            message=AmlMessage("user", "x"),
            visible_messages=(),
            active_threads=(),
            scope=Scope(ScopeDomain.USER, user_id="u"),
            origin_runtime_id="runtime",
            evidence_ref="e1",
        )


def _clear_profile_env(monkeypatch: pytest.MonkeyPatch) -> None:
    keys = (
        "AML_PROFILE",
        "AML_DATA_ROOT",
        "AML_RUN_ID",
        "AML_EMBED_ENDPOINT",
        "AML_EMBED_API_KEY",
        "AML_EMBED_MODEL",
        "AML_EMBED_DIMENSION",
        "AML_HYDE_ENDPOINT",
        "AML_HYDE_API_KEY",
        "AML_HYDE_MODEL",
        "AML_BODY_ENDPOINT",
        "AML_BODY_API_KEY",
        "AML_BODY_MODEL",
        "AML_DECISION_BACKEND",
    )
    for key in keys:
        monkeypatch.delenv(key, raising=False)


def test_bm25_profile_requires_no_model_configuration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_profile_env(monkeypatch)
    monkeypatch.setenv("AML_PROFILE", "bm25")
    monkeypatch.setenv("AML_DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("AML_RUN_ID", "profile-bm25")

    runtime = build_runtime_from_env()
    assert runtime.config.thread_enabled is False
    assert runtime.config.lce_enabled is False
    assert runtime._embedding is None


def test_hybrid_profile_requires_and_accepts_embedding_configuration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_profile_env(monkeypatch)
    monkeypatch.setenv("AML_PROFILE", "hybrid")
    monkeypatch.setenv("AML_DATA_ROOT", str(tmp_path))
    with pytest.raises(ValueError, match="requires AML_EMBED"):
        build_runtime_from_env()

    monkeypatch.setenv(
        "AML_EMBED_ENDPOINT",
        "https://example.com/v1/embeddings",
    )
    monkeypatch.setenv("AML_EMBED_API_KEY", "key")
    monkeypatch.setenv("AML_EMBED_MODEL", "embed")
    monkeypatch.setenv("AML_EMBED_DIMENSION", "3")
    runtime = build_runtime_from_env()
    assert runtime._embedding is not None
    assert runtime.config.thread_enabled is False


def test_thread_profile_requires_body_semantics(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_profile_env(monkeypatch)
    monkeypatch.setenv("AML_PROFILE", "thread")
    monkeypatch.setenv("AML_DATA_ROOT", str(tmp_path))
    monkeypatch.setenv(
        "AML_EMBED_ENDPOINT",
        "https://example.com/v1/embeddings",
    )
    monkeypatch.setenv("AML_EMBED_API_KEY", "key")
    monkeypatch.setenv("AML_EMBED_MODEL", "embed")
    monkeypatch.setenv("AML_EMBED_DIMENSION", "3")
    with pytest.raises(ValueError, match="AML_BODY"):
        build_runtime_from_env()

    monkeypatch.setenv(
        "AML_BODY_ENDPOINT",
        "https://example.com/v1/chat/completions",
    )
    monkeypatch.setenv("AML_BODY_API_KEY", "key")
    monkeypatch.setenv("AML_BODY_MODEL", "body")
    runtime = build_runtime_from_env()
    assert runtime.config.thread_enabled is True
    assert runtime._semantic is not None


def test_profile_rejects_invalid_name_and_partial_provider_triplet(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_profile_env(monkeypatch)
    monkeypatch.setenv("AML_PROFILE", "bogus")
    with pytest.raises(ValueError, match="AML_PROFILE"):
        build_runtime_from_env()

    monkeypatch.setenv("AML_PROFILE", "hybrid")
    monkeypatch.setenv(
        "AML_EMBED_ENDPOINT",
        "https://example.com/v1/embeddings",
    )
    with pytest.raises(ValueError, match="supplied together"):
        build_runtime_from_env()
