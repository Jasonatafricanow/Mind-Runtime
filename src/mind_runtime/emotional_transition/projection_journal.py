"""Runtime-owned derived journal. No FACT/Memory admission or state writes."""

import json
import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING

from mind_runtime.contracts import AffectiveDimensionProfile, HistoricalContextBundle

if TYPE_CHECKING:
    from mind_runtime.emotional_transition.effects import AppraisalProjector

from mind_runtime.contracts import Scope, ScopeDomain, SemanticAppraisal, SemanticEventCandidate
from mind_runtime.contracts.late_projection import (
    AcceptedAppraisal,
    AppraisalProjectionResult,
    ProjectionEffect,
    ProjectionStatus,
    canonical_json,
    digest,
)


def decode_acceptance(payload: str) -> AcceptedAppraisal:
    data = json.loads(payload)
    if data.get("projection_scope") is not None:
        data["projection_scope"]["domain"] = ScopeDomain(data["projection_scope"]["domain"])
        data["projection_scope"] = Scope(**data["projection_scope"])
    for key, cls in (("appraisal", SemanticAppraisal), ("candidate", SemanticEventCandidate)):
        item = data[key]
        item["scope"]["domain"] = ScopeDomain(item["scope"]["domain"])
        item["scope"] = Scope(**item["scope"])
        for field in ("meanings", "evidence_refs", "attributes"):
            if field in item:
                item[field] = tuple(tuple(v) if isinstance(v, list) else v for v in item[field])
        data[key] = cls(**item)
    for key in ("trusted_evidence_refs", "route_abstention_reasons", "reason_codes"):
        data[key] = tuple(data[key])
    record = AcceptedAppraisal(**data)
    if not record.valid_lineage():
        raise ValueError("corrupt acceptance lineage")
    return record


def decode_projection(payload: str) -> AppraisalProjectionResult:
    data = json.loads(payload)
    data.setdefault("admission_mode", "legacy_independent")
    data["status"] = ProjectionStatus(data["status"])
    for item in data["effects"]:
        if item.get("target_scope") is not None:
            item["target_scope"]["domain"] = ScopeDomain(item["target_scope"]["domain"])
            item["target_scope"] = Scope(**item["target_scope"])
    data["effects"] = tuple(ProjectionEffect(**item) for item in data["effects"])
    for key in ("reason_codes", "provenance"):
        data[key] = tuple(data[key])
    return AppraisalProjectionResult(**data)


class ProjectionJournal:
    def __init__(
        self, path: str | Path = ":memory:", *, connection: sqlite3.Connection | None = None
    ) -> None:
        self._owns_connection = connection is None
        self.connection = connection or sqlite3.connect(str(path))
        self.connection.executescript("""
            CREATE TABLE IF NOT EXISTS appraisal_evaluations (
                acceptance_id TEXT PRIMARY KEY, interaction_id TEXT NOT NULL,
                candidate_id TEXT NOT NULL, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS appraisal_projections (
                projection_id TEXT PRIMARY KEY, dependency_digest TEXT UNIQUE NOT NULL,
                acceptance_id TEXT NOT NULL, content_digest TEXT NOT NULL, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS appraisal_supersessions (
                old_acceptance_id TEXT PRIMARY KEY, new_acceptance_id TEXT UNIQUE NOT NULL);
        """)

    def close(self) -> None:
        if self._owns_connection:
            self.connection.close()

    def _insert_immutable(
        self, table: str, key_column: str, key: str, columns: str, values: tuple[str, ...]
    ) -> None:
        row = self.connection.execute(
            f"SELECT payload FROM {table} WHERE {key_column}=?", (key,)
        ).fetchone()
        if row is not None:
            if row[0] != values[-1]:
                raise ValueError("derived identity payload conflict")
            return
        self.connection.execute(
            f"INSERT INTO {table} ({key_column},{columns}) VALUES "
            f"({','.join('?' for _ in range(len(values) + 1))})",
            (key, *values),
        )

    def get_acceptance(self, acceptance_id: str) -> AcceptedAppraisal | None:
        row = self.connection.execute(
            "SELECT payload FROM appraisal_evaluations WHERE acceptance_id=?", (acceptance_id,)
        ).fetchone()
        if row is None:
            return None
        record = decode_acceptance(row[0])
        if record.acceptance_id != acceptance_id:
            raise ValueError("corrupt acceptance identity")
        return record

    def accepted_for_interaction(self, interaction_id: str) -> tuple[AcceptedAppraisal, ...]:
        rows = self.connection.execute(
            "SELECT acceptance_id FROM appraisal_evaluations WHERE interaction_id=? "
            "ORDER BY candidate_id, acceptance_id",
            (interaction_id,),
        ).fetchall()
        records = tuple(self.get_acceptance(row[0]) for row in rows)
        current = tuple(
            record for record in records
            if record is not None and record.status == "ACCEPTED"
            and self._successor(record.acceptance_id) is None
        )
        if len({record.candidate.candidate_id for record in current}) != len(current):
            raise ValueError("ambiguous accepted appraisal replay")
        return current

    def replay_projection(
        self, projector: "AppraisalProjector", *, acceptance: AcceptedAppraisal
    ) -> AppraisalProjectionResult:
        """Read the original evaluation for this admission without new dependencies."""
        result = self.projection_for_acceptance(projector, acceptance=acceptance)
        if result is None:
            raise ValueError("accepted appraisal has no persisted projection")
        return result

    def projection_for_acceptance(
        self, projector: "AppraisalProjector", *, acceptance: AcceptedAppraisal
    ) -> AppraisalProjectionResult | None:
        """Return the original result, or None when acceptance awaits evaluation."""
        if self.get_acceptance(acceptance.acceptance_id) != acceptance:
            raise ValueError("accepted appraisal is not journal-resolvable")
        row = self.connection.execute(
            "SELECT projection_id FROM appraisal_projections WHERE acceptance_id=? "
            "ORDER BY rowid LIMIT 1",
            (acceptance.acceptance_id,),
        ).fetchone()
        if row is None:
            return None
        result = self.get_projection(row[0])
        if result is None:
            raise ValueError("persisted projection is missing")
        self._validate_source(result, acceptance, result.dependency_digest)
        projector.validate_materialized_result(result, acceptance=acceptance)
        return result

    def get_projection(self, projection_id: str) -> AppraisalProjectionResult | None:
        row = self.connection.execute(
            "SELECT payload,content_digest,acceptance_id,dependency_digest "
            "FROM appraisal_projections WHERE projection_id=?",
            (projection_id,),
        ).fetchone()
        if not row:
            return None
        result = decode_projection(row[0])
        if (
            digest(json.loads(row[0])) != row[1]
            or result.projection_id != projection_id
            or result.dependency_digest != row[3]
            or row[2] not in result.provenance
        ):
            raise ValueError("corrupt projection identity or payload")
        return result

    def _successor(self, acceptance_id: str) -> str | None:
        row = self.connection.execute(
            "SELECT new_acceptance_id FROM appraisal_supersessions WHERE old_acceptance_id=?",
            (acceptance_id,),
        ).fetchone()
        return str(row[0]) if row else None

    def find_acceptance(
        self, *, candidate: SemanticEventCandidate, interaction_id: str, persona_id: str
    ) -> AcceptedAppraisal | None:
        rows = self.connection.execute(
            "SELECT acceptance_id,payload FROM appraisal_evaluations "
            "WHERE interaction_id=? AND candidate_id=?",
            (interaction_id, candidate.candidate_id),
        ).fetchall()
        current = []
        for identity, payload in rows:
            record = decode_acceptance(payload)
            if record.acceptance_id != identity:
                raise ValueError("corrupt acceptance identity")
            if (
                record.persona_id != persona_id
                or record.candidate.scope != candidate.scope
                or record.candidate.origin_runtime_id != candidate.origin_runtime_id
            ):
                continue
            if record.candidate != candidate:
                raise ValueError("acceptance source payload conflict")
            if self._successor(record.acceptance_id) is None:
                current.append(record)
        if len(current) > 1:
            raise ValueError("ambiguous current acceptance; explicit supersession required")
        return current[0] if current else None

    def _persist_acceptance(self, acceptance: AcceptedAppraisal) -> None:
        self._insert_immutable(
            "appraisal_evaluations",
            "acceptance_id",
            acceptance.acceptance_id,
            "interaction_id,candidate_id,payload",
            (
                acceptance.interaction_id,
                acceptance.candidate.candidate_id,
                canonical_json(acceptance),
            ),
        )

    def supersede(self, *, old_acceptance_id: str, acceptance: AcceptedAppraisal) -> None:
        """Append an explicit replacement; old records remain readable for audit."""
        if not acceptance.valid_lineage():
            raise ValueError("invalid acceptance lineage")
        with self.connection:
            old = self.get_acceptance(old_acceptance_id)
            if old is None:
                raise ValueError("supersession source acceptance is missing")
            if (
                old.candidate != acceptance.candidate
                or old.interaction_id != acceptance.interaction_id
                or old.persona_id != acceptance.persona_id
                or old.projection_scope != acceptance.projection_scope
                or old.trusted_evidence_refs != acceptance.trusted_evidence_refs
            ):
                raise ValueError("supersession source payload mismatch")
            if old_acceptance_id == acceptance.acceptance_id:
                raise ValueError("supersession cycle")
            successor = self._successor(old_acceptance_id)
            if successor is not None:
                if (
                    successor == acceptance.acceptance_id
                    and self.get_acceptance(successor) == acceptance
                ):
                    return
                raise ValueError("superseded acceptance conflict")
            if self._successor(acceptance.acceptance_id) is not None:
                raise ValueError("cannot reactivate superseded acceptance")
            current = self.find_acceptance(
                candidate=old.candidate,
                interaction_id=old.interaction_id,
                persona_id=old.persona_id,
            )
            if current != old:
                raise ValueError("supersession source is not current")
            self._persist_acceptance(acceptance)
            self.connection.execute(
                "INSERT INTO appraisal_supersessions VALUES (?,?)",
                (old_acceptance_id, acceptance.acceptance_id),
            )

    def materialize(
        self,
        projector: "AppraisalProjector",
        *,
        acceptance: AcceptedAppraisal,
        history: HistoricalContextBundle | None,
        persona: tuple[AffectiveDimensionProfile, ...] = (),
    ) -> AppraisalProjectionResult:
        if not acceptance.valid_lineage():
            raise ValueError("invalid acceptance lineage")
        if self._successor(acceptance.acceptance_id) is not None:
            raise ValueError("cannot materialize superseded acceptance")
        current = self.find_acceptance(
            candidate=acceptance.candidate,
            interaction_id=acceptance.interaction_id,
            persona_id=acceptance.persona_id,
        )
        if current is not None and current != acceptance:
            raise ValueError("acceptance conflict requires explicit supersession")
        # Semantic acceptance is durable before projection evaluation. A
        # projection crash leaves an auditable, retryable accepted source.
        with self.connection:
            self._persist_acceptance(acceptance)
        dep = projector.dependency_digest(acceptance=acceptance, history=history, persona=persona)
        existing = self.get_projection("projection-" + dep)
        if existing is not None:
            if self.get_acceptance(acceptance.acceptance_id) != acceptance:
                raise ValueError("projection has missing acceptance")
            self._validate_source(existing, acceptance, dep)
            projector.validate_materialized_result(
                existing, acceptance=acceptance, same_recipe_version=True
            )
            return existing
        result = projector.project(acceptance=acceptance, history=history, persona=persona)
        self._validate_source(result, acceptance, dep)
        projector.validate_materialized_result(
            result, acceptance=acceptance, same_recipe_version=True
        )
        with self.connection:
            self._insert_immutable(
                "appraisal_projections",
                "projection_id",
                result.projection_id,
                "dependency_digest,acceptance_id,content_digest,payload",
                (dep, acceptance.acceptance_id, digest(result), canonical_json(result)),
            )
        return result

    @staticmethod
    def _validate_source(
        result: AppraisalProjectionResult, acceptance: AcceptedAppraisal, dependency: str
    ) -> None:
        if (
            result.dependency_digest != dependency
            or result.source_candidate_ref != acceptance.candidate.candidate_id
            or result.source_appraisal_ref != acceptance.appraisal.appraisal_id
            or acceptance.acceptance_id not in result.provenance
        ):
            raise ValueError("projection source or dependency identity mismatch")
