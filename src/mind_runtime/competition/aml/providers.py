"""OpenAI-compatible providers owned by the AML competition host."""

from __future__ import annotations

import hashlib
import json

from mind_runtime.competition.aml.contracts import AmlMessage
from mind_runtime.competition.aml.semantic import AmlHostSemanticPort
from mind_runtime.contracts import Scope, SemanticEventCandidate
from mind_runtime.emotional_transition.provider import UrllibChatTransport
from mind_runtime.memory.embedding import EmbeddingIdentity, validate_vector
from mind_runtime.memory.product import MemoryThread


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
        raise ValueError(
            "chat provider returned no usable content"
        ) from exc


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


class _OpenAIChat:
    def __init__(
        self,
        *,
        endpoint: str,
        api_key: str,
        model: str,
        timeout_seconds: float,
        allowed_hosts: tuple[str, ...] = (),
    ) -> None:
        if not endpoint.strip() or not api_key.strip() or not model.strip():
            raise ValueError(
                "endpoint, api_key and model must be nonempty"
            )
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or not 0 < float(timeout_seconds) <= 120
        ):
            raise ValueError("timeout_seconds must be in (0, 120]")
        self.endpoint = endpoint
        self.api_key = api_key
        self.model = model
        self.timeout = float(timeout_seconds)
        self.transport = UrllibChatTransport(
            allowed_hosts=allowed_hosts
        )

    def complete(
        self,
        prompt: str,
        *,
        max_tokens: int,
    ) -> str:
        response = self.transport.post_json(
            self.endpoint,
            {
                "model": self.model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0,
                "max_tokens": max_tokens,
                "_headers": {
                    "Authorization": f"Bearer {self.api_key}",
                },
            },
            self.timeout,
        )
        return _chat_text(response)


class OpenAICompatibleCompletion:
    """Callable completion seam for PromptHyDEExpander."""

    def __init__(
        self,
        *,
        endpoint: str,
        api_key: str,
        model: str,
        timeout_seconds: float = 12.0,
        allowed_hosts: tuple[str, ...] = (),
    ) -> None:
        self._chat = _OpenAIChat(
            endpoint=endpoint,
            api_key=api_key,
            model=model,
            timeout_seconds=timeout_seconds,
            allowed_hosts=allowed_hosts,
        )

    def __call__(self, prompt: str) -> str:
        return self._chat.complete(prompt, max_tokens=300)


class OpenAICompatibleEmbedding:
    """OpenAI-compatible embedding adapter for competition profiles."""

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
        if type(dimension) is not int or dimension < 1:
            raise ValueError("dimension must be a positive integer")
        self._identity = EmbeddingIdentity(
            "openai-compatible",
            model,
            dimension,
            revision,
        )
        self._chat = _OpenAIChat(
            endpoint=endpoint,
            api_key=api_key,
            model=model,
            timeout_seconds=timeout_seconds,
            allowed_hosts=allowed_hosts,
        )

    @property
    def identity(self) -> EmbeddingIdentity:
        return self._identity

    def embed(self, text: str) -> tuple[float, ...]:
        if not isinstance(text, str) or not text.strip():
            raise ValueError("embedding input must be nonempty")
        response = self._chat.transport.post_json(
            self._chat.endpoint,
            {
                "model": self._chat.model,
                "input": [text],
                "_headers": {
                    "Authorization": (
                        f"Bearer {self._chat.api_key}"
                    ),
                },
            },
            self._chat.timeout,
        )
        try:
            data = response["data"]
            if not isinstance(data, list) or len(data) != 1:
                raise ValueError
            row = data[0]
            if not isinstance(row, dict):
                raise ValueError
            raw = row["embedding"]
            if not isinstance(raw, list):
                raise ValueError
            vector = tuple(float(value) for value in raw)
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(
                "embedding provider returned an invalid vector"
            ) from exc
        return validate_vector(vector, self.identity)


class OpenAICompatibleAmlHostSemanticProvider(AmlHostSemanticPort):
    """Competition Host/Body semantic producer for Thread hints only."""

    def __init__(
        self,
        *,
        endpoint: str,
        api_key: str,
        model: str,
        timeout_seconds: float = 20.0,
        allowed_hosts: tuple[str, ...] = (),
    ) -> None:
        self._chat = _OpenAIChat(
            endpoint=endpoint,
            api_key=api_key,
            model=model,
            timeout_seconds=timeout_seconds,
            allowed_hosts=allowed_hosts,
        )

    def events(
        self,
        *,
        message: AmlMessage,
        visible_messages: tuple[AmlMessage, ...],
        active_threads: tuple[MemoryThread, ...],
        scope: Scope,
        origin_runtime_id: str,
        evidence_ref: str,
    ) -> tuple[SemanticEventCandidate, ...]:
        transcript = "\n".join(
            f"{item.role}: {item.content}"
            for item in visible_messages[-8:]
        )[-12000:]
        active = "\n".join(
            f"{thread.open_question} :: "
            f"{thread.working_summary or ''}"
            for thread in active_threads[-8:]
        )[-8000:]
        prompt = (
            "You are the Body/Host semantic adapter for a memory system. "
            "Judge only whether CURRENT opens/continues an unresolved "
            "multi-turn line (track), resolves one (resolve), or does "
            "neither (none). Return exactly one JSON object with keys "
            "action, question, summary, mature, confidence. question is a "
            "short stable description of the logical line. mature may be "
            "true only when visible history has repeated independent "
            "support. Do not invent facts. Use null where unavailable.\n\n"
            f"Active lines:\n{active or '(none)'}\n\n"
            f"Visible transcript:\n{transcript}\n\n"
            f"CURRENT:\n{message.role}: {message.content}"
        )
        data = _json_object(
            self._chat.complete(prompt, max_tokens=300)
        )
        action = data.get("action")
        question = data.get("question")
        summary = data.get("summary")
        mature = data.get("mature", False)
        confidence = data.get("confidence", 1.0)
        if not isinstance(action, str):
            raise ValueError("semantic action must be a string")
        action = action.strip().casefold()
        if action == "none":
            return ()
        if action not in {"track", "resolve"}:
            raise ValueError("semantic action is outside bounded set")
        if question is not None and not isinstance(question, str):
            raise ValueError("question must be string or null")
        if summary is not None and not isinstance(summary, str):
            raise ValueError("summary must be string or null")
        if action == "track" and (
            not isinstance(question, str) or not question.strip()
        ):
            raise ValueError("track requires a stable question")
        if isinstance(confidence, bool) or not isinstance(
            confidence, (int, float)
        ):
            raise ValueError("confidence must be numeric")
        value = float(confidence)
        if not 0 <= value <= 1:
            raise ValueError("confidence must be in [0, 1]")
        attrs: list[tuple[str, str]] = [
            ("thread_action", action),
        ]
        if isinstance(question, str) and question.strip():
            attrs.append(("thread_question", question.strip()))
        if isinstance(summary, str) and summary.strip():
            attrs.append(("thread_summary", summary.strip()))
        if mature is True:
            attrs.append(("thread_mature", "true"))
        digest = hashlib.sha256(
            json.dumps(
                [
                    evidence_ref,
                    action,
                    question,
                    summary,
                ],
                ensure_ascii=False,
            ).encode()
        ).hexdigest()[:24]
        return (
            SemanticEventCandidate(
                candidate_id=f"aml-thread-{digest}",
                scope=scope,
                origin_runtime_id=origin_runtime_id,
                kind="aml.thread_signal",
                attributes=tuple(attrs),
                confidence=value,
                evidence_refs=(evidence_ref,),
            ),
        )
