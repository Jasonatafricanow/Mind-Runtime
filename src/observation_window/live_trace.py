"""OW-3 live trace adapter: read-only observer for the J8-E3 transition result.

This module is the read-only seam between MR's live `transition_result`
and OW-3's immutable causal-chain snapshot. It does NOT modify MR's
runtime; it does NOT participate in turn decisions; missing OW
consumers change nothing.

Architecture:

    MR production turn
          ↓
    EngineEmotionalTransitionPort.transition()  (J8-E3 Gate 8)
          ↓ returns AppraisalAffectTransitionResult | EmotionalTransitionResult
    OWLiveTraceSource.observe(turn_index, transition_result, rules_by_id)
          ↓ pure read + immutable copy
    ObservedTurnSnapshot
          ↓
    Observation Window UI

The caller wires `OWLiveTraceSource` at composition root. OW-3
deliberately does NOT import any MR orchestrator — the adapter takes
the result object (already extracted) plus an optional rule→dimension
lookup that the caller builds from `orchestrator._appraisal_rules`.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable

from mind_runtime.contracts.emotional_transition import (
    AssessmentContribution,
    AssessmentTrace,
    EmotionalTransitionResult,
)

from observation_window.causal_contracts import (
    AppraisalCompositionStatus,
    AppraisalId,
    InteractionId,
    ObservedAppraisal,
    ObservedAppraisalDecision,
    ObservedAppraisalSourceOutput,
    ObservedAssessmentTrace,
    ObservedContribution,
    ObservedTurnSnapshot,
    RuleId,
    SourceRef,
    TraceId,
)


def _now_utc() -> datetime:
    return datetime.now(tz=timezone.utc)


def _is_appraisal_result_subtype(result: object) -> bool:
    """True if result is the J8-E3 Gate 8 subtype with appraisal fields.

    Avoids a hard isinstance against the production class name to keep
    OW-3 decoupled from MR module layout. The discriminator is the
    presence of the two J8-E3 fields.
    """
    return hasattr(result, "appraisal_result") and hasattr(
        result, "appraisal_affect_decisions"
    )


def _classify_composition(
    result: EmotionalTransitionResult,
    *,
    rules_provided: bool,
) -> AppraisalCompositionStatus:
    """Decide OFF / ON / UNKNOWN from the live result + caller hints.

    - If the result is NOT the J8-E3 subtype → OFF (stub or default config).
    - If the subtype exists but `appraisal_result is None` → OFF
      (the orchestrator's `NullAppraisalResultSource` was used).
    - If the subtype exists and `appraisal_result is not None` → ON.
    """
    if not _is_appraisal_result_subtype(result):
        return AppraisalCompositionStatus.OFF
    appraisal_result = getattr(result, "appraisal_result", None)
    decisions = getattr(result, "appraisal_affect_decisions", ())
    if appraisal_result is None:
        return AppraisalCompositionStatus.OFF
    if not rules_provided and not decisions:
        # ON but no rules fired; still ON.
        return AppraisalCompositionStatus.ON
    return AppraisalCompositionStatus.ON


def _decision_source_ref(
    appraisal_id: str, rule_id: str, state_ref: str
) -> SourceRef:
    """The canonical source_ref token used in J8-E3 contributions."""
    return SourceRef(f"appraisal:{appraisal_id}:{rule_id}:state:{state_ref}")


def _observed_decision(
    decision: Any,
    index: int,
    *,
    rule_dimension_lookup: dict[RuleId, str] | None,
) -> ObservedAppraisalDecision:
    """Map a J8-E3 decision into the OW-3 immutable form.

    The production ``AppraisalAffectDecision`` at J8-E3 Gate 8 carries:
    appraisal_id, rule_id, dimension, direction, base_amount,
    impulse_amount, provider_confidence, applicability,
    matched_state_refs, evidence_refs, applied, reason_code.
    The `abstention_reason` OW-3 field is populated from `reason_code`
    when `applied=False` — the runtime's reason vocabulary is
    preserved verbatim.
    """
    # The decision itself carries the dimension it targets.
    effective_dimension = decision.dimension

    state_ref = decision.matched_state_refs[0] if decision.matched_state_refs else ""
    src_ref = (
        _decision_source_ref(decision.appraisal_id, decision.rule_id, state_ref)
        if state_ref
        else SourceRef(f"appraisal:{decision.appraisal_id}:{decision.rule_id}")
    )

    return ObservedAppraisalDecision(
        decision_index=index,
        appraisal_id=AppraisalId(decision.appraisal_id),
        rule_id=RuleId(decision.rule_id),
        matched_state_refs=decision.matched_state_refs,
        evidence_refs=decision.evidence_refs,
        provider_confidence=decision.provider_confidence,
        applied=decision.applied,
        reason_code=decision.reason_code,
        abstention_reason=decision.reason_code if not decision.applied else None,
        effective_dimension=effective_dimension,
        source_ref=src_ref,
    )


def _observed_appraisal(appraisal: Any) -> ObservedAppraisal:
    """Map a ResolvedAppraisal to OW-3 immutable form.

    The production ResolvedAppraisal at J8-E3 Gate 8 carries:
    appraisal_id, source_kind, source_candidate_id, polarity, status,
    meanings, relevance, applicability, causal_status, confidence,
    evidence_refs, audit_refs, authority_ref, state_decisions,
    abstain_code, reject_code. OW-3 only surfaces the ones useful for
    provenance / decision inspection.
    """
    return ObservedAppraisal(
        appraisal_id=AppraisalId(appraisal.appraisal_id),
        polarity=str(appraisal.polarity.value) if appraisal.polarity is not None else "unknown",
        authority=str(appraisal.source_kind),
        causal_status=str(appraisal.causal_status.value) if appraisal.causal_status is not None else "unknown",
        provider_confidence=appraisal.confidence,
        primary_evidence_refs=appraisal.evidence_refs,
        secondary_evidence_refs=appraisal.audit_refs,
    )


def _observed_appraisal_source(
    result: Any | None,
) -> ObservedAppraisalSourceOutput | None:
    """Map an AppraisalResult to OW-3 immutable form, or None if absent.

    The production ``AppraisalResult`` at J8-E3 Gate 8 carries a
    ``resolved: ResolvedAppraisal`` and ``route_ref: str``. The
    abstention / reject / candidate / rejected fields are surfaced
    here for backward compatibility with the OW-3 spec's
    "Decision/Abstention Inspector" view, but populated from the
    ``resolved`` sub-record (status, abstain_code, reject_code) since
    those are the actual runtime fields.
    """
    if result is None:
        return None
    resolved = result.resolved
    abstention: str | None = None
    if resolved.abstain_code is not None:
        abstention = str(resolved.abstain_code.value)
    reject: str | None = None
    if resolved.reject_code is not None:
        reject = str(resolved.reject_code.value)
    # candidate_count / rejected_count are derived from evidence_refs
    # presence — the production AppraisalResult does not split into
    # candidates/rejected tuples; the surface only needs a count.
    candidate_count = len(resolved.evidence_refs)
    rejected_count = len(resolved.audit_refs)
    return ObservedAppraisalSourceOutput(
        abstention_reason=abstention,
        reject_reason=reject,
        candidate_count=candidate_count,
        rejected_count=rejected_count,
        provenance_ref=result.route_ref,
        created_at=None,  # production AppraisalResult does not carry created_at
    )


def _observed_contribution(
    c: AssessmentContribution,
) -> ObservedContribution:
    return ObservedContribution(
        dimension=c.dimension,
        source_kind=c.source_kind,
        source_ref=SourceRef(c.source_ref),
        amount=c.amount,
        confidence=c.confidence,
        applied=c.applied,
        reason_code=c.reason_code,
    )


def _observed_trace(trace: AssessmentTrace) -> ObservedAssessmentTrace:
    return ObservedAssessmentTrace(
        trace_id=TraceId(trace.trace_id),
        scope=trace.scope,
        origin_runtime_id=trace.origin_runtime_id,
        context_ref=trace.context_ref,
        persona_id=trace.persona_id,
        persona_version=trace.persona_version,
        state_before=dict(trace.state_before),
        state_after=dict(trace.state_after),
        contributions=tuple(_observed_contribution(c) for c in trace.contributions),
        evidence_refs=trace.evidence_refs,
        history_refs=trace.history_refs,
        abstention_reasons=trace.abstention_reasons,
        created_at=trace.created_at,
    )


class OWLiveTraceSource:
    """Read-only observer that converts J8-E3 transition results into OW-3 snapshots.

    The source holds no state between calls — every ``observe()`` is a
    pure read of the input objects. The caller is responsible for
    passing in the live result (from `orchestrator.transition_result`).
    """

    def __init__(self) -> None:
        pass  # no state

    def observe(
        self,
        *,
        interaction_id: str,
        result: EmotionalTransitionResult,
        rules_by_id: dict[RuleId, str] | None = None,
        transitions: Iterable[str] = (),
    ) -> ObservedTurnSnapshot:
        """Build an immutable OW-3 snapshot of one turn's causal chain.

        Parameters
        ----------
        interaction_id:
            The turn's interaction ID (from the orchestrator's `_turn`).
        result:
            The live `EmotionalTransitionResult` (or its J8-E3 subtype)
            returned by `EngineEmotionalTransitionPort.transition()`.
        rules_by_id:
            Optional mapping from `RuleId` → dimension string. The caller
            can build this from the orchestrator's
            ``self._appraisal_rules`` at composition root. If absent,
            decisions' `effective_dimension` is `None` and the rule_id
            is surfaced verbatim.
        transitions:
            Optional iterable of state_ids that were committed during
            this turn (e.g. from the orchestrator's recent transitions).
            This is **only** an informational cross-link; OW-3 does NOT
            infer causation from it.
        """
        composition = _classify_composition(result, rules_provided=bool(rules_by_id))

        # The assessment trace is always present on the base result.
        trace = result.assessment_trace
        snapshot_trace = _observed_trace(trace)

        # J8-E3 subtype fields.
        appraisal_result_obj: Any | None = None
        decisions_tuple: tuple[Any, ...] = ()
        if _is_appraisal_result_subtype(result):
            appraisal_result_obj = getattr(result, "appraisal_result")
            decisions_tuple = tuple(getattr(result, "appraisal_affect_decisions"))

        # Build the OW-3 decision list.
        observed_decisions = tuple(
            _observed_decision(
                d, idx, rule_dimension_lookup=rules_by_id
            )
            for idx, d in enumerate(decisions_tuple)
        )

        # ResolvedAppraisals: derive from the AppraisalResult's resolved
        # sub-record. The production AppraisalResult carries exactly one
        # resolved appraisal; the OW-3 surface still exposes a tuple to
        # keep the read-model symmetric.
        observed_appraisals: tuple[ObservedAppraisal, ...] = ()
        if appraisal_result_obj is not None:
            resolved = appraisal_result_obj.resolved
            observed_appraisals = (
                ObservedAppraisal(
                    appraisal_id=AppraisalId(resolved.appraisal_id),
                    polarity=str(resolved.polarity.value) if resolved.polarity is not None else "unknown",
                    authority=str(resolved.source_kind),
                    causal_status=str(resolved.causal_status.value) if resolved.causal_status is not None else "unknown",
                    provider_confidence=resolved.confidence,
                    primary_evidence_refs=resolved.evidence_refs,
                    secondary_evidence_refs=resolved.audit_refs,
                ),
            )

        observed_source = _observed_appraisal_source(appraisal_result_obj)

        # Scope + origin: take from the trace.
        scope = snapshot_trace.scope
        origin = snapshot_trace.origin_runtime_id

        return ObservedTurnSnapshot(
            interaction_id=InteractionId(interaction_id),
            scope=scope,
            origin_runtime_id=origin,
            composition=composition,
            appraisal_source=observed_source,
            appraisals=observed_appraisals,
            decisions=observed_decisions,
            assessment_trace=snapshot_trace,
            trace_created_at=snapshot_trace.created_at,
            snapshot_at=_now_utc(),
            transitions=tuple(transitions),
        )