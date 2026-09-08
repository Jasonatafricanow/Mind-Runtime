"""C10-C2-AUTH: Slow-state → behavioral-prior projection contract.

Frozen by `docs/C10_C2_AUTH_SLOW_BEHAVIORAL_PROJECTION_AUTHORITY.md`.

This module introduces ONE contract type:

    BehavioralPriorContribution

It codifies the shape of the projection from authoritative slow
RuntimeState (agent.slow.*, written by SlowPlasticityWriter per
ADR-0017 + C10-BW-ONTO) into the behavioral pipeline (DecisionContext,
ExpressionContextItem). It carries the full provenance bundle required
by C2-F10 / C2-F16.

This is a contract-only artifact. The compiler integration that builds
BehavioralPriorContribution from SlowStateProjection +
SlowStateExpressionRule is deferred to a follow-up ticket (C2-IMPL);
the existing `expression/context.py:415-437` compiler already conforms
to this contract by construction.
"""

from __future__ import annotations

from dataclasses import dataclass

from mind_runtime.contracts.common import require_non_empty
from mind_runtime.contracts.scope import Scope


# Slow-state dimension namespace prefixes recognized by the contract.
# The kernel is dimension-agnostic (ADR-C10-A1 §1.4); the contract
# accepts the configured slow prefix verbatim and rejects only what
# is clearly NOT slow (the affect prefix), to preserve the no-aliasing
# invariant C2-F7.
#
# The exact prefix is configuration-owned (see
# `docs/C10_BW_MINIMAL_CONTRACT_CLOSURE.md` and
# `docs/C10_BW_CONTRACT_CLOSURE_CORRECTION.md`); "agent.slow." is the
# current production convention. Other slow prefixes (e.g.,
# "agent.learned.", "agent.longitudinal.") are also valid.
_AFFECT_PREFIX = "agent.affect."


@dataclass(frozen=True, slots=True)
class BehavioralPriorContribution:
    """One explicit slow-state → behavioral-prior projection.

    Carries the provenance bundle from authoritative slow RuntimeState
    (per ADR-0017 + C10-BW-ONTO) into a single behavioral-prior
    artifact. The compiler consumes a tuple of these to emit
    ExpressionContextItem rows.

    Frozen by C10-C2-AUTH §10.3 / §14.2 / C2-F9 / C2-F16.

    Fields:
        dimension            : str        # verbatim slow dimension
                                            # (e.g., "agent.slow.trust")
        source_state_id      : str        # RuntimeState.state_id
                                            # (provenance; C2-I12)
        source_version       : int        # RuntimeState.version
                                            # (provenance; C2-I12)
        band_label           : str        # SlowStateBand.label after
                                            # band mapping
        output_key           : str        # SlowStateExpressionRule
                                            # output_key (config-owned)
        rule_priority        : int        # rule priority
                                            # (config-owned)
        evidence_refs        : tuple[str, ...]
                                           # union of window records'
                                           # evidence_refs (C2-I3, H6)
        source_decision_ids  : tuple[str, ...]
                                           # union of window records'
                                           # source_decision_id (C2-I4)
        scope                : Scope      # scope of source RuntimeState
        origin_runtime_id    : str        # source RuntimeState origin

    Invariants (frozen):
        - dimension MUST NOT start with the affect prefix
          (no-aliasing; C2-F7).
        - dimension MUST be non-empty.
        - source_state_id MUST be non-empty (C2-I12).
        - source_version MUST be a positive integer.
        - evidence_refs entries MUST be non-empty (per H6 chain).
        - source_decision_ids entries MUST be non-empty.
        - scope / origin_runtime_id equal the source RuntimeState's
          scope / origin_runtime_id (C2-I5).
    """

    dimension: str
    source_state_id: str
    source_version: int
    band_label: str
    output_key: str
    rule_priority: int
    evidence_refs: tuple[str, ...]
    source_decision_ids: tuple[str, ...]
    scope: Scope
    origin_runtime_id: str

    def __post_init__(self) -> None:
        # No-aliasing invariant C2-F7: slow must not alias affect.
        if self.dimension.startswith(_AFFECT_PREFIX):
            raise ValueError(
                f"BehavioralPriorContribution.dimension {self.dimension!r} "
                f"starts with the affect prefix {_AFFECT_PREFIX!r}; "
                f"this violates the no-aliasing invariant (C2-F7). "
                f"Slow state must NOT be conflated with affect."
            )
        require_non_empty(self.dimension, "BehavioralPriorContribution.dimension")
        require_non_empty(self.source_state_id, "BehavioralPriorContribution.source_state_id")
        require_non_empty(self.band_label, "BehavioralPriorContribution.band_label")
        require_non_empty(self.output_key, "BehavioralPriorContribution.output_key")
        require_non_empty(self.origin_runtime_id, "BehavioralPriorContribution.origin_runtime_id")
        if isinstance(self.source_version, bool) or not isinstance(self.source_version, int):
            raise ValueError("BehavioralPriorContribution.source_version must be an integer")
        if self.source_version < 1:
            raise ValueError("BehavioralPriorContribution.source_version must be >= 1")
        if isinstance(self.rule_priority, bool) or not isinstance(self.rule_priority, int):
            raise ValueError("BehavioralPriorContribution.rule_priority must be an integer")
        if self.rule_priority < 0:
            raise ValueError("BehavioralPriorContribution.rule_priority must be >= 0")
        # Provenance invariants: chain entries must be non-empty opaque IDs.
        if not isinstance(self.evidence_refs, tuple):
            raise ValueError("BehavioralPriorContribution.evidence_refs must be a tuple")
        for ref in self.evidence_refs:
            require_non_empty(ref, "BehavioralPriorContribution.evidence_refs entries")
        if not isinstance(self.source_decision_ids, tuple):
            raise ValueError("BehavioralPriorContribution.source_decision_ids must be a tuple")
        for decision_id in self.source_decision_ids:
            require_non_empty(
                decision_id, "BehavioralPriorContribution.source_decision_ids entries"
            )
        if not isinstance(self.scope, Scope):
            raise ValueError("BehavioralPriorContribution.scope must be a Scope instance")


__all__ = ["BehavioralPriorContribution"]