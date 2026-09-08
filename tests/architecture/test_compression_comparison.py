"""Frozen and compressed topology comparison over identical named inputs."""

from tests.architecture.compression_cases import (
    CASES,
    COMPRESSED_TOPOLOGY,
    FROZEN_TOPOLOGY,
    evaluate,
)


def test_comparison_covers_all_seven_approved_inputs() -> None:
    assert tuple(case.case_id for case in CASES) == (
        "recent_wake_at_night",
        "repeated_plan_cancellation",
        "long_silence",
        "high_longing_active_chat",
        "due_intent",
        "cooldown_block",
        "ambiguous_utterance",
    )
    assert all(case.owner.startswith("MR-D") for case in CASES)


def test_both_topologies_evaluate_the_same_input_inventory_deterministically() -> None:
    for case in CASES:
        frozen_first = evaluate(FROZEN_TOPOLOGY, case)
        frozen_replay = evaluate(FROZEN_TOPOLOGY, case)
        compressed_first = evaluate(COMPRESSED_TOPOLOGY, case)
        compressed_replay = evaluate(COMPRESSED_TOPOLOGY, case)
        assert frozen_first == frozen_replay
        assert compressed_first == compressed_replay
        assert frozen_first.case_id == compressed_first.case_id == case.case_id
        assert frozen_first.terminal_authority == compressed_first.terminal_authority
        assert frozen_first.behavior_owner == compressed_first.behavior_owner == case.owner


def test_compressed_topology_removes_duplicate_runtime_representation() -> None:
    assert FROZEN_TOPOLOGY.runtime_hops == (
        "situation",
        "resolved_appraisal",
        "dynamics",
        "motivation",
        "policy",
    )
    assert COMPRESSED_TOPOLOGY.runtime_hops == (
        "context",
        "emotional_transition",
        "intent_policy",
    )
    assert COMPRESSED_TOPOLOGY.semantic_representation_count == 3
    assert FROZEN_TOPOLOGY.semantic_representation_count == 6
    assert COMPRESSED_TOPOLOGY.duplicate_rule_count == 0
    assert FROZEN_TOPOLOGY.duplicate_rule_count == 2


def test_compressed_topology_has_one_policy_owner_and_no_llm_authority() -> None:
    assert COMPRESSED_TOPOLOGY.policy_owner_count == 1
    assert COMPRESSED_TOPOLOGY.llm_authority_count == 0
    assert COMPRESSED_TOPOLOGY.trace_covers_all_contributions is True
    assert COMPRESSED_TOPOLOGY.replay_input_count < FROZEN_TOPOLOGY.replay_input_count
    assert COMPRESSED_TOPOLOGY.modules_per_new_affect_dimension < (
        FROZEN_TOPOLOGY.modules_per_new_affect_dimension
    )


def test_unimplemented_behavior_is_named_deferred_not_claimed_green() -> None:
    results = tuple(evaluate(COMPRESSED_TOPOLOGY, case) for case in CASES)
    assert all(result.behavior_status == "deferred" for result in results)
    assert {result.behavior_owner for result in results} == {"MR-D8", "MR-D9"}
