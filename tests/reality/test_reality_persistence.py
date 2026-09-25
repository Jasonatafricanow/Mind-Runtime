"""Tests for Reality Observation additive persistence and legacy migration (RED 2)."""

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

from mind_runtime.contracts import (
    EffectiveWindow,
    EffectiveWindowKind,
    Observation,
    ObservationModality,
    Scope,
    ScopeDomain,
    SemanticDaypart,
    SemanticPrecision,
    SemanticRelation,
    SemanticTime,
    SyncFields,
)
from mind_runtime.facts.persistence import SqliteFactBackend

NOW = datetime(2026, 9, 9, 14, 0, tzinfo=UTC)


def make_scope() -> Scope:
    return Scope(domain=ScopeDomain.USER, user_id="u1")


def make_sync(obs_id: str, scope: Scope) -> SyncFields:
    return SyncFields(scope, "r1", obs_id, 1, f"idem-{obs_id}")


def make_observation(
    obs_id: str,
    *,
    key: str = "user.health.stomach_pain.observed",
    value: object = "active",
    confidence: float = 0.9,
    observed_at: datetime = NOW,
    modality: ObservationModality = ObservationModality.ASSERTED,
    semantic_time: SemanticTime | None = None,
    effective_window: EffectiveWindow | None = None,
) -> Observation:
    s = make_scope()
    kwargs: dict[str, object] = {
        "id": obs_id,
        "interaction_id": "i1",
        "scope": s,
        "origin_runtime_id": "r1",
        "type": "factual",
        "key": key,
        "value": value,
        "confidence": confidence,
        "observed_at": observed_at,
        "evidence_refs": ("ev-1",),
        "sync": make_sync(obs_id, s),
        "modality": modality,
    }
    if semantic_time is not None:
        kwargs["semantic_time"] = semantic_time
    if effective_window is not None:
        kwargs["effective_window"] = effective_window
    return Observation(**kwargs)  # type: ignore[arg-type]


def test_new_observation_full_round_trip(tmp_path: Path) -> None:
    db_path = tmp_path / "facts.db"
    backend = SqliteFactBackend(db_path)
    try:
        st = SemanticTime(
            relation=SemanticRelation.FUTURE,
            precision=SemanticPrecision.DAYPART,
            daypart=SemanticDaypart.AFTERNOON,
        )
        ew = EffectiveWindow(
            kind=EffectiveWindowKind.INTERVAL,
            start_at=NOW + timedelta(hours=1),
            end_at=NOW + timedelta(hours=5),
        )
        obs = make_observation(
            "obs-roundtrip",
            modality=ObservationModality.PLANNED,
            semantic_time=st,
            effective_window=ew,
            confidence=0.92,
        )
        assert backend.save_observation(obs) is True

        loaded = backend.find_observation(obs.scope, obs.id)
        assert loaded is not None
        assert loaded.id == obs.id
        assert loaded.modality == ObservationModality.PLANNED
        assert loaded.semantic_time == st
        assert loaded.effective_window == ew
        assert loaded.confidence == 0.92
    finally:
        backend.close()


def test_storage_sentinel_codec(tmp_path: Path) -> None:
    """Proves domain effective_window=None maps to DB 'unresolved', and vice-versa."""
    db_path = tmp_path / "facts.db"
    backend = SqliteFactBackend(db_path)
    try:
        obs = make_observation(
            "obs-sentinel",
            modality=ObservationModality.TENTATIVE,
            semantic_time=SemanticTime(
                relation=SemanticRelation.FUTURE,
                precision=SemanticPrecision.RANGE,
            ),
            effective_window=None,
        )
        assert backend.save_observation(obs) is True

        # Inspect raw SQLite storage
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT effective_window_kind, effective_start_at, effective_end_at "
            "FROM observations WHERE id = 'obs-sentinel'"
        ).fetchone()
        assert row is not None
        assert row["effective_window_kind"] == "unresolved"
        assert row["effective_start_at"] is None
        assert row["effective_end_at"] is None
        conn.close()

        # Reading back from domain API returns None
        loaded = backend.find_observation(obs.scope, obs.id)
        assert loaded is not None
        assert loaded.effective_window is None
    finally:
        backend.close()


def test_legacy_db_migration_and_defaults(tmp_path: Path) -> None:
    """Proves an existing SQLite DB created with legacy schema is migrated additively."""
    db_path = tmp_path / "legacy.db"

    # Create table with exact legacy schema (no modality / semantic columns)
    legacy_schema = """
    CREATE TABLE observations (
        scope_domain TEXT NOT NULL,
        scope_user_id TEXT NOT NULL DEFAULT '',
        scope_agent_id TEXT NOT NULL DEFAULT '',
        scope_persona_id TEXT NOT NULL DEFAULT '',
        scope_relationship_id TEXT NOT NULL DEFAULT '',
        scope_world_id TEXT NOT NULL DEFAULT '',
        scope_interaction_id TEXT NOT NULL DEFAULT '',
        id TEXT NOT NULL,
        interaction_id TEXT NOT NULL,
        origin_runtime_id TEXT NOT NULL,
        type TEXT NOT NULL,
        key TEXT NOT NULL,
        value TEXT NOT NULL,
        confidence REAL NOT NULL,
        observed_at TEXT NOT NULL,
        evidence_refs TEXT NOT NULL,
        sync_version INTEGER NOT NULL,
        sync_idem_key TEXT NOT NULL,
        PRIMARY KEY (
            scope_domain, scope_user_id, scope_agent_id, scope_persona_id,
            scope_relationship_id, scope_world_id, scope_interaction_id, id
        )
    );
    """
    conn = sqlite3.connect(str(db_path))
    conn.executescript(legacy_schema)
    conn.execute(
        "INSERT INTO observations ("
        "scope_domain, scope_user_id, id, interaction_id, origin_runtime_id, "
        "type, key, value, confidence, observed_at, evidence_refs, "
        "sync_version, sync_idem_key"
        ") VALUES ("
        "?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?"
        ")",
        (
            "user",
            "u1",
            "legacy-obs-1",
            "i-legacy",
            "r1",
            "factual",
            "user.sleep.phase.observed",
            '"awake"',
            1.0,
            NOW.isoformat(),
            '["ev-1"]',
            1,
            "idem-1",
        ),
    )
    conn.commit()
    conn.close()

    # Open with SqliteFactBackend, which must apply non-destructive migration
    backend = SqliteFactBackend(db_path)
    try:
        loaded_legacy = backend.find_observation(make_scope(), "legacy-obs-1")
        assert loaded_legacy is not None
        assert loaded_legacy.id == "legacy-obs-1"
        assert loaded_legacy.modality == ObservationModality.ASSERTED
        assert loaded_legacy.semantic_time.relation == SemanticRelation.UNRESOLVED
        assert loaded_legacy.semantic_time.precision == SemanticPrecision.UNRESOLVED
        assert loaded_legacy.semantic_time.daypart is None
        assert loaded_legacy.effective_window is None

        # Insert a new observation into the migrated DB
        new_obs = make_observation(
            "new-obs-after-migration",
            modality=ObservationModality.PLANNED,
            semantic_time=SemanticTime(
                relation=SemanticRelation.FUTURE,
                precision=SemanticPrecision.DAYPART,
                daypart=SemanticDaypart.AFTERNOON,
            ),
            effective_window=EffectiveWindow(
                kind=EffectiveWindowKind.INTERVAL,
                start_at=NOW + timedelta(hours=1),
                end_at=NOW + timedelta(hours=4),
            ),
        )
        assert backend.save_observation(new_obs) is True

        all_obs = backend.load_observations()
        assert len(all_obs) == 2
    finally:
        backend.close()


def test_restart_loading(tmp_path: Path) -> None:
    db_path = tmp_path / "restart.db"
    st = SemanticTime(
        relation=SemanticRelation.FUTURE,
        precision=SemanticPrecision.DAYPART,
        daypart=SemanticDaypart.EVENING,
    )
    ew = EffectiveWindow(
        kind=EffectiveWindowKind.INTERVAL,
        start_at=NOW + timedelta(hours=2),
        end_at=NOW + timedelta(hours=6),
    )
    obs = make_observation(
        "obs-restart", modality=ObservationModality.PLANNED, semantic_time=st, effective_window=ew
    )

    b1 = SqliteFactBackend(db_path)
    b1.save_observation(obs)
    b1.close()

    b2 = SqliteFactBackend(db_path)
    try:
        loaded = b2.find_observation(obs.scope, obs.id)
        assert loaded is not None
        assert loaded.modality == ObservationModality.PLANNED
        assert loaded.semantic_time == st
        assert loaded.effective_window == ew
    finally:
        b2.close()
