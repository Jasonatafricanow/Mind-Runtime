"""Scripted agent double for the D2S walking skeleton."""

from collections.abc import Sequence

from mind_runtime.contracts import ProviderExpressionContext
from mind_runtime.pipeline.ports import AgentFailure


class FakeAgent:
    """Returns scripted responses in order; raises on scripted failures.

    Each entry is either a string (response) or an AgentFailure (raise).
    Records every call for inspection.
    """

    def __init__(self, script: Sequence[str | AgentFailure]) -> None:
        if not script:
            raise ValueError("script must not be empty")
        self._script = list(script)
        self._index = 0
        self._calls: list[ProviderExpressionContext] = []

    @property
    def call_count(self) -> int:
        return len(self._calls)

    @property
    def calls(self) -> tuple[ProviderExpressionContext, ...]:
        return tuple(self._calls)

    def respond(self, provider_context: ProviderExpressionContext) -> str:
        self._calls.append(provider_context)
        entry = self._script[self._index]
        if self._index < len(self._script) - 1:
            self._index += 1
        if isinstance(entry, AgentFailure):
            raise entry
        return entry
