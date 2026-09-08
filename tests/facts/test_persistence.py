"""D3.C2 SqliteFactBackend tests: first-batch tables, round-trips, idempotency."""

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from mind_runtime.contracts import (
    Authority,
    AuthorityLevel,
    Evidence,
    Interaction,
    InteractionStatus,
    Observation,
    Scope,
    ScopeDomain,
    SyncFields,
)
from mind_runtime.facts.persistence import SqliteFactBackend, _to_json

NOW = datetime(2026, 8, 21, 10, 0, tzinfo=UTC)


def make_scope(user_id: str = "user-1") -> Scope:
    return Scope(domain=ScopeDomain.USER, user_id=user_id)


def make_sync(scope: Scope, object_id: str) -> SyncFields:
    return SyncFields(scope, "runtime-1", object_id, 1, f"idem-{object_id}")


def make_evidence(
    evidence_id: str = "evidence-1",
    *,
    scope: Scope | None = None,
    level: AuthorityLevel = AuthorityLevel.ASSERTED,
) -> Evidence:
    factual_scope = scope or make_scope()
    authority_source = None if level is AuthorityLevel.NONE else f"source-{evidence_id}"
    return Evidence(
        id=evidence_id,
        scope=factual_scope,
        origin_runtime_id="runtime-1",
        source_type="user_message",
        source_id=f"source-{evidence_id}",
        authority_level=level,
        authority=Authority(factual_scope, level, authority_source),
        occurred_at=NOW,
        received_at=NOW,
        payload={"text": "hello"},
        sync=make_sync(factual_scope, evidence_id),
    )


def make_observation(
    observation_id: str = "observation-evidence-1",
    *,
    scope: Scope | None = None,
    evidence_id: str = "evidence-1",
    interaction_id: str = "interaction-1",
) -> Observation:
    factual_scope = scope or make_scope()
    return Observation(
        id=observation_id,
        interaction_id=interaction_id,
        scope=factual_scope,
        origin_runtime_id="runtime-1",
        type="factual",
        key="user.observed",
        value="hello",
        confidence=1.0,
        observed_at=NOW,
        evidence_refs=(evidence_id,),
        sync=make_sync(factual_scope, observation_id),
    )


def make_interaction(
    interaction_id: str = "interaction-1",
    *,
    status: InteractionStatus = InteractionStatus.OPEN,
    scope: Scope | None = None,
) -> Interaction:
    return Interaction(
        interaction_id=interaction_id,
        scope=scope or make_scope(),
        channel="chat",
        session_id="session-1",
        turn_id="turn-1",
        started_at=NOW,
        committed_at=NOW if status is InteractionStatus.COMMITTED else None,
        status=status,
    )


def test_first_batch_table_names_are_exactly_three(tmp_path: Path) -> None:
    backend = SqliteFactBackend(tmp_path / "facts.db")
    assert set(backend.table_names()) == {"interactions", "evidence", "observations"}


def test_empty_backend_loads_nothing(tmp_path: Path) -> None:
    backend = SqliteFactBackend(tmp_path / "facts.db")
    assert backend.load_interactions() == ()
    assert backend.load_evidence() == ()
    assert backend.load_observations() == ()


def test_evidence_round_trip_with_interaction_binding(tmp_path: Path) -> None:
    backend = SqliteFactBackend(tmp_path / "facts.db")
    evidence = make_evidence()
    assert backend.save_evidence(evidence, interaction_id="interaction-9") is True
    (loaded, interaction_id) = backend.load_evidence()[0]
    assert loaded == evidence
    assert loaded.payload == evidence.payload
    assert interaction_id == "interaction-9"


def test_evidence_duplicate_rejected_and_count_stays_one(tmp_path: Path) -> None:
    backend = SqliteFactBackend(tmp_path / "facts.db")
    evidence = make_evidence()
    assert backend.save_evidence(evidence, interaction_id="i-1") is True
    assert backend.save_evidence(evidence, interaction_id="i-1") is False
    assert len(backend.load_evidence()) == 1


def test_evidence_same_id_different_scope_both_stored(tmp_path: Path) -> None:
    backend = SqliteFactBackend(tmp_path / "facts.db")
    scope_a = make_scope("user-a")
    scope_b = make_scope("user-b")
    assert backend.save_evidence(make_evidence(scope=scope_a), interaction_id="i-1") is True
    assert backend.save_evidence(make_evidence(scope=scope_b), interaction_id="i-1") is True
    assert len(backend.load_evidence()) == 2


def test_evidence_none_authority_round_trip(tmp_path: Path) -> None:
    backend = SqliteFactBackend(tmp_path / "facts.db")
    evidence = make_evidence(level=AuthorityLevel.NONE)
    assert backend.save_evidence(evidence, interaction_id="i-1") is True
    (loaded, _) = backend.load_evidence()[0]
    assert loaded == evidence
    assert loaded.authority.source_id is None


def test_evidence_agent_scope_round_trip(tmp_path: Path) -> None:
    backend = SqliteFactBackend(tmp_path / "facts.db")
    scope = Scope(domain=ScopeDomain.AGENT, agent_id="kayla", persona_id="persona-kayla")
    evidence = make_evidence(scope=scope)
    assert backend.save_evidence(evidence, interaction_id="i-1") is True
    (loaded, _) = backend.load_evidence()[0]
    assert loaded.scope == scope


def test_observation_round_trip(tmp_path: Path) -> None:
    backend = SqliteFactBackend(tmp_path / "facts.db")
    observation = make_observation()
    assert backend.save_observation(observation) is True
    loaded = backend.load_observations()[0]
    assert loaded == observation
    assert loaded.value == observation.value
    assert loaded.evidence_refs == (observation.evidence_refs[0],)


def test_observation_duplicate_rejected(tmp_path: Path) -> None:
    backend = SqliteFactBackend(tmp_path / "facts.db")
    observation = make_observation()
    assert backend.save_observation(observation) is True
    assert backend.save_observation(observation) is False
    assert len(backend.load_observations()) == 1


def test_save_admission_writes_pair_atomically(tmp_path: Path) -> None:
    backend = SqliteFactBackend(tmp_path / "facts.db")
    evidence = make_evidence()
    observation = make_observation()
    assert (
        backend.save_admission(evidence, interaction_id="interaction-1", observation=observation)
        is True
    )
    assert len(backend.load_evidence()) == 1
    assert len(backend.load_observations()) == 1


def test_save_admission_duplicate_evidence_rolls_back_observation(tmp_path: Path) -> None:
    backend = SqliteFactBackend(tmp_path / "facts.db")
    evidence = make_evidence()
    observation = make_observation()
    assert backend.save_evidence(evidence, interaction_id="interaction-1") is True
    assert (
        backend.save_admission(evidence, interaction_id="interaction-1", observation=observation)
        is False
    )
    # The observation insert was rolled back with the duplicate evidence.
    assert len(backend.load_observations()) == 0


def test_interaction_round_trip_and_lifecycle_update(tmp_path: Path) -> None:
    backend = SqliteFactBackend(tmp_path / "facts.db")
    backend.save_interaction(make_interaction())
    assert backend.load_interactions()[0].status is InteractionStatus.OPEN
    # Commit rewrites the same row (the one legitimate mutation).
    committed = make_interaction(status=InteractionStatus.COMMITTED)
    backend.save_interaction(committed)
    loaded = backend.load_interactions()
    assert len(loaded) == 1
    assert loaded[0].status is InteractionStatus.COMMITTED
    assert loaded[0].committed_at == NOW


def test_backend_close_releases_file(tmp_path: Path) -> None:
    backend = SqliteFactBackend(tmp_path / "facts.db")
    backend.close()
    # Reopening the same file works after close.
    reopened = SqliteFactBackend(tmp_path / "facts.db")
    assert reopened.load_evidence() == ()


def test_to_json_deterministic_and_json_safe() -> None:
    assert _to_json({"b": 1, "a": 2}) == _to_json({"a": 2, "b": 1}) == '{"a": 2, "b": 1}'


def test_to_json_round_trips_tuples_and_frozen_mappings() -> None:
    assert _to_json(("a", "b")) == '["a", "b"]'
    assert _to_json({"nested": {"x": (1, 2)}}) == '{"nested": {"x": [1, 2]}}'


def test_to_json_rejects_non_serializable_values() -> None:
    with pytest.raises(ValueError, match="JSON-serializable"):
        _to_json({"raw": b"\x00"})
    with pytest.raises(ValueError, match="round-trip"):
        _to_json(frozenset({"a"}))


def test_rows_persist_exactly_the_three_tables(tmp_path: Path) -> None:
    path = tmp_path / "facts.db"
    SqliteFactBackend(path)
    conn = sqlite3.connect(path)
    tables = {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    }
    conn.close()
    assert tables == {"interactions", "evidence", "observations"}
