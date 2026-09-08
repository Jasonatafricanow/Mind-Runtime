"""D3.5 provenance tests: occurred_at vs received_at kept distinct."""

from datetime import UTC, datetime, timedelta

from mind_runtime.contracts import (
    Authority,
    AuthorityLevel,
    Evidence,
    Scope,
    ScopeDomain,
    SyncFields,
)
from mind_runtime.facts.provenance import ProvenanceRecorder

NOW = datetime(2026, 8, 20, 21, 0, tzinfo=UTC)


def make_scope() -> Scope:
    return Scope(domain=ScopeDomain.USER, user_id="user-1")


def make_evidence(
    *,
    occurred_at: datetime,
    received_at: datetime,
    evidence_id: str = "evidence-1",
) -> Evidence:
    scope = make_scope()
    return Evidence(
        id=evidence_id,
        scope=scope,
        origin_runtime_id="runtime-1",
        source_type="user_message",
        source_id=f"source-{evidence_id}",
        authority_level=AuthorityLevel.ASSERTED,
        authority=Authority(scope, AuthorityLevel.ASSERTED, f"source-{evidence_id}"),
        occurred_at=occurred_at,
        received_at=received_at,
        payload={"text": "hello"},
        sync=SyncFields(scope, "runtime-1", evidence_id, 1, f"idem-{evidence_id}"),
    )


def test_provenance_preserves_occurred_vs_received() -> None:
    recorder = ProvenanceRecorder()
    occurred = NOW - timedelta(hours=2)
    recorder.record(make_evidence(occurred_at=occurred, received_at=NOW), interaction_id="i-1")
    entry = recorder.all()[0]
    assert entry.occurred_at == occurred
    assert entry.received_at == NOW
    assert entry.occurred_at != entry.received_at


def test_provenance_delayed_event_ordering_information() -> None:
    """G9 base: delayed event keeps both timestamps for later reconcile."""
    recorder = ProvenanceRecorder()
    occurred = NOW - timedelta(minutes=130)
    received = NOW
    recorder.record(make_evidence(occurred_at=occurred, received_at=received), interaction_id="i-1")
    entry = recorder.entries("i-1")[0]
    # Ordering info is complete: occurred <= received, and the delay is visible.
    assert entry.occurred_at <= entry.received_at
    assert (entry.received_at - entry.occurred_at) == timedelta(minutes=130)


def test_provenance_filters_by_interaction() -> None:
    recorder = ProvenanceRecorder()
    recorder.record(
        make_evidence(evidence_id="e1", occurred_at=NOW, received_at=NOW),
        interaction_id="i-1",
    )
    recorder.record(
        make_evidence(evidence_id="e2", occurred_at=NOW, received_at=NOW),
        interaction_id="i-2",
    )
    assert len(recorder.entries("i-1")) == 1
    assert recorder.entries("i-1")[0].evidence_id == "e1"


def test_provenance_recording_is_idempotent_per_event() -> None:
    """D3.C2/C3: replaying one event never appends a second provenance entry."""
    recorder = ProvenanceRecorder()
    evidence = make_evidence(occurred_at=NOW, received_at=NOW)
    recorder.record(evidence, interaction_id="i-1")
    recorder.record(evidence, interaction_id="i-1")
    assert len(recorder.all()) == 1


def test_provenance_entry_is_immutable() -> None:
    from dataclasses import FrozenInstanceError

    import pytest

    recorder = ProvenanceRecorder()
    recorder.record(make_evidence(occurred_at=NOW, received_at=NOW), interaction_id="i-1")
    entry = recorder.all()[0]
    with pytest.raises(FrozenInstanceError):
        entry.evidence_id = "other"  # type: ignore[misc]
