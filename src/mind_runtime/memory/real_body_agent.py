"""P0 Canonicalization — real LLM Body adapter.

A single-purpose `AgentPort.respond` that calls a real LLM chat endpoint.
Records every call and response for inspection.

Body egress is OUTSIDE MR's existing `ModelEgressPolicy` (that policy is
for the affect-classification semantic path). Body generation is a
different egress channel. This adapter uses MR's existing
`UrllibChatTransport` and SSRF guard, but does NOT route through
`OpenAICompatibleProvider` because the Body does not emit semantic
candidates — it emits natural language.
"""

from __future__ import annotations

import urllib.parse
from typing import Any

from mind_runtime.contracts import ProviderExpressionContext
from mind_runtime.emotional_transition.provider import (
    UrllibChatTransport,
    validate_egress_url,
)


class LLMUnavailable(Exception):
    """The Body LLM call failed; the test should mark this as INCONCLUSIVE,
    not PASS."""


def _is_gemini_native(url: str) -> bool:
    return "generativelanguage.googleapis.com" in url and ":generateContent" in url


class RealLLMBodyAgent:
    """Real LLM Body adapter."""

    def __init__(
        self,
        *,
        endpoint_url: str,
        model: str,
        api_key: str,
        user_question: str,
        allowed_hosts: tuple[str, ...] = (),
        timeout_s: float = 60.0,
        api_key_header: str | None = None,
        api_key_prefix: str | None = None,
        extra_body: dict[str, object] | None = None,
    ) -> None:
        validate_egress_url(endpoint_url, allowed_hosts=allowed_hosts)
        self._endpoint_url = endpoint_url
        self._model = model
        self._api_key = api_key
        self._user_question = user_question
        self._transport = UrllibChatTransport(allowed_hosts=allowed_hosts)
        self._timeout_s = timeout_s
        self._gemini = _is_gemini_native(endpoint_url)
        self._api_key_header = api_key_header
        self._api_key_prefix = api_key_prefix
        self._extra_body = extra_body or {}
        self._calls: list[ProviderExpressionContext] = []
        self._responses: list[str] = []

    @property
    def calls(self) -> tuple[ProviderExpressionContext, ...]:
        return tuple(self._calls)

    @property
    def responses(self) -> tuple[str, ...]:
        return tuple(self._responses)

    def respond(self, provider_context: ProviderExpressionContext) -> str:
        self._calls.append(provider_context)
        user_text = (
            "Context the agent has been given:\n"
            f"{provider_context.text}\n\n"
            f"User question: {self._user_question}\n\n"
            "Reply as the agent. Be brief."
        )
        url, framed, _headers = self._build_request(user_text)
        try:
            parsed = self._transport.post_json(url, framed, self._timeout_s)
        except Exception as exc:
            raise LLMUnavailable(f"body llm call failed: {exc!r}") from exc
        text = _extract_chat_content(parsed, self._gemini)
        if not isinstance(text, str) or not text.strip():
            raise LLMUnavailable(f"body llm empty content: {parsed!r}")
        self._responses.append(text)
        return text

    def _build_request(self, user_text: str) -> tuple[str, dict[str, object], dict[str, str]]:
        if self._gemini:
            sep = "&" if "?" in self._endpoint_url else "?"
            url = f"{self._endpoint_url}{sep}key={urllib.parse.quote(self._api_key, safe='')}"
            framed: dict[str, object] = {
                "contents": [
                    {
                        "role": "user",
                        "parts": [{"text": user_text}],
                    }
                ],
                "generationConfig": {
                    "temperature": 0.0,
                    "maxOutputTokens": 800,
                },
            }
            return url, framed, {"Content-Type": "application/json"}
        header_name = self._api_key_header or "Authorization"
        prefix = self._api_key_prefix or "Bearer "
        framed = {
            "model": self._model,
            "messages": [{"role": "user", "content": user_text}],
            "temperature": 0.0,
            "max_tokens": 800,
            **self._extra_body,
            "_headers": {header_name: prefix + self._api_key},
        }
        return self._endpoint_url, framed, {}


def _extract_chat_content(parsed: dict[str, Any], is_gemini: bool) -> Any:
    if is_gemini:
        try:
            candidates = parsed["candidates"]
            if not candidates:
                return None
            content = candidates[0].get("content") if isinstance(candidates[0], dict) else None
            if not isinstance(content, dict):
                return None
            parts = content.get("parts")
            if not parts:
                return None
            for part in parts:
                if isinstance(part, dict) and "text" in part:
                    text = part["text"]
                    if text:
                        return text
        except (KeyError, TypeError, IndexError):
            return None
        return None
    try:
        choices = parsed["choices"]
        if not choices:
            return None
        return choices[0]["message"]["content"]
    except (KeyError, TypeError, IndexError):
        return None
