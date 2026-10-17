from __future__ import annotations

import json
import sqlite3
from dataclasses import replace

import pytest

from mind_runtime.memory.core import MemoryCore, MemoryCoreSelectionError
from tests.facts.test_admission import make_evidence, make_scope
from tests.memory.test_admission import admit, setup_plane


def _seed(tmp_path, count: int = 2) -> tuple[str, ...]:
    service, _, store, backend = setup_plane(tmp_path)
    try:
        for index in range(count):
            evidence = replace(
                make_evidence(evidence_id=f"source-{index}"),
                payload={"text": f"Canonical fact {index}"},
            )
            admit(service, evidence, interaction_id=f"interaction-{index}")
        return tuple(memory.memory_id for memory in store.load_all())
    finally:
        store.close()
        backend.close()


def test_memory_core_opens_without_runtime_binding_and_preserves_selection_order(
    tmp_path,
) -> None:
    memory_ids = _seed(tmp_path)

    with MemoryCore(tmp_path / "memory.sqlite", read_only=True) as core:
        selected = core.select(
            memory_ids[::-1],
            scope=make_scope(),
            active_only=True,
        )
        assert tuple(memory.memory_id for memory in selected) == memory_ids[::-1]


def test_memory_core_rejects_partial_duplicate_and_wrong_scope_selection(
    tmp_path,
) -> None:
    (memory_id,) = _seed(tmp_path, count=1)

    with MemoryCore(tmp_path / "memory.sqlite", read_only=True) as core:
        with pytest.raises(MemoryCoreSelectionError):
            core.select((memory_id, "missing"))
        with pytest.raises(MemoryCoreSelectionError):
            core.select((memory_id, memory_id))
        with pytest.raises(MemoryCoreSelectionError):
            core.select((memory_id,), scope=make_scope("other"))


def test_memory_core_active_filter_is_read_side_only(tmp_path) -> None:
    (memory_id,) = _seed(tmp_path, count=1)
    db_path = tmp_path / "memory.sqlite"

    with sqlite3.connect(db_path) as conn:
        payload = json.loads(
            conn.execute(
                "SELECT payload FROM canonical_memory WHERE memory_id=?",
                (memory_id,),
            ).fetchone()[0]
        )
        payload["lifecycle"] = "archived"
        conn.execute(
            "UPDATE canonical_memory SET payload=? WHERE memory_id=?",
            (json.dumps(payload), memory_id),
        )

    with MemoryCore(db_path, read_only=True) as core:
        archived = core.get(memory_id)
        assert archived is not None
        assert archived.lifecycle.value == "archived"
        with pytest.raises(MemoryCoreSelectionError):
            core.select((memory_id,), active_only=True)
