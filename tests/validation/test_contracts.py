"""Frozen D11S certification record contracts."""

import json
from dataclasses import fields, replace
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, cast

import pytest

import mind_runtime.validation.contracts as subject
from mind_runtime.validation.contracts import (
    REQUIRED_COMPONENT_IDS,
    ArtifactManifest,
    CertificationPlan,
    CertificationReport,
    DailyDecisionDigest,
    InvariantResult,
    SimulationEvent,
    decode_runtime_manifest,
    load_runtime_config_manifest,
    verify_fixture_artifacts,
)
from mind_runtime.validation.digest import canonical_json_bytes, sha256_bytes

NOW = datetime(2026, 8, 23, tzinfo=UTC)
SHA = "a" * 64


def make_event(**overrides: object) -> SimulationEvent:
    values: dict[str, object] = {
        "event_id": "event-0",
        "at_offset": timedelta(0),
        "evidence": (),
        "historical_context": None,
        "expected_path": "typed_event",
    }
    values.update(overrides)
    return SimulationEvent(**values)  # type: ignore[arg-type]


def make_plan(**overrides: object) -> CertificationPlan:
    values: dict[str, object] = {
        "certification_id": "cert-1",
        "source_head": "7c609f5363404e1884f94c4c0cfd9b609eadcdd0",
        "persona_version": "kayla-v0",
        "runtime_config_manifest_sha256": SHA,
        "horizon_days": 30,
        "started_at": NOW,
        "events": (make_event(),),
        "checkpoint_interval": timedelta(days=1),
    }
    values.update(overrides)
    return CertificationPlan(**values)  # type: ignore[arg-type]


def make_digest(day: int = 0) -> DailyDecisionDigest:
    return DailyDecisionDigest(day, SHA, SHA, SHA, SHA, SHA)


def make_invariant(**overrides: object) -> InvariantResult:
    values: dict[str, object] = {
        "code": "bounded",
        "passed": True,
        "observed": "within bounds",
        "expected": "within bounds",
        "evidence_refs": ("trace-1",),
    }
    values.update(overrides)
    return InvariantResult(**values)  # type: ignore[arg-type]


def make_report(**overrides: object) -> CertificationReport:
    values: dict[str, object] = {
        "certification_id": "cert-1",
        "source_head": "7c609f5363404e1884f94c4c0cfd9b609eadcdd0",
        "input_sha256": SHA,
        "runtime_config_manifest_sha256": SHA,
        "virtual_horizon_days": 30,
        "wall_clock_execution_seconds": 0.25,
        "first_run_daily_digests": tuple(make_digest(day) for day in range(30)),
        "replay_daily_digests": tuple(make_digest(day) for day in range(30)),
        "invariants": (make_invariant(),),
        "certification_sha256": SHA,
    }
    values.update(overrides)
    return CertificationReport(**values)  # type: ignore[arg-type]


def test_plan_accepts_only_fixed_horizons_and_exact_head() -> None:
    with pytest.raises(ValueError, match="horizon_days"):
        make_plan(horizon_days=31)
    with pytest.raises(ValueError, match="source_head"):
        make_plan(source_head=" ")


@pytest.mark.parametrize(
    "source_head",
    [
        "7C609F5363404E1884F94C4C0CFD9B609EADCDD0",
        "7c609f5",
        "g" * 40,
    ],
)
def test_plan_and_report_require_exact_lowercase_git_sha(source_head: str) -> None:
    with pytest.raises(ValueError, match="source_head"):
        make_plan(source_head=source_head)
    with pytest.raises(ValueError, match="source_head"):
        make_report(source_head=source_head)


def test_event_order_and_identity_are_unambiguous() -> None:
    event = make_event(event_id="event-1", at_offset=timedelta(days=1))
    assert event.evidence == tuple(event.evidence)
    with pytest.raises(ValueError, match="non-negative"):
        make_event(at_offset=timedelta(seconds=-1))


def test_report_requires_each_invariant_once_and_all_evidence_refs() -> None:
    duplicate = make_invariant(code="bounded")
    with pytest.raises(ValueError, match="unique"):
        make_report(invariants=(duplicate, duplicate))
    with pytest.raises(ValueError, match="evidence_refs"):
        make_invariant(evidence_refs=())
    with pytest.raises(ValueError, match="invariants"):
        make_report(invariants=())
    assert make_report(invariants=(make_invariant(code="fixture-specific"),)).invariants[
        0
    ].code == ("fixture-specific")


def test_contract_records_are_frozen_slotted_and_have_exact_fields() -> None:
    assert tuple(field.name for field in fields(SimulationEvent)) == (
        "event_id",
        "at_offset",
        "evidence",
        "historical_context",
        "expected_path",
    )
    assert tuple(field.name for field in fields(CertificationPlan)) == (
        "certification_id",
        "source_head",
        "persona_version",
        "runtime_config_manifest_sha256",
        "horizon_days",
        "started_at",
        "events",
        "checkpoint_interval",
    )
    assert not hasattr(make_plan(), "__dict__")
    with pytest.raises((AttributeError, TypeError)):
        make_plan().source_head = "other"  # type: ignore[misc]


def test_report_binds_matching_daily_digest_counts_and_finite_wall_clock() -> None:
    with pytest.raises(ValueError, match="digest"):
        make_report(replay_daily_digests=())
    with pytest.raises(ValueError, match="wall_clock_execution_seconds"):
        make_report(wall_clock_execution_seconds=float("nan"))


@pytest.mark.parametrize(
    "wall_time",
    [True, -0.1, float("nan"), float("inf"), float("-inf")],
)
def test_report_rejects_bool_negative_and_nonfinite_wall_clock(wall_time: object) -> None:
    with pytest.raises(ValueError, match="wall_clock_execution_seconds"):
        make_report(wall_clock_execution_seconds=wall_time)


def test_certification_tuple_fields_reject_mutable_lists() -> None:
    manifest = _manifest()
    plan = make_plan()
    snapshot = subject.DecisionAuthoritySnapshot((), (), (), (), None, None, "none")
    invariant = make_invariant()
    report = make_report()
    root = Path(__file__).parents[2]
    horizon = subject.load_horizon_template(root / "certification/d11s/inputs/horizon-30.json")
    model = subject.load_model_swap_fixture(root / "certification/d11s/inputs/model-swap-left.json")
    restart = subject.load_restart_fixture(root / "certification/d11s/inputs/restart-g12.json")
    decoded = subject.decode_runtime_manifest(manifest)

    invalid_records = (
        lambda: replace(manifest, components=cast(Any, list(manifest.components))),
        lambda: replace(manifest, fixture_artifacts=cast(Any, list(manifest.fixture_artifacts))),
        lambda: replace(plan, events=cast(Any, list(plan.events))),
        lambda: replace(snapshot, accepted_event_refs=cast(Any, [])),
        lambda: replace(snapshot, transition_refs=cast(Any, [])),
        lambda: replace(snapshot, canonical_state_refs=cast(Any, [])),
        lambda: replace(snapshot, candidate_intent_refs=cast(Any, [])),
        lambda: replace(invariant, evidence_refs=cast(Any, ["trace-1"])),
        lambda: replace(
            report,
            first_run_daily_digests=cast(Any, list(report.first_run_daily_digests)),
        ),
        lambda: replace(
            report,
            replay_daily_digests=cast(Any, list(report.replay_daily_digests)),
        ),
        lambda: replace(report, invariants=cast(Any, list(report.invariants))),
        lambda: replace(horizon, events=cast(Any, list(horizon.events))),
        lambda: replace(model, responses=cast(Any, list(model.responses))),
        lambda: replace(restart, states=cast(Any, list(restart.states))),
        lambda: replace(decoded.intent_engine, rules=cast(Any, list(decoded.intent_engine.rules))),
        lambda: replace(decoded, emotional_effects=cast(Any, list(decoded.emotional_effects))),
    )
    for construct in invalid_records:
        with pytest.raises(ValueError, match="immutable tuple"):
            construct()


def test_component_payload_is_recursively_copied_and_frozen() -> None:
    payload: dict[str, object] = {"nested": [{"value": 1}], "label": "fixed"}
    expected = canonical_json_bytes(payload)
    component = subject.RuntimeComponentConfig("fixture", "v1", payload, sha256_bytes(expected))

    nested = cast(list[dict[str, int]], payload["nested"])
    nested[0]["value"] = 2
    payload["new"] = True

    assert canonical_json_bytes(component.payload) == expected
    assert sha256_bytes(canonical_json_bytes(component.payload)) == component.payload_sha256


def test_daily_digest_is_limited_to_the_virtual_horizon() -> None:
    with pytest.raises(ValueError, match="virtual_day"):
        DailyDecisionDigest(-1, SHA, SHA, SHA, SHA, SHA)
    assert make_digest(29).virtual_day == 29


def test_artifact_manifest_requires_repository_relative_path_and_actual_bytes_identity() -> None:
    with pytest.raises(ValueError, match="logical_path"):
        ArtifactManifest("/absolute.json", 1, SHA)
    with pytest.raises(ValueError, match="byte_length"):
        ArtifactManifest("report.json", -1, SHA)


def test_component_registry_is_exact_and_closed() -> None:
    assert REQUIRED_COMPONENT_IDS == frozenset(
        {
            "state_definitions",
            "persona_profile",
            "fact_ingest",
            "effective_state",
            "situation",
            "emotional_effects",
            "historical_context",
            "intent_engine",
            "intent_lifecycle",
            "action_policy",
            "policy_resources",
            "decision_context",
            "context_renderer",
            "expression_guard",
            "expression_coordinator",
            "previous_expression",
            "checkpoint_policy",
            "semantic_provider",
            "receipt_registry",
            "slow_plasticity",
            "appraisal_producer_strategy",
            "homeostasis",
        }
    )


def test_checked_in_manifest_binds_and_decodes_every_effective_component() -> None:
    root = Path(__file__).parents[2]
    manifest = load_runtime_config_manifest(root / "certification/d11s/inputs/runtime-config.json")
    verify_fixture_artifacts(manifest, root)
    decoded = decode_runtime_manifest(manifest)
    assert frozenset(field.name for field in fields(decoded)) == REQUIRED_COMPONENT_IDS


def _manifest() -> subject.RuntimeConfigManifest:
    root = Path(__file__).parents[2]
    return load_runtime_config_manifest(root / "certification/d11s/inputs/runtime-config.json")


def test_all_record_guards_reject_malformed_identity_time_and_collections(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(ValueError, match="hexadecimal"):
        subject._require_hash("A" * 64, "hash")
    with pytest.raises(ValueError, match="UTC"):
        subject._require_utc(datetime(2026, 8, 23, tzinfo=timezone(timedelta(hours=2))), "at")
    monkeypatch.setattr(subject, "require_aware_utc", lambda value, name: None)
    with pytest.raises(ValueError, match="UTC"):
        subject._require_utc(datetime(2026, 8, 23, tzinfo=timezone(timedelta(hours=2))), "at")
    with pytest.raises(ValueError, match="immutable"):
        make_event(evidence=cast(Any, []))
    with pytest.raises(ValueError, match="Evidence"):
        make_event(evidence=cast(Any, (object(),)))
    with pytest.raises(ValueError, match="HistoricalContextBundle"):
        make_event(historical_context=cast(Any, object()))
    with pytest.raises(ValueError, match="payload"):
        subject.RuntimeComponentConfig("x", "v1", cast(Any, {}), SHA)
    with pytest.raises(ValueError, match="byte_length"):
        subject.InputArtifactRef("x.json", True, SHA)
    with pytest.raises(ValueError, match="repository-relative"):
        subject.ArtifactManifest("..\\x.json", 0, SHA)


def test_manifest_plan_snapshot_digest_invariant_and_report_rejection_paths() -> None:
    manifest = _manifest()
    with pytest.raises(ValueError, match="unique"):
        replace(manifest, components=(manifest.components[0],) * len(REQUIRED_COMPONENT_IDS))
    with pytest.raises(ValueError, match="closed registry"):
        replace(manifest, components=manifest.components[:-1])
    with pytest.raises(ValueError, match="unique"):
        replace(manifest, fixture_artifacts=(manifest.fixture_artifacts[0],) * 2)
    with pytest.raises(ValueError, match="recovery_horizon_days"):
        replace(manifest, recovery_horizon_days=True)
    with pytest.raises(ValueError, match="convergence_tolerance"):
        replace(manifest, convergence_tolerance=" ")
    with pytest.raises(ValueError, match="must not be empty"):
        subject._persona({"persona_id": "kayla", "version": 1, "dimensions": []})
    with pytest.raises(ValueError, match="positive integer"):
        subject._context(
            {
                "allowed_situation_facts": [],
                "affect_rules": [],
                "persona_style_constraints": [],
                "allowed_history_kinds": [],
                "max_history_items": 0,
                "max_prior_expression_chars": 1,
                "max_item_chars": 1,
                "max_items": 1,
                "max_render_chars": 1,
            }
        )
    with pytest.raises(ValueError, match="unique"):
        make_plan(events=(make_event(event_id="same"), make_event(event_id="same")))
    with pytest.raises(ValueError, match="exceed"):
        make_plan(events=(make_event(at_offset=timedelta(days=31)),))
    with pytest.raises(ValueError, match="checkpoint_interval"):
        make_plan(checkpoint_interval=timedelta(0))
    with pytest.raises(ValueError, match="checkpoint_interval"):
        make_plan(checkpoint_interval=timedelta(days=1, microseconds=1))
    with pytest.raises(ValueError, match="aware"):
        make_plan(started_at=datetime(2026, 8, 23))
    with pytest.raises(ValueError, match="accepted_event_refs"):
        subject.DecisionAuthoritySnapshot(("",), (), (), (), None, None, "none")
    with pytest.raises(ValueError, match="selected_intent_ref"):
        subject.DecisionAuthoritySnapshot((), (), (), (), "", None, "none")
    with pytest.raises(ValueError, match="policy_result_ref"):
        subject.DecisionAuthoritySnapshot((), (), (), (), None, "", "none")
    with pytest.raises(ValueError, match="checkpoint_recovery"):
        subject.DecisionAuthoritySnapshot((), (), (), (), None, None, "")
    with pytest.raises(ValueError, match="non-negative"):
        subject.DailyDecisionDigest(True, SHA, SHA, SHA, SHA, SHA)
    with pytest.raises(ValueError, match="canonical_state_hash"):
        subject.DailyDecisionDigest(0, "x", SHA, SHA, SHA, SHA)
    with pytest.raises(ValueError, match="passed"):
        make_invariant(passed=cast(Any, 1))
    with pytest.raises(ValueError, match="evidence_refs entries"):
        make_invariant(evidence_refs=("",))
    with pytest.raises(ValueError, match="virtual_horizon_days"):
        make_report(virtual_horizon_days=31)
    with pytest.raises(ValueError, match="wall_clock_execution_seconds"):
        make_report(wall_clock_execution_seconds=-0.1)
    with pytest.raises(ValueError, match="first_run_daily_digests"):
        make_report(first_run_daily_digests=tuple(make_digest(day) for day in range(29)))
    with pytest.raises(ValueError, match="replay_daily_digests"):
        make_report(replay_daily_digests=tuple(make_digest(day) for day in range(29)))
    with pytest.raises(ValueError, match="first_run daily"):
        make_report(
            first_run_daily_digests=(make_digest(1),)
            + tuple(make_digest(day) for day in range(1, 30))
        )
    with pytest.raises(ValueError, match="replay daily"):
        make_report(
            replay_daily_digests=(make_digest(1),) + tuple(make_digest(day) for day in range(1, 30))
        )
    failed_report = make_report(invariants=(make_invariant(passed=False),))
    assert failed_report.invariants[0].passed is False
    with pytest.raises(ValueError, match="invariants"):
        make_report(invariants=())


def test_closed_component_decoders_reject_schema_drift_and_invalid_values() -> None:
    manifest = _manifest()
    components = {item.component_id: item for item in manifest.components}
    for component in components.values():
        payload = {**component.payload, "unexpected": True}
        forged = replace(
            component,
            payload=payload,
            payload_sha256=sha256_bytes(canonical_json_bytes(payload)),
        )
        with pytest.raises(ValueError):
            subject.decode_component(forged)
    invalid_payloads: dict[str, dict[str, object]] = {
        "state_definitions": {"definitions": []},
        "persona_profile": {"persona_id": "kayla_v0", "version": 1, "dimensions": []},
        "fact_ingest": {"backend": "memory", "clock": "simulation"},
        "effective_state": {
            "definitions_component": "implicit",
            "state_backend": "sqlite",
        },
        "emotional_effects": {"rules": []},
        "historical_context": {
            "mode": "disabled",
            "provider_mode": "none",
            "budget": 0,
        },
        "intent_engine": {"runtime_id": "d11s-runtime-1", "rules": []},
        "intent_lifecycle": {"backend": "memory"},
        "action_policy": {"proactive_cooldown": 0, "rules": []},
        "context_renderer": {"config_component": "implicit"},
        "expression_coordinator": {"max_rewrites": True},
        "previous_expression": {"mode": "fixed", "expression": None},
        "checkpoint_policy": {"interval": 0, "backend": "sqlite"},
        "semantic_provider": {
            "mode": "disabled",
            "minimum_confidence": True,
            "conflict_margin": 0.1,
        },
        "receipt_registry": {"mode": "sqlite"},
    }
    for component_id, payload in invalid_payloads.items():
        component = components[component_id]
        forged = replace(
            component,
            payload=payload,
            payload_sha256=sha256_bytes(canonical_json_bytes(payload)),
        )
        with pytest.raises(ValueError):
            subject.decode_component(forged)
    component = components["receipt_registry"]
    with pytest.raises(ValueError, match="unknown component"):
        subject.decode_component(replace(component, component_id="unknown"))
    with pytest.raises(ValueError, match="schema_version"):
        subject.decode_component(replace(component, schema_version="v2"))
    with pytest.raises(ValueError, match="payload hash"):
        subject.decode_component(replace(component, payload_sha256=SHA))
    with pytest.raises(ValueError, match="keys"):
        subject._mapping({"extra": 1}, set(), "component")


def test_manifest_loader_and_fixture_verifier_fail_closed_for_disk_mutation(tmp_path: Path) -> None:
    manifest_path = Path(__file__).parents[2] / "certification/d11s/inputs/runtime-config.json"
    assert subject.decode_runtime_config_manifest_bytes(
        manifest_path.read_bytes()
    ) == subject.load_runtime_config_manifest(manifest_path)
    with pytest.raises(TypeError, match="must be bytes"):
        subject.decode_runtime_config_manifest_bytes(cast(Any, "not-bytes"))
    with pytest.raises(ValueError, match="valid UTF-8 JSON"):
        subject.decode_runtime_config_manifest_bytes(b"\xff")

    with pytest.raises(ValueError, match="valid UTF-8 JSON"):
        subject.load_runtime_config_manifest(tmp_path / "missing.json")
    invalid = tmp_path / "invalid.json"
    invalid.write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="schema drift"):
        subject.load_runtime_config_manifest(invalid)
    invalid.write_text(
        json.dumps({"manifest_version": "v", "components": {}, "fixture_artifacts": []}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="schema drift"):
        subject.load_runtime_config_manifest(invalid)
    raw = json.loads(
        (Path(__file__).parents[2] / "certification/d11s/inputs/runtime-config.json").read_text(
            encoding="utf-8"
        )
    )
    raw["components"] = {}
    invalid.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ValueError, match="components and fixture_artifacts"):
        subject.load_runtime_config_manifest(invalid)
    raw["components"] = []
    invalid.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ValueError, match="closed registry"):
        subject.load_runtime_config_manifest(invalid)
    raw = json.loads(
        (Path(__file__).parents[2] / "certification/d11s/inputs/runtime-config.json").read_text(
            encoding="utf-8"
        )
    )
    raw["components"][0] = {"component_id": "x"}
    invalid.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ValueError, match="component schema"):
        subject.load_runtime_config_manifest(invalid)
    raw = json.loads(
        (Path(__file__).parents[2] / "certification/d11s/inputs/runtime-config.json").read_text(
            encoding="utf-8"
        )
    )
    raw["fixture_artifacts"][0] = {"logical_path": "x"}
    invalid.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ValueError, match="fixture artifact schema"):
        subject.load_runtime_config_manifest(invalid)
    manifest = _manifest()
    with pytest.raises(ValueError, match="missing fixture"):
        subject.verify_fixture_artifacts(manifest, tmp_path)
    path = tmp_path / manifest.fixture_artifacts[0].logical_path
    path.parent.mkdir(parents=True)
    path.write_bytes(b"changed")
    with pytest.raises(ValueError, match="bytes do not match"):
        subject.verify_fixture_artifacts(manifest, tmp_path)
