"""Dependency-light dense retrieval over an immutable canonical Memory snapshot."""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass

from mind_runtime.memory.contracts import CommittedMemory, MemoryLifecycle
from mind_runtime.memory.embedding import EmbeddingProvider, validate_vector
from mind_runtime.memory.retrieval import (
    MemoryRetrievalQuery,
    RetrievalProviderUnavailable,
    RetrievedMemoryCandidate,
)
from mind_runtime.memory.store import scope_json


@dataclass(frozen=True, slots=True)
class _DenseDocument:
    memory_id: str
    scope_key: str
    vector: tuple[float, ...]


def _cosine(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    numerator = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return numerator / (left_norm * right_norm)


class InMemoryDenseRetrievalProvider:
    """Dense snapshot provider used when a separate vector DB is unnecessary."""

    def __init__(
        self,
        memories: Iterable[CommittedMemory],
        *,
        embedding: EmbeddingProvider,
    ) -> None:
        self._embedding = embedding
        documents: list[_DenseDocument] = []
        try:
            for memory in memories:
                if not isinstance(memory, CommittedMemory):
                    raise ValueError(
                        "dense snapshot requires canonical CommittedMemory values"
                    )
                if memory.lifecycle is not MemoryLifecycle.ACTIVE:
                    continue
                vector = validate_vector(
                    embedding.embed(memory.content),
                    embedding.identity,
                )
                documents.append(
                    _DenseDocument(
                        memory.memory_id,
                        scope_json(memory.scope),
                        vector,
                    )
                )
        except Exception as exc:
            if isinstance(exc, ValueError):
                raise
            raise RetrievalProviderUnavailable(
                "dense Memory snapshot construction failed"
            ) from exc
        self._documents = tuple(documents)

    def search(
        self, query: MemoryRetrievalQuery
    ) -> tuple[RetrievedMemoryCandidate, ...]:
        if query.limit == 0:
            return ()
        try:
            query_vector = validate_vector(
                self._embedding.embed(query.text),
                self._embedding.identity,
            )
        except Exception as exc:
            raise RetrievalProviderUnavailable(
                "dense query embedding failed"
            ) from exc
        scope_key = scope_json(query.scope)
        ranked = sorted(
            (
                (_cosine(query_vector, document.vector), document.memory_id)
                for document in self._documents
                if document.scope_key == scope_key
            ),
            key=lambda item: (-item[0], item[1]),
        )
        return tuple(
            RetrievedMemoryCandidate(
                memory_id=memory_id,
                provider="dense-memory-snapshot",
                provider_ref=f"dense:{memory_id}",
                score=score,
            )
            for score, memory_id in ranked[: query.limit]
        )
