"""Only the successful factual admission hook may register Memory eligibility."""

import json
from typing import TYPE_CHECKING

from mind_runtime.contracts import Evidence, SyncFields
from mind_runtime.contracts.common import require_non_empty
from mind_runtime.facts.persistence import FactBackend
from mind_runtime.facts.ports import FactAdmissionDisposition, FactAdmissionResult
from mind_runtime.memory.contracts import CommittedMemory, MemoryCandidate
from mind_runtime.memory.extraction import DeterministicExtractor, MemoryExtractor, memory_identity
from mind_runtime.memory.store import CanonicalMemoryStore, scope_json
from mind_runtime.providers.clock import Clock

if TYPE_CHECKING:
    from mind_runtime.memory.thread_updates import ThreadUpdateWorker


class MemoryAdmissionService:
    def __init__(
        self,
        *,
        store: CanonicalMemoryStore,
        facts: FactBackend,
        clock: Clock,
        origin_runtime_id: str,
        enabled: bool = False,
        extractor: MemoryExtractor | None = None,
        thread_updates: ThreadUpdateWorker | None = None,
    ) -> None:
        require_non_empty(origin_runtime_id, "origin_runtime_id")
        if type(enabled) is not bool:
            raise ValueError("enabled must be bool")
        self._store, self._facts, self._clock = store, facts, clock
        self._origin, self._enabled = origin_runtime_id, enabled
        self._extractor = extractor if extractor is not None else DeterministicExtractor()
        self._thread_updates = thread_updates

    def after_admission(self, evidence: Evidence, result: FactAdmissionResult) -> None:
        if not self._enabled:
            return
        observation = result.observation
        pair = self._facts.find_evidence(evidence.scope, evidence.id)
        admitted = self._facts.find_observation(evidence.scope, f"observation-{evidence.id}")
        if (
            pair is None
            or pair[0] != evidence
            or admitted != observation
            or admitted is None
            or observation.scope != evidence.scope
            or observation.evidence_refs != (evidence.id,)
            or pair[1] != observation.interaction_id
        ):
            raise ValueError("Memory requires the exact durable admitted Evidence/Observation pair")
        key = json.dumps([self._origin, scope_json(evidence.scope), evidence.id, observation.id])
        if result.disposition is FactAdmissionDisposition.NEW:
            self._store._register_job(key, self._clock.now())
        job = self._store._job(key)
        if job is None:
            self._drain_thread_updates()
            return  # no historical backfill, including REPAIRED without eligibility
        if job[2]:
            self._drain_thread_updates()
            return
        if job[1] is None:
            candidates = self._extractor.extract(evidence, observation)
            if not isinstance(candidates, tuple) or len(candidates) > 32:
                raise ValueError("extractor must return a tuple of at most 32 candidates")
            memories = []
            seen = set()
            for candidate in candidates:
                if (
                    not isinstance(candidate, MemoryCandidate)
                    or candidate.scope != evidence.scope
                    or candidate.provenance.observation_id != observation.id
                    or not set(candidate.provenance.evidence_refs).issubset({evidence.id})
                ):
                    raise ValueError("candidate exceeds its admitted source authority")
                memory_id = memory_identity(candidate, self._origin)
                if memory_id in seen:
                    raise ValueError("duplicate candidate identity")
                seen.add(memory_id)
                memories.append(
                    CommittedMemory(
                        memory_id=memory_id,
                        scope=evidence.scope,
                        content=candidate.content,
                        provenance=candidate.provenance,
                        origin_runtime_id=self._origin,
                        committed_at=job[0],
                        sync=SyncFields(evidence.scope, self._origin, memory_id, 1, memory_id),
                    )
                )
            self._store._freeze_job(key, tuple(memories))
        self._store._complete_job(key)
        self._drain_thread_updates()

    def _drain_thread_updates(self) -> None:
        if self._thread_updates is not None:
            self._thread_updates.run_once(limit=32)
