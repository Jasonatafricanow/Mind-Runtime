"""Optional fuzzy identity projection for already-signaled Thread events."""

from __future__ import annotations

from dataclasses import dataclass

from mind_runtime.decision import (
    DecisionCapability,
    DecisionKind,
    DecisionQuestion,
    DecisionRequest,
)
from mind_runtime.memory.product import MemoryThread


@dataclass(frozen=True, slots=True)
class ThreadIdentityCandidate:
    thread: MemoryThread
    support_text: str = ""


class ThreadIdentityDecisionProjection:
    """Choose an existing OPEN Thread only when deterministic identity is weak.

    Body/Host has already decided that the current event is a Thread signal.
    This projection answers only which bounded existing line, if any, is the
    same logical line. It owns no Thread creation, maturity, or authority.
    """

    feature = "memory.thread.identity"
    projection_version = "v1"

    def __init__(
        self,
        decision: DecisionCapability,
        *,
        max_candidates: int = 8,
        minimum_probability: float = 0.65,
    ) -> None:
        if not isinstance(decision, DecisionCapability):
            raise TypeError("decision must be DecisionCapability")
        if type(max_candidates) is not int or not 1 <= max_candidates <= 16:
            raise ValueError("max_candidates must be in [1, 16]")
        if (
            isinstance(minimum_probability, bool)
            or not isinstance(minimum_probability, (int, float))
            or not 0.5 <= float(minimum_probability) <= 1.0
        ):
            raise ValueError("minimum_probability must be in [0.5, 1]")
        self._decision = decision
        self._max_candidates = max_candidates
        self._minimum_probability = float(minimum_probability)

    @property
    def available(self) -> bool:
        return self._decision.available

    def choose(
        self,
        *,
        question: str | None,
        summary: str | None,
        candidates: tuple[ThreadIdentityCandidate, ...],
    ) -> str | None:
        if not self.available or not candidates:
            return None
        bounded = candidates[: self._max_candidates]
        query = " ".join(
            value.strip()
            for value in (question, summary)
            if isinstance(value, str) and value.strip()
        )
        if not query:
            return None
        state: dict[str, str] = {"current_thread_signal": query[:4096]}
        options = ["none"]
        for index, candidate in enumerate(bounded):
            key = f"thread_{index}"
            options.append(key)
            state[key] = (
                f"question: {candidate.thread.open_question}\n"
                f"summary: {candidate.thread.working_summary or ''}\n"
                f"support: {candidate.support_text}"
            )[:4096]
        result = self._decision.evaluate(
            DecisionRequest(
                feature=self.feature,
                projection_version=self.projection_version,
                state=state,
                questions=(
                    DecisionQuestion(
                        question_id="same_line",
                        kind=DecisionKind.CHOICE,
                        instructions=(
                            "Which existing thread is the same unresolved "
                            "logical line as current_thread_signal? Choose "
                            "none when the event opens a distinct line."
                        ),
                        options=tuple(options),
                    ),
                ),
            )
        )
        if result is None:
            return None
        answer = result.answer("same_line")
        selected = answer.selected
        if (
            selected is None
            or selected == "none"
            or answer.probability(selected) < self._minimum_probability
        ):
            return None
        if not selected.startswith("thread_"):
            return None
        try:
            index = int(selected.removeprefix("thread_"))
        except ValueError:
            return None
        if not 0 <= index < len(bounded):
            return None
        return bounded[index].thread.thread_id
