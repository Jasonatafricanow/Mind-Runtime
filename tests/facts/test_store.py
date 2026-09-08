"""D3.3 Evidence/Observation append-only store tests."""

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime

import pytest

from mind_runtime.contracts import (
    Authority,
    AuthorityLevel,
    Evidence,
    Observation,
    Scope,
    ScopeDomain,
    SyncFields,
)
from mind_runtime.facts.store import EvidenceStore, ObservationStore

NOW = datetime(2026, 8, 20, 20, 0, tzinfo=UTC)


def make_scope(user_id: str = "user-1") -> Scope:
    return Scope(domain=ScopeDomain.USER, user_id=user_id)


def make_sync(scope: Scope, object_id: str) -> SyncFields:
    return SyncFields(scope, "runtime-1", object_id, 1, f"idem-{object_id}")


def make_evidence(evidence_id: str, scope: Scope) -> Evidence:
    return Evidence(
        id=evidence_id,
        scope=scope,
        origin_runtime_id="runtime-1",
        source_type="user_message",
        source_id=f"source-{evidence_id}",
        authority_level=AuthorityLevel.ASSERTED,
        authority=Authority(scope, AuthorityLevel.ASSERTED, f"source-{evidence_id}"),
        occurred_at=NOW,
        received_at=NOW,
        payload={"text": "hello"},
        sync=make_sync(scope, evidence_id),
    )


def make_observation(observation_id: str, scope: Scope, evidence_id: str) -> Observation:
    return Observation(
        id=observation_id,
        interaction_id="interaction-1",
        scope=scope,
        origin_runtime_id="runtime-1",
        type="factual",
        key="user.observed",
        value="hello",
        confidence=1.0,
        observed_at=NOW,
        evidence_refs=(evidence_id,),
        sync=make_sync(scope, observation_id),
    )


# --- EvidenceStore ---


def test_evidence_append_first_time_true() -> None:
    store = EvidenceStore()
    scope = make_scope()
    assert store.append(make_evidence("evidence-1", scope)) is True
    assert store.count() == 1


def test_evidence_duplicate_scope_id_rejected() -> None:
    store = EvidenceStore()
    scope = make_scope()
    evidence = make_evidence("evidence-1", scope)
    assert store.append(evidence) is True
    assert store.append(evidence) is False
    assert store.count() == 1


def test_evidence_same_id_different_scope_allowed() -> None:
    store = EvidenceStore()
    scope_a = make_scope("user-a")
    scope_b = make_scope("user-b")
    assert store.append(make_evidence("evidence-1", scope_a)) is True
    assert store.append(make_evidence("evidence-1", scope_b)) is True
    assert store.count() == 2


def test_evidence_store_has_no_update_or_delete() -> None:
    store = EvidenceStore()
    scope = make_scope()
    store.append(make_evidence("evidence-1", scope))
    assert not hasattr(store, "update")
    assert not hasattr(store, "delete")


def test_evidence_store_lists_entries() -> None:
    store = EvidenceStore()
    scope = make_scope()
    evidence = make_evidence("evidence-1", scope)
    store.append(evidence)
    assert store.all() == (evidence,)


def test_evidence_store_get_by_scope_and_id() -> None:
    store = EvidenceStore()
    scope = make_scope()
    evidence = make_evidence("evidence-1", scope)
    store.append(evidence)
    assert store.get(scope, "evidence-1") is evidence
    assert store.get(scope, "missing") is None


# --- ObservationStore ---


def test_observation_append_first_time_true() -> None:
    store = ObservationStore()
    scope = make_scope()
    assert store.append(make_observation("obs-1", scope, "evidence-1")) is True
    assert store.count() == 1


def test_observation_duplicate_scope_id_rejected() -> None:
    store = ObservationStore()
    scope = make_scope()
    observation = make_observation("obs-1", scope, "evidence-1")
    assert store.append(observation) is True
    assert store.append(observation) is False
    assert store.count() == 1


def test_observation_store_has_no_update_or_delete() -> None:
    store = ObservationStore()
    scope = make_scope()
    store.append(make_observation("obs-1", scope, "evidence-1"))
    assert not hasattr(store, "update")
    assert not hasattr(store, "delete")


def test_observation_store_lists_entries() -> None:
    store = ObservationStore()
    scope = make_scope()
    observation = make_observation("obs-1", scope, "evidence-1")
    store.append(observation)
    assert store.all() == (observation,)


def test_observation_entries_are_immutable() -> None:
    store = ObservationStore()
    scope = make_scope()
    observation = make_observation("obs-1", scope, "evidence-1")
    store.append(observation)
    stored = store.get(scope, "obs-1")
    assert stored is observation
    # D1 Observation is frozen; mutation raises.
    with pytest.raises(FrozenInstanceError):
        observation.key = "other"  # type: ignore[misc]
