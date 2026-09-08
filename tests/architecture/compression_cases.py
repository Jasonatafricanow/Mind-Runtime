"""Deterministic test-side model for the D7R frozen/compressed comparison."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CompressionCase:
    """One identical input presented to both topology descriptions."""

    case_id: str
    owner: str
    terminal_authority: str


@dataclass(frozen=True, slots=True)
class Topology:
    """Measured structural properties of one runtime topology."""

    name: str
    runtime_hops: tuple[str, ...]
    semantic_representation_count: int
    duplicate_rule_count: int
    policy_owner_count: int
    llm_authority_count: int
    trace_covers_all_contributions: bool
    replay_input_count: int
    modules_per_new_affect_dimension: int
    test_surface_count: int
    llm_failure_scope: str


@dataclass(frozen=True, slots=True)
class ComparisonResult:
    """Replayable structural result without claiming future behavior exists."""

    topology: str
    case_id: str
    terminal_authority: str
    behavior_owner: str
    behavior_status: str
    hop_count: int
    semantic_representation_count: int
    duplicate_rule_count: int
    policy_owner_count: int
    llm_authority_count: int
    trace_sufficient: bool
    replay_input_count: int
    modules_per_new_affect_dimension: int
    test_surface_count: int
    llm_failure_scope: str


CASES = (
    CompressionCase("recent_wake_at_night", "MR-D8", "transition"),
    CompressionCase("repeated_plan_cancellation", "MR-D8", "transition"),
    CompressionCase("long_silence", "MR-D9", "intent"),
    CompressionCase("high_longing_active_chat", "MR-D9", "policy"),
    CompressionCase("due_intent", "MR-D9", "intent"),
    CompressionCase("cooldown_block", "MR-D9", "policy"),
    CompressionCase("ambiguous_utterance", "MR-D8", "semantic_abstain"),
)

FROZEN_TOPOLOGY = Topology(
    name="frozen_v0_1_4",
    runtime_hops=(
        "situation",
        "resolved_appraisal",
        "dynamics",
        "motivation",
        "policy",
    ),
    semantic_representation_count=6,
    duplicate_rule_count=2,
    policy_owner_count=2,
    llm_authority_count=1,
    trace_covers_all_contributions=False,
    replay_input_count=8,
    modules_per_new_affect_dimension=4,
    test_surface_count=5,
    llm_failure_scope="appraisal_chain",
)

COMPRESSED_TOPOLOGY = Topology(
    name="compressed_d7r",
    runtime_hops=("context", "emotional_transition", "intent_policy"),
    semantic_representation_count=3,
    duplicate_rule_count=0,
    policy_owner_count=1,
    llm_authority_count=0,
    trace_covers_all_contributions=True,
    replay_input_count=4,
    modules_per_new_affect_dimension=2,
    test_surface_count=3,
    llm_failure_scope="optional_semantic_candidate",
)


def evaluate(topology: Topology, case: CompressionCase) -> ComparisonResult:
    """Evaluate topology structure for an input; behavior remains owner-deferred."""

    return ComparisonResult(
        topology=topology.name,
        case_id=case.case_id,
        terminal_authority=case.terminal_authority,
        behavior_owner=case.owner,
        behavior_status="deferred",
        hop_count=len(topology.runtime_hops),
        semantic_representation_count=topology.semantic_representation_count,
        duplicate_rule_count=topology.duplicate_rule_count,
        policy_owner_count=topology.policy_owner_count,
        llm_authority_count=topology.llm_authority_count,
        trace_sufficient=topology.trace_covers_all_contributions,
        replay_input_count=topology.replay_input_count,
        modules_per_new_affect_dimension=topology.modules_per_new_affect_dimension,
        test_surface_count=topology.test_surface_count,
        llm_failure_scope=topology.llm_failure_scope,
    )
