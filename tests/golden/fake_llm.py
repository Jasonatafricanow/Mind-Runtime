"""Fake LLM for golden scenarios: records call_count/prompt_type/response."""

from collections.abc import Mapping

from tests.golden.scenario import LlmCall


class FakeLLM:
    """Scripted LLM double that records every call."""

    def __init__(self, script: Mapping[str, object]) -> None:
        self._script = dict(script)
        self._calls: list[LlmCall] = []

    @property
    def call_count(self) -> int:
        return len(self._calls)

    @property
    def prompt_types(self) -> list[str]:
        return [call.prompt_type for call in self._calls]

    @property
    def calls(self) -> tuple[LlmCall, ...]:
        return tuple(self._calls)

    def complete(self, prompt_type: str) -> object:
        if prompt_type not in self._script:
            raise KeyError(f"unscripted prompt type: {prompt_type}")
        response = self._script[prompt_type]
        self._calls.append(LlmCall(prompt_type, response))
        return response
