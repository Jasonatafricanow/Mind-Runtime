"""Explicit bounded historical context; never assemble a transcript."""

from dataclasses import dataclass

from historical.source_curator import HistoricalSourceCurator, SourceDisposition
from historical.source_iterator import HistoricalSource


@dataclass(frozen=True)
class HistoricalContext:
    current: HistoricalSource
    context_only: tuple
    activated_blocks: tuple

    @property
    def activated_memory_ids(self):
        return tuple(block.memory_id for block in self.activated_blocks)


class HistoricalContextAssembler:
    def __init__(self, sources, memory, *, max_context=4, max_blocks=4, max_chars=12000):
        self.sources, self.memory = sources, memory
        self.max_context, self.max_blocks, self.max_chars = max_context, max_blocks, max_chars
        if min(max_context, max_blocks, max_chars) < 1:
            raise ValueError("positive offline context bounds required")

    def assemble(self, current, *, context_refs=(), activated_memory_ids=()):
        curator = HistoricalSourceCurator()
        if self.sources.get(current.source_ref) != current:
            raise ValueError("current historical source drift")
        if curator.classify(current) != SourceDisposition.COMPILE:
            raise ValueError("only eligible USER source may compile")
        if len(context_refs) > self.max_context or len(activated_memory_ids) > self.max_blocks:
            raise ValueError("historical context selection exceeds bound")
        if len({ref.source_key for ref in context_refs}) != len(context_refs):
            raise ValueError("duplicate context source")
        context = []
        for ref in context_refs:
            item = self.sources.get(ref)
            if item is None or item.source_ref != ref:
                raise ValueError("exact context source required")
            if (
                ref.session_id != current.source_ref.session_id
                or item.ordering_key >= current.ordering_key
                or curator.classify(item, necessary_context=True) != SourceDisposition.CONTEXT_ONLY
            ):
                raise ValueError("context must be earlier CONTEXT_ONLY material in this session")
            context.append(item)
        blocks = (
            self.memory.select(
                tuple(activated_memory_ids),
                scope=self.sources.scope,
                active_only=True,
                max_items=self.max_blocks,
            )
            if activated_memory_ids
            else ()
        )
        if any(self.memory.get_semantic_metadata(block.memory_id) is None for block in blocks):
            raise ValueError("only MR-Mem canonical SemanticBlocks may be activated")
        if any(block.occurred_at > current.source_ref.occurred_at for block in blocks):
            raise ValueError("future historical cognition cannot supply current context")
        chars = sum(len(item.content or "") for item in (current, *context, *blocks))
        if chars > self.max_chars:
            raise ValueError("historical context exceeds character budget; select less context")
        return HistoricalContext(current, tuple(context), blocks)
