from __future__ import annotations

from datetime import UTC, datetime

from mind_runtime.contracts import Scope, ScopeDomain
from mind_runtime.memory.contracts import (
    CommittedMemory,
    MemoryLifecycle,
    MemoryProvenance,
)
from mind_runtime.memory.embedding import EmbeddingIdentity
from mind_runtime.memory.providers.dense import InMemoryDenseRetrievalProvider
from mind_runtime.memory.retrieval import MemoryRetrievalQuery


class _Embedding:
    identity = EmbeddingIdentity("fake", "tiny", 3, "v1")

    def embed(self, text: str) -> tuple[float, ...]:
        lowered = text.casefold()
        if "apple" in lowered:
            return (1.0, 0.0, 0.0)
        if "beach" in lowered:
            return (0.0, 1.0, 0.0)
        return (0.0, 0.0, 1.0)


def _memory(memory_id: str, content: str, user_id: str = "u") -> CommittedMemory:
    scope = Scope(ScopeDomain.USER, user_id=user_id)
    return CommittedMemory(
        memory_id=memory_id,
        scope=scope,
        content=content,
        provenance=MemoryProvenance(
            (f"e-{memory_id}",),
            f"o-{memory_id}",
            "test",
            interaction_id=f"i-{memory_id}",
        ),
        lifecycle=MemoryLifecycle.ACTIVE,
        committed_at=datetime(2026, 1, 1, tzinfo=UTC),
        origin_runtime_id="runtime",
    )


def test_dense_snapshot_ranks_semantic_match_and_preserves_scope() -> None:
    provider = InMemoryDenseRetrievalProvider(
        (
            _memory("apple", "The user likes apples."),
            _memory("beach", "The user likes beaches."),
            _memory("other-user", "The user likes apples.", "other"),
        ),
        embedding=_Embedding(),
    )
    hits = provider.search(
        MemoryRetrievalQuery(
            Scope(ScopeDomain.USER, user_id="u"),
            "apple preference",
            10,
        )
    )
    assert tuple(item.memory_id for item in hits) == ("apple", "beach")
    assert hits[0].score == 1.0
