"""Runtime single-writer admission authority (MR-RUNTIME-05).

Process-local, per-namespace serialization of canonical turn admissions.

Contract (MR-RUNTIME-04 §15 decision table + MR-RUNTIME-04-R1 audit):
for each storage namespace, at most ONE canonical admission sequence is
active at a time, and every admitted turn is durably based on the canonical
result of all prior admitted turns in that sequence.

Scope and limits:

- **One process.** The registry lives in process memory. Two independent
  PROCESSES holding the same RuntimeBinding/namespace are NOT excluded by
  this authority — cross-process shared runtime remains UNSUPPORTED
  (future Runtime Service ticket).
- **Keyed by resolved namespace path** (the state DB path), never by
  thread_id, session_id, channel, or adapter object identity. Different
  namespaces (Lab A / Lab B / Production) get independent authorities and
  run fully in parallel.
- **No durable state.** This introduces no lease file, writer epoch, or any
  new persisted authority (MR-RUNTIME-05 §21 decision: implementation of the
  already-accepted contract, no new ADR).

The orchestrator acquires the lease for the WHOLE turn lifecycle
(begin_turn → commit_turn/abort_turn) because the admission unit is
"read authoritative base → derive → persist → publish"; serializing only
the SQLite INSERT would leave the stale derivation — the actual R1 failure
— unprotected.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Protocol


class AdmissionLease:
    """One active admission. Release exactly once (idempotent for safety)."""

    def __init__(self, authority: NamespaceAdmissionAuthority) -> None:
        self._authority = authority
        self._released = False

    @property
    def namespace_key(self) -> str:
        return self._authority.namespace_key

    def release(self) -> None:
        if self._released:
            return
        self._released = True
        self._authority._release()


class RuntimeTurnAdmission(Protocol):
    """What an admission authority must expose to the orchestrator."""

    def acquire(self, *, turn_context: str = "") -> AdmissionLease: ...


class NamespaceAdmissionAuthority:
    """Serializes canonical turn admissions for ONE storage namespace.

    Instances are process-wide singletons per resolved namespace path:
    every stack built over the same namespace shares one authority, so
    multiple thread-local adapters / orchestrators form one admission
    sequence instead of competing writers.
    """

    _registry: dict[str, NamespaceAdmissionAuthority] = {}
    _registry_guard = threading.Lock()

    def __init__(self, namespace_key: str) -> None:
        self._namespace_key = namespace_key
        self._lock = threading.Lock()
        self._holder: str | None = None

    @classmethod
    def for_state_db(cls, state_db: str | Path) -> NamespaceAdmissionAuthority:
        """Return the process-wide authority for the namespace owning state_db."""
        key = str(Path(state_db).resolve())
        with cls._registry_guard:
            authority = cls._registry.get(key)
            if authority is None:
                authority = cls(key)
                cls._registry[key] = authority
            return authority

    @property
    def namespace_key(self) -> str:
        return self._namespace_key

    @property
    def current_holder(self) -> str | None:
        """Diagnostic: who holds the active admission (None = idle)."""
        return self._holder

    def acquire(self, *, turn_context: str = "") -> AdmissionLease:
        """Block until the namespace's current admission completes."""
        self._lock.acquire()
        try:
            self._holder = turn_context or threading.current_thread().name
        except Exception:  # pragma: no cover — defensive; never keep a lock
            self._lock.release()
            raise
        return AdmissionLease(self)

    def try_acquire(self, *, turn_context: str = "") -> AdmissionLease | None:
        """Non-blocking variant (diagnostics/tests)."""
        if not self._lock.acquire(blocking=False):
            return None
        self._holder = turn_context or threading.current_thread().name
        return AdmissionLease(self)

    def _release(self) -> None:
        self._holder = None
        self._lock.release()
