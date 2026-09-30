"""Current LCE Path-B binding over MR-owned canonical Memory.

MR remains the factual authority. This module exposes a read-only canonical
source adapter to LCE and gives LCE its own derived projection store. No MR
Memory row is copied into an LCE factual database.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, cast

from mind_runtime.contracts import InspirationMaterial, Scope
from mind_runtime.contracts.common import require_aware_utc
from mind_runtime.facts.persistence import SqliteFactReader
from mind_runtime.integrations.lce import (
    LceAcceptedUnderstanding,
    LceIntegrationUnavailable,
    MrMemorySubstrateAdapter,
    _accepted_understandings,
    _ensure_current_lce_layout,
    _scope_lce_root,
    _verify_binding,
)
from mind_runtime.memory.contracts import CommittedMemory, MemoryLifecycle
from mind_runtime.memory.providers.bm25 import lexical_tokens
from mind_runtime.memory.store import CanonicalMemoryStore, scope_json
from mind_runtime.runtime_binding import RuntimeBinding, bind_storage

if TYPE_CHECKING:
    from lce.cognition.convergence import AuthorityConfig
    from lce.cognition.inspiration import (
        InspirationConfig,
        InspirationInterpreter,
    )
    from lce.cognition.line_graph import (
        CallableProjectionConfig,
        LineAssemblerConfig,
    )
    from lce.cognition.promotion import BoundedInterpreter
    from lce.core.projection import LceProjectionCore, ProcessResult
    from lce.reference_memory.contracts import RawEvidence, SemanticBlock
    from lce.semantic.contracts import SemanticDecisionProvider
    from lce.structure.surface import SurfaceConfig
    from lce.structure.trajectory import (
        NeighbourCandidateProvider,
        TrajectoryConfig,
        TrajectoryRuntimeResult,
    )


_SOURCE_PREFIX = "mr-source:"
_SYNC_DB_FILENAME = "mr_projection_sync.sqlite"
_WARM_RECONCILE_LOCK = threading.Lock()
_PROJECTION_WRITE_LOCK = threading.RLock()
_WARM_RECONCILED: dict[str, object] = {}


@dataclass(frozen=True, slots=True)
class LceProjectionReconcileReport:
    source_count: int
    processed_sources: int
    invalidated_sources: int
    retired_sources: int
    projection_rebuilt: bool
    current: bool


@dataclass(frozen=True, slots=True)
class _SyncReceipt:
    evidence_id: str
    source_fingerprint: str
    source_state: str
    status: str


class _LceProjectionSyncLedger:
    """Composition-owned producer/consumer receipts; never cognition authority."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), timeout=30.0)
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS source_sync (
                evidence_id TEXT PRIMARY KEY,
                source_fingerprint TEXT NOT NULL,
                source_state TEXT NOT NULL,
                status TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sync_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def receipts(self) -> dict[str, _SyncReceipt]:
        return {
            str(row[0]): _SyncReceipt(
                evidence_id=str(row[0]),
                source_fingerprint=str(row[1]),
                source_state=str(row[2]),
                status=str(row[3]),
            )
            for row in self._conn.execute(
                "SELECT evidence_id,source_fingerprint,source_state,status "
                "FROM source_sync"
            )
        }

    def reconcile_required(self) -> bool:
        row = self._conn.execute(
            "SELECT value FROM sync_meta WHERE key='reconcile_required'"
        ).fetchone()
        dirty = row is not None and str(row[0]) == "1"
        if dirty:
            return True
        return self._conn.execute(
            "SELECT 1 FROM source_sync WHERE status='pending' LIMIT 1"
        ).fetchone() is not None

    def set_reconcile_required(self, required: bool) -> None:
        if type(required) is not bool:
            raise TypeError("required must be bool")
        with self._conn:
            self._conn.execute(
                "INSERT INTO sync_meta(key,value) "
                "VALUES('reconcile_required',?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                ("1" if required else "0",),
            )

    def pending_ids(self) -> tuple[str, ...]:
        return tuple(
            str(row[0])
            for row in self._conn.execute(
                "SELECT evidence_id FROM source_sync "
                "WHERE status='pending' ORDER BY evidence_id"
            )
        )

    def mark(
        self,
        *,
        evidence_id: str,
        source_fingerprint: str,
        source_state: str,
        status: str,
    ) -> None:
        if status not in {"pending", "synced", "missing"}:
            raise ValueError("unsupported LCE sync receipt status")
        with self._conn:
            self._conn.execute(
                "INSERT INTO source_sync "
                "(evidence_id,source_fingerprint,source_state,status,updated_at) "
                "VALUES (?,?,?,?,?) "
                "ON CONFLICT(evidence_id) DO UPDATE SET "
                "source_fingerprint=excluded.source_fingerprint,"
                "source_state=excluded.source_state,"
                "status=excluded.status,"
                "updated_at=excluded.updated_at",
                (
                    evidence_id,
                    source_fingerprint,
                    source_state,
                    status,
                    datetime.now(UTC).isoformat(),
                ),
            )


def _source_fingerprint(item: RawEvidence) -> str:
    payload = {
        "evidence_id": item.evidence_id,
        "content": item.content,
        "occurred_at": item.occurred_at.isoformat(),
        "known_at": item.effective_known_at.isoformat(),
        "ordering_key": item.effective_ordering_key,
        "state": item.state,
        "superseded_by": item.superseded_by,
        "provenance": dict(item.provenance),
    }
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _effective_window_payload(window: object) -> dict[str, object] | None:
    if window is None:
        return None
    kind = getattr(window, "kind", None)
    start_at = getattr(window, "start_at", None)
    end_at = getattr(window, "end_at", None)
    return {
        "kind": getattr(kind, "value", str(kind)),
        "start_at": (
            start_at.isoformat()
            if isinstance(start_at, datetime)
            else None
        ),
        "end_at": (
            end_at.isoformat()
            if isinstance(end_at, datetime)
            else None
        ),
    }


def _semantic_time_payload(value: object) -> dict[str, object]:
    relation = getattr(value, "relation", None)
    precision = getattr(value, "precision", None)
    daypart = getattr(value, "daypart", None)
    return {
        "relation": getattr(relation, "value", str(relation)),
        "precision": getattr(precision, "value", str(precision)),
        "daypart": (
            None
            if daypart is None
            else getattr(daypart, "value", str(daypart))
        ),
    }


class MrLceCanonicalSourceAdapter:
    """Expose MR canonical Memory as grouped read-only LCE Raw Evidence.

    Multiple canonical Memory rows produced from one interaction remain one
    independent LCE source unit. This preserves the same anti-self-amplification
    rule used by Thread maturity: one turn cannot become several independent
    authority votes merely because extraction emitted several Memory rows.
    """

    def __init__(self, adapter: MrMemorySubstrateAdapter) -> None:
        if not isinstance(adapter, MrMemorySubstrateAdapter):
            raise TypeError("adapter must be MrMemorySubstrateAdapter")
        self._adapter = adapter

    @property
    def scope(self) -> Scope:
        return self._adapter.scope

    def _all_scope_memories(self) -> tuple[CommittedMemory, ...]:
        _verify_binding(self._adapter.binding, self._adapter._paths)
        store = CanonicalMemoryStore(
            self._adapter._paths.memory_db,
            read_only=True,
        )
        try:
            return tuple(
                memory
                for memory in store.load_all()
                if memory.scope == self._adapter.scope
            )
        finally:
            store.close()

    @staticmethod
    def _authority_key(memory: CommittedMemory) -> tuple[object, ...]:
        interaction_id = memory.provenance.interaction_id
        if interaction_id is not None:
            return (
                "interaction",
                memory.origin_runtime_id,
                interaction_id,
            )
        return (
            "evidence",
            memory.origin_runtime_id,
            *memory.provenance.evidence_refs,
        )

    def _source_id(
        self,
        authority_key: tuple[object, ...],
    ) -> str:
        payload = json.dumps(
            {
                "scope": scope_json(self._adapter.scope),
                "authority_key": authority_key,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        return _SOURCE_PREFIX + hashlib.sha256(
            payload.encode("utf-8")
        ).hexdigest()[:24]

    def _groups(
        self,
    ) -> dict[str, tuple[CommittedMemory, ...]]:
        grouped: dict[
            tuple[object, ...],
            list[CommittedMemory],
        ] = {}
        for memory in self._all_scope_memories():
            grouped.setdefault(
                self._authority_key(memory),
                [],
            ).append(memory)
        output: dict[str, tuple[CommittedMemory, ...]] = {}
        for key, memories in grouped.items():
            output[self._source_id(key)] = tuple(
                sorted(memories, key=lambda item: item.memory_id)
            )
        return output

    def _raw_evidence(
        self,
        evidence_id: str,
        memories: tuple[CommittedMemory, ...],
    ) -> RawEvidence:
        try:
            from lce.reference_memory.contracts import RawEvidence
        except ImportError as exc:
            raise LceIntegrationUnavailable(
                "install the current optional lce-core package"
            ) from exc

        if not memories:
            raise KeyError(evidence_id)
        reader = SqliteFactReader(self._adapter._paths.facts_db)
        try:
            occurred_points: list[datetime] = []
            known_points: list[datetime] = []
            evidence_refs: set[str] = set()
            observation_payloads: list[dict[str, object]] = []
            for memory in memories:
                source_observation = reader.find_observation(
                    self._adapter.scope,
                    memory.provenance.observation_id,
                )
                if source_observation is None:
                    raise KeyError(memory.memory_id)
                source_evidence: list[dict[str, str]] = []
                for source_ref in memory.provenance.evidence_refs:
                    pair = reader.find_evidence(
                        self._adapter.scope,
                        source_ref,
                    )
                    if pair is None:
                        raise KeyError(source_ref)
                    evidence = pair[0]
                    evidence_refs.add(evidence.id)
                    occurred_points.append(evidence.occurred_at)
                    known_points.append(evidence.received_at)
                    source_evidence.append(
                        {
                            "evidence_id": evidence.id,
                            "occurred_at": evidence.occurred_at.isoformat(),
                            "received_at": evidence.received_at.isoformat(),
                        }
                    )
                known_points.extend(
                    (
                        memory.committed_at,
                        source_observation.observed_at,
                    )
                )
                observation_payloads.append(
                    {
                        "memory_id": memory.memory_id,
                        "observation_id": source_observation.id,
                        "observed_at": source_observation.observed_at.isoformat(),
                        "semantic_time": _semantic_time_payload(
                            source_observation.semantic_time
                        ),
                        "effective_window": _effective_window_payload(
                            source_observation.effective_window
                        ),
                        "source_evidence": source_evidence,
                    }
                )
        finally:
            reader.close()

        if not occurred_points or not known_points:
            raise KeyError(evidence_id)
        all_active = all(
            memory.lifecycle is MemoryLifecycle.ACTIVE
            for memory in memories
        )
        content = "\n".join(
            dict.fromkeys(memory.content.strip() for memory in memories)
        )
        interaction_ids = tuple(
            sorted(
                {
                    memory.provenance.interaction_id
                    for memory in memories
                    if memory.provenance.interaction_id is not None
                }
            )
        )
        return RawEvidence(
            evidence_id=evidence_id,
            content=content,
            occurred_at=min(occurred_points),
            known_at=max(known_points),
            state="VALID" if all_active else "INVALID",
            provenance={
                "canonical": True,
                "source_kind": "mr-canonical-memory-group",
                "scope": scope_json(self._adapter.scope),
                "memory_ids": tuple(
                    memory.memory_id for memory in memories
                ),
                "evidence_refs": tuple(sorted(evidence_refs)),
                "observation_ids": tuple(
                    memory.provenance.observation_id
                    for memory in memories
                ),
                "interaction_ids": interaction_ids,
                "observations": observation_payloads,
            },
        )

    def get_evidence(self, evidence_id: str) -> RawEvidence:
        if (
            not isinstance(evidence_id, str)
            or not evidence_id.startswith(_SOURCE_PREFIX)
        ):
            raise KeyError(evidence_id)
        groups = self._groups()
        memories = groups.get(evidence_id)
        if memories is None:
            raise KeyError(evidence_id)
        return self._raw_evidence(evidence_id, memories)

    def list_all_evidence(self) -> tuple[RawEvidence, ...]:
        """Return all current canonical groups, including invalid lifecycle state."""
        return tuple(
            sorted(
                (
                    self._raw_evidence(evidence_id, memories)
                    for evidence_id, memories in self._groups().items()
                ),
                key=lambda item: (
                    item.effective_ordering_key,
                    item.evidence_id,
                ),
            )
        )

    def list_current_valid_evidence(self) -> tuple[RawEvidence, ...]:
        return tuple(
            item
            for item in self.list_all_evidence()
            if item.current_valid
        )

    def evidence_for_interaction_id(
        self,
        interaction_id: str,
    ) -> tuple[RawEvidence, ...]:
        if not isinstance(interaction_id, str) or not interaction_id.strip():
            raise ValueError("interaction_id must be nonempty")
        return tuple(
            item
            for item in self.list_all_evidence()
            if interaction_id
            in tuple(item.provenance.get("interaction_ids", ()))
        )

    def evidence_for_memory_ids(
        self,
        memory_ids: tuple[str, ...],
    ) -> tuple[RawEvidence, ...]:
        selected = self._adapter._selected_memories(memory_ids)
        selected_ids = {memory.memory_id for memory in selected}
        materials = tuple(
            self._raw_evidence(evidence_id, memories)
            for evidence_id, memories in self._groups().items()
            if any(
                memory.memory_id in selected_ids
                for memory in memories
            )
        )
        return tuple(
            sorted(
                materials,
                key=lambda item: (
                    item.effective_ordering_key,
                    item.evidence_id,
                ),
            )
        )

    def memory_ids_for_source(
        self,
        evidence_id: str,
    ) -> tuple[str, ...]:
        item = self.get_evidence(evidence_id)
        raw = item.provenance.get("memory_ids", ())
        if not isinstance(raw, (list, tuple)):
            return ()
        return tuple(
            value
            for value in raw
            if isinstance(value, str) and value
        )

    def original_source_refs(
        self,
        evidence_id: str,
    ) -> tuple[str, ...]:
        item = self.get_evidence(evidence_id)
        raw = item.provenance.get("evidence_refs", ())
        if not isinstance(raw, (list, tuple)):
            return ()
        return tuple(
            value
            for value in raw
            if isinstance(value, str) and value
        )


    def current_memory_ids(self) -> tuple[str, ...]:
        """Return current ACTIVE canonical Memory IDs for background catch-up."""
        return tuple(
            sorted(
                memory.memory_id
                for memory in self._all_scope_memories()
                if memory.lifecycle is MemoryLifecycle.ACTIVE
            )
        )



# Backward-compatible alias for the just-published MR integration seam.
# The canonical contract now lives in mind_runtime.contracts.
LceInspirationMaterial = InspirationMaterial


@dataclass(frozen=True)
class LceProjectionSession:
    """Embedded current LCE projection over MR canonical Memory."""

    core: LceProjectionCore
    _source: MrLceCanonicalSourceAdapter
    _legacy_adapter: MrMemorySubstrateAdapter

    @property
    def db_path(self) -> Path:
        return Path(self.core.baselines.db_path)

    def canonical_memory_ids(self) -> tuple[str, ...]:
        """Current ACTIVE canonical Memory IDs visible to the LCE source."""
        return self._source.current_memory_ids()

    def sync_all(self) -> tuple[ProcessResult, ...]:
        """Compile every current canonical source; replay is idempotent."""
        with _PROJECTION_WRITE_LOCK:
            return cast(
                "tuple[ProcessResult, ...]",
                self.core.run_batch(
                    self._source.list_current_valid_evidence()
                ),
            )

    def sync_memory_ids(
        self,
        memory_ids: tuple[str, ...],
        *,
        mode: str = "nearline",
    ) -> tuple[ProcessResult, ...]:
        if mode not in {"nearline", "batch"}:
            raise ValueError("mode must be nearline or batch")
        with _PROJECTION_WRITE_LOCK:
            materials = self._source.evidence_for_memory_ids(memory_ids)
            if mode == "batch":
                return cast(
                    "tuple[ProcessResult, ...]",
                    self.core.run_batch(materials),
                )
            return tuple(
                self.core.process(material, mode="nearline")
                for material in materials
            )

    @property
    def sync_db_path(self) -> Path:
        return _scope_lce_root(self._legacy_adapter) / _SYNC_DB_FILENAME

    def _projected_source_ids(self) -> set[str]:
        return {
            evidence_id
            for block in self.core.memory.list_semantic_blocks(
                current_valid_only=False
            )
            for evidence_id in block.raw_evidence_ids
        }

    def _retire_source(
        self,
        evidence_id: str,
        *,
        projected_source_ids: set[str],
    ) -> bool:
        if evidence_id not in projected_source_ids:
            return False
        self.core.source_changed_and_rebuild(evidence_id)
        return True

    def reconcile_canonical(self) -> LceProjectionReconcileReport:
        with _PROJECTION_WRITE_LOCK:
            return self._reconcile_canonical_locked()

    def _reconcile_canonical_locked(self) -> LceProjectionReconcileReport:
        """Bring durable LCE projection state to the current MR source boundary.

        This is a warm-start producer/consumer reconciliation, not a full
        re-import. Existing complete sources are adopted into the receipt
        ledger without reprocessing; only missing/pending sources are run.
        """
        materials = self._source.list_all_evidence()
        by_id = {item.evidence_id: item for item in materials}
        projected = self._projected_source_ids()
        ledger = _LceProjectionSyncLedger(self.sync_db_path)
        processed = invalidated = retired = 0
        try:
            receipts = ledger.receipts()

            # Historical projection inputs that no longer exist in canonical
            # Memory must be retired explicitly. A tombstone receipt prevents
            # repeating the same rebuild on every restart.
            for evidence_id in sorted(
                (projected | set(receipts)) - set(by_id)
            ):
                prior = receipts.get(evidence_id)
                if prior is not None and prior.status == "missing":
                    continue
                if self._retire_source(
                    evidence_id,
                    projected_source_ids=projected,
                ):
                    invalidated += 1
                    retired += 1
                ledger.mark(
                    evidence_id=evidence_id,
                    source_fingerprint="-",
                    source_state="MISSING",
                    status="missing",
                )

            pending: list[RawEvidence] = []
            for material in materials:
                evidence_id = material.evidence_id
                fingerprint = _source_fingerprint(material)
                prior = receipts.get(evidence_id)

                if (
                    prior is not None
                    and prior.status == "synced"
                    and prior.source_fingerprint == fingerprint
                    and prior.source_state == material.state
                ):
                    continue

                if not material.current_valid:
                    if self._retire_source(
                        evidence_id,
                        projected_source_ids=projected,
                    ):
                        invalidated += 1
                    ledger.mark(
                        evidence_id=evidence_id,
                        source_fingerprint=fingerprint,
                        source_state=material.state,
                        status="synced",
                    )
                    continue

                if (
                    prior is not None
                    and prior.status in {"synced", "missing"}
                    and prior.source_state != "VALID"
                ):
                    raise RuntimeError(
                        "canonical LCE source identity was reactivated under "
                        "a terminal receipt"
                    )
                if (
                    prior is not None
                    and prior.status == "synced"
                    and prior.source_state == "VALID"
                    and prior.source_fingerprint != fingerprint
                ):
                    raise RuntimeError(
                        "canonical LCE source changed under a stable source ID"
                    )

                # Migration path for deployments that predate MR-side sync
                # receipts: LCE's complete pipeline stage is authoritative
                # evidence that this immutable source was already consumed.
                if (
                    prior is None
                    and self.core.memory.get_pipeline_stage(evidence_id)
                    == "complete"
                ):
                    ledger.mark(
                        evidence_id=evidence_id,
                        source_fingerprint=fingerprint,
                        source_state=material.state,
                        status="synced",
                    )
                    continue

                ledger.mark(
                    evidence_id=evidence_id,
                    source_fingerprint=fingerprint,
                    source_state=material.state,
                    status="pending",
                )
                pending.append(material)

            if pending:
                ordered = tuple(
                    sorted(
                        {item.evidence_id: item for item in pending}.values(),
                        key=lambda item: (
                            item.effective_ordering_key,
                            item.evidence_id,
                        ),
                    )
                )
                self.core.run_batch(ordered)
                processed = len(ordered)
                for material in ordered:
                    ledger.mark(
                        evidence_id=material.evidence_id,
                        source_fingerprint=_source_fingerprint(material),
                        source_state=material.state,
                        status="synced",
                    )

            rebuilt = self.core.ensure_current_projection() is not None
            current = not ledger.pending_ids()
            if current:
                ledger.set_reconcile_required(False)
            return LceProjectionReconcileReport(
                source_count=len(materials),
                processed_sources=processed,
                invalidated_sources=invalidated,
                retired_sources=retired,
                projection_rebuilt=rebuilt,
                current=current,
            )
        finally:
            ledger.close()

    def sync_committed_interaction(
        self,
        interaction_id: str,
    ) -> tuple[ProcessResult, ...]:
        with _PROJECTION_WRITE_LOCK:
            return self._sync_committed_interaction_locked(interaction_id)

    def _sync_committed_interaction_locked(
        self,
        interaction_id: str,
    ) -> tuple[ProcessResult, ...]:
        """Nearline-consume one fully committed MR interaction group.

        Pending receipts from an earlier post-commit failure are retried first
        so source ordering cannot advance past an unconsumed older input.
        """
        if not isinstance(interaction_id, str) or not interaction_id.strip():
            raise ValueError("interaction_id must be nonempty")
        ledger = _LceProjectionSyncLedger(self.sync_db_path)
        projected = self._projected_source_ids()
        try:
            target = {
                item.evidence_id: item
                for item in self._source.evidence_for_interaction_id(
                    interaction_id
                )
            }
            for evidence_id in ledger.pending_ids():
                if evidence_id in target:
                    continue
                try:
                    target[evidence_id] = self._source.get_evidence(
                        evidence_id
                    )
                except KeyError:
                    self._retire_source(
                        evidence_id,
                        projected_source_ids=projected,
                    )
                    ledger.mark(
                        evidence_id=evidence_id,
                        source_fingerprint="-",
                        source_state="MISSING",
                        status="missing",
                    )

            to_process: list[RawEvidence] = []
            receipts = ledger.receipts()
            for material in sorted(
                target.values(),
                key=lambda item: (
                    item.effective_ordering_key,
                    item.evidence_id,
                ),
            ):
                fingerprint = _source_fingerprint(material)
                prior = receipts.get(material.evidence_id)
                if (
                    prior is not None
                    and prior.status == "synced"
                    and prior.source_fingerprint == fingerprint
                    and prior.source_state == material.state
                ):
                    continue
                if not material.current_valid:
                    self._retire_source(
                        material.evidence_id,
                        projected_source_ids=projected,
                    )
                    ledger.mark(
                        evidence_id=material.evidence_id,
                        source_fingerprint=fingerprint,
                        source_state=material.state,
                        status="synced",
                    )
                    continue
                if (
                    prior is not None
                    and prior.status == "synced"
                    and prior.source_state == "VALID"
                    and prior.source_fingerprint != fingerprint
                ):
                    raise RuntimeError(
                        "canonical LCE source changed after committed projection"
                    )
                ledger.mark(
                    evidence_id=material.evidence_id,
                    source_fingerprint=fingerprint,
                    source_state=material.state,
                    status="pending",
                )
                to_process.append(material)

            results = tuple(
                self.core.process(material, mode="nearline")
                for material in to_process
            )
            for material in to_process:
                ledger.mark(
                    evidence_id=material.evidence_id,
                    source_fingerprint=_source_fingerprint(material),
                    source_state=material.state,
                    status="synced",
                )
            self.core.ensure_current_projection()
            return results
        finally:
            ledger.close()

    def bootstrap_trajectory(
        self,
        *,
        knowledge_cutoff: datetime,
    ) -> TrajectoryRuntimeResult:
        if knowledge_cutoff.tzinfo != UTC:
            raise ValueError("knowledge_cutoff must be UTC")
        with _PROJECTION_WRITE_LOCK:
            return self.core.bootstrap_trajectory(
                knowledge_cutoff=knowledge_cutoff
            )

    def discover_inspiration(
        self,
        *,
        knowledge_cutoff: datetime,
        trajectory_result: TrajectoryRuntimeResult | None = None,
    ) -> tuple[LceInspirationMaterial, ...]:
        """Return only opaque ID + content from LCE inspiration discovery."""
        if knowledge_cutoff.tzinfo != UTC:
            raise ValueError("knowledge_cutoff must be UTC")
        materials = self.core.discover_inspiration(
            knowledge_cutoff=knowledge_cutoff,
            trajectory_result=trajectory_result,
        )
        return tuple(
            LceInspirationMaterial(
                material_id=item.material_id,
                content=item.content,
            )
            for item in materials
        )

    def inspiration_materials(
        self,
        *,
        limit: int = 20,
    ) -> tuple[LceInspirationMaterial, ...]:
        materials = self.core.inspiration_materials(limit=limit)
        return tuple(
            LceInspirationMaterial(
                material_id=item.material_id,
                content=item.content,
            )
            for item in materials
        )

    def consume_inspiration(self, material_id: str) -> None:
        self.core.consume_inspiration(material_id)

    def dismiss_inspiration(self, material_id: str) -> None:
        self.core.dismiss_inspiration(material_id)

    def accepted_understandings(
        self,
        current_context: str | None,
        *,
        limit: int = 4,
    ) -> tuple[LceAcceptedUnderstanding, ...]:
        if type(limit) is not int or not 0 <= limit <= 100:
            raise ValueError("limit must be an integer in [0, 100]")
        if limit == 0:
            return ()

        # Path A Baselines use canonical MR Memory IDs and are intentionally
        # invisible to LCE's SemanticBlock reader.
        path_a = _accepted_understandings(
            self._legacy_adapter,
            self.core.baselines,
            current_context=current_context,
            limit=limit,
        )

        query_tokens = set(lexical_tokens(current_context or ""))
        path_b: list[LceAcceptedUnderstanding] = []
        for view in self.core.query(current_context):
            memory_ids: set[str] = set()
            source_refs: set[str] = set()
            valid = True
            for source_id in view.supporting_source_refs:
                try:
                    memory_ids.update(
                        self._source.memory_ids_for_source(source_id)
                    )
                    source_refs.update(
                        self._source.original_source_refs(source_id)
                    )
                except KeyError:
                    valid = False
                    break
            if not valid or not memory_ids:
                continue
            if query_tokens:
                searchable = set(
                    lexical_tokens(view.content)
                )
                overlap = len(query_tokens & searchable)
                relevance = overlap / len(query_tokens)
            else:
                relevance = 1.0
            path_b.append(
                LceAcceptedUnderstanding(
                    content=view.content,
                    baseline_id=view.baseline_id,
                    region_id=view.region_id,
                    revision_number=view.revision_number,
                    supporting_memory_ids=tuple(sorted(memory_ids)),
                    source_refs=tuple(sorted(source_refs)),
                    relevance=min(1.0, relevance),
                )
            )

        by_id = {
            item.baseline_id: item
            for item in (*path_a, *path_b)
        }
        ordered = sorted(
            by_id.values(),
            key=lambda item: (
                -item.relevance,
                item.region_id,
                -item.revision_number,
            ),
        )
        return tuple(ordered[:limit])

    def close(self) -> None:
        self.core.close()

    def __enter__(self) -> LceProjectionSession:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


def open_lce_projection_binding(
    binding: RuntimeBinding,
    scope: Scope,
    *,
    enabled: bool = False,
    provider: SemanticDecisionProvider | None = None,
    interpreter: BoundedInterpreter | None = None,
    trajectory_config: TrajectoryConfig | None = None,
    trajectory_neighbour_provider: NeighbourCandidateProvider | None = None,
    authority_config: AuthorityConfig | None = None,
    line_assembler_config: LineAssemblerConfig | None = None,
    callable_projection_config: CallableProjectionConfig | None = None,
    inspiration_config: InspirationConfig | None = None,
    inspiration_interpreter: InspirationInterpreter | None = None,
    surface_config: SurfaceConfig | None = None,
    block_embedder: Callable[[SemanticBlock], tuple[float, ...]] | None = None,
    block_embedding_version: str = "mr-lce-vector-v1",
    production_root: Path | str | None = None,
    lab_root: Path | str | None = None,
) -> LceProjectionSession | None:
    """Open current Path B without granting LCE factual write authority."""
    if type(enabled) is not bool:
        raise TypeError("enabled must be bool")
    if not enabled:
        return None
    if (
        not isinstance(block_embedding_version, str)
        or not block_embedding_version.strip()
    ):
        raise ValueError("block_embedding_version must be nonempty")

    adapter = MrMemorySubstrateAdapter(
        binding,
        scope,
        production_root=production_root,
        lab_root=lab_root,
    )
    _verify_binding(binding, adapter._paths)
    CanonicalMemoryStore(
        adapter._paths.memory_db,
        read_only=True,
    ).close()
    _ensure_current_lce_layout(adapter)

    try:
        from lce.core.projection import LceProjectionCore
        from lce.reference_memory.composite import ProjectionSubstrate
        from lce.reference_memory.projection_state import (
            SqliteProjectionStateStore,
        )
    except ImportError as exc:
        raise LceIntegrationUnavailable(
            "install the current optional lce-core package"
        ) from exc

    source = MrLceCanonicalSourceAdapter(adapter)
    state = SqliteProjectionStateStore(
        _scope_lce_root(adapter) / "projection_state"
    )
    substrate = ProjectionSubstrate(
        source,
        state,
        close_source=False,
        close_state=True,
    )
    try:
        core = LceProjectionCore(
            _scope_lce_root(adapter),
            memory=substrate,
            provider=provider,
            interpreter=interpreter,
            lineage_id="mr-canonical-memory",
            trajectory_config=trajectory_config,
            trajectory_neighbour_provider=trajectory_neighbour_provider,
            authority_config=authority_config,
            line_assembler_config=line_assembler_config,
            callable_projection_config=callable_projection_config,
            inspiration_config=inspiration_config,
            inspiration_interpreter=inspiration_interpreter,
            surface_config=surface_config,
            block_embedder=block_embedder,
            block_embedding_version=block_embedding_version,
            close_memory=True,
        )
    except BaseException:
        substrate.close()
        raise
    return LceProjectionSession(core, source, adapter)


@dataclass(frozen=True, slots=True)
class LceCommittedMemoryProjection:
    """Post-commit nearline consumer for MR canonical Memory."""

    binding: RuntimeBinding
    enabled: bool = False
    production_root: Path | str | None = None
    lab_root: Path | str | None = None

    def sync_committed_interaction(
        self,
        *,
        interaction_id: str,
        scope: Scope,
        committed_at: datetime,
    ) -> None:
        require_aware_utc(committed_at, "committed_at")
        if not self.enabled:
            return
        adapter = MrMemorySubstrateAdapter(
            self.binding,
            scope,
            production_root=self.production_root,
            lab_root=self.lab_root,
        )
        _verify_binding(self.binding, adapter._paths)
        ledger = _LceProjectionSyncLedger(
            _scope_lce_root(adapter) / _SYNC_DB_FILENAME
        )
        try:
            recover_first = ledger.reconcile_required()
            # This durable marker is written before importing/opening LCE.
            # Even dependency/open failures therefore become retryable work.
            ledger.set_reconcile_required(True)
        finally:
            ledger.close()

        session = open_lce_projection_binding(
            self.binding,
            scope,
            enabled=True,
            production_root=self.production_root,
            lab_root=self.lab_root,
        )
        if session is None:
            raise LceIntegrationUnavailable(
                "enabled LCE projection binding did not open"
            )
        with session:
            if recover_first:
                report = session.reconcile_canonical()
                if not report.current:
                    raise RuntimeError(
                        "LCE recovery did not reach current canonical state"
                    )
            session.sync_committed_interaction(interaction_id)

        ledger = _LceProjectionSyncLedger(
            _scope_lce_root(adapter) / _SYNC_DB_FILENAME
        )
        try:
            if not ledger.pending_ids():
                ledger.set_reconcile_required(False)
        finally:
            ledger.close()


def lce_projection_reconcile_required(
    binding: RuntimeBinding,
    scope: Scope,
    *,
    production_root: Path | str | None = None,
    lab_root: Path | str | None = None,
) -> bool:
    """Read the durable producer/consumer dirty state without running cognition."""
    adapter = MrMemorySubstrateAdapter(
        binding,
        scope,
        production_root=production_root,
        lab_root=lab_root,
    )
    _verify_binding(binding, adapter._paths)
    path = _scope_lce_root(adapter) / _SYNC_DB_FILENAME
    if not path.exists():
        return True
    conn = sqlite3.connect(
        f"file:{path.as_posix()}?mode=ro",
        uri=True,
        timeout=1.0,
    )
    try:
        row = conn.execute(
            "SELECT value FROM sync_meta WHERE key='reconcile_required'"
        ).fetchone()
        if row is not None and str(row[0]) == "1":
            return True
        return conn.execute(
            "SELECT 1 FROM source_sync WHERE status='pending' LIMIT 1"
        ).fetchone() is not None
    finally:
        conn.close()


def warm_reconcile_lce_projection(
    binding: RuntimeBinding,
    scope: Scope,
    *,
    enabled: bool = False,
    production_root: Path | str | None = None,
    lab_root: Path | str | None = None,
) -> LceProjectionReconcileReport | None:
    """Synchronously prove MR canonical Memory and LCE are current at boot.

    Successful reconciliation is cached only for this process/runtime/scope.
    A process restart clears the cache and therefore re-runs the durable diff.
    """
    if type(enabled) is not bool:
        raise TypeError("enabled must be bool")
    if not enabled:
        return None
    if not isinstance(scope, Scope):
        raise TypeError("scope must be Scope")

    paths = bind_storage(
        binding,
        production_root=production_root,
        lab_root=lab_root,
    )
    # LCE is enabled only together with Memory in production. A fresh runtime
    # may not have admitted its first Memory yet, so establish the empty
    # canonical store before opening the read-only source adapter.
    CanonicalMemoryStore(paths.memory_db).close()
    key = json.dumps(
        [str(paths.root.resolve()), scope_json(scope)],
        ensure_ascii=False,
    )
    with _WARM_RECONCILE_LOCK:
        cached = _WARM_RECONCILED.get(key)
        if isinstance(cached, LceProjectionReconcileReport):
            return cached
        session = open_lce_projection_binding(
            binding,
            scope,
            enabled=True,
            production_root=production_root,
            lab_root=lab_root,
        )
        if session is None:
            raise LceIntegrationUnavailable(
                "enabled LCE projection binding did not open"
            )
        with session:
            report = session.reconcile_canonical()
        if not report.current:
            raise RuntimeError(
                "LCE warm reconciliation left pending canonical sources"
            )
        _WARM_RECONCILED[key] = report
        return report

__all__ = [
    "LceCommittedMemoryProjection",
    "LceInspirationMaterial",
    "LceProjectionReconcileReport",
    "LceProjectionSession",
    "MrLceCanonicalSourceAdapter",
    "lce_projection_reconcile_required",
    "open_lce_projection_binding",
    "warm_reconcile_lce_projection",
]
