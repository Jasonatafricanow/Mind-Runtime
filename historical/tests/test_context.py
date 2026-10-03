import pytest
from historical.context_assembler import HistoricalContextAssembler
from mr_mem.memory.core import MemoryCore


def test_short_user_has_only_explicit_assistant_context(native, tmp_path):
    _, _, reader = native
    records = tuple(reader.iterate())
    with MemoryCore(tmp_path / "context.sqlite") as memory:
        assembler = HistoricalContextAssembler(reader, memory)
        result = assembler.assemble(records[1], context_refs=(records[0].source_ref,))
        assert result.current.content == "A"
        assert tuple(item.content for item in result.context_only) == ("采用 A 还是 B？",)
        assert result.activated_blocks == ()
        assert assembler.assemble(records[4]).context_only == ()
        for ref in (records[1].source_ref, records[2].source_ref, records[3].source_ref):
            with pytest.raises(ValueError, match="CONTEXT_ONLY"):
                assembler.assemble(records[4], context_refs=(ref,))
        with pytest.raises(ValueError, match="CONTEXT_ONLY"):
            assembler.assemble(records[1], context_refs=(records[-1].source_ref,))


def test_complete_selection_rejected_on_unknown_block_and_budget(native, tmp_path):
    _, _, reader = native
    source = tuple(reader.iterate())[1]
    with MemoryCore(tmp_path / "context.sqlite") as memory:
        with pytest.raises(ValueError, match="unavailable"):
            HistoricalContextAssembler(reader, memory).assemble(
                source,
                activated_memory_ids=("unknown",),
            )
        with pytest.raises(ValueError, match="character budget"):
            HistoricalContextAssembler(reader, memory, max_chars=1).assemble(
                source,
                context_refs=(reader.before(source)[0].source_ref,),
            )
