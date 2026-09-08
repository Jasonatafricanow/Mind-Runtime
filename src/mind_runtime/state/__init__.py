"""Mind Runtime canonical state plane (D4, MR-1B)."""

from mind_runtime.state.definitions import (
    StateDefinitionRegistry,
    ValidityKind,
    ValidityPolicy,
    parse_validity_policy,
)
from mind_runtime.state.ids import canonical_state_id
from mind_runtime.state.intents import (
    INGEST_PHASE,
    TURN_COMMIT_PHASE,
    build_ingest_intent,
    build_turn_commit_intent,
    ingest_intents_from_transitions,
)
from mind_runtime.state.lifecycle import (
    CURRENT_LIKE_LIFECYCLES,
    TERMINAL_LIFECYCLES,
    StateLifecycle,
    is_current_like,
    is_known_lifecycle,
    is_terminal,
)
from mind_runtime.state.persistence import (
    SqliteStateBackend,
    StateBackend,
    canonical_state_rows_equal,
)
from mind_runtime.state.ports import ResolverEffectiveStatePort
from mind_runtime.state.reconciler import (
    FactualReconciler,
    ReconcileResult,
    StateIntent,
    interpret_observation,
)
from mind_runtime.state.relevance import RelevanceOutcome, evaluate_relevance
from mind_runtime.state.resolver import EffectiveStateResolver, EffectiveStateView
from mind_runtime.state.validity import ValidityOutcome, evaluate_validity

__all__ = [
    "CURRENT_LIKE_LIFECYCLES",
    "EffectiveStateResolver",
    "EffectiveStateView",
    "FactualReconciler",
    "INGEST_PHASE",
    "ReconcileResult",
    "RelevanceOutcome",
    "ResolverEffectiveStatePort",
    "SqliteStateBackend",
    "StateBackend",
    "StateDefinitionRegistry",
    "StateIntent",
    "StateLifecycle",
    "TURN_COMMIT_PHASE",
    "TERMINAL_LIFECYCLES",
    "ValidityKind",
    "ValidityOutcome",
    "ValidityPolicy",
    "build_ingest_intent",
    "build_turn_commit_intent",
    "canonical_state_id",
    "canonical_state_rows_equal",
    "evaluate_relevance",
    "evaluate_validity",
    "ingest_intents_from_transitions",
    "interpret_observation",
    "is_current_like",
    "is_known_lifecycle",
    "is_terminal",
    "parse_validity_policy",
]
