"""OW-3 causal-chain join.

Resolves the chain Appraisal → Rule → Decision → Contribution for a
single affect dimension by joining on canonical `source_ref` tokens
(`appraisal:<id>:<rule>:state:<ref>`).

No timing inference. No "same turn" guess. Every link is bound to a
real ID/ref that exists in the live trace.
"""

from __future__ import annotations

from observation_window.causal_contracts import (
    CausalChainLink,
    InteractionId,
    ResolvedCausalChain,
    SourceRef,
)


def _build_chain_for_dimension(
    snapshot,  # ObservedTurnSnapshot
    dimension: str,
) -> ResolvedCausalChain:
    """Build the per-dimension resolved causal chain.

    Joins the live trace data by source_ref tokens. The chain is
    ordered (appraisal → rule → decision → contribution) and includes
    abstention reason links when present.
    """
    chain: list[CausalChainLink] = []

    # Find the contribution(s) for this dimension in the assessment trace.
    contribs_for_dim = [
        c for c in snapshot.assessment_trace.contributions if c.dimension == dimension
    ]
    if not contribs_for_dim:
        # No contribution for this dimension; the state may still have
        # changed via a different path (event/history) or not at all.
        # If the trace has the dimension in state_before / state_after,
        # we still surface a "no J8-E3 contribution" signal.
        state_before = snapshot.assessment_trace.state_before.get(dimension)
        state_after = snapshot.assessment_trace.state_after.get(dimension)
        if state_before is None or state_after is None:
            return _empty_chain(snapshot, dimension, has_no_data=True)
        return _empty_chain(snapshot, dimension, has_no_data=False)

    has_appraisal = False
    has_applied_decision = False
    has_abstention = False
    abstention_reasons: list[str] = []

    # Build the canonical source_refs to look up against decisions.
    decision_by_ref: dict[SourceRef, list] = {}
    for d in snapshot.decisions:
        decision_by_ref.setdefault(d.source_ref, []).append(d)

    # For each contribution, walk the upstream chain.
    for c in contribs_for_dim:
        if c.source_kind == "appraisal":
            has_appraisal = True
            # Find the decision that produced this contribution.
            matching_decisions = decision_by_ref.get(c.source_ref, [])
            for d in matching_decisions:
                if d.applied:
                    has_applied_decision = True
                else:
                    has_abstention = True
                    if d.abstention_reason:
                        abstention_reasons.append(d.abstention_reason)
                # Add the appraisal link (once per appraisal_id).
                if not any(link.identifier == d.appraisal_id and link.kind == "appraisal" for link in chain):
                    chain.append(
                        CausalChainLink(
                            kind="appraisal",
                            identifier=d.appraisal_id,
                            label=f"appraisal {d.appraisal_id}",
                            amount=None,
                            confidence=d.provider_confidence,
                            source_ref=None,
                            applied=None,
                            reason_code=None,
                            extra={"matched_state_refs": list(d.matched_state_refs)},
                        )
                    )
                # Rule link.
                chain.append(
                    CausalChainLink(
                        kind="rule",
                        identifier=d.rule_id,
                        label=f"rule {d.rule_id}",
                        amount=None,
                        confidence=d.provider_confidence,
                        source_ref=d.source_ref,
                        applied=d.applied,
                        reason_code=d.reason_code,
                        extra={"effective_dimension": d.effective_dimension},
                    )
                )
                # Decision link.
                chain.append(
                    CausalChainLink(
                        kind="decision",
                        identifier=f"{d.appraisal_id}:{d.rule_id}",
                        label=f"decision {d.appraisal_id}::{d.rule_id} applied={d.applied}",
                        amount=None,
                        confidence=d.provider_confidence,
                        source_ref=d.source_ref,
                        applied=d.applied,
                        reason_code=d.reason_code,
                        extra={"abstention_reason": d.abstention_reason},
                    )
                )
        else:
            # Non-appraisal contributions (event, history, recovery, etc.)
            chain.append(
                CausalChainLink(
                    kind=c.source_kind,  # type: ignore[arg-type]
                    identifier=c.source_ref,
                    label=f"{c.source_kind} {c.source_ref}",
                    amount=c.amount,
                    confidence=c.confidence,
                    source_ref=c.source_ref,
                    applied=c.applied,
                    reason_code=c.reason_code,
                    extra={},
                )
            )

        # Always emit the contribution link.
        chain.append(
            CausalChainLink(
                kind="contribution",
                identifier=c.source_ref,
                label=f"contribution {c.source_ref} amount={c.amount:+.4f}",
                amount=c.amount,
                confidence=c.confidence,
                source_ref=c.source_ref,
                applied=c.applied,
                reason_code=c.reason_code,
                extra={},
            )
        )

    state_before = snapshot.assessment_trace.state_before.get(dimension, 0.0)
    state_after = snapshot.assessment_trace.state_after.get(dimension, 0.0)
    delta = state_after - state_before

    return ResolvedCausalChain(
        interaction_id=snapshot.interaction_id,
        dimension=dimension,
        state_before=state_before,
        state_after=state_after,
        delta=delta,
        chain=tuple(chain),
        has_appraisal=has_appraisal,
        has_applied_decision=has_applied_decision,
        has_abstention=has_abstention,
        abstention_reasons=tuple(abstention_reasons),
    )


def _empty_chain(
    snapshot,
    dimension: str,
    *,
    has_no_data: bool,
) -> ResolvedCausalChain:
    state_before = snapshot.assessment_trace.state_before.get(dimension, 0.0)
    state_after = snapshot.assessment_trace.state_after.get(dimension, 0.0)
    delta = state_after - state_before
    chain: list[CausalChainLink] = []
    if has_no_data:
        # Dimension not in trace at all.
        chain.append(
            CausalChainLink(
                kind="missing",
                identifier=dimension,
                label=f"UNRESOLVED_REFERENCE dimension {dimension!r} not in trace",
                amount=None,
                confidence=None,
                source_ref=None,
                applied=None,
                reason_code="DIMENSION_NOT_IN_TRACE",
                extra={},
            )
        )
    else:
        chain.append(
            CausalChainLink(
                kind="no_appraisal",
                identifier=dimension,
                label=f"no J8-E3 contribution for {dimension!r} (state change may be event/history/recovery)",
                amount=None,
                confidence=None,
                source_ref=None,
                applied=None,
                reason_code=None,
                extra={},
            )
        )
    return ResolvedCausalChain(
        interaction_id=snapshot.interaction_id,
        dimension=dimension,
        state_before=state_before,
        state_after=state_after,
        delta=delta,
        chain=tuple(chain),
        has_appraisal=False,
        has_applied_decision=False,
        has_abstention=False,
        abstention_reasons=(),
    )


class CausalChainBuilder:
    """Builds ResolvedCausalChain instances from OWLiveTraceSource snapshots."""

    def __init__(self) -> None:
        pass  # no state

    def build_for_dimension(
        self, snapshot, dimension: str
    ) -> ResolvedCausalChain:
        return _build_chain_for_dimension(snapshot, dimension)

    def build_for_all_changed_dimensions(self, snapshot) -> tuple[ResolvedCausalChain, ...]:
        """Return the chain for every dimension that appears in the trace."""
        all_dims: set[str] = set(snapshot.assessment_trace.state_before.keys())
        all_dims |= set(snapshot.assessment_trace.state_after.keys())
        all_dims |= {c.dimension for c in snapshot.assessment_trace.contributions}
        return tuple(
            self.build_for_dimension(snapshot, dim)
            for dim in sorted(all_dims)
        )

    def build(self, snapshot_or_result) -> tuple[ResolvedCausalChain, ...]:
        """Build all per-dimension chains from a snapshot or a raw J8-E3 result.

        Accepts either an `ObservedTurnSnapshot` (preferred) or a
        live `EmotionalTransitionResult` (in which case the source is
        invoked internally to convert it). This keeps tests
        single-line-call while preserving the strict read-only boundary.

        For non-J8-E3 baseline results, no chains are produced
        (the OW-3 spec requires a clean OFF display, not a
        "missing reference" error for the J8-E3 chain itself).
        """
        from observation_window.live_trace import OWLiveTraceSource

        if hasattr(snapshot_or_result, "assessment_trace"):
            source = OWLiveTraceSource()
            snap = source.observe(
                interaction_id="ix-inline",
                result=snapshot_or_result,
            )
            return self.build_for_all_changed_dimensions(snap)
        return self.build_for_all_changed_dimensions(snapshot_or_result)