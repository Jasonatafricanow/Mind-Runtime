"""Bounded untrusted proposals; MR identity never uses provider identifiers."""

import hashlib
import json
from collections.abc import Mapping
from typing import Protocol

from mind_runtime.contracts import Evidence, Observation
from mind_runtime.memory.contracts import MemoryCandidate, MemoryProvenance
from mind_runtime.memory.store import scope_json


class MemoryExtractor(Protocol):
    def extract(
        self, evidence: Evidence, observation: Observation
    ) -> tuple[MemoryCandidate, ...]: ...


class DeterministicExtractor:
    def extract(self, evidence: Evidence, observation: Observation) -> tuple[MemoryCandidate, ...]:
        text = evidence.payload.get("text") if isinstance(evidence.payload, Mapping) else None
        if not isinstance(text, str) or not text.strip():
            return ()
        return (
            MemoryCandidate(
                "text-v1:0",
                evidence.scope,
                text,
                MemoryProvenance((evidence.id,), observation.id, "text-v1"),
            ),
        )


def memory_identity(candidate: MemoryCandidate, origin_runtime_id: str) -> str:
    identity = [
        "mr-memory-v1",
        origin_runtime_id,
        json.loads(scope_json(candidate.scope)),
        candidate.provenance.observation_id,
        candidate.provenance.evidence_refs,
        candidate.provenance.extractor_version,
        candidate.candidate_id,
    ]
    return "memory-" + hashlib.sha256(json.dumps(identity, ensure_ascii=False).encode()).hexdigest()
