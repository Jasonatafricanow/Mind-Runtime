"""D4.2 TTL / validity resolution for canonical state.

Rules frozen by the baseline:

- Only current-like lifecycles (ACTIVE, IMPROVING) can expire by time.
- Terminal lifecycles (RESOLVED, COMPLETED, CANCELLED, SUPERSEDED) are
  NEVER rewritten to EXPIRED by time — expiry is blocked regardless of
  ``valid_until``.
- Status strings outside the frozen vocabulary are treated as opaque: the
  resolver cannot prove they are current-like, so no time-based change is
  applied (fail-safe).
- Expiration produces a new canonical state record (deterministic
  ``state_id``, incremented ``version``) — the old record stays immutable
  history; the transition is recorded by the caller.
"""

from dataclasses import dataclass
from datetime import datetime

from mind_runtime.contracts import RuntimeState, SyncFields
from mind_runtime.state.ids import canonical_state_id
from mind_runtime.state.lifecycle import StateLifecycle, is_current_like, is_terminal


def _expired_successor(state: RuntimeState, *, now: datetime) -> RuntimeState:
    next_version = state.version + 1
    next_state_id = canonical_state_id(state.dimension, next_version)
    return RuntimeState(
        state_id=next_state_id,
        scope=state.scope,
        dimension=state.dimension,
        value=state.value,
        status=StateLifecycle.EXPIRED.value,
        valid_from=state.valid_from,
        valid_until=state.valid_until,
        relevant_until=state.relevant_until,
        last_observed_at=state.last_observed_at,
        evidence_refs=state.evidence_refs,
        transition_refs=state.transition_refs,
        updated_at=now,
        origin_runtime_id=state.origin_runtime_id,
        version=next_version,
        sync=SyncFields(
            state.scope,
            state.origin_runtime_id,
            next_state_id,
            next_version,
            f"idem-{next_state_id}",
        ),
    )


@dataclass(frozen=True)
class ValidityOutcome:
    """The validity verdict for one state at one instant."""

    state: RuntimeState
    changed: bool
    reason: str

    @property
    def expired(self) -> bool:
        return self.reason == "expired_by_ttl"


def evaluate_validity(state: RuntimeState, *, now: datetime) -> ValidityOutcome:
    """Evaluate one state's temporal validity at ``now``.

    ``now`` must be aware UTC (the contract enforces it on construction).
    """
    if is_terminal(state.status):
        # Terminal states answer "what happened?"; time cannot expire them.
        return ValidityOutcome(state=state, changed=False, reason="terminal_protected")
    if not is_current_like(state.status):
        return ValidityOutcome(state=state, changed=False, reason="opaque_status")
    if state.valid_until is None or now <= state.valid_until:
        return ValidityOutcome(state=state, changed=False, reason="valid")
    return ValidityOutcome(
        state=_expired_successor(state, now=now),
        changed=True,
        reason="expired_by_ttl",
    )
