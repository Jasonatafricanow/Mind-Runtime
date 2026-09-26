"""The single optional model-facing judgment port used across MR features."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from mind_runtime.decision.contracts import DecisionRequest, DecisionResult


class DecisionModelError(RuntimeError):
    """Base failure raised by an optional decision-model backend."""


class DecisionModelUnavailable(DecisionModelError):
    """The configured backend cannot serve this request right now."""


class DecisionModelInvalidResponse(DecisionModelError):
    """The backend returned a malformed or contract-incompatible response."""


@runtime_checkable
class DecisionModelPort(Protocol):
    @property
    def backend_name(self) -> str: ...

    def evaluate(self, request: DecisionRequest) -> DecisionResult: ...
