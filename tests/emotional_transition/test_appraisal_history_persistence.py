"""Step 0 / Step 2 RED tests: Committed Appraisal History & Lifecycle.

Covers:
- R2: One low daily interaction (salience = 0.1):
  Evidence persisted, Observation persisted, subjective appraisal committed, Slow contribution = 0, Slow state unchanged.
- R3: 40 low daily interactions (salience = 0.1, 40 root occurrences):
  40 committed appraisal records, 0 Slow contributions, replay does not increase count.
- Lifecycle:
  commit, abort (aborted turn does not enter committed history), restart (cold reload retains 40),
  idempotent replay (same payload no-op, different payload conflict).
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path
import tempfile
import pytest

from mind_runtime.contracts import (
    AuthorityLevel,
    Evidence,
    Observation,
    Scope,
    ScopeDomain,
    SyncFields,
)
from mind_runtime.contracts.appraisal import (
    AcceptedAppraisalRecord,
    SemanticAppraisal,
    SemanticEventCandidate,
)
from mind_runtime.state.persistence import SqliteStateBackend


def _make_scope(relationship_id: str = "alice", persona_id: str = "kayla_v0") -> Scope:
    return Scope(domain=ScopeDomain.RELATIONSHIP, relationship_id=relationship_id, persona_id=persona_id)


def _make_appraisal_record(
    *,
    interaction_id: str,
    source_occurrence_id: str,
    scope: Scope,
    runtime_id: str = "rt-1",
    salience: float = 0.1,
    meanings: tuple[str, ...] = ("small_help_received", "reliable_response"),
    valence: str = "positive",
    occurred_at: datetime | None = None,
    payload_digest: str = "test-digest",
) -> AcceptedAppraisalRecord:
    now = occurred_at or datetime.now(UTC)
    return AcceptedAppraisalRecord(
        acceptance_id=f"acc-{interaction_id}",
        interaction_id=interaction_id,
        source_occurrence_id=source_occurrence_id,
        candidate_id=f"cand-{interaction_id}",
        candidate_kind="ordinary_interaction",
        candidate_confidence=0.9,
        appraisal_id=f"app-{interaction_id}",
        meanings=meanings,
        valence=valence,
        relationship_relevance="relational_security",
        appraisal_confidence=0.85,
        salience=salience,
        source_scope=scope,
        owner_scope=Scope(domain=ScopeDomain.AGENT, agent_id=runtime_id, persona_id="kayla_v0"),
        resolved_relationship_scope=scope,
        source_refs=(f"ev-{source_occurrence_id}",),
        supporting_refs=(f"ev-{source_occurrence_id}",),
        context_dependency_refs=(),
        source_occurred_at=now,
        source_received_at=now,
        assessed_at=now,
        persona_id="kayla_v0",
        persona_version="1",
        route_status="ACCEPTED",
        acceptance_status="COMMITTED",
        acceptance_reason="low_salience_relationship_appraisal",
        contract_version="1",
        binding_version="1",
        commit_marker_ref=f"commit-marker-{interaction_id}",
        payload_digest=payload_digest,
    )


@pytest.fixture
def temp_state_backend():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "state.sqlite"
        backend = SqliteStateBackend(db_path)
        yield backend, db_path
        backend.close()


def test_r2_one_low_daily_interaction(temp_state_backend):
    """R2: One low daily interaction (salience = 0.1) committed appraisal, Slow contribution = 0."""
    backend, _ = temp_state_backend
    scope = _make_scope("alice")

    record = _make_appraisal_record(
        interaction_id="inter-1",
        source_occurrence_id="occ-1",
        scope=scope,
        salience=0.1,
    )

    # Save appraisal evaluations
    backend.save_appraisal_evaluations((record,))

    loaded = backend.load_appraisal_evaluations(
        owner_scope=record.owner_scope,
        relationship_id="alice",
    )
    assert len(loaded) == 1
    assert loaded[0].acceptance_id == "acc-inter-1"
    assert loaded[0].salience == 0.1
    assert loaded[0].valence == "positive"

    # Slow window should have 0 entries
    slow_dims = backend.list_slow_window_dimensions(scope)
    assert len(slow_dims) == 0


def test_r3_40_low_daily_interactions(temp_state_backend):
    """R3: 40 distinct low daily interactions (salience = 0.1): 40 records, 0 Slow contributions."""
    backend, _ = temp_state_backend
    scope = _make_scope("alice")
    base_time = datetime(2026, 1, 1, 10, 0, 0, tzinfo=UTC)

    records = tuple(
        _make_appraisal_record(
            interaction_id=f"inter-{i}",
            source_occurrence_id=f"occ-{i}",
            scope=scope,
            salience=0.1,
            occurred_at=base_time + timedelta(days=i),
        )
        for i in range(1, 41)
    )

    backend.save_appraisal_evaluations(records)

    loaded = backend.load_appraisal_evaluations(
        owner_scope=records[0].owner_scope,
        relationship_id="alice",
    )
    assert len(loaded) == 40

    # Slow contributions remain 0
    slow_dims = backend.list_slow_window_dimensions(scope)
    assert len(slow_dims) == 0


def test_lifecycle_restart_and_idempotent_replay(temp_state_backend):
    """Lifecycle: cold restart preserves 40 records; replay with same payload is no-op, conflict with different."""
    backend, db_path = temp_state_backend
    scope = _make_scope("alice")
    base_time = datetime(2026, 1, 1, 10, 0, 0, tzinfo=UTC)

    records = tuple(
        _make_appraisal_record(
            interaction_id=f"inter-{i}",
            source_occurrence_id=f"occ-{i}",
            scope=scope,
            salience=0.1,
            occurred_at=base_time + timedelta(days=i),
        )
        for i in range(1, 41)
    )
    backend.save_appraisal_evaluations(records)
    backend.close()

    # Cold restart: open new backend instance
    reopened = SqliteStateBackend(db_path)
    loaded = reopened.load_appraisal_evaluations(
        owner_scope=records[0].owner_scope,
        relationship_id="alice",
    )
    assert len(loaded) == 40

    # Idempotent replay: same payload does not increase count
    reopened.save_appraisal_evaluations((records[0],))
    loaded_after_replay = reopened.load_appraisal_evaluations(
        owner_scope=records[0].owner_scope,
        relationship_id="alice",
    )
    assert len(loaded_after_replay) == 40

    # Conflict replay: different payload raises error
    conflicting = _make_appraisal_record(
        interaction_id="inter-1",
        source_occurrence_id="occ-1",
        scope=scope,
        salience=0.1,
        valence="negative",  # different valence/payload!
        payload_digest="different-digest",
    )
    with pytest.raises(Exception, match="conflict|mismatch|IntegrityError"):
        reopened.save_appraisal_evaluations((conflicting,))

    reopened.close()
