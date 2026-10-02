import json
import sys

import pytest
from historical.agy_adapter import ExternalAGYAdapter, build_prompt
from historical.context_assembler import HistoricalContextAssembler
from mr_mem.memory.core import MemoryCore
from mr_mem.memory.semantic_contracts import SCHEMA_VERSION, SemanticDeltaError
from mr_mem.memory.semantic_validator import validate_semantic_delta


def delta(meaning="用户选择 A。", *, status="resolved", refs=()):
    return {
        "schema_version": SCHEMA_VERSION,
        "points": [
            {
                "point_id": "p1",
                "meaning": meaning,
                "status": status,
                "speech_act": "directive",
                "polarity": "positive",
                "epistemic_status": "asserted",
                "temporal_scope": "current",
                "unresolved_refs": list(refs),
            }
        ],
        "dependencies": [],
    }


def test_command_final_payload_is_separate_from_tool_logs(native, tmp_path):
    _, _, sources = native
    current = tuple(sources.iterate())[1]
    with MemoryCore(tmp_path / "context.sqlite") as memory:
        context = HistoricalContextAssembler(sources, memory).assemble(
            current,
            context_refs=(sources.before(current)[0].source_ref,),
        )
    script = tmp_path / "external.py"
    script.write_text(
        "import sys;from pathlib import Path\n"
        "assert 'historical_semantic_delta_prompt_v1' in sys.stdin.read()\n"
        "print('Ran shell; CI green; agent progress')\n"
        f"Path(sys.argv[1]).write_text({json.dumps(delta())!r},encoding='utf-8')\n",
        encoding="utf-8",
    )
    payload = ExternalAGYAdapter((sys.executable, str(script), "{output}"), cwd=tmp_path).compile(
        context
    )
    result = validate_semantic_delta(payload, activated_memory_ids=())
    assert result.points[0].meaning == "用户选择 A。"
    assert "Ran shell" not in payload
    assert "assistant" in build_prompt(context)
    with pytest.raises(SemanticDeltaError):
        validate_semantic_delta(delta(status="INVALID"), activated_memory_ids=())
