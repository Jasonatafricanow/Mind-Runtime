"""D11S 30/90-day certification through three empty canonical compositions."""

import subprocess
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import pytest

from mind_runtime.facts.persistence import SqliteFactBackend
from mind_runtime.validation import CertificationPlan, load_horizon_template, sha256_bytes
from mind_runtime.validation.invariants import (
    LongHorizonCertification,
    _run_in_empty_root,
    certify_horizon,
    long_horizon_semantic_hash,
)

ROOT = Path(__file__).parents[2]
INPUTS = ROOT / "certification/d11s/inputs"
MANIFEST = INPUTS / "runtime-config.json"
HEAD = subprocess.run(
    ["git", "rev-parse", "--verify", "HEAD"],
    cwd=ROOT,
    check=True,
    capture_output=True,
    text=True,
).stdout.strip()

EXPECTED_PATHS = {
    "neutral_noop",
    "positive_typed_event",
    "negative_typed_event",
    "idempotent_replay",
    "false_history",
    "authoritative_correction",
    "near_upper_bound",
    "near_lower_bound",
    "intent_due",
    "intent_expired",
    "intent_reconsidered",
    "return_to_baseline",
    "restart_checkpoint",
}
Certified30 = tuple[CertificationPlan, Path, LongHorizonCertification]


def make_plan(days: int) -> CertificationPlan:
    template = load_horizon_template(INPUTS / f"horizon-{days}.json")
    return CertificationPlan(
        certification_id=template.certification_id,
        source_head=HEAD,
        persona_version=template.persona_version,
        runtime_config_manifest_sha256=sha256_bytes(MANIFEST.read_bytes()),
        horizon_days=template.horizon_days,
        started_at=template.started_at,
        events=template.events,
        checkpoint_interval=template.checkpoint_interval,
    )


@pytest.fixture(scope="module")
def certified_30(tmp_path_factory: pytest.TempPathFactory) -> Certified30:
    root = tmp_path_factory.mktemp("certified-30")
    plan = make_plan(30)
    return plan, root, certify_horizon(plan, root=root, repository_root=ROOT)


@pytest.mark.parametrize("days", [30, 90])
def test_fixed_horizon_is_bounded_and_byte_replayable(days: int, tmp_path: Path) -> None:
    plan = make_plan(days)

    result = certify_horizon(plan, root=tmp_path, repository_root=ROOT)

    assert result.virtual_horizon_days == days
    assert result.source_head == HEAD
    assert result.input_sha256 == sha256_bytes((INPUTS / f"horizon-{days}.json").read_bytes())
    assert result.runtime_config_manifest_sha256 == sha256_bytes(MANIFEST.read_bytes())
    assert result.first_run_daily_digests == result.replay_daily_digests
    assert result.first_run_record_hashes == result.replay_record_hashes
    # Both control roots are independent counterfactuals: their record
    # streams differ from the treatment (and from each other).
    assert result.history_control_run_record_hashes != result.first_run_record_hashes
    assert result.no_duplicate_control_run_record_hashes != result.first_run_record_hashes
    assert result.history_control_run_record_hashes != result.no_duplicate_control_run_record_hashes
    assert len(result.first_run_daily_digests) == days + 1
    assert {item.code for item in result.invariants} == {
        "state.boundedness",
        "replay.semantic_records",
        "time.registered_dynamics",
        "history.no_self_excitation",
        "history.false_history_reversible",
    }
    assert all(item.passed for item in result.invariants)
    assert result.wall_clock_execution_seconds >= 0
    assert result.semantic_sha256 == long_horizon_semantic_hash(result)
    for run_name in (
        "first-run",
        "replay-run",
        "history-control-run",
        "no-duplicate-control-run",
    ):
        assert (tmp_path / run_name / "facts.sqlite").is_file()


@pytest.mark.parametrize("days", [30, 90])
def test_templates_decode_every_required_event_without_augmentation(days: int) -> None:
    plan = make_plan(days)

    assert {event.expected_path for event in plan.events} == EXPECTED_PATHS
    assert tuple(event.event_id for event in plan.events) == tuple(
        event.event_id for event in load_horizon_template(INPUTS / f"horizon-{days}.json").events
    )


def test_all_runs_persist_only_exact_template_evidence(certified_30: Certified30) -> None:
    plan, root, _result = certified_30

    expected_evidence_ids = tuple(
        dict.fromkeys(evidence.id for event in plan.events for evidence in event.evidence)
    )
    # The duplicate event still opens its audit Interaction in the treatment
    # runs (ADR-0009 §3); the no-duplicate control derives from the template
    # with that event removed, so it opens one fewer Interaction.
    total_events = len(plan.events)
    duplicate_event = next(
        event for event in plan.events if event.expected_path == "idempotent_replay"
    )
    for run_name, expected_interactions in (
        ("first-run", total_events),
        ("replay-run", total_events),
        ("history-control-run", total_events),
        ("no-duplicate-control-run", total_events - 1),
    ):
        backend = SqliteFactBackend(root / run_name / "facts.sqlite")
        try:
            assert tuple(item.id for item, _interaction_id in backend.load_evidence()) == (
                expected_evidence_ids
            )
            assert len(backend.load_interactions()) == expected_interactions
            assert all(
                item.source_type != "assistant_expression"
                for item, _interaction_id in backend.load_evidence()
            )
            if run_name != "no-duplicate-control-run":
                assert any(
                    item.interaction_id.endswith(f"{duplicate_event.event_id}:interaction")
                    for item in backend.load_interactions()
                )
            else:
                assert not any(
                    item.interaction_id.endswith(f"{duplicate_event.event_id}:interaction")
                    for item in backend.load_interactions()
                )
        finally:
            backend.close()


def test_semantic_hash_excludes_wall_clock_metadata(certified_30: Certified30) -> None:
    _plan, _root, result = certified_30
    changed = replace(
        result,
        wall_clock_execution_seconds=result.wall_clock_execution_seconds + 123.0,
    )

    assert long_horizon_semantic_hash(changed) == result.semantic_sha256


def test_certification_requires_an_empty_root(tmp_path: Path) -> None:
    (tmp_path / "preexisting.txt").write_text("not empty", encoding="utf-8")

    with pytest.raises(ValueError, match="empty"):
        certify_horizon(make_plan(30), root=tmp_path, repository_root=ROOT)


def test_certification_rejects_source_head_mismatch(tmp_path: Path) -> None:
    plan = replace(make_plan(30), source_head="0" * 40)

    with pytest.raises(ValueError, match="source HEAD"):
        certify_horizon(plan, root=tmp_path, repository_root=ROOT)


def test_certification_rejects_runtime_manifest_mismatch(tmp_path: Path) -> None:
    plan = replace(make_plan(30), runtime_config_manifest_sha256="f" * 64)

    with pytest.raises(ValueError, match="runtime manifest"):
        certify_horizon(plan, root=tmp_path, repository_root=ROOT)


def test_certification_rejects_plan_not_decoded_from_template(tmp_path: Path) -> None:
    plan = replace(make_plan(30), certification_id="changed-certification")

    with pytest.raises(ValueError, match="exact verified horizon"):
        certify_horizon(plan, root=tmp_path, repository_root=ROOT)


def test_default_repository_root_resolves_checked_out_source(tmp_path: Path) -> None:
    assert certify_horizon(make_plan(30), root=tmp_path).source_head == HEAD


def test_history_control_run_requires_the_named_withheld_event(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="named withheld event id"):
        _run_in_empty_root(
            make_plan(30),
            tmp_path,
            ROOT,
            MANIFEST,
            ("stub",),
            history_control_event_id="",
        )


def test_excluded_events_control_requires_named_exclusions(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="at least one named event"):
        _run_in_empty_root(
            make_plan(30),
            tmp_path,
            ROOT,
            MANIFEST,
            ("stub",),
            excluded_event_ids=frozenset(),
        )


def test_excluded_events_control_rejects_an_unknown_event(tmp_path: Path) -> None:
    plan = make_plan(30)
    duplicate_event = next(
        event for event in plan.events if event.expected_path == "idempotent_replay"
    )
    control_plan = replace(
        plan,
        events=tuple(event for event in plan.events if event.event_id != duplicate_event.event_id),
    )
    with pytest.raises(ValueError, match="verified horizon artifact"):
        _run_in_empty_root(
            control_plan,
            tmp_path,
            ROOT,
            MANIFEST,
            ("stub",),
            excluded_event_ids=frozenset({"some-unknown-event"}),
        )


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"source_head": "z" * 40}, "source_head"),
        ({"input_sha256": "bad"}, "input_sha256"),
        ({"runtime_config_manifest_sha256": "bad"}, "runtime_config_manifest_sha256"),
        ({"virtual_horizon_days": 31}, "virtual_horizon_days"),
        ({"wall_clock_execution_seconds": -1.0}, "wall_clock_execution_seconds"),
        ({"wall_clock_execution_seconds": float("nan")}, "wall_clock_execution_seconds"),
        ({"wall_clock_execution_seconds": True}, "wall_clock_execution_seconds"),
        ({"first_run_daily_digests": []}, "immutable tuple"),
        ({"replay_daily_digests": []}, "immutable tuple"),
        ({"first_run_record_hashes": []}, "immutable tuple"),
        ({"replay_record_hashes": []}, "immutable tuple"),
        ({"history_control_run_record_hashes": []}, "immutable tuple"),
        ({"no_duplicate_control_run_record_hashes": []}, "immutable tuple"),
        ({"invariants": []}, "immutable tuple"),
        ({"semantic_sha256": "bad"}, "semantic_sha256"),
    ],
)
def test_long_horizon_result_rejects_malformed_contracts(
    certified_30: Certified30,
    changes: dict[str, object],
    message: str,
) -> None:
    _plan, _root, result = certified_30

    with pytest.raises(ValueError, match=message):
        replace(result, **cast(Any, changes))


def test_long_horizon_result_rejects_duplicate_invariants_and_wrong_semantic_hash(
    certified_30: Certified30,
) -> None:
    _plan, _root, result = certified_30

    with pytest.raises(ValueError, match="unique"):
        replace(result, invariants=(result.invariants[0], result.invariants[0]))
    with pytest.raises(ValueError, match="closed semantic record"):
        replace(result, semantic_sha256="f" * 64)
