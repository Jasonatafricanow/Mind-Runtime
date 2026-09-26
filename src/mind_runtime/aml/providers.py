"""Host-owned semantic helpers for the AML adapter.

These helpers are outside MR's authority plane. They may propose bounded
Thread hints or HyDE text, but cannot construct canonical Memory, Scope,
provenance, or accepted LCE cognition.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Protocol

from mind_runtime.aml.contracts import AmlMessage
from mind_runtime.emotional_transition.provider import UrllibChatTransport
from mind_runtime.memory.embedding import EmbeddingIdentity, validate_vector


@dataclass(frozen=True, slots=True)
class ThreadSemanticDecision:
    action: str
    question: str | None = None
    summary: str | None = None
    mature: bool = False
    confidence: float = 1.0

    def __post_init__(self) -> None:
        if self.action not in {"track", "resolve", "none"}:
            raise ValueError("action must be track, resolve, or none")
        if self.question is not None and (
            not isinstance(self.question, str) or not self.question.strip()
        ):
            raise ValueError("question must be nonempty when supplied")
        if self.summary is not None and (
            not isinstance(self.summary, str) or not self.summary.strip()
        ):
            raise ValueError("summary must be nonempty when supplied")
        if type(self.mature) is not bool:
            raise TypeError("mature must be bool")
        if (
            isinstance(self.confidence, bool)
            or not isinstance(self.confidence, (int, float))
            or not 0 <= float(self.confidence) <= 1
        ):
            raise ValueError("confidence must be in [0, 1]")
        if self.action == "track" and self.question is None:
            raise ValueError("track requires a question")


class AmlThreadSemanticPort(Protocol):
    def analyze(
        self,
        *,
        message: AmlMessage,
        context: tuple[AmlMessage, ...],
        active_threads: tuple[str, ...] = (),
    ) -> ThreadSemanticDecision:
        ...


def _chat_text(response: dict[str, object]) -> str:
    try:
        choices = response["choices"]
        if not isinstance(choices, list) or not choices:
            raise ValueError
        first = choices[0]
        if not isinstance(first, dict):
            raise ValueError
        message = first["message"]
        if not isinstance(message, dict):
            raise ValueError
        content = message["content"]
        if not isinstance(content, str) or not content.strip():
            raise ValueError
        return content.strip()
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("chat provider returned no usable content") from exc


def _json_object(text: str) -> dict[str, object]:
    stripped = text.strip()
    fence = chr(96) * 3
    if stripped.startswith(fence) and stripped.endswith(fence):
        stripped = stripped[len(fence):].strip()
        if stripped.casefold().startswith("json"):
            stripped = stripped[4:].strip()
        stripped = stripped[:-len(fence)].strip()
    parsed = json.loads(stripped)
    if not isinstance(parsed, dict):
        raise ValueError("model output must be one JSON object")
    return parsed


class OpenAICompatibleThreadSemanticProvider:
    """Bounded AML-host semantic proposer for Thread maintenance."""

    def __init__(
        self,
        *,
        endpoint: str,
        api_key: str,
        model: str,
        timeout_seconds: float = 20.0,
        allowed_hosts: tuple[str, ...] = (),
    ) -> None:
        if not endpoint.strip() or not api_key.strip() or not model.strip():
            raise ValueError("endpoint, api_key and model must be nonempty")
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or not 0 < float(timeout_seconds) <= 120
        ):
            raise ValueError("timeout_seconds must be in (0, 120]")
        self._endpoint = endpoint
        self._api_key = api_key
        self._model = model
        self._timeout = float(timeout_seconds)
        self._transport = UrllibChatTransport(allowed_hosts=allowed_hosts)

    def analyze(
        self,
        *,
        message: AmlMessage,
        context: tuple[AmlMessage, ...],
        active_threads: tuple[str, ...] = (),
    ) -> ThreadSemanticDecision:
        transcript = "\n".join(
            f"{item.role}: {item.content}" for item in context[-8:]
        )[-12000:]
        thread_context = "\n".join(active_threads[-8:])[-8000:]
        prompt = (
            "You are the host-side semantic adapter for a memory system. "
            "Judge only whether the CURRENT message opens/continues an unresolved "
            "multi-turn line (track), resolves such a line (resolve), or does "
            "neither (none). Do not infer hidden facts. Return exactly one JSON "
            "object with keys action, question, summary, mature, confidence. "
            "question is a short stable description of the unresolved line; "
            "summary is the current state of that line. mature may be true only "
            "when the visible transcript contains repeated independent support. "
            "Use null for unavailable question/summary.\n\n"
            f"Existing active working lines:\n{thread_context or '(none)'}\n\n"
            f"Visible transcript:\n{transcript}\n\n"
            f"CURRENT:\n{message.role}: {message.content}"
        )
        parsed = self._transport.post_json(
            self._endpoint,
            {
                "model": self._model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0,
                "max_tokens": 300,
                "_headers": {
                    "Authorization": f"Bearer {self._api_key}",
                },
            },
            self._timeout,
        )
        data = _json_object(_chat_text(parsed))
        action = data.get("action")
        question = data.get("question")
        summary = data.get("summary")
        mature = data.get("mature", False)
        confidence = data.get("confidence", 1.0)
        if not isinstance(action, str):
            raise ValueError("semantic provider action must be a string")
        if question is not None and not isinstance(question, str):
            raise ValueError("semantic provider question must be string or null")
        if summary is not None and not isinstance(summary, str):
            raise ValueError("semantic provider summary must be string or null")
        return ThreadSemanticDecision(
            action=action.strip().casefold(),
            question=question.strip() if isinstance(question, str) else None,
            summary=summary.strip() if isinstance(summary, str) else None,
            mature=mature if type(mature) is bool else False,
            confidence=float(confidence),
        )


class OpenAICompatibleCompletion:
    """Small host-side completion seam usable by PromptHyDEExpander."""

    def __init__(
        self,
        *,
        endpoint: str,
        api_key: str,
        model: str,
        timeout_seconds: float = 12.0,
        allowed_hosts: tuple[str, ...] = (),
    ) -> None:
        if not endpoint.strip() or not api_key.strip() or not model.strip():
            raise ValueError("endpoint, api_key and model must be nonempty")
        self._endpoint = endpoint
        self._api_key = api_key
        self._model = model
        self._timeout = float(timeout_seconds)
        self._transport = UrllibChatTransport(allowed_hosts=allowed_hosts)

    def __call__(self, prompt: str) -> str:
        response = self._transport.post_json(
            self._endpoint,
            {
                "model": self._model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0,
                "max_tokens": 300,
                "_headers": {
                    "Authorization": f"Bearer {self._api_key}",
                },
            },
            self._timeout,
        )
        return _chat_text(response)



class OpenAICompatibleEmbedding:
    """OpenAI-compatible embedding adapter for AML deployment profiles."""

    def __init__(
        self,
        *,
        endpoint: str,
        api_key: str,
        model: str,
        dimension: int,
        revision: str,
        timeout_seconds: float = 12.0,
        allowed_hosts: tuple[str, ...] = (),
    ) -> None:
        if not endpoint.strip() or not api_key.strip() or not model.strip():
            raise ValueError("endpoint, api_key and model must be nonempty")
        self._identity = EmbeddingIdentity(
            "openai-compatible",
            model,
            dimension,
            revision,
        )
        self._endpoint = endpoint
        self._api_key = api_key
        self._model = model
        self._timeout = float(timeout_seconds)
        self._transport = UrllibChatTransport(allowed_hosts=allowed_hosts)

    @property
    def identity(self) -> EmbeddingIdentity:
        return self._identity

    def embed(self, text: str) -> tuple[float, ...]:
        if not isinstance(text, str) or not text.strip():
            raise ValueError("embedding input must be nonempty")
        response = self._transport.post_json(
            self._endpoint,
            {
                "model": self._model,
                "input": [text],
                "_headers": {
                    "Authorization": f"Bearer {self._api_key}",
                },
            },
            self._timeout,
        )
        try:
            data = response["data"]
            if not isinstance(data, list) or len(data) != 1:
                raise ValueError
            row = data[0]
            if not isinstance(row, dict):
                raise ValueError
            vector = row["embedding"]
            if not isinstance(vector, list):
                raise ValueError
            values = tuple(float(value) for value in vector)
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(
                "embedding provider returned an invalid vector response"
            ) from exc
        return validate_vector(values, self._identity)
