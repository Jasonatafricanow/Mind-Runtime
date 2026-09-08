import subprocess
import time
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import pytest

from mind_runtime.contracts import IntentStatus
from mind_runtime.pipeline.checkpoints import RecoveryDecision
from mind_runtime.pipeline.fake_agent import FakeAgent
from mind_runtime.validation import (
    CanonicalCertificationComposition,
    CertificationPlan,
    CertificationRuntimeConfig,
    DurablePaths,
    HorizonDayCapture,
    HorizonRun,
    HorizonRunner,
    SimulationClock,
    build_composition,
    load_horizon_template,
    sha256_bytes,
)
from mind_runtime.validation import composition as composition_subject
from mind_runtime.validation import horizon as horizon_subject
from mind_runtime.validation.contracts import DailyDecisionDigest, DecisionAuthoritySnapshot

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


def make_plan(days: int = 30) -> CertificationPlan:
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


def make_factory(
    root: Path,
) -> Callable[[CertificationPlan, SimulationClock], CanonicalCertificationComposition]:
    def factory(
        plan: CertificationPlan, clock: SimulationClock
    ) -> CanonicalCertificationComposition:
        return build_composition(
            CertificationRuntimeConfig(
                repository_root=ROOT,
                manifest_path=MANIFEST,
                manifest_sha256=plan.runtime_config_manifest_sha256,
                durable_paths=DurablePaths.under(root),
                clock=clock,
                certification_id=plan.certification_id,
                agent=FakeAgent(("当然。",)),
            )
        )

    return factory


@pytest.mark.parametrize("days", [30, 90])
def test_runner_captures_every_virtual_day_without_sleep(
    days: int, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(time, "sleep", lambda _seconds: pytest.fail("sleep forbidden"))

    plan = make_plan(days)
    run = HorizonRunner(make_factory(tmp_path)).run(plan)

    assert tuple(d.virtual_day for d in run.daily_digests) == tuple(range(days + 1))
    assert tuple(c.virtual_day for c in run.daily_captures) == tuple(range(days + 1))
    assert run.virtual_horizon_days == days
    assert run.daily_captures[0].captured_at == plan.started_at
    assert run.daily_captures[-1].captured_at == plan.started_at + timedelta(days=days)
    assert run.wall_clock_execution_seconds >= 0


def test_runner_applies_day_zero_before_its_digest_and_closes_composition(tmp_path: Path) -> None:
    run = HorizonRunner(make_factory(tmp_path)).run(make_plan())

    assert run.daily_captures[0].snapshot.selected_intent_ref is not None
    assert run.daily_captures[0].records.canonical_states
    assert run.daily_captures[0].records.intent_history
    assert run.daily_captures[0].records.transition_results
    assert run.daily_captures[0].records.policy_results
    assert run.daily_captures[0].records.interactions
    assert run.daily_captures[0].records.receipts
    assert run.daily_captures[-1].records.evidence
    assert run.daily_captures[-1].records.observations
    assert run.daily_captures[0].snapshot.checkpoint_recovery == "no_checkpoint"
    assert all(
        len(value) == 64
        for digest in run.daily_digests
        for value in (
            digest.canonical_state_hash,
            digest.pending_intent_hash,
            digest.transition_trace_hash,
            digest.policy_decision_hash,
            digest.checkpoint_recovery_hash,
        )
    )

    facts = DurablePaths.under(tmp_path).facts_db
    assert facts.exists()
    facts.rename(tmp_path / "closed-facts.sqlite")


def test_daily_digest_hashes_full_records_not_only_stable_ids(tmp_path: Path) -> None:
    capture = HorizonRunner(make_factory(tmp_path)).run(make_plan()).daily_captures[0]
    baseline = horizon_subject._daily_digest(capture.virtual_day, capture.records)

    state = capture.records.canonical_states[0]
    assert isinstance(state.value, float)
    changed_state = replace(state, value=state.value + 0.001)
    state_records = replace(
        capture.records,
        canonical_states=(changed_state, *capture.records.canonical_states[1:]),
    )
    assert changed_state.state_id == state.state_id
    assert (
        horizon_subject._daily_digest(capture.virtual_day, state_records).canonical_state_hash
        != baseline.canonical_state_hash
    )

    intent = capture.records.intent_history[0]
    changed_status = (
        IntentStatus.CANDIDATE
        if intent.status is not IntentStatus.CANDIDATE
        else IntentStatus.DEFERRED
    )
    status_records = replace(
        capture.records,
        intent_history=(
            replace(intent, status=changed_status),
            *capture.records.intent_history[1:],
        ),
    )
    assert (
        horizon_subject._daily_digest(capture.virtual_day, status_records).pending_intent_hash
        != baseline.pending_intent_hash
    )

    version_records = replace(
        capture.records,
        intent_history=(
            replace(intent, sync=replace(intent.sync, version=intent.sync.version + 1)),
            *capture.records.intent_history[1:],
        ),
    )
    assert (
        horizon_subject._daily_digest(capture.virtual_day, version_records).pending_intent_hash
        != baseline.pending_intent_hash
    )


def test_runner_rejects_factory_with_noncanonical_result() -> None:
    def invalid_factory(_plan: CertificationPlan, _clock: SimulationClock) -> object:
        return object()

    with pytest.raises(ValueError, match="CanonicalCertificationComposition"):
        HorizonRunner(
            cast(
                Callable[[CertificationPlan, SimulationClock], CanonicalCertificationComposition],
                invalid_factory,
            )
        ).run(make_plan())


@pytest.mark.parametrize(
    "changed_plan",
    [
        lambda plan: replace(plan, source_head="0" * 40),
        lambda plan: replace(plan, certification_id=f"{plan.certification_id}-changed"),
        lambda plan: replace(plan, persona_version=f"{plan.persona_version}-changed"),
        lambda plan: replace(plan, events=tuple(reversed(plan.events))),
        lambda plan: replace(
            plan,
            events=(
                replace(plan.events[0], event_id=f"{plan.events[0].event_id}-changed"),
                *plan.events[1:],
            ),
        ),
        lambda plan: replace(
            plan,
            events=(
                replace(plan.events[0], at_offset=plan.events[0].at_offset + timedelta(hours=1)),
                *plan.events[1:],
            ),
        ),
        lambda plan: replace(plan, started_at=plan.started_at + timedelta(hours=1)),
        lambda plan: replace(plan, checkpoint_interval=timedelta(hours=12)),
    ],
)
def test_runner_rejects_any_plan_not_equal_to_verified_horizon_bytes(
    changed_plan: Callable[[CertificationPlan], CertificationPlan], tmp_path: Path
) -> None:
    plan = changed_plan(make_plan())

    with pytest.raises(ValueError, match="verified horizon artifact"):
        HorizonRunner(make_factory(tmp_path)).run(plan)


def test_runner_rejects_composition_certification_identity_outside_verified_plan(
    tmp_path: Path,
) -> None:
    def mismatched_factory(
        plan: CertificationPlan, clock: SimulationClock
    ) -> CanonicalCertificationComposition:
        return build_composition(
            CertificationRuntimeConfig(
                repository_root=ROOT,
                manifest_path=MANIFEST,
                manifest_sha256=plan.runtime_config_manifest_sha256,
                durable_paths=DurablePaths.under(tmp_path),
                clock=clock,
                certification_id=f"{plan.certification_id}-outside-plan",
                agent=FakeAgent(("当然。",)),
            )
        )

    with pytest.raises(ValueError, match="verified horizon artifact"):
        HorizonRunner(mismatched_factory).run(make_plan())


def test_runner_reverifies_matching_horizon_bytes_before_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan = make_plan()
    horizon_path = INPUTS / "horizon-30.json"
    original = horizon_path.read_bytes()
    real_read_bytes = Path.read_bytes
    horizon_reads = 0

    def attacked_read_bytes(path: Path) -> bytes:
        nonlocal horizon_reads
        if path == horizon_path:
            horizon_reads += 1
            return original if horizon_reads == 1 else original + b" "
        return real_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", attacked_read_bytes)

    with pytest.raises(ValueError, match="horizon artifact bytes"):
        HorizonRunner(make_factory(tmp_path)).run(plan)

    assert horizon_reads == 2


def test_runner_fails_closed_when_matching_horizon_disappears_before_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan = make_plan()
    horizon_path = INPUTS / "horizon-30.json"
    real_read_bytes = Path.read_bytes
    horizon_reads = 0

    def disappearing_read_bytes(path: Path) -> bytes:
        nonlocal horizon_reads
        if path == horizon_path:
            horizon_reads += 1
            if horizon_reads == 2:
                raise OSError("removed after manifest fixture verification")
        return real_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", disappearing_read_bytes)

    with pytest.raises(ValueError, match="horizon artifact is unavailable"):
        HorizonRunner(make_factory(tmp_path)).run(plan)

    assert horizon_reads == 2


def make_contract_run() -> HorizonRun:
    snapshot = DecisionAuthoritySnapshot((), (), (), (), None, None, "no_interaction")
    records = composition_subject._DailyAuthorityRecords(
        snapshot,
        (),
        (),
        (),
        (),
        (),
        (),
        (),
        (),
        (),
        (),
        (),
        (),
        None,
        RecoveryDecision("", None, None, "no_checkpoint"),
    )
    started_at = datetime(2026, 1, 1, tzinfo=UTC)
    captures = tuple(
        HorizonDayCapture(day, started_at + timedelta(days=day), snapshot, records)
        for day in range(31)
    )
    digest = "3" * 64
    digests = tuple(
        DailyDecisionDigest(day, digest, digest, digest, digest, digest) for day in range(31)
    )
    return HorizonRun(30, captures, digests, 0.1)


@pytest.mark.parametrize("value", [float("inf"), float("nan")])
def test_horizon_run_rejects_non_finite_wall_time(value: float) -> None:
    with pytest.raises(ValueError, match="finite"):
        replace(make_contract_run(), wall_clock_execution_seconds=value)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("virtual_horizon_days", 31, "exactly 30 or 90"),
        ("daily_captures", [], "immutable tuples"),
        ("daily_digests", [], "immutable tuples"),
        ("daily_captures", (), "day zero through the final day"),
        ("daily_digests", (), "day zero through the final day"),
        ("wall_clock_execution_seconds", -0.1, "non-negative"),
        ("wall_clock_execution_seconds", True, "non-negative"),
    ],
)
def test_horizon_run_rejects_incomplete_or_mutable_records(
    field: str, value: object, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        replace(make_contract_run(), **{field: cast(Any, value)})


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"virtual_day": -1}, "virtual_day"),
        ({"virtual_day": True}, "virtual_day"),
        ({"captured_at": datetime(2026, 1, 1)}, "aware UTC"),
        ({"snapshot": object()}, "DecisionAuthoritySnapshot"),
        ({"records": object()}, "full daily authority"),
    ],
)
def test_day_capture_rejects_invalid_values(changes: dict[str, object], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        replace(make_contract_run().daily_captures[0], **cast(Any, changes))


def test_day_capture_requires_records_for_the_same_snapshot() -> None:
    capture = make_contract_run().daily_captures[0]
    other = DecisionAuthoritySnapshot((), (), (), (), None, None, "different")

    with pytest.raises(ValueError, match="must match"):
        replace(capture, records=replace(capture.records, snapshot=other))


def test_runner_requires_a_callable_factory() -> None:
    with pytest.raises(ValueError, match="callable"):
        HorizonRunner(cast(Any, object()))
