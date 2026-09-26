from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from mind_runtime.memory.core import MemoryCore, MemoryCoreSelectionError
from tests.facts.test_admission import make_evidence, make_scope
from tests.memory.test_admission import admit, setup_plane


def _seed(tmp_path: Path, count: int = 2) -> tuple[str, ...]:
    service, _, store, backend = setup_plane(tmp_path)
    try:
        for index in range(count):
            evidence = replace(
                make_evidence(evidence_id=f"source-{index}"),
                payload={"text": f"Canonical fact {index}"},
            )
            admit(
                service,
                evidence,
                interaction_id=f"interaction-{index}",
            )
        return tuple(memory.memory_id for memory in store.load_all())
    finally:
        store.close()
        backend.close()


def test_memory_core_selects_exact_order_without_runtime_binding(tmp_path: Path) -> None:
    ids = _seed(tmp_path)
    with MemoryCore(tmp_path / "memory.sqlite", read_only=True) as core:
        selected = core.select(
            ids[::-1],
            scope=make_scope(),
            active_only=True,
        )
    assert tuple(item.memory_id for item in selected) == ids[::-1]


def test_memory_core_rejects_partial_and_duplicate_selections(tmp_path: Path) -> None:
    (memory_id,) = _seed(tmp_path, 1)
    with MemoryCore(tmp_path / "memory.sqlite", read_only=True) as core:
        with pytest.raises(MemoryCoreSelectionError):
            core.select((memory_id, "missing"))
        with pytest.raises(MemoryCoreSelectionError):
            core.select((memory_id, memory_id))
