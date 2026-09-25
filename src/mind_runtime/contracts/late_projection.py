"""ADR-0027 derived semantic records; never canonical facts or state."""

import hashlib
import json
from dataclasses import asdict, dataclass, is_dataclass
from datetime import datetime
from enum import StrEnum

from mind_runtime.contracts.appraisal import SemanticAppraisal, SemanticEventCandidate
from mind_runtime.contracts.historical import HistoricalContextBundle
from mind_runtime.contracts.scope import Scope
from mind_runtime.contracts.state import StateDomain, state_domain_for_scope


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


class ApplicationStatus(StrEnum):
    EVALUATED = "EVALUATED"
    PENDING = "APPLICATION_PENDING"
    COMMITTED = "COMMITTED"
    ABORTED = "ABORTED"


def application_identity(
    runtime_id: str, acceptance_id: str, effect_group_id: str, original_interaction_id: str
) -> str:
    """One original admission identity, independent of projection version."""
    return "application-" + digest(
        (runtime_id, acceptance_id, effect_group_id, original_interaction_id)
    )


@dataclass(frozen=True, slots=True)
class ApplicationReceipt:
    application_id: str
    projection_id: str
    acceptance_id: str
    interaction_id: str
    effect_group_id: str
    runtime_id: str
    scope: Scope
    status: ApplicationStatus
    commit_ref: str | None
    transition_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.status, ApplicationStatus):
            raise ValueError("application status must be typed")
        if self.application_id != application_identity(
            self.runtime_id, self.acceptance_id, self.effect_group_id, self.interaction_id
        ):
            raise ValueError("application identity does not match original interaction")
        if self.scope.domain.value != "agent":
            raise ValueError("appraisal application must target an agent scope")
        if self.status is ApplicationStatus.COMMITTED and self.commit_ref is None:
            raise ValueError("committed application requires commit ref")
        if self.status is not ApplicationStatus.COMMITTED and self.commit_ref is not None:
            raise ValueError("uncommitted application cannot claim commit")


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

    def __post_init__(self) -> None:
        if self.operation not in ("delta", "proposed_value"):
            raise ValueError("invalid projection operation")
        try:
            domain = StateDomain(self.target_domain)
        except ValueError as error:
            raise ValueError("invalid projection target domain") from error
        if self.target_scope is not None and state_domain_for_scope(self.target_scope) != domain:
            raise ValueError("projection target domain conflicts with target scope")


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
    admission_mode: str = "legacy_independent"

    def __post_init__(self) -> None:
        if self.admission_mode not in ("legacy_independent", "required_joint"):
            raise ValueError("invalid materialized effect group admission mode")
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
