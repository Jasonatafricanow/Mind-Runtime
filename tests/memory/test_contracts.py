from dataclasses import fields, replace
from datetime import UTC, datetime

import pytest

from mind_runtime.contracts import Scope, ScopeDomain, SyncFields


def test_memory_contract_exists():
    from mind_runtime.memory import contracts

    assert hasattr(contracts, "CommittedMemory")


def memory():
    from mind_runtime.memory.contracts import CommittedMemory, MemoryProvenance

    scope = Scope(ScopeDomain.USER, user_id="user")
    return CommittedMemory(
        memory_id="memory-1",
        scope=scope,
        content="hello",
        provenance=MemoryProvenance(
            ("evidence-1",),
            "observation-1",
            "text-v1",
            interaction_id="interaction-1",
        ),
        origin_runtime_id="runtime-1",
        committed_at=datetime(2026, 9, 7, tzinfo=UTC),
        sync=SyncFields(scope, "runtime-1", "memory-1", 1, "memory-1"),
    )


def test_canonical_fields_are_provider_free_and_not_agent_owned():
    obj = memory()
    assert not (
        {"agent_id", "provider_ref", "embedding", "vector", "storage_namespace"}
        & {f.name for f in fields(obj)}
    )
    assert obj.sync_fields() == obj.sync
    assert obj.lifecycle.value == "active"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"scope": "user"},
        {"content": " "},
        {"origin_runtime_id": "other"},
        {"memory_id": "other"},
        {"lifecycle": "active"},
    ],
)
def test_invalid_memory_contract_fails_closed(kwargs):
    with pytest.raises(ValueError):
        replace(memory(), **kwargs)


def test_empty_provenance_rejected():
    from mind_runtime.memory.contracts import MemoryProvenance

    with pytest.raises(ValueError):
        MemoryProvenance((), "observation-1", "text-v1")
