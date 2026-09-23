"""Compressed EmotionalTransitionPort backed by the D7 DynamicsEngine.

C10-B-W wiring: this port also invokes the HomeostasisGate at Seam B
(per C10-B1-R3 §13.2) and produces HomeostasisDecision records in the
AssessmentTrace. Slow-state-eligible decisions (SLOW_ACCEPT) are
returned to the orchestrator for consumption by the SlowPlasticityWriter.

Seam B (R3-frozen): contribution-aware, inside the single combined
Dynamics call. The Gate is invoked once per contribution per turn.
"""

from dataclasses import dataclass
from datetime import timedelta
from typing import Any, cast

from mind_runtime.contracts import (
    AssessmentContribution,
    AssessmentTrace,
    EmotionalTransitionInput,
    EmotionalTransitionResult,
    ProjectedMindState,
    RuntimeState,
    Scope,
    ScopeDomain,
    SemanticAppraisalContext,
    SemanticRoutingResult,
    SyncFields,
)
from mind_runtime.contracts.state import state_domain_for_scope
from mind_runtime.dynamics.engine import Contribution, DynamicsEngine
from mind_runtime.emotional_transition.appraisal import SemanticAppraisalProducer
from mind_runtime.emotional_transition.effects import (
    AppraisalProjector,
    EventEffectRule,
    MappedEffects,
    mapping_from_projection,
)
from mind_runtime.emotional_transition.projection_journal import ProjectionJournal
from mind_runtime.emotional_transition.semantic import SemanticRouter
from mind_runtime.state.definitions import StateDefinitionRegistry
from mind_runtime.homeostasis.contracts import (
    CandidateStateDelta,
    HomeostasisDecision,
    HomeostasisDisposition,
    HomeostasisGate,
)
from mind_runtime.contracts.telemetry import TelemetrySinkProtocol, TelemetryStage


def _projection_scope_for(
    engine: DynamicsEngine, *, turn_scope: Scope, explicit: Scope | None
) -> Scope:
    """Resolve and validate the Persona-owned affect projection scope."""

    if explicit is not None:
        resolved = explicit
    else:
        dimensions = engine.persona.dimensions
        if not dimensions:
            raise ValueError("engine projected no affect dimensions")
        prefixes = {dimension.dimension.partition(".")[0] for dimension in dimensions}
        if prefixes == {"agent"}:
            resolved = Scope(
                domain=ScopeDomain.AGENT,
                agent_id=engine.persona.persona_id,
                persona_id=engine.persona.persona_id,
            )
        elif prefixes == {"user"}:
            resolved = turn_scope
        else:
            raise ValueError(
                f"persona dimensions must be uniformly agent.* or user.* (got {sorted(prefixes)})"
            )
    domain = state_domain_for_scope(resolved)
    for dimension in engine.persona.dimensions:
        prefix = dimension.dimension.partition(".")[0]
        if prefix != domain.value:
            raise ValueError(
                f"persona dimension {dimension.dimension!r} conflicts with "
                f"projection scope domain {domain.value}"
            )
    return resolved


@dataclass(frozen=True, slots=True)
class EmotionalTransitionOutcome:
    """Result of a single emotional transition including slow-state decisions.

    Wraps the original EmotionalTransitionResult with the HomeostasisDecision
    records produced by the HomeostasisGate. The orchestrator passes the
    slow_decisions to the SlowPlasticityWriter.
    """

    transition_result: EmotionalTransitionResult
    slow_decisions: tuple[HomeostasisDecision, ...]


class EngineEmotionalTransitionPort:
    """Apply the D7 algorithms once and expose their complete assessment trace.

    C10-B-W: the HomeostasisGate is invoked at Seam B (C10-B1-R3 §13.2)
    for every ordinary / event-sourced contribution. Recovery and coupling
    contributions are passed through per R3-F4 (coupling is derived, not
    gated) and §11.1 (recovery is not a gateable candidate).
    """

    def __init__(
        self,
        *,
        engine: DynamicsEngine,
        runtime_id: str = "runtime-1",
        effect_rules: tuple[EventEffectRule, ...] = (),
        semantic_router: SemanticRouter | None = None,
        homeostasis_gate: HomeostasisGate | None = None,
        appraisal_producer: SemanticAppraisalProducer | None = None,
        projection_journal: ProjectionJournal | None = None,
        state_definitions: StateDefinitionRegistry | None = None,
        telemetry_sink: TelemetrySinkProtocol | None = None,
    ) -> None:
        self._engine = engine
        self._runtime_id = runtime_id
        self._semantic_router = semantic_router or SemanticRouter()
        self._homeostasis_gate = homeostasis_gate
        self._appraisal_producer = appraisal_producer
        self._projection_journal = projection_journal
        self._projector = AppraisalProjector(
            rules=effect_rules,
            persona_profile=engine.persona,
            definitions=state_definitions,
        )
        self._effects = self._projector
        if appraisal_producer is not None and (
            projection_journal is None or state_definitions is None
        ):
            raise ValueError("accepted appraisal projection requires durable journal and definitions")
        self._telemetry_sink = telemetry_sink

    def transition(self, transition_input: EmotionalTransitionInput) -> EmotionalTransitionResult:
        return self.transition_with_gate(transition_input).transition_result

    @property
    def projection_journal(self) -> ProjectionJournal | None:
        return self._projection_journal

    def transition_with_gate(
        self, transition_input: EmotionalTransitionInput
    ) -> EmotionalTransitionOutcome:
        """Run the transition and (optionally) invoke the HomeostasisGate.

        If ``homeostasis_gate`` was injected at construction, the gate is
        invoked once per ordinary / event-sourced contribution per turn
        (R3 Seam B, R3-F5). Recovery and coupling contributions are NOT
        re-routed through the gate (R3 §11.1, R3-F4). The gate returns
        HomeostasisDecision records; the slow-state-eligible decisions
        (SLOW_ACCEPT) are returned to the caller via the outcome.
        """
        persona = self._engine.persona
        if (
            transition_input.persona_id != persona.persona_id
            or transition_input.persona_version != persona.version
            or transition_input.persona != persona.dimensions
        ):
            raise ValueError("transition persona metadata must match engine persona metadata")
        cached_acceptances = (
            self._projection_journal.accepted_for_interaction(transition_input.interaction_id)
            if self._projection_journal is not None else ()
        )
        if cached_acceptances:
            if any(
                record.candidate.scope != transition_input.scope
                or record.candidate.origin_runtime_id != self._runtime_id
                or record.persona_id != persona.persona_id
                or record.projection_scope != transition_input.projection_scope
                for record in cached_acceptances
            ):
                raise ValueError("cached appraisal replay lineage mismatch")
            cached_candidates = tuple(record.candidate for record in cached_acceptances)
            if transition_input.semantic_candidates and (
                transition_input.semantic_candidates != cached_candidates
            ):
                raise ValueError("cached appraisal candidate conflict")
        else:
            cached_candidates = ()
        try:
            routing = self._semantic_router.route(
                observations=transition_input.observations,
                context=transition_input.context,
                supplied_candidates=cached_candidates or transition_input.semantic_candidates,
                telemetry_sink=self._telemetry_sink,
            )
        except Exception as exc:
            if self._telemetry_sink is not None:
                try:
                    self._telemetry_sink.record(
                        interaction_id=transition_input.interaction_id,
                        stage=TelemetryStage.SEMANTIC_ERROR,
                        status="FAILED",
                        occurred_at=transition_input.clock,
                        payload={"error": str(exc)},
                        source_refs=(),
                    )
                except Exception:
                    pass
            raise

        if self._telemetry_sink is not None:
            try:
                if routing.candidates:
                    for candidate in routing.candidates:
                        self._telemetry_sink.record(
                            interaction_id=transition_input.interaction_id,
                            stage=TelemetryStage.SEMANTIC_CANDIDATE,
                            status="PROPOSED",
                            occurred_at=transition_input.clock,
                            payload={
                                "candidate_id": candidate.candidate_id,
                                "event_kind": getattr(candidate, "event_kind", getattr(candidate, "kind", None)),
                                "confidence": candidate.confidence,
                                "summary": getattr(candidate, "summary", getattr(candidate, "kind", None)),
                                "evidence_refs": list(candidate.evidence_refs),
                            },
                            source_refs=candidate.evidence_refs,
                        )
                elif routing.abstention_reasons:
                    self._telemetry_sink.record(
                        interaction_id=transition_input.interaction_id,
                        stage=TelemetryStage.SEMANTIC_ABSTAIN,
                        status="ABSTAINED",
                        occurred_at=transition_input.clock,
                        payload={
                            "abstention_reasons": list(routing.abstention_reasons),
                            "route": getattr(routing.route, "value", str(routing.route)),
                        },
                        source_refs=(),
                    )
            except Exception:
                pass

        # ADR-0019-R4 APPRAISAL-2: Producer sits after SemanticRouter.route()
        # and before EffectMapper.map(). Populate appraisals_by_candidate_id.
        projection_scope = _projection_scope_for(
            self._engine,
            turn_scope=transition_input.scope,
            explicit=transition_input.projection_scope,
        )
        accepted_appraisals = []
        projection_refs = []
        materialized_projections = []
        mapped_parts = []
        cached_by_candidate = {
            record.candidate.candidate_id: record for record in cached_acceptances
        }
        if self._appraisal_producer is not None and routing.candidates:
            appraisals = dict(routing.appraisals_by_candidate_id)
            for candidate in routing.candidates:
                appraisal_ctx = SemanticAppraisalContext(
                    candidate=candidate,
                    situation=transition_input.context,
                    persona=transition_input.persona,
                    history=transition_input.history_context,
                    current_affect=transition_input.current_affect,
                )
                try:
                    acceptance = cached_by_candidate.get(candidate.candidate_id)
                    if acceptance is None:
                        acceptance = self._appraisal_producer.accept(
                            candidate=candidate,
                            context=appraisal_ctx,
                            interaction_id=transition_input.interaction_id,
                            persona_id=transition_input.persona_id,
                            route_abstention_reasons=routing.abstention_reasons,
                            projection_scope=projection_scope,
                        )
                    assembled_appraisal = acceptance.appraisal
                    appraisals[candidate.candidate_id] = assembled_appraisal
                    if acceptance.status == "ACCEPTED":
                        assert self._projection_journal is not None
                        if acceptance.candidate.candidate_id in cached_by_candidate:
                            projection = self._projection_journal.projection_for_acceptance(
                                self._projector, acceptance=acceptance
                            )
                            if projection is None:
                                projection = self._projection_journal.materialize(
                                    self._projector,
                                    acceptance=acceptance,
                                    history=transition_input.history_context,
                                    persona=transition_input.persona,
                                )
                        else:
                            projection = self._projection_journal.materialize(
                                self._projector,
                                acceptance=acceptance,
                                history=transition_input.history_context,
                                persona=transition_input.persona,
                            )
                        accepted_appraisals.append(acceptance)
                        projection_refs.append(projection.projection_id)
                        materialized_projections.append(projection)
                        mapped_parts.append(mapping_from_projection(projection))
                    if self._telemetry_sink is not None:
                        try:
                            self._telemetry_sink.record(
                                interaction_id=transition_input.interaction_id,
                                stage=TelemetryStage.APPRAISAL,
                                status="ACCEPTED",
                                occurred_at=transition_input.clock,
                                payload={
                                    "candidate_id": candidate.candidate_id,
                                    "appraisal_id": getattr(assembled_appraisal, "appraisal_id", None),
                                    "meanings": list(getattr(assembled_appraisal, "meanings", ())),
                                    "valence": getattr(assembled_appraisal, "valence", None),
                                    "salience": getattr(assembled_appraisal, "salience", None),
                                    "confidence": getattr(assembled_appraisal, "confidence", None),
                                    "appraisal_confidence": getattr(assembled_appraisal, "confidence", None),
                                    "relationship_relevance": getattr(assembled_appraisal, "relationship_relevance", None),
                                },
                                source_refs=tuple(getattr(assembled_appraisal, "evidence_refs", ())),
                            )
                        except Exception:
                            pass
                except Exception as app_exc:
                    if self._telemetry_sink is not None:
                        try:
                            self._telemetry_sink.record(
                                interaction_id=transition_input.interaction_id,
                                stage=TelemetryStage.APPRAISAL_ERROR,
                                status="FAILED",
                                occurred_at=transition_input.clock,
                                payload={
                                    "candidate_id": candidate.candidate_id,
                                    "error": str(app_exc),
                                },
                                source_refs=candidate.evidence_refs,
                            )
                        except Exception:
                            pass
                    raise
            routing = SemanticRoutingResult(
                route=routing.route,
                candidates=routing.candidates,
                provider_call_count=routing.provider_call_count,
                abstention_reasons=routing.abstention_reasons,
                appraisals_by_candidate_id=appraisals,
            )
        evidence_refs = tuple(
            dict.fromkeys(
                transition_input.context.evidence_refs
                + tuple(ref for candidate in routing.candidates for ref in candidate.evidence_refs)
            )
        )
        # A producer-owned rejection/error is never a legacy caller. Only a
        # caller with no appraisal producer may use the compatibility mapper.
        legacy_no_appraisal = self._appraisal_producer is None
        if not legacy_no_appraisal:
            mapped = MappedEffects(
                impulses=tuple(i for part in mapped_parts for i in part.impulses),
                audit_contributions=tuple(
                    c for part in mapped_parts for c in part.audit_contributions
                ),
                source_confidences=tuple(
                    c for part in mapped_parts for c in part.source_confidences
                ),
                salience_by_source={
                    k: v for part in mapped_parts for k, v in part.salience_by_source.items()
                },
                evidence_refs_by_source={
                    k: v for part in mapped_parts for k, v in part.evidence_refs_by_source.items()
                },
                abstention_reasons=tuple(
                    dict.fromkeys(r for part in mapped_parts for r in part.abstention_reasons)
                ),
            )
        else:
            # Explicit LEGACY_NO_APPRAISAL compatibility route.
            mapped = self._effects.map(
                routing=routing,
                history=transition_input.history_context,
            )
        if self._telemetry_sink is not None and mapped.impulses:
            try:
                self._telemetry_sink.record(
                    interaction_id=transition_input.interaction_id,
                    stage=TelemetryStage.IMPULSE,
                    status="EXECUTED",
                    occurred_at=transition_input.clock,
                    payload={
                        "impulses": [
                            {
                                "dimension": imp.dimension,
                                "amount": imp.amount,
                                "source_ref": imp.source_ref,
                                "rule_id": getattr(imp, "rule_id", None),
                            }
                            for imp in mapped.impulses
                        ],
                        "rule_ids": [
                            getattr(imp, "rule_id", None)
                            for imp in mapped.impulses
                            if getattr(imp, "rule_id", None) is not None
                        ],
                    },
                    source_refs=(),
                )
            except Exception:
                pass
        result = self._engine.step(
            current={
                state.dimension: float(cast(float, state.value))
                for state in transition_input.current_affect
            },
            elapsed=transition_input.elapsed,
            impulses=mapped.impulses,
        )
        if not result.proposed:
            raise ValueError("engine projected no affect dimensions")
        current_by_dimension = {state.dimension: state for state in transition_input.current_affect}
        states: list[RuntimeState] = []
        for dimension, value in result.proposed:
            before = current_by_dimension.get(dimension)
            version = before.version + 1 if before is not None else 1
            state_id = f"{dimension}:{version}:projected-{transition_input.interaction_id}"
            states.append(
                RuntimeState(
                    state_id=state_id,
                    scope=projection_scope,
                    origin_runtime_id=self._runtime_id,
                    dimension=dimension,
                    value=value,
                    status="active",
                    valid_from=transition_input.clock,
                    valid_until=None,
                    relevant_until=None,
                    last_observed_at=transition_input.clock,
                    evidence_refs=evidence_refs,
                    transition_refs=((before.state_id,) if before is not None else ()),
                    updated_at=transition_input.clock,
                    version=version,
                    sync=SyncFields(
                        projection_scope,
                        self._runtime_id,
                        state_id,
                        version,
                        f"idem-{state_id}",
                    ),
                )
            )
        projection_id = f"projection-{transition_input.interaction_id}"
        projected = ProjectedMindState(
            projection_id=projection_id,
            scope=projection_scope,
            origin_runtime_id=self._runtime_id,
            projected_states=tuple(states),
            sync=SyncFields(
                projection_scope,
                self._runtime_id,
                projection_id,
                1,
                f"idem-{projection_id}",
            ),
            committed=False,
        )
        confidences = dict(mapped.source_confidences)
        contributions: list[AssessmentContribution] = []
        for contribution in result.contributions:
            source_kind = contribution.source.partition(":")[0]
            source_ref = contribution.source
            # Audit trail. Per C10-SALIENCE-IMPL-R2: the audit path
            # MUST NOT fabricate confidence. For impulse contributions,
            # the upstream authority supplies confidence via
            # `source_confidences`; for non-impulse contributions
            # (recovery, coupling, relationship), upstream does NOT
            # supply confidence (R3 §7 frozen: RECOVERY has no confidence
            # column, COUPLING has no confidence column). The current
            # AssessmentContribution.confidence: float schema cannot
            # represent "no upstream authority" — this is a schema gap,
            # not a value to fabricate. This seam fails closed until
            # C10-ASSESSMENT-CONFIDENCE-SCHEMA closes the gap.
            if contribution.source.startswith("impulse:"):
                stripped = contribution.source.removeprefix("impulse:")
                source_kind = stripped.partition(":")[0]
                source_ref = stripped.partition(":")[2]
                upstream_conf = confidences.get(stripped)
                if upstream_conf is None:
                    raise ValueError(
                        f"audit-trail confidence missing for impulse source "
                        f"{stripped!r}; upstream must supply via source_confidences"
                    )
                confidence: float = upstream_conf
                contributions.append(
                    AssessmentContribution(
                        dimension=contribution.dimension,
                        source_kind=source_kind,
                        source_ref=source_ref,
                        amount=contribution.amount,
                        confidence=confidence,
                        applied=True,
                        reason_code=None,
                    )
                )
                continue
            # Non-impulse (recovery / coupling / relationship): the
            # engine's Contribution source is the source_kind directly
            # (e.g., "recovery", "coupling:<dim>", "relationship").
            # Per R3 §7 frozen: these kinds have no upstream confidence
            # column. Per C10-ASSESSMENT-CONFIDENCE-SCHEMA: the audit
            # row's confidence is None — the structural "no upstream
            # authority for this row" signal. This is the per-row honest
            # reflection, NOT a fabricated value.
            source_kind = contribution.source.partition(":")[0]
            if ":" in contribution.source:
                source_ref = contribution.source.partition(":")[2]
            else:
                # Preserve pre-existing convention: when there is no colon
                # (e.g., "recovery"), source_ref = source_kind (the full
                # source string), not empty.
                source_ref = contribution.source
            contributions.append(
                AssessmentContribution(
                    dimension=contribution.dimension,
                    source_kind=source_kind,
                    source_ref=source_ref,
                    amount=contribution.amount,
                    confidence=None,
                    applied=True,
                    reason_code=None,
                )
            )
        contributions.extend(mapped.audit_contributions)
        trace_id = f"assessment-{transition_input.interaction_id}"
        trace = AssessmentTrace(
            trace_id=trace_id,
            scope=transition_input.scope,
            origin_runtime_id=self._runtime_id,
            context_ref=transition_input.context.situation_id,
            persona_id=persona.persona_id,
            persona_version=persona.version,
            state_before=tuple(
                (state.dimension, float(cast(float, state.value)))
                for state in transition_input.current_affect
            ),
            contributions=tuple(contributions),
            state_after=result.proposed,
            evidence_refs=evidence_refs,
            history_refs=self._history_refs(transition_input),
            abstention_reasons=tuple(
                dict.fromkeys(routing.abstention_reasons + mapped.abstention_reasons)
            ),
            route_decision=routing.route,
            created_at=transition_input.clock,
        )
        accepted_events = (
            tuple(acceptance.candidate for acceptance in accepted_appraisals)
            if not legacy_no_appraisal
            else routing.candidates[:1]
            if routing.candidates
            and mapped.impulses
            and not routing.abstention_reasons
            and not mapped.abstention_reasons
            else ()
        )
        # R3 Seam B: invoke HomeostasisGate once per contribution per turn.
        # Recovery and coupling contributions are NOT gate-routed (R3 §11.1, F4).
        # The gate only sees ordinary/event-sourced contributions.
        slow_decisions = self._invoke_homeostasis_gate(
            transition_input=transition_input,
            result=result,
            mapped=mapped,
            projected=projected,
        )
        for projection in materialized_projections:
            if projection.admission_mode != "required_joint":
                continue
            for effect in projection.effects:
                allowed = (
                    ("fast_apply", "slow_accept")
                    if effect.operation == "delta" else ("slow_accept",)
                )
                if not any(
                    decision.candidate.source_event_ref == effect.source_ref
                    and decision.candidate.target_dimension == effect.dimension
                    and decision.decision.value in allowed
                    for decision in slow_decisions
                ):
                    raise ValueError("required-joint effect group admission denied")

        # Emit human-explainable affect computation breakdown
        if self._telemetry_sink is not None:
            try:
                breakdowns: list[dict[str, Any]] = []
                proposed_dict = dict(result.proposed)
                for profile in persona.dimensions:
                    dim = profile.dimension
                    before_state = current_by_dimension.get(dim)
                    before_val = (
                        float(cast(float, before_state.value))
                        if before_state is not None
                        else profile.initial_value
                    )
                    after_val = proposed_dict.get(dim, before_val)
                    final_delta = after_val - before_val

                    # 1. Recovery (from DynamicsEngine.step execution contributions)
                    rec_contribs = [
                        c
                        for c in result.contributions
                        if c.dimension == dim and c.source == "recovery"
                    ]
                    rec_amount = sum(c.amount for c in rec_contribs) if rec_contribs else 0.0
                    rec_status = (
                        "present" if abs(rec_amount) > 1e-9 else "actual_zero"
                    )

                    # 2. Impulse & rule (from DynamicsEngine.step execution contributions)
                    cand = (
                        routing.candidates[0]
                        if (
                            routing.candidates
                            and not routing.abstention_reasons
                            and not mapped.abstention_reasons
                        )
                        else None
                    )
                    sem_status = "present" if cand else "not_applicable"
                    imp_contribs = [
                        c
                        for c in result.contributions
                        if c.dimension == dim and c.source.startswith("impulse:")
                    ]
                    if imp_contribs:
                        scaled_impulse = sum(c.amount for c in imp_contribs)
                        imp_status = "present"
                        rule = (
                            self._effects._rules.get(cand.kind)
                            if (cand and hasattr(self._effects, "_rules"))
                            else None
                        )
                        base_amount = rule.base_amount if (rule is not None and rule.dimension == dim) else None
                        rule_id = getattr(rule, "rule_id", None) if rule is not None else None
                        rule_status = "present" if (rule_id or base_amount is not None) else "not_applicable"
                        formula = (
                            f"{base_amount} × {cand.confidence:.2f} × {profile.sensitivity:.2f} = {scaled_impulse:+.4f}"
                            if (base_amount is not None and cand)
                            else f"{scaled_impulse:+.4f}"
                        )
                    else:
                        scaled_impulse = 0.0
                        imp_status = "not_applicable"
                        rule_status = "not_applicable"
                        formula = None
                        rule_id = None
                        base_amount = None

                    # 3. Coupling
                    coup_contribs = [
                        c
                        for c in result.contributions
                        if c.dimension == dim and c.source.startswith("coupling:")
                    ]
                    if coup_contribs:
                        coup_amount = sum(c.amount for c in coup_contribs)
                        coup_sources = [
                            f"{c.source} ({c.amount:+.4f})"
                            for c in coup_contribs
                        ]
                        coup_status = (
                            "present" if abs(coup_amount) > 1e-9 else "actual_zero"
                        )
                    else:
                        coup_amount = 0.0
                        coup_sources = []
                        coup_status = "not_applicable"

                    # 4. Homeostasis
                    dim_decisions = [
                        d
                        for d in slow_decisions
                        if getattr(d, "target_dimension", None) == dim
                    ]
                    if dim_decisions:
                        d = dim_decisions[0]
                        homeo_status = "present"
                        homeo_disp = getattr(
                            d.disposition, "value", str(d.disposition)
                        )
                        homeo_reason = getattr(d, "reason", None)
                    else:
                        homeo_status = "not_applicable"
                        homeo_disp = "PASSTHROUGH"
                        homeo_reason = (
                            "immediate affect dimensions bypass slow homeostasis gate"
                        )

                    breakdowns.append(
                        {
                            "dimension": dim,
                            "before": {
                                "status": "present",
                                "value": round(before_val, 4),
                            },
                            "recovery": {
                                "status": rec_status,
                                "amount": round(rec_amount, 4),
                                "elapsed_seconds": round(
                                    transition_input.elapsed.total_seconds()
                                    if isinstance(transition_input.elapsed, timedelta)
                                    else float(transition_input.elapsed or 0.0),
                                    2,
                                ),
                                "policy": self._engine._policies.get(
                                    dim, self._engine._default_policy
                                ).__class__.__name__,
                            },
                            "semantic_candidate": {
                                "status": sem_status,
                                "candidate_id": getattr(cand, "candidate_id", None),
                                "kind": getattr(cand, "kind", None),
                                "confidence": (
                                    round(cand.confidence, 4)
                                    if getattr(cand, "confidence", None) is not None
                                    else None
                                ),
                            },
                            "matched_rule": {
                                "status": rule_status,
                                "rule_id": rule_id,
                                "base_amount": base_amount,
                            },
                            "persona_sensitivity": {
                                "status": "present",
                                "value": round(profile.sensitivity, 4),
                            },
                            "impulse": {
                                "status": imp_status,
                                "amount": (
                                    round(scaled_impulse, 4)
                                    if imp_status == "present"
                                    else 0.0
                                ),
                                "formula": formula,
                            },
                            "coupling": {
                                "status": coup_status,
                                "amount": (
                                    round(coup_amount, 4)
                                    if coup_status != "not_applicable"
                                    else 0.0
                                ),
                                "sources": coup_sources,
                            },
                            "homeostasis": {
                                "status": homeo_status,
                                "disposition": homeo_disp,
                                "reason": homeo_reason,
                            },
                            "final_delta": round(final_delta, 4),
                            "after": {
                                "status": "present",
                                "value": round(after_val, 4),
                            },
                        }
                    )

                self._telemetry_sink.record(
                    interaction_id=transition_input.interaction_id,
                    stage=TelemetryStage.AFFECT_CONTRIBUTION,
                    status="CALCULATED",
                    occurred_at=transition_input.clock,
                    payload={
                        "dimensions": breakdowns,
                        "elapsed_seconds": (
                            transition_input.elapsed.total_seconds()
                            if isinstance(transition_input.elapsed, timedelta)
                            else float(transition_input.elapsed or 0.0)
                        ),
                    },
                    source_refs=evidence_refs,
                )
            except Exception:
                pass

        return EmotionalTransitionOutcome(
            transition_result=EmotionalTransitionResult(
                projected=projected,
                accepted_events=accepted_events,
                assessment_trace=trace,
                accepted_appraisals=tuple(accepted_appraisals),
                projection_refs=tuple(projection_refs),
                legacy_no_appraisal=legacy_no_appraisal,
            ),
            slow_decisions=slow_decisions,
        )

    def _invoke_homeostasis_gate(
        self,
        transition_input: EmotionalTransitionInput,
        result,  # DynamicsResult
        mapped,  # EffectMappingResult
        projected: ProjectedMindState,
    ) -> tuple[HomeostasisDecision, ...]:
        """Invoke the HomeostasisGate at Seam B (R3 §13.2) once per turn.

        Two contribution paths reach the gate:

          (a) **Immediate path**: contributions emitted by DynamicsEngine
              (dimension ∈ persona.dimensions). Engine is the only authority
              for immediate affect contributions.

          (b) **Longitudinal path**: impulses from EffectMapper whose
              source_ref starts with "longitudinal:". The engine does not
              process these (per ticket C10-BW-UPSTREAM-R2 §5 — longitudinal
              bypasses DynamicsEngine by design). They reach the gate
              **directly** as impulses, NOT as synthetic Contributions.

        Both paths produce `CandidateStateDelta` for the gate. The gate
        decides per candidate; recovery and coupling remain passthrough.

        No fallback, no synthesis, no heuristic estimation:
          - missing salience  → raise (fail closed)
          - missing evidence  → raise (H6 invariant)
          - missing confidence → raise
          - impulse-key substitution for evidence → REMOVED
          - salience = confidence proxy             → REMOVED
        """
        if self._homeostasis_gate is None:
            return ()

        decisions: list[HomeostasisDecision] = []
        current_by_dimension = {
            state.dimension: state for state in transition_input.current_affect
        }
        source_confidences = dict(mapped.source_confidences)
        # Per C10-BW-UPSTREAM-R2 §A/§B: salience and evidence_refs are
        # upstream authority values, sourced from the originating
        # SemanticEventCandidate / SemanticAppraisal via the EffectMapper's
        # salience_by_source / evidence_refs_by_source tables. The port does
        # NOT own these values; it only routes them to the gate.

        # ----------------------------------------------------------------
        # Path (a) — immediate affect contributions from DynamicsEngine.
        # The engine produced a Contribution row per persona-dimension
        # impulse (source = "impulse:event:<id>"). Authority values come
        # from mapped.salience_by_source / mapped.evidence_refs_by_source.
        # ----------------------------------------------------------------
        engine_event_contributions = [
            c for c in result.contributions
            if c.source.startswith("impulse:")
        ]

        for contribution in engine_event_contributions:
            impulse_key = contribution.source.removeprefix("impulse:")
            decisions.append(
                self._gate_one_candidate(
                    transition_input=transition_input,
                    contribution_source=contribution.source,
                    contribution_dimension=contribution.dimension,
                    contribution_amount=contribution.amount,
                    upstream_salience=mapped.salience_by_source.get(impulse_key),
                    upstream_evidence_refs=mapped.evidence_refs_by_source.get(
                        impulse_key, ()
                    ),
                    current_by_dimension=current_by_dimension,
                    source_confidences=source_confidences,
                )
            )

        # ----------------------------------------------------------------
        # Path (b) — longitudinal contributions from EffectMapper.
        # These bypass the engine entirely. The Impulse IS the contribution;
        # authority values are read from mapped.salience_by_source /
        # mapped.evidence_refs_by_source keyed by impulse.source_ref.
        # ----------------------------------------------------------------
        for impulse in mapped.impulses:
            if not impulse.source_ref.startswith("longitudinal:"):
                continue  # only longitudinal-prefixed impulses
            decisions.append(
                self._gate_one_candidate(
                    transition_input=transition_input,
                    contribution_source=impulse.source_ref,
                    contribution_dimension=impulse.dimension,
                    contribution_amount=impulse.amount,
                    upstream_salience=mapped.salience_by_source.get(impulse.source_ref),
                    upstream_evidence_refs=mapped.evidence_refs_by_source.get(
                        impulse.source_ref, ()
                    ),
                    current_by_dimension=current_by_dimension,
                    source_confidences=source_confidences,
                )
            )

        decisions_tuple = tuple(decisions)
        if self._telemetry_sink is not None and decisions_tuple:
            try:
                for d in decisions_tuple:
                    disp = getattr(d.decision, "value", str(d.decision))
                    self._telemetry_sink.record(
                        interaction_id=transition_input.interaction_id,
                        stage=TelemetryStage.HOMEOSTASIS,
                        status="EXECUTED",
                        occurred_at=transition_input.clock,
                        payload={
                            "decision_id": d.decision_id,
                            "target_dimension": d.candidate.target_dimension,
                            "proposed_value": d.candidate.proposed_value,
                            "prior_value": d.prior_value,
                            "disposition": disp,
                            "salience": d.candidate.salience,
                            "confidence": d.candidate.confidence,
                            "reason": d.reason,
                        },
                        source_refs=tuple(d.candidate.evidence_refs),
                    )
                    if disp == "slow_accept":
                        self._telemetry_sink.record(
                            interaction_id=transition_input.interaction_id,
                            stage=TelemetryStage.SLOW_DECISION,
                            status="ACCEPTED",
                            occurred_at=transition_input.clock,
                            payload={
                                "decision_id": d.decision_id,
                                "target_dimension": d.candidate.target_dimension,
                                "proposed_value": d.candidate.proposed_value,
                                "salience": d.candidate.salience,
                                "confidence": d.candidate.confidence,
                            },
                            source_refs=tuple(d.candidate.evidence_refs),
                        )
            except Exception:
                pass

        return decisions_tuple

    def _gate_one_candidate(
        self,
        *,
        transition_input: EmotionalTransitionInput,
        contribution_source: str,
        contribution_dimension: str,
        contribution_amount: float,
        upstream_salience: float | None,
        upstream_evidence_refs: tuple[str, ...],
        current_by_dimension: dict[str, RuntimeState],
        source_confidences: dict[str, float],
    ) -> HomeostasisDecision:
        """Build one CandidateStateDelta for the gate from upstream contribution.

        Strict — no synthetic Contribution authority here. The contribution
        facts (source, dimension, amount) come from upstream callers:
          - engine contributions (DynamicsEngine.step output) for path (a)
          - EffectMapper impulses for path (b)

        Salience and evidence_refs are passed as upstream authority
        values per C10-SALIENCE-IMPL-R2. The seam forwards None directly
        (CandidateStateDelta.salience is float | None). The gate's own
        policy determines the disposition for unavailable salience
        (never SLOW_ACCEPT).
        """
        impulse_key = contribution_source.removeprefix("impulse:")
        dimension = contribution_dimension
        amount = contribution_amount

        # Confidence: upstream authority. Per §B. Missing → fail closed.
        confidence = source_confidences.get(impulse_key)
        if confidence is None:
            raise ValueError(
                f"confidence is missing for contribution source {impulse_key!r}; "
                f"upstream authority must supply it (per C10-BW-UPSTREAM-R2 §B)"
            )

        # Salience: upstream authority, may be None (unavailable / not appraised).
        # Per C10-SALIENCE-IMPL-R2: the seam forwards None directly.
        # CandidateStateDelta.salience is float | None (the contract accepts None).
        # The gate's own policy determines the disposition for None
        # (never SLOW_ACCEPT).
        salience: float | None = upstream_salience

        # H6 invariant: evidence_refs must be non-empty for any SLOW_*
        # disposition. Upstream authority carries them; the port does NOT
        # substitute impulse_key when upstream is empty (per §B authority).
        if not upstream_evidence_refs:
            raise ValueError(
                f"evidence_refs is empty for contribution source {impulse_key!r}; "
                f"H6 invariant: empty evidence → no SLOW_*. Per §B lineage."
            )

        prior_state = current_by_dimension.get(dimension)
        prior_value = (
            float(cast(float, prior_state.value)) if prior_state else None
        )

        candidate = CandidateStateDelta(
            target_dimension=dimension,
            proposed_value=amount,
            scope=transition_input.scope,
            evidence_refs=upstream_evidence_refs,
            salience=salience,  # float | None forwarded as-is
            confidence=confidence,
            source_event_ref=impulse_key,
            observed_at=transition_input.clock,
        )

        return self._homeostasis_gate.decide(candidate, prior_value)

    @staticmethod
    def _history_refs(transition_input: EmotionalTransitionInput) -> tuple[str, ...]:
        history = transition_input.history_context
        if history is None:
            return ()
        refs = list(history.source_refs)
        for summary in history.pattern_summaries:
            refs.extend(summary.matched_refs)
        return tuple(dict.fromkeys(refs))
