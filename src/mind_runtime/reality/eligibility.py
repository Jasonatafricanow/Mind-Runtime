"""State eligibility gate for Reality observations (MR-REALITY §7)."""

from datetime import datetime
from enum import StrEnum

from mind_runtime.contracts import (
    EffectiveWindowKind,
    Observation,
    ObservationModality,
    ScopeDomain,
    SemanticRelation,
)


class StateEligibility(StrEnum):
    """The four frozen outcomes of the Reality StateEligibility gate."""

    ELIGIBLE_CURRENT = "eligible_current"
    ELIGIBLE_TERMINAL = "eligible_terminal"
    OBSERVATION_ONLY = "observation_only"
    REJECTED = "rejected"


def evaluate_state_eligibility(
    observation: Observation,
    *,
    admission_anchor: datetime | None = None,
    has_exact_target: bool = False,
    is_valid_definition: bool = True,
) -> StateEligibility:
    """Project an admitted Observation into a replay-stable eligibility result.

    Rules (MR-REALITY §7):
      - Only ASSERTED user propositions can be ELIGIBLE_CURRENT or ELIGIBLE_TERMINAL.
      - PLANNED, TENTATIVE, ESTIMATED, INFERRED default to OBSERVATION_ONLY.
      - Terminal operations (.resolved, .completed, .cancelled) require an
        authoritative exact target; otherwise they remain OBSERVATION_ONLY.
      - Current-state eligibility requires:
          1. ASSERTED modality
          2. CURRENT semantic relation
          3. Resolved effective window containing the admission anchor
             (OPEN_INTERVAL [start <= anchor] or INTERVAL [start <= anchor < end])
          4. POINT is instant-only and not current-state proof (OBSERVATION_ONLY)
          5. Valid definition

    ``Observation.observed_at`` is the durable admission anchor.  An explicit
    ``admission_anchor`` is accepted only as a checked assertion of that same
    value; retry/restart wall-clock time is never an authority input.
    """
    anchor = observation.observed_at
    if admission_anchor is not None and admission_anchor != anchor:
        raise ValueError("admission_anchor must equal observation.observed_at")

    if observation.scope.domain != ScopeDomain.USER:
        return StateEligibility.REJECTED

    if not is_valid_definition:
        return StateEligibility.OBSERVATION_ONLY

    # Non-ASSERTED modalities are always OBSERVATION_ONLY
    if observation.modality != ObservationModality.ASSERTED:
        return StateEligibility.OBSERVATION_ONLY

    # Explicit terminal operations
    is_terminal = observation.key.endswith((".resolved", ".completed", ".cancelled"))
    if is_terminal:
        if has_exact_target:
            return StateEligibility.ELIGIBLE_TERMINAL
        return StateEligibility.OBSERVATION_ONLY

    # Non-current relations cannot be current state
    if observation.semantic_time.relation != SemanticRelation.CURRENT:
        return StateEligibility.OBSERVATION_ONLY

    # Window validation
    window = observation.effective_window
    if window is None:
        return StateEligibility.OBSERVATION_ONLY

    if window.kind == EffectiveWindowKind.POINT:
        # POINT is an instant, not continuous current-state proof
        return StateEligibility.OBSERVATION_ONLY

    if window.kind == EffectiveWindowKind.OPEN_INTERVAL:
        if window.start_at <= anchor:
            return StateEligibility.ELIGIBLE_CURRENT
        return StateEligibility.OBSERVATION_ONLY

    if window.kind == EffectiveWindowKind.INTERVAL:
        if window.end_at is not None and window.start_at <= anchor < window.end_at:
            return StateEligibility.ELIGIBLE_CURRENT
        return StateEligibility.OBSERVATION_ONLY

    return StateEligibility.OBSERVATION_ONLY
