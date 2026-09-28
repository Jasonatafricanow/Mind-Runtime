"""Bounded background LCE -> InspirationMaterial worker.

The worker owns execution opportunity only. It does not grant outbound
permission, mutate factual Memory, or decide whether a material should be sent.
"""

from __future__ import annotations

import sqlite3
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from mind_runtime.cognition.modes import CognitiveMode
from mind_runtime.contracts import InspirationMaterial
from mind_runtime.integrations.lce_projection import LceProjectionSession

_DISCOVERY_VERSION = "mr-lce-inspiration-v1"
_SYNC_CHUNK_SIZE = 100


@dataclass(frozen=True, slots=True)
class BackgroundInspirationReport:
    """Operability-only result for one bounded background pass."""

    mode: CognitiveMode
    new_memory_ids: int
    discovered_materials: int
    pending_materials: int


class LceInspirationBackgroundWorker:
    """Catch up canonical Memory, run one Path-B pass, and queue material.

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
        self._lock = threading.RLock()
        self._reserved_by_wake: dict[str, str] = {}
        self._reserved_ids: set[str] = set()
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

        New canonical Memory is synchronized incrementally. Full trajectory
        bootstrap runs only when new canonical material arrived or when this
        discovery version has never run for the namespace.
        """
        if mode not in {CognitiveMode.DAYDREAM, CognitiveMode.DREAM}:
            raise ValueError("background inspiration mode must be DAYDREAM or DREAM")
        if now.tzinfo != UTC:
            raise ValueError("now must be aware UTC")

        current_ids = self._session.canonical_memory_ids()
        processed = self._processed_ids()
        new_ids = tuple(memory_id for memory_id in current_ids if memory_id not in processed)
        first_discovery = self._meta("discovery_version") != _DISCOVERY_VERSION

        for offset in range(0, len(new_ids), _SYNC_CHUNK_SIZE):
            chunk = new_ids[offset : offset + _SYNC_CHUNK_SIZE]
            self._session.sync_memory_ids(chunk, mode="nearline")

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
        """Reserve one pending material for one allowed proactive wake."""
        if not isinstance(wake_id, str) or not wake_id.strip():
            raise ValueError("wake_id must be nonempty")
        with self._lock:
            existing_id = self._reserved_by_wake.get(wake_id)
            if existing_id is not None:
                for material in self._session.inspiration_materials(limit=100):
                    if material.material_id == existing_id:
                        return material
                return None

            for material in self._session.inspiration_materials(limit=100):
                if material.material_id in self._reserved_ids:
                    continue
                self._reserved_by_wake[wake_id] = material.material_id
                self._reserved_ids.add(material.material_id)
                return material
        return None

    def consume_for_wake(self, wake_id: str) -> str | None:
        """Consume reserved material only after successful outbound delivery."""
        with self._lock:
            material_id = self._reserved_by_wake.pop(wake_id, None)
            if material_id is None:
                return None
            self._reserved_ids.discard(material_id)
        self._session.consume_inspiration(material_id)
        return material_id

    def release_for_wake(self, wake_id: str) -> str | None:
        """Release a reservation after rejection/abort so it may be retried."""
        with self._lock:
            material_id = self._reserved_by_wake.pop(wake_id, None)
            if material_id is not None:
                self._reserved_ids.discard(material_id)
            return material_id
