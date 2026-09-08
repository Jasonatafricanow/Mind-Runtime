"""D11S.5 history anti-amplification audit tests (G27)."""

import subprocess
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import pytest

from mind_runtime.contracts import (
    HistoricalContextItem,
    PatternMatchSummary,
    Scope,
    ScopeDomain,
)
from mind_runtime.validation import load_history_fixture
from mind_runtime.validation.history_audit import (
    HistoryAuditResult,
    audit_repeated_history,
    derive_expected_history_effect,
)

ROOT = Path(__file__).resolve().parents[2]
INPUTS = ROOT / "certification/d11s/inputs"
HISTORY_FIXTURE = INPUTS / "history-g27.json"
MANIFEST = INPUTS / "runtime-config.json"
HEAD = subprocess.run(
    ["git", "rev-parse", "--verify", "HEAD"],
    cwd=ROOT,
    check=True,
    capture_output=True,
    text=True,
).stdout.strip()


def make_history_item() -> HistoricalContextItem:
    fixture = load_history_fixture(HISTORY_FIXTURE)
    return fixture.bundle.episodes[0]


def make_pattern_summary() -> PatternMatchSummary:
    fixture = load_history_fixture(HISTORY_FIXTURE)
    return fixture.bundle.pattern_summaries[0]


def test_three_surfacings_keep_one_source_and_unit_influence(tmp_path: Path) -> None:
    result = audit_repeated_history(
        make_history_item(),
        make_pattern_summary(),
        retrievals=3,
        root=tmp_path,
        repository_root=ROOT,
    )

    assert isinstance(result, HistoryAuditResult)
    assert result.unique_source_count == 1
    assert result.retrieval_count == 3
    assert result.influence_multiplier == 1.0
    assert not result.reinforced
    assert tuple(item.decision_index for item in result.decision_influences) == (0, 1, 2)
    assert all(
        item.contribution_refs == ("history-g27-summary-1",) for item in result.decision_influences
    )
    expected = derive_expected_history_effect(MANIFEST, HISTORY_FIXTURE)
    assert all(item.effect_amount == expected for item in result.decision_influences)
    assert result.match_count_unchanged
    assert result.effect_amount_unchanged


def test_expected_effect_amount_is_derived_not_observed() -> None:
    """The expected amount comes from the verified manifest rule and fixture
    summary (0.03 per match * 1 match * 1.0 confidence, capped at 0.05),
    before any retrieval, and retrieval count is not an argument."""
    expected = derive_expected_history_effect(MANIFEST, HISTORY_FIXTURE)

    assert expected == 0.03
    assert derive_expected_history_effect.__doc__ is not None


def test_wrong_scope_fails_closed(tmp_path: Path) -> None:
    item = replace(
        make_history_item(),
        scope=Scope(domain=ScopeDomain.USER, user_id="user-other"),
    )

    with pytest.raises(ValueError, match="scope"):
        audit_repeated_history(
            item,
            make_pattern_summary(),
            retrievals=3,
            root=tmp_path,
            repository_root=ROOT,
        )


def test_item_summary_association_mismatch_fails_closed(tmp_path: Path) -> None:
    summary = replace(make_pattern_summary(), matched_refs=("some-other-item",))

    with pytest.raises(ValueError, match="matched_refs"):
        audit_repeated_history(
            make_history_item(),
            summary,
            retrievals=3,
            root=tmp_path,
            repository_root=ROOT,
        )


def test_duplicate_summary_id_in_bundle_fails_closed(tmp_path: Path) -> None:
    fixture = load_history_fixture(HISTORY_FIXTURE)
    bundle = replace(
        fixture.bundle,
        pattern_summaries=(fixture.bundle.pattern_summaries[0],) * 2,
    )

    with pytest.raises(ValueError, match="duplicate summary"):
        audit_repeated_history(
            make_history_item(),
            make_pattern_summary(),
            retrievals=3,
            bundle=bundle,
            root=tmp_path,
            repository_root=ROOT,
        )


def test_changed_summary_identity_fails_closed(tmp_path: Path) -> None:
    summary = replace(make_pattern_summary(), summary_id="history-g27-summary-changed")

    with pytest.raises(ValueError, match="summary identity"):
        audit_repeated_history(
            make_history_item(),
            summary,
            retrievals=3,
            root=tmp_path,
            repository_root=ROOT,
        )


def test_changed_item_identity_fails_closed(tmp_path: Path) -> None:
    item = replace(make_history_item(), item_id="history-g27-item-changed")

    with pytest.raises(ValueError, match="item identity"):
        audit_repeated_history(
            item,
            make_pattern_summary(),
            retrievals=3,
            root=tmp_path,
            repository_root=ROOT,
        )


def test_retrieval_count_mismatch_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="retrieval_count"):
        audit_repeated_history(
            make_history_item(),
            make_pattern_summary(),
            retrievals=2,
            root=tmp_path,
            repository_root=ROOT,
        )


def test_retrieval_metadata_cannot_change_effect_amount(tmp_path: Path) -> None:
    """A summary whose match_count/confidence would change the observed
    amount fails the audit: retrieval metadata cannot alter the effect."""
    summary = replace(make_pattern_summary(), match_count=3)
    expected = derive_expected_history_effect(MANIFEST, HISTORY_FIXTURE)
    assert expected == 0.03  # fixture-derived; the mutated summary must not win

    with pytest.raises(ValueError, match="effect amount"):
        audit_repeated_history(
            make_history_item(),
            summary,
            retrievals=3,
            root=tmp_path,
            repository_root=ROOT,
        )


def test_triple_contribution_fails_closed(tmp_path: Path) -> None:
    """Three summaries would produce three history contributions: rejected."""
    fixture = load_history_fixture(HISTORY_FIXTURE)
    second = replace(
        fixture.bundle.pattern_summaries[0],
        summary_id="history-g27-summary-2",
        matched_refs=(fixture.bundle.episodes[0].item_id,),
    )
    third = replace(
        fixture.bundle.pattern_summaries[0],
        summary_id="history-g27-summary-3",
        matched_refs=(fixture.bundle.episodes[0].item_id,),
    )
    bundle = replace(
        fixture.bundle,
        pattern_summaries=(fixture.bundle.pattern_summaries[0], second, third),
    )

    with pytest.raises(ValueError, match="exactly one summary"):
        audit_repeated_history(
            make_history_item(),
            make_pattern_summary(),
            retrievals=3,
            bundle=bundle,
            root=tmp_path,
            repository_root=ROOT,
        )


def test_new_relation_in_bundle_fails_closed(tmp_path: Path) -> None:
    fixture = load_history_fixture(HISTORY_FIXTURE)
    bundle = replace(
        fixture.bundle,
        relationship_events=(
            replace(
                fixture.bundle.episodes[0],
                item_id="history-g27-relation-1",
                kind="relationship_event",
            ),
        ),
    )

    with pytest.raises(ValueError, match="relationship"):
        audit_repeated_history(
            make_history_item(),
            make_pattern_summary(),
            retrievals=3,
            bundle=bundle,
            root=tmp_path,
            repository_root=ROOT,
        )


def test_bundle_identity_change_fails_closed(tmp_path: Path) -> None:
    """A mutated bundle whose identity differs from the verified fixture is
    rejected. (Persona-change protection is indirect: every effective persona
    setting is bound by the runtime-config payload hashes.)"""
    fixture = load_history_fixture(HISTORY_FIXTURE)
    bundle = replace(fixture.bundle, bundle_id="history-g27-bundle-mutated")

    with pytest.raises(ValueError, match="bundle identity"):
        audit_repeated_history(
            make_history_item(),
            make_pattern_summary(),
            retrievals=3,
            bundle=bundle,
            root=tmp_path,
            repository_root=ROOT,
        )


def test_result_rejects_malformed_contracts() -> None:
    from mind_runtime.validation.history_audit import DecisionInfluence

    def influence(index: int) -> DecisionInfluence:
        return DecisionInfluence(
            decision_index=index,
            contribution_refs=("history-g27-summary-1",),
            effect_amount=0.03,
        )

    base = HistoryAuditResult(
        unique_source_count=1,
        retrieval_count=3,
        influence_multiplier=1.0,
        reinforced=False,
        decision_influences=(influence(0), influence(1), influence(2)),
        match_count_unchanged=True,
        effect_amount_unchanged=True,
        expected_effect_amount=0.03,
        bundle_hashes=("a" * 64,),
        durable_row_counts=(),
    )
    with pytest.raises(ValueError, match="unique_source_count"):
        replace(base, unique_source_count=0)
    with pytest.raises(ValueError, match="retrieval_count"):
        replace(base, retrieval_count=0)
    with pytest.raises(ValueError, match="influence_multiplier"):
        replace(base, influence_multiplier=2.0)
    with pytest.raises(ValueError, match="reinforced"):
        replace(base, reinforced="no")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="expected_effect_amount"):
        replace(base, expected_effect_amount=float("nan"))
    with pytest.raises(ValueError, match="SHA-256"):
        replace(base, bundle_hashes=("bad",))
    with pytest.raises(ValueError, match="decision_index"):
        replace(
            base,
            decision_influences=(
                DecisionInfluence(
                    decision_index=-1,
                    contribution_refs=("history-g27-summary-1",),
                    effect_amount=0.03,
                ),
            ),
        )


def test_durable_roots_are_independent_and_tables_unchanged(tmp_path: Path) -> None:
    result = audit_repeated_history(
        make_history_item(),
        make_pattern_summary(),
        retrievals=3,
        root=tmp_path,
        repository_root=ROOT,
    )
    assert result.unique_source_count == 1
    assert result.durable_row_counts != ()
    for _plane, counts in result.durable_row_counts:
        assert all(count >= 0 for _table, count in counts)


def test_non_uniform_row_count_growth_fails_closed() -> None:
    """A later surfacing that writes extra durable rows is rejected."""
    from mind_runtime.validation.history_audit import _require_uniform_deltas

    uniform = (
        (
            "facts",
            (("interactions", 1), ("evidence", 1), ("observations", 1)),
        ),
        (
            "state",
            (("states", 0), ("state_transitions", 4), ("state_definitions", 0)),
        ),
        ("intents", (("intents", 1), ("intent_history", 2), ("intent_transitions", 1))),
        ("checkpoints", (("checkpoints", 0),)),
    )
    _require_uniform_deltas([uniform, uniform, uniform])

    grown = (
        ("facts", (("interactions", 2), ("evidence", 2), ("observations", 2))),
        (
            "state",
            (("states", 0), ("state_transitions", 5), ("state_definitions", 0)),
        ),
        ("intents", (("intents", 2), ("intent_history", 3), ("intent_transitions", 2))),
        ("checkpoints", (("checkpoints", 0),)),
    )
    with pytest.raises(ValueError, match="non-uniformly"):
        _require_uniform_deltas([uniform, uniform, grown])


def test_decision_influence_rejects_malformed_records() -> None:
    from mind_runtime.validation.history_audit import DecisionInfluence

    with pytest.raises(ValueError, match="decision_index"):
        DecisionInfluence(decision_index=True, contribution_refs=("s",), effect_amount=1.0)
    with pytest.raises(ValueError, match="decision_index"):
        DecisionInfluence(decision_index=-1, contribution_refs=("s",), effect_amount=1.0)
    with pytest.raises(ValueError, match="contribution_refs"):
        DecisionInfluence(decision_index=0, contribution_refs=(), effect_amount=1.0)
    with pytest.raises(ValueError, match="contribution refs"):
        DecisionInfluence(decision_index=0, contribution_refs=(" ",), effect_amount=1.0)
    with pytest.raises(ValueError, match="effect_amount"):
        DecisionInfluence(decision_index=0, contribution_refs=("s",), effect_amount=True)
    with pytest.raises(ValueError, match="effect_amount"):
        DecisionInfluence(decision_index=0, contribution_refs=("s",), effect_amount=float("nan"))


def test_result_rejects_remaining_malformed_contracts() -> None:
    from mind_runtime.validation.history_audit import DecisionInfluence

    def make(**changes: object) -> HistoryAuditResult:
        influence = DecisionInfluence(
            decision_index=0, contribution_refs=("history-g27-summary-1",), effect_amount=0.03
        )
        base = HistoryAuditResult(
            unique_source_count=1,
            retrieval_count=1,
            influence_multiplier=1.0,
            reinforced=False,
            decision_influences=(influence,),
            match_count_unchanged=True,
            effect_amount_unchanged=True,
            expected_effect_amount=0.03,
            bundle_hashes=("a" * 64,),
            durable_row_counts=(),
        )
        return replace(base, **cast(Any, changes))

    with pytest.raises(ValueError, match="unique_source_count"):
        make(unique_source_count=0)
    with pytest.raises(ValueError, match="unique_source_count"):
        make(unique_source_count=True)
    with pytest.raises(ValueError, match="retrieval_count"):
        make(retrieval_count=0)
    with pytest.raises(ValueError, match="influence_multiplier"):
        make(influence_multiplier=0.5)
    with pytest.raises(ValueError, match="influence_multiplier"):
        make(influence_multiplier=float("nan"))
    with pytest.raises(ValueError, match="reinforced"):
        make(reinforced=1)
    with pytest.raises(ValueError, match="immutable tuple"):
        make(decision_influences=[])
    with pytest.raises(ValueError, match="DecisionInfluence"):
        make(decision_influences=(("not", "an", "influence"),))
    with pytest.raises(ValueError, match="cover every retrieval"):
        make(decision_influences=())
    with pytest.raises(ValueError, match="indices"):
        make(
            decision_influences=(
                DecisionInfluence(
                    decision_index=1,
                    contribution_refs=("history-g27-summary-1",),
                    effect_amount=0.03,
                ),
            )
        )
    with pytest.raises(ValueError, match="match_count_unchanged"):
        make(match_count_unchanged="yes")
    with pytest.raises(ValueError, match="effect_amount_unchanged"):
        make(effect_amount_unchanged="yes")
    with pytest.raises(ValueError, match="expected_effect_amount"):
        make(expected_effect_amount=True)
    with pytest.raises(ValueError, match="bundle_hashes"):
        make(bundle_hashes=())
    with pytest.raises(ValueError, match="bundle_hashes"):
        make(bundle_hashes=("short",))
    with pytest.raises(ValueError, match="immutable tuple"):
        make(durable_row_counts=[])
    with pytest.raises(ValueError, match="plane names"):
        make(durable_row_counts=((" ", (("t", 1),)),))
    with pytest.raises(ValueError, match="immutable tuples"):
        make(durable_row_counts=(("facts", [("t", 1)]),))
    with pytest.raises(ValueError, match="non-negative integers"):
        make(durable_row_counts=(("facts", (("t", -1),)),))
    with pytest.raises(ValueError, match="non-negative integers"):
        make(durable_row_counts=(("facts", (("t", True),)),))
    with pytest.raises(ValueError, match="non-negative integers"):
        make(durable_row_counts=(("facts", ((" ", 1),)),))


def test_expected_effect_low_confidence_returns_zero(tmp_path: Path) -> None:
    """A summary below the manifest confidence gate contributes zero."""
    import json

    from mind_runtime.validation import derive_expected_history_effect

    raw = json.loads(HISTORY_FIXTURE.read_text(encoding="utf-8"))
    raw["bundle"]["pattern_summaries"][0]["confidence"] = 0.1
    path = tmp_path / "history-low.json"
    path.write_text(json.dumps(raw), encoding="utf-8")

    assert derive_expected_history_effect(MANIFEST, path) == 0.0


def test_low_confidence_summary_has_no_applied_contribution(tmp_path: Path) -> None:
    """A summary below the confidence gate produces no applied history
    contribution: the audit fails closed."""
    fixture = load_history_fixture(HISTORY_FIXTURE)
    low_confidence = replace(fixture.bundle.pattern_summaries[0], confidence=0.1)

    with pytest.raises(ValueError, match="exactly one summary contribution"):
        audit_repeated_history(
            fixture.bundle.episodes[0],
            low_confidence,
            retrievals=3,
            root=tmp_path,
            repository_root=ROOT,
        )


def test_bundle_structural_checks_fail_closed(tmp_path: Path) -> None:
    fixture = load_history_fixture(HISTORY_FIXTURE)
    item = fixture.bundle.episodes[0]
    summary = fixture.bundle.pattern_summaries[0]
    with pytest.raises(ValueError, match="bundle identity"):
        audit_repeated_history(
            item,
            summary,
            retrievals=3,
            bundle=replace(fixture.bundle, provider_trace="mutated-trace"),
            root=tmp_path,
            repository_root=ROOT,
        )
    with pytest.raises(ValueError, match="certification scope"):
        audit_repeated_history(
            item,
            summary,
            retrievals=3,
            bundle=replace(
                fixture.bundle,
                scope=Scope(domain=ScopeDomain.USER, user_id="user-other"),
            ),
            root=tmp_path,
            repository_root=ROOT,
        )
    extra_episode = replace(fixture.bundle.episodes[0], item_id="history-g27-extra-item")
    with pytest.raises(ValueError, match="exactly the supplied item"):
        audit_repeated_history(
            item,
            summary,
            retrievals=3,
            bundle=replace(fixture.bundle, episodes=(item, extra_episode)),
            root=tmp_path,
            repository_root=ROOT,
        )


def test_missing_plan_cancelled_rule_fails_closed() -> None:
    from mind_runtime.validation.history_audit import _find_plan_cancelled_rule

    with pytest.raises(ValueError, match="plan_cancelled"):
        _find_plan_cancelled_rule({"rules": ({"event_kind": "other"},)})


def test_missing_anxiety_dimension_fails_closed() -> None:
    from mind_runtime.validation.history_audit import _anxiety_sensitivity

    class FakeDimension:
        dimension = "agent.affect.other"
        sensitivity = 0.5

    class FakeProfile:
        dimensions = (FakeDimension(),)

    class FakeDecoded:
        persona_profile = FakeProfile()

    with pytest.raises(ValueError, match="anxiety"):
        _anxiety_sensitivity(cast(Any, FakeDecoded()))


def test_capture_history_amount_fails_closed_without_trace() -> None:
    from mind_runtime.validation.history_audit import _capture_history_amount

    with pytest.raises(ValueError, match="no transition result"):
        _capture_history_amount(None, "history-g27-summary-1")


def test_immutable_bundle_check_fails_closed(tmp_path: Path) -> None:
    from mind_runtime.validation import sha256_bytes
    from mind_runtime.validation.digest import canonical_json_bytes
    from mind_runtime.validation.history_audit import _require_immutable_bundle

    fixture = load_history_fixture(HISTORY_FIXTURE)
    bundle = fixture.bundle
    pre_hash = sha256_bytes(canonical_json_bytes(bundle))
    _require_immutable_bundle(bundle, pre_hash)
    with pytest.raises(ValueError, match="immutable"):
        _require_immutable_bundle(bundle, "0" * 64)


def test_certification_requires_an_empty_root(tmp_path: Path) -> None:
    (tmp_path / "preexisting.txt").write_text("not empty", encoding="utf-8")

    with pytest.raises(ValueError, match="empty"):
        audit_repeated_history(
            make_history_item(),
            make_pattern_summary(),
            retrievals=3,
            root=tmp_path,
            repository_root=ROOT,
        )


def test_default_repository_root_resolves_checked_out_source(tmp_path: Path) -> None:
    result = audit_repeated_history(
        make_history_item(),
        make_pattern_summary(),
        retrievals=3,
        root=tmp_path,
    )
    assert result.unique_source_count == 1


def test_valid_supplied_bundle_is_accepted(tmp_path: Path) -> None:
    fixture = load_history_fixture(HISTORY_FIXTURE)
    result = audit_repeated_history(
        fixture.bundle.episodes[0],
        fixture.bundle.pattern_summaries[0],
        retrievals=3,
        bundle=fixture.bundle,
        root=tmp_path,
        repository_root=ROOT,
    )
    assert result.unique_source_count == 1
    assert result.effect_amount_unchanged


def test_inventory_change_detected() -> None:
    from mind_runtime.validation.history_audit import _require_unchanged_inventory

    _require_unchanged_inventory({"facts": ("evidence",)}, {"facts": ("evidence",)})
    with pytest.raises(ValueError, match="inventories"):
        _require_unchanged_inventory({"facts": ("evidence",)}, {"facts": ("states",)})
