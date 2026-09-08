"""ADR-0027 derived semantic records; never canonical facts or state."""

import hashlib
import json
from dataclasses import asdict, dataclass, is_dataclass
from datetime import datetime
from enum import StrEnum

from mind_runtime.contracts.appraisal import SemanticAppraisal, SemanticEventCandidate
from mind_runtime.contracts.historical import HistoricalContextBundle
from mind_runtime.contracts.scope import Scope


def authorized_history(history: object, scope: Scope, runtime_id: str) -> bool:
    if history is None:
        return True
    if not isinstance(history, HistoricalContextBundle):
        return False
    return (
        history.scope == scope
        and history.origin_runtime_id == runtime_id
        and all(
            item.scope == scope
            for item in history.episodes + history.stable_facts + history.relationship_events
        )
        and all(
            item.scope == scope and item.origin_runtime_id == runtime_id
            for item in history.pattern_summaries
        )
    )


def canonical_json(value: object) -> str:
    def encode(item: object) -> object:
        if is_dataclass(item) and not isinstance(item, type):
            return asdict(item)
        if isinstance(item, datetime):
            return item.isoformat()
        raise TypeError(f"unsupported projection dependency: {type(item).__name__}")

    return json.dumps(
        value,
        default=encode,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def digest(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


class ProjectionStatus(StrEnum):
    MAPPED = "MAPPED"
    UNMAPPED = "UNMAPPED"
    ABSTAINED = "ABSTAINED"
    REJECTED = "REJECTED"


@dataclass(frozen=True, slots=True)
class AcceptedAppraisal:
    acceptance_id: str
    status: str
    appraisal: SemanticAppraisal
    candidate: SemanticEventCandidate
    interaction_id: str
    persona_id: str
    trusted_evidence_refs: tuple[str, ...]
    route_abstention_reasons: tuple[str, ...]
    reason_codes: tuple[str, ...]
    projection_scope: Scope | None = None
    owner: str = "SemanticAppraisalProducer"
    owner_version: str = "1"

    def valid_lineage(self) -> bool:
        a, c = self.appraisal, self.candidate
        return bool(
            self.owner == "SemanticAppraisalProducer"
            and self.owner_version == "1"
            and self.interaction_id
            and self.persona_id
            and a.scope == c.scope
            and a.origin_runtime_id == c.origin_runtime_id
            and a.appraisal_id == f"appraisal-{c.candidate_id}"
            and set(a.evidence_refs).issubset(self.trusted_evidence_refs)
            and set(c.evidence_refs).issubset(self.trusted_evidence_refs)
            and self.acceptance_id
            == "acceptance-"
            + digest(
                (
                    a,
                    c,
                    self.interaction_id,
                    self.persona_id,
                    self.trusted_evidence_refs,
                    self.route_abstention_reasons,
                    self.status,
                    self.reason_codes,
                    self.projection_scope,
                )
            )
        )


@dataclass(frozen=True, slots=True)
class ProjectionEffect:
    dimension: str
    amount: float
    source_ref: str
    operation: str = "delta"
    target_domain: str = "agent"
    target_scope: Scope | None = None


@dataclass(frozen=True, slots=True)
class AppraisalProjectionResult:
    projection_id: str
    status: ProjectionStatus
    source_appraisal_ref: str | None
    source_candidate_ref: str | None
    projector_id: str
    projector_version: str
    dependency_digest: str
    effects: tuple[ProjectionEffect, ...]
    reason_codes: tuple[str, ...]
    provenance: tuple[str, ...]
    # Canonical JSON snapshot preserves the complete old mapper payload without
    # mutable dictionaries in this immutable materialized result.
    mapping_json: str

    def __post_init__(self) -> None:
        if self.status != ProjectionStatus.MAPPED and self.effects:
            raise ValueError("non-mapped projection cannot contain effects")
        canonical_json(self.effects)
        if self.projection_id != "projection-" + self.dependency_digest:
            raise ValueError("projection identity mismatch")
        mapped = json.loads(self.mapping_json)
        if [(e.dimension, e.amount, e.source_ref) for e in self.effects] != [
            (e["dimension"], e["amount"], e["source_ref"]) for e in mapped["impulses"]
        ]:
            raise ValueError("projection effects disagree with mapping payload")
