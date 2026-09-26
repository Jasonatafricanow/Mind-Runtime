"""Projection from canonical Memory candidates into generic decision questions."""

from __future__ import annotations

from dataclasses import dataclass

from mind_runtime.decision import (
    DecisionCapability,
    DecisionKind,
    DecisionQuestion,
    DecisionRequest,
)


@dataclass(frozen=True, slots=True)
class MemoryRerankCandidate:
    memory_id: str
    content: str

    def __post_init__(self) -> None:
        if not isinstance(self.memory_id, str) or not self.memory_id.strip():
            raise ValueError("memory_id must be nonempty")
        if not isinstance(self.content, str) or not self.content.strip():
            raise ValueError("content must be nonempty")


class MemoryRetrievalDecisionProjection:
    """Optional semantic reranking over already-authorized canonical Memory."""

    feature = "memory.retrieval.rerank"
    projection_version = "v1"

    def __init__(
        self,
        decision: DecisionCapability,
        *,
        max_candidate_characters: int = 2048,
        max_candidates: int = 24,
    ) -> None:
        if not isinstance(decision, DecisionCapability):
            raise TypeError("decision must be DecisionCapability")
        if (
            type(max_candidate_characters) is not int
            or not 128 <= max_candidate_characters <= 8192
        ):
            raise ValueError("max_candidate_characters must be in [128, 8192]")
        if type(max_candidates) is not int or not 2 <= max_candidates <= 24:
            raise ValueError("max_candidates must be in [2, 24]")
        self._decision = decision
        self._max_candidate_characters = max_candidate_characters
        self._max_candidates = max_candidates

    @property
    def available(self) -> bool:
        return self._decision.available

    def rerank(
        self,
        *,
        query: str,
        candidates: tuple[MemoryRerankCandidate, ...],
    ) -> tuple[str, ...]:
        baseline = tuple(candidate.memory_id for candidate in candidates)
        if len(candidates) < 2 or not self._decision.available:
            return baseline
        judged = candidates[: self._max_candidates]
        untouched = candidates[self._max_candidates :]
        state: dict[str, str] = {"query": query[:4096]}
        questions: list[DecisionQuestion] = []
        for index, candidate in enumerate(judged):
            key = f"candidate_{index}"
            state[key] = candidate.content[: self._max_candidate_characters]
            questions.append(
                DecisionQuestion(
                    question_id=f"relevance_{index}",
                    kind=DecisionKind.BOOLEAN,
                    instructions=(
                        f"Is {key} materially relevant to answering or contextualizing "
                        "the current query? Judge semantic relevance only, not factual truth."
                    ),
                )
            )
        result = self._decision.evaluate(
            DecisionRequest(
                feature=self.feature,
                projection_version=self.projection_version,
                state=state,
                questions=tuple(questions),
            )
        )
        if result is None:
            return baseline
        scored = [
            (
                result.answer(f"relevance_{index}").yes_probability,
                index,
                candidate.memory_id,
            )
            for index, candidate in enumerate(judged)
        ]
        scored.sort(key=lambda item: (-item[0], item[1]))
        return tuple(memory_id for _, _, memory_id in scored) + tuple(
            candidate.memory_id for candidate in untouched
        )
