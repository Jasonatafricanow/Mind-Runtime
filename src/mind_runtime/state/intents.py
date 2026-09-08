"""TransitionIntent construction for the two commit phases (D5.1).

The frozen core transaction rule separates the two phases:

- ``ingest`` — facts already happened: Evidence/Observation are durable on
  admission, and the reconciled canonical factual state may commit
  immediately (G13b: ingested facts survive a cognitive abort).
- ``turn_commit`` — derived mind transitions (affect/relationship) exist
  only as a Projection during the turn and become canonical exclusively
  through ``commit_turn``.

``TransitionIntent`` (D1 contract) carries ``commit_phase``; these builders
produce the typed intents from reconcile outcomes and projections so no
caller can mix the phases.
"""

from mind_runtime.contracts import (
    RuntimeState,
    Scope,
    StateTransition,
    TransitionIntent,
)

INGEST_PHASE = "ingest"
TURN_COMMIT_PHASE = "turn_commit"


def build_ingest_intent(
    *,
    interaction_id: str,
    scope: Scope,
    origin_runtime_id: str,
    target_dimension: str,
    before: RuntimeState,
    proposed_after: RuntimeState,
    cause_refs: tuple[str, ...],
    confidence: float = 1.0,
    policy: str = "reconciler",
) -> TransitionIntent:
    """Build an ingest-phase intent (facts may commit before turn_commit)."""
    return TransitionIntent(
        intent_id=f"ingest:{interaction_id}:{target_dimension}:{proposed_after.version}",
        interaction_id=interaction_id,
        scope=scope,
        origin_runtime_id=origin_runtime_id,
        target_dimension=target_dimension,
        before=before,
        proposed_after=proposed_after,
        cause_refs=cause_refs,
        policy=policy,
        confidence=confidence,
        commit_phase=INGEST_PHASE,
    )


def build_turn_commit_intent(
    *,
    interaction_id: str,
    scope: Scope,
    origin_runtime_id: str,
    target_dimension: str,
    before: RuntimeState,
    proposed_after: RuntimeState,
    cause_refs: tuple[str, ...],
    confidence: float,
    policy: str = "dynamics",
) -> TransitionIntent:
    """Build a turn_commit-phase intent (derived mind transition)."""
    return TransitionIntent(
        intent_id=f"turn_commit:{interaction_id}:{target_dimension}:{proposed_after.version}",
        interaction_id=interaction_id,
        scope=scope,
        origin_runtime_id=origin_runtime_id,
        target_dimension=target_dimension,
        before=before,
        proposed_after=proposed_after,
        cause_refs=cause_refs,
        policy=policy,
        confidence=confidence,
        commit_phase=TURN_COMMIT_PHASE,
    )


def ingest_intents_from_transitions(
    *,
    interaction_id: str,
    transitions: tuple[StateTransition, ...],
    origin_runtime_id: str,
) -> tuple[TransitionIntent, ...]:
    """Derive ingest-phase intents from committed reconcile transitions.

    Every reconcile transition (creation, reaffirm, supersession, expiry,
    terminal) is a factual state change and therefore an ingest-phase
    intent. The intent ids are deterministic for replay.
    """
    return tuple(
        build_ingest_intent(
            interaction_id=interaction_id,
            scope=transition.scope,
            origin_runtime_id=origin_runtime_id,
            target_dimension=transition.from_state.dimension,
            before=transition.from_state,
            proposed_after=transition.to_state,
            cause_refs=transition.from_state.evidence_refs,
        )
        for transition in transitions
    )
