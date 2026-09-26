"""Optional model-backed LCE proposals owned by the AML host."""

from __future__ import annotations

import json
from collections.abc import Sequence

from lce.cognition.promotion import (
    BoundedInterpretation,
    BoundedInterpretationPackage,
)
from lce.reference_memory.contracts import RawEvidence, SemanticBlock
from lce.semantic.contracts import (
    SemanticDecision,
    SemanticGroup,
)

from mind_runtime.emotional_transition.provider import UrllibChatTransport


def _content(response: dict[str, object]) -> str:
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
        raise ValueError("LCE host model returned no usable content") from exc


def _json(text: str) -> dict[str, object]:
    stripped = text.strip()
    fence = chr(96) * 3
    if stripped.startswith(fence) and stripped.endswith(fence):
        stripped = stripped[len(fence):].strip()
        if stripped.casefold().startswith("json"):
            stripped = stripped[4:].strip()
        stripped = stripped[:-len(fence)].strip()
    parsed = json.loads(stripped)
    if not isinstance(parsed, dict):
        raise ValueError("LCE host model must return one JSON object")
    return parsed


class _Chat:
    def __init__(
        self,
        *,
        endpoint: str,
        api_key: str,
        model: str,
        timeout_seconds: float,
        allowed_hosts: tuple[str, ...],
    ) -> None:
        if not endpoint.strip() or not api_key.strip() or not model.strip():
            raise ValueError("endpoint, api_key and model must be nonempty")
        self.endpoint = endpoint
        self.api_key = api_key
        self.model = model
        self.timeout = float(timeout_seconds)
        self.transport = UrllibChatTransport(allowed_hosts=allowed_hosts)

    def call(self, prompt: str, *, max_tokens: int) -> dict[str, object]:
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
        return _json(_content(response))


class OpenAICompatibleLceSemanticProvider:
    """Body-owned proposal adapter for the existing LCE compiler seam."""

    def __init__(
        self,
        *,
        endpoint: str,
        api_key: str,
        model: str,
        timeout_seconds: float = 20.0,
        allowed_hosts: tuple[str, ...] = (),
    ) -> None:
        self._chat = _Chat(
            endpoint=endpoint,
            api_key=api_key,
            model=model,
            timeout_seconds=timeout_seconds,
            allowed_hosts=allowed_hosts,
        )

    def decide(
        self,
        *,
        evidence: RawEvidence,
        open_block: SemanticBlock | None,
        recent_blocks: Sequence[SemanticBlock],
    ) -> SemanticDecision:
        recent = [
            {
                "block_id": block.block_id,
                "subject": str(block.metadata.get("subject", "")),
                "content": block.content,
            }
            for block in tuple(recent_blocks)[-12:]
        ]
        open_payload = (
            None
            if open_block is None
            else {
                "block_id": open_block.block_id,
                "subject": str(open_block.metadata.get("subject", "")),
                "content": open_block.content,
            }
        )
        prompt = (
            "Classify one canonical memory unit for a longitudinal Semantic "
            "Block compiler. Return exactly one JSON object with keys action, "
            "subject, cognition, groups, recap_block_ids, new_information, "
            "reason. action must be NEW, CONTINUE, MERGE, SPLIT, AUXILIARY, "
            "or RECAP. Prefer CONTINUE only when the current evidence truly "
            "continues the open subject. Use RECAP only for repeated material; "
            "recap_block_ids may contain only IDs shown below. SPLIT requires "
            "at least two groups, each with subject and cognition. Do not infer "
            "facts not present in the evidence.\n\n"
            f"Evidence: {evidence.content}\n"
            f"Open block: {json.dumps(open_payload, ensure_ascii=False)}\n"
            f"Recent blocks: {json.dumps(recent, ensure_ascii=False)}"
        )
        data = self._chat.call(prompt, max_tokens=700)
        action = data.get("action")
        subject = data.get("subject")
        cognition = data.get("cognition")
        reason = data.get("reason", "")
        if not all(isinstance(value, str) for value in (action, subject, cognition, reason)):
            raise ValueError("LCE semantic proposal has invalid scalar fields")
        raw_groups = data.get("groups", [])
        if not isinstance(raw_groups, list):
            raise ValueError("LCE semantic groups must be a list")
        groups: list[SemanticGroup] = []
        for raw in raw_groups:
            if not isinstance(raw, dict):
                raise ValueError("LCE semantic group must be an object")
            group_subject = raw.get("subject")
            group_cognition = raw.get("cognition")
            if not isinstance(group_subject, str) or not isinstance(group_cognition, str):
                raise ValueError("LCE semantic group fields must be strings")
            groups.append(SemanticGroup(group_subject, group_cognition))
        raw_recaps = data.get("recap_block_ids", [])
        if not isinstance(raw_recaps, list) or any(
            not isinstance(item, str) for item in raw_recaps
        ):
            raise ValueError("recap_block_ids must be a string list")
        allowed = {block.block_id for block in recent_blocks}
        recap_ids = tuple(raw_recaps)
        if any(item not in allowed for item in recap_ids):
            raise ValueError("LCE semantic proposal selected an unknown recap block")
        new_information = data.get("new_information")
        if new_information is not None and not isinstance(new_information, str):
            raise ValueError("new_information must be string or null")
        return SemanticDecision(
            action=action,
            subject=subject,
            cognition=cognition,
            groups=tuple(groups),
            recap_block_ids=recap_ids,
            new_information=new_information,
            reason=reason,
        )


class OpenAICompatibleBoundedInterpreter:
    """Bounded LCE interpretation over only the package supplied by LCE."""

    def __init__(
        self,
        *,
        endpoint: str,
        api_key: str,
        model: str,
        timeout_seconds: float = 20.0,
        allowed_hosts: tuple[str, ...] = (),
    ) -> None:
        self._chat = _Chat(
            endpoint=endpoint,
            api_key=api_key,
            model=model,
            timeout_seconds=timeout_seconds,
            allowed_hosts=allowed_hosts,
        )

    def interpret(
        self,
        package: BoundedInterpretationPackage,
    ) -> BoundedInterpretation:
        blocks = [
            {
                "block_id": block.block_id,
                "content": block.content,
                "subject": str(block.metadata.get("subject", "")),
            }
            for block in package.semantic_blocks
        ]
        previous = (
            package.previous_baseline.content
            if package.previous_baseline is not None
            else None
        )
        prompt = (
            "Interpret only the bounded longitudinal evidence below. Return "
            "exactly one JSON object with status, content, supporting_block_ids. "
            "status must be PROPOSED, UNKNOWN, or REJECTED. Use UNKNOWN when "
            "the relation is underdetermined. A PROPOSED content must state a "
            "specific longitudinal conclusion supported by the selected blocks. "
            "supporting_block_ids may contain only IDs shown below. Do not add "
            "outside knowledge.\n\n"
            f"Candidate relation: {package.candidate.relation_type}\n"
            f"Previous accepted understanding: {previous}\n"
            f"Blocks: {json.dumps(blocks, ensure_ascii=False)}"
        )
        data = self._chat.call(prompt, max_tokens=700)
        status = data.get("status")
        content = data.get("content")
        raw_ids = data.get("supporting_block_ids", [])
        if not isinstance(status, str):
            raise ValueError("bounded interpretation status must be a string")
        if content is not None and not isinstance(content, str):
            raise ValueError("bounded interpretation content must be string or null")
        if not isinstance(raw_ids, list) or any(
            not isinstance(item, str) for item in raw_ids
        ):
            raise ValueError("supporting_block_ids must be a string list")
        allowed = {block.block_id for block in package.semantic_blocks}
        block_ids = tuple(raw_ids)
        if any(block_id not in allowed for block_id in block_ids):
            raise ValueError("bounded interpretation selected unauthorized support")
        return BoundedInterpretation(
            content=content,
            supporting_block_ids=block_ids,
            status=status,
            model_trace={
                "provider": "openai-compatible-host",
                "model": self._chat.model,
            },
        )
