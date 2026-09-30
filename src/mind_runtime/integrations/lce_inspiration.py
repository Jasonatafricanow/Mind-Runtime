"""Bounded background LCE -> InspirationMaterial worker.

The worker owns execution opportunity only. It does not grant outbound
permission, mutate factual Memory, or decide whether a material should be sent.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from mind_runtime.cognition.modes import CognitiveMode
from mind_runtime.contracts import InspirationMaterial
from mind_runtime.integrations.lce_projection import LceProjectionSession

_DISCOVERY_VERSION = "mr-lce-inspiration-v1"


@dataclass(frozen=True, slots=True)
class BackgroundInspirationReport:
    """Operability-only result for one bounded background pass."""

    mode: CognitiveMode
    new_memory_ids: int
    discovered_materials: int
    pending_materials: int


class LceInspirationBackgroundWorker:
    """Run bounded Path-B discovery over an already reconciled projection.

    DAYDREAM/DREAM only decide which background execution lane is being used.
    They do not change LCE authority or create outbound permission.
    """

    def __init__(
        self,
        session: LceProjectionSession,
        *,
        state_path: Path | str | None = None,
    ) -> None:
        if not isinstance(session, LceProjectionSession):
            raise TypeError("session must be an LceProjectionSession")
        self._session = session
        self._state_path = Path(
            state_path
            if state_path is not None
            else Path(session.core.root) / "background_inspiration.sqlite"
        )
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_state()

    @property
    def state_path(self) -> Path:
        return self._state_path

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._state_path)

    def _init_state(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS processed_memory_ids (
                    memory_id TEXT PRIMARY KEY,
                    processed_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS worker_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS material_reservations (
                    wake_id TEXT PRIMARY KEY,
                    material_id TEXT NOT NULL UNIQUE,
                    reserved_at TEXT NOT NULL
                )
                """
            )
            conn.commit()

    def _processed_ids(self) -> set[str]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT memory_id FROM processed_memory_ids"
            ).fetchall()
        return {str(row[0]) for row in rows}

    def _meta(self, key: str) -> str | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT value FROM worker_meta WHERE key = ?",
                (key,),
            ).fetchone()
        return None if row is None else str(row[0])

    def _commit_progress(
        self,
        memory_ids: tuple[str, ...],
        *,
        at: datetime,
    ) -> None:
        with self._connect() as conn:
            for memory_id in memory_ids:
                conn.execute(
                    "INSERT OR IGNORE INTO processed_memory_ids "
                    "(memory_id, processed_at) VALUES (?, ?)",
                    (memory_id, at.isoformat()),
                )
            conn.execute(
                "INSERT INTO worker_meta(key, value) VALUES('discovery_version', ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (_DISCOVERY_VERSION,),
            )
            conn.commit()

    def refresh(
        self,
        *,
        mode: CognitiveMode,
        now: datetime,
    ) -> BackgroundInspirationReport:
        """Run one bounded background pass.

        Canonical catch-up authority belongs to the shared MR->LCE reconcile
        seam. This worker verifies that seam first, then uses its own processed
        Memory IDs only to decide whether inspiration discovery needs another
        pass.
        """
        if mode not in {CognitiveMode.DAYDREAM, CognitiveMode.DREAM}:
            raise ValueError("background inspiration mode must be DAYDREAM or DREAM")
        if now.tzinfo != UTC:
            raise ValueError("now must be aware UTC")

        current_ids = self._session.canonical_memory_ids()
        processed = self._processed_ids()
        new_ids = tuple(memory_id for memory_id in current_ids if memory_id not in processed)
        first_discovery = self._meta("discovery_version") != _DISCOVERY_VERSION

        # One reconciliation contract owns missing/invalid source handling.
        # Do not maintain a second Memory-ID based ingestion path here.
        reconcile = self._session.reconcile_canonical()
        if not reconcile.current:
            raise RuntimeError(
                "LCE projection is not current before inspiration discovery"
            )

        discovered: tuple[InspirationMaterial, ...] = ()
        if new_ids or first_discovery:
            trajectory = self._session.bootstrap_trajectory(
                knowledge_cutoff=now,
            )
            discovered = tuple(
                self._session.discover_inspiration(
                    knowledge_cutoff=now,
                    trajectory_result=trajectory,
                )
            )
            self._commit_progress(new_ids, at=now)

        pending = self._session.inspiration_materials(limit=100)
        return BackgroundInspirationReport(
            mode=mode,
            new_memory_ids=len(new_ids),
            discovered_materials=len(discovered),
            pending_materials=len(pending),
        )

    def pending_materials(
        self,
        *,
        limit: int = 20,
    ) -> tuple[InspirationMaterial, ...]:
        return tuple(self._session.inspiration_materials(limit=limit))

    def reserve_next(self, wake_id: str) -> InspirationMaterial | None:
        """Durably reserve one pending material for one allowed proactive wake."""
        if not isinstance(wake_id, str) or not wake_id.strip():
            raise ValueError("wake_id must be nonempty")

        pending = self._session.inspiration_materials(limit=100)
        by_id = {material.material_id: material for material in pending}
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
                "SELECT material_id FROM material_reservations WHERE wake_id = ?",
                (wake_id,),
            ).fetchone()
            if existing is not None:
                material_id = str(existing[0])
                material = by_id.get(material_id)
                if material is None:
                    # The LCE material is no longer pending (for example it
                    # was consumed after delivery) so the stale reservation
                    # must not pin the wake forever.
                    conn.execute(
                        "DELETE FROM material_reservations WHERE wake_id = ?",
                        (wake_id,),
                    )
                    conn.commit()
                    return None
                conn.commit()
                return material

            reserved_ids = {
                str(row[0])
                for row in conn.execute(
                    "SELECT material_id FROM material_reservations"
                ).fetchall()
            }
            for material in pending:
                if material.material_id in reserved_ids:
                    continue
                conn.execute(
                    "INSERT INTO material_reservations"
                    "(wake_id, material_id, reserved_at) VALUES (?, ?, ?)",
                    (
                        wake_id,
                        material.material_id,
                        datetime.now(UTC).isoformat(),
                    ),
                )
                conn.commit()
                return material
            conn.commit()
        return None

    def consume_for_wake(self, wake_id: str) -> str | None:
        """Consume reserved material only after successful outbound delivery."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT material_id FROM material_reservations WHERE wake_id = ?",
                (wake_id,),
            ).fetchone()
        if row is None:
            return None
        material_id = str(row[0])

        # LCE consumption is the product-state authority. Delete the MR
        # reservation only after LCE accepted the consume operation.
        self._session.consume_inspiration(material_id)
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM material_reservations "
                "WHERE wake_id = ? AND material_id = ?",
                (wake_id, material_id),
            )
            conn.commit()
        return material_id

    def release_for_wake(self, wake_id: str) -> str | None:
        """Release a reservation after rejection/abort so it may be retried."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT material_id FROM material_reservations WHERE wake_id = ?",
                (wake_id,),
            ).fetchone()
            if row is None:
                return None
            material_id = str(row[0])
            conn.execute(
                "DELETE FROM material_reservations WHERE wake_id = ?",
                (wake_id,),
            )
            conn.commit()
        return material_id

