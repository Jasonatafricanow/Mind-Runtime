"""Configuration-owned event and bounded-history affect effect mapping."""

from dataclasses import dataclass, field

from mind_runtime.contracts import (
    AssessmentContribution,
    HistoricalContextBundle,
    SemanticRoutingResult,
)
from mind_runtime.contracts.common import require_non_empty
from mind_runtime.dynamics.engine import Impulse


def _require_number(value: float, field_name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field_name} must be numeric")


@dataclass(frozen=True, slots=True)
class EventEffectRule:
    """One configuration-owned event-to-dimension mapping; never Persona-specific.

    Per ``docs/C10_LONGITUDINAL_TARGET_ONTOLOGY_CONTRACT.md`` BW-ONTO-6,
    the upstream rule is the authoritative source of the longitudinal target.
    If ``longitudinal_target_dimension`` is set, the EffectMapper emits a
    longitudinal ``Impulse`` targeting that dimension alongside the immediate
    affect ``Impulse``. The writer does NOT transform dimension strings;
    the mapping is configuration-owned here.
    """

    event_kind: str
    dimension: str
    base_amount: float
    history_amount_per_match: float = 0.0
    history_amount_cap: float = 0.0
    minimum_history_confidence: float = 0.5
    # Longitudinal target configuration (ADR-0018-R2 LONG-3, LONG-4).
    # Pairwise invariant: both absent OR both present.
    # When both are present, EffectMapper emits an Impulse targeting
    # longitudinal_target_dimension with verbatim amount = longitudinal_proposed_value
    # (no scaling by confidence or salience).
    longitudinal_target_dimension: str | None = None
    longitudinal_proposed_value: float | None = None

    def __post_init__(self) -> None:
        require_non_empty(self.event_kind, "event_kind")
        require_non_empty(self.dimension, "dimension")
        _require_number(self.base_amount, "base_amount")
        _require_number(self.history_amount_per_match, "history_amount_per_match")
        _require_number(self.history_amount_cap, "history_amount_cap")
        if self.history_amount_per_match < 0:
            raise ValueError("history_amount_per_match must be non-negative")
        if self.history_amount_cap < 0:
            raise ValueError("history_amount_cap must be non-negative")
        if (
            isinstance(self.minimum_history_confidence, bool)
            or not 0 <= self.minimum_history_confidence <= 1
        ):
            raise ValueError("minimum_history_confidence must be in [0, 1]")
        # ADR-0018-R2 LONG-3 pairwise invariant:
        # Both absent OR both present. Partial pair raises ValueError.
        has_dim = self.longitudinal_target_dimension is not None
        has_val = self.longitudinal_proposed_value is not None
        if has_dim != has_val:
            raise ValueError(
                "longitudinal_target_dimension and longitudinal_proposed_value must be "
                "pairwise (both present or both absent)"
            )
        if self.longitudinal_target_dimension is not None:
            require_non_empty(self.longitudinal_target_dimension, "longitudinal_target_dimension")
        if self.longitudinal_proposed_value is not None:
            _require_number(self.longitudinal_proposed_value, "longitudinal_proposed_value")
            if not 0.0 <= self.longitudinal_proposed_value <= 1.0:
                raise ValueError("longitudinal_proposed_value must be in [0, 1]")


@dataclass(frozen=True, slots=True)
class MappedEffects:
    """Pure mapper output consumed once by DynamicsEngine.

    salience_by_source and evidence_refs_by_source carry the per-impulse
    authority values derived from the originating
    ``SemanticEventCandidate`` / ``SemanticAppraisal``. They are NOT
    configuration — per ADR-0016, salience is the Appraisal authority; per
    R3-H6, evidence_refs is the runtime provenance authority. Keys are
    impulse ``source_ref`` strings (``"event:<id>"``, ``"longitudinal:<id>"``,
    ``"history:<id>"``). Missing keys mean "unknown / unavailable" — NOT
    a default zero.
    """

    impulses: tuple[Impulse, ...]
    audit_contributions: tuple[AssessmentContribution, ...]
    source_confidences: tuple[tuple[str, float], ...]
    salience_by_source: dict[str, float | None] = field(default_factory=dict)
    evidence_refs_by_source: dict[str, tuple[str, ...]] = field(
        default_factory=dict
    )
    abstention_reasons: tuple[str, ...] = ()


class EffectMapper:
    """Map one accepted candidate plus bounded history into explicit impulses."""

    def __init__(self, *, rules: tuple[EventEffectRule, ...]) -> None:
        by_kind: dict[str, EventEffectRule] = {}
        for rule in rules:
            if rule.event_kind in by_kind:
                raise ValueError("event effect rule kinds must be unique")
            by_kind[rule.event_kind] = rule
        self._rules = by_kind

    def map(
        self,
        *,
        routing: SemanticRoutingResult,
        history: HistoricalContextBundle | None,
    ) -> MappedEffects:
        if history is not None and history.scope != routing.route.scope:
            raise ValueError("history scope must match semantic route scope")
        if not routing.candidates:
            return MappedEffects((), (), (), routing.abstention_reasons)

        candidate = routing.candidates[0]
        rule = self._rules.get(candidate.kind)
        if routing.abstention_reasons:
            reason = routing.abstention_reasons[0]
            return MappedEffects(
                impulses=(),
                audit_contributions=(
                    AssessmentContribution(
                        dimension=rule.dimension if rule is not None else "semantic.event",
                        source_kind="event",
                        source_ref=candidate.candidate_id,
                        amount=0.0,
                        confidence=candidate.confidence,
                        applied=False,
                        reason_code=reason,
                    ),
                ),
                source_confidences=(),
                abstention_reasons=routing.abstention_reasons,
            )
        if rule is None:
            reason = "unknown_event_kind"
            return MappedEffects(
                impulses=(),
                audit_contributions=(
                    AssessmentContribution(
                        dimension="semantic.event",
                        source_kind="event",
                        source_ref=candidate.candidate_id,
                        amount=0.0,
                        confidence=candidate.confidence,
                        applied=False,
                        reason_code=reason,
                    ),
                ),
                source_confidences=(),
                abstention_reasons=(reason,),
            )

        event_source = f"event:{candidate.candidate_id}"
        # Per C10-SALIENCE-IMPL-R2, salience authority is the
        # SemanticAppraisal carried in the routing result's
        # `appraisals_by_candidate_id` map (NOT embedded in the
        # candidate). The rule is NOT a salience source.
        appraisal = routing.appraisals_by_candidate_id.get(candidate.candidate_id)
        upstream_salience: float | None = (
            appraisal.salience if appraisal is not None else None
        )
        upstream_evidence_refs = candidate.evidence_refs

        impulses: list[Impulse] = [
            Impulse(
                dimension=rule.dimension,
                amount=rule.base_amount * candidate.confidence,
                source_ref=event_source,
            )
        ]
        confidences: list[tuple[str, float]] = [(event_source, candidate.confidence)]
        salience_by_source: dict[str, float | None] = {
            event_source: upstream_salience
        }
        evidence_refs_by_source: dict[str, tuple[str, ...]] = {
            event_source: upstream_evidence_refs
        }

        # Per ADR-0018-R2 LONG-4:
        # When both longitudinal_target_dimension and longitudinal_proposed_value
        # are present, emit an additional Impulse targeting that dimension with
        # verbatim amount = rule.longitudinal_proposed_value (no confidence scaling).
        if rule.longitudinal_target_dimension is not None and rule.longitudinal_proposed_value is not None:
            longitudinal_source = f"longitudinal:{candidate.candidate_id}"
            impulses.append(
                Impulse(
                    dimension=rule.longitudinal_target_dimension,
                    amount=rule.longitudinal_proposed_value,
                    source_ref=longitudinal_source,
                )
            )
            confidences.append((longitudinal_source, candidate.confidence))
            # Per C10-BW-UPSTREAM-R2 §A / ADR-0018-R2 LONG-6: longitudinal
            # contribution inherits appraisal salience from the originating
            # SemanticEventCandidate / SemanticAppraisal.
            salience_by_source[longitudinal_source] = upstream_salience
            evidence_refs_by_source[longitudinal_source] = upstream_evidence_refs

        audit: list[AssessmentContribution] = []
        abstentions: list[str] = []

        seen_summaries: set[str] = set()
        for summary in history.pattern_summaries if history is not None else ():
            if summary.summary_id in seen_summaries:
                continue
            seen_summaries.add(summary.summary_id)
            if summary.confidence < rule.minimum_history_confidence:
                audit.append(
                    AssessmentContribution(
                        dimension=rule.dimension,
                        source_kind="history",
                        source_ref=summary.summary_id,
                        amount=0.0,
                        confidence=summary.confidence,
                        applied=False,
                        reason_code="low_history_confidence",
                    )
                )
                abstentions.append("low_history_confidence")
                continue
            amount = min(
                rule.history_amount_cap,
                rule.history_amount_per_match * summary.match_count * summary.confidence,
            )
            if amount <= 0:
                continue
            history_source = f"history:{summary.summary_id}"
            impulses.append(
                Impulse(
                    dimension=rule.dimension,
                    amount=amount,
                    source_ref=history_source,
                )
            )
            confidences.append((history_source, summary.confidence))
            # Per C10-BW-UPSTREAM-R2 §P3: history-pattern evidence_refs come
            # from the history bundle, not the rule. The summary's matched_refs
            # are the per-turn evidence lineage.
            history_evidence = tuple(summary.matched_refs)
            salience_by_source[history_source] = upstream_salience
            evidence_refs_by_source[history_source] = history_evidence

        return MappedEffects(
            impulses=tuple(impulses),
            audit_contributions=tuple(audit),
            source_confidences=tuple(confidences),
            salience_by_source=salience_by_source,
            evidence_refs_by_source=evidence_refs_by_source,
            abstention_reasons=tuple(dict.fromkeys(abstentions)),
        )
