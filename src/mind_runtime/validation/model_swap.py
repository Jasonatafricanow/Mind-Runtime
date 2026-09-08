"""D11S.4 model-swap invariance: identical internal authority across providers.

The certification materializes the same pre-turn durable snapshot into two
separate stores, then independently executes the full real canonical turn on
each side from identical frozen turn-input bytes with a different expression
provider (AgentPort). The D8-D10 authority (accepted events, contribution
trace, projected/committed State, candidate ordering, selected Intent,
ActionPolicy result, and the full captured authority records excluding the
expression receipts) must be byte-equal; only the accepted prose may differ.
"""

import shutil
import subprocess
from dataclasses import dataclass, replace
from datetime import timedelta
from pathlib import Path

from mind_runtime.pipeline.fake_agent import FakeAgent
from mind_runtime.pipeline.ports import AgentPort
from mind_runtime.validation.composition import (
    CertificationRuntimeConfig,
    DurablePaths,
    _DailyAuthorityRecords,
    build_composition,
)
from mind_runtime.validation.contracts import (
    CertificationPlan,
    SimulationEvent,
    decode_horizon_template_bytes,
    decode_runtime_config_manifest_bytes,
    verify_fixture_artifacts,
)
from mind_runtime.validation.digest import canonical_json_bytes, sha256_bytes
from mind_runtime.validation.schedule import SimulationClock


@dataclass(frozen=True, slots=True)
class ModelSwapResult:
    """Paired expression-provider comparison over one identical canonical turn."""

    expressions_differ: bool
    left_agent_called: int
    right_agent_called: int
    provider_context_bytes_same: bool
    internal_transition_same: bool
    intent_same: bool
    policy_same: bool
    left_expression: str
    right_expression: str
    internal_digest: str
    provider_context_sha256: str

    def __post_init__(self) -> None:
        for field_name in (
            "expressions_differ",
            "provider_context_bytes_same",
            "internal_transition_same",
            "intent_same",
            "policy_same",
        ):
            if not isinstance(getattr(self, field_name), bool):
                raise ValueError(f"{field_name} must be a boolean")
        for field_name in ("left_agent_called", "right_agent_called"):
            if (
                isinstance(getattr(self, field_name), bool)
                or not isinstance(getattr(self, field_name), int)
                or getattr(self, field_name) < 0
            ):
                raise ValueError(f"{field_name} must be a non-negative integer")
        for field_name in ("left_expression", "right_expression"):
            if not getattr(self, field_name).strip():
                raise ValueError(f"{field_name} must not be empty")
        for field_name in ("internal_digest", "provider_context_sha256"):
            if not _is_sha256(getattr(self, field_name)):
                raise ValueError(f"{field_name} must be a SHA-256")


def compare_model_swap(
    left_agent: AgentPort,
    right_agent: AgentPort,
    plan: CertificationPlan,
    *,
    root: Path,
    repository_root: Path | None = None,
) -> ModelSwapResult:
    """Compare the full canonical turn under two expression providers.

    Raises (fail closed) on: a plan that does not decode from the exact
    verified horizon bytes, a mismatched source HEAD or runtime manifest, a
    non-empty certification root, an agent that fails or is not called exactly
    once, provider contexts that differ, or equal accepted prose.
    """
    repository = Path(__file__).resolve().parents[3]
    if repository_root is not None:
        repository = repository_root.resolve()
    current_head = _current_source_head(repository)
    if plan.source_head != current_head:
        raise ValueError("plan source HEAD must equal the checked-out source HEAD")
    if root.exists() and any(root.iterdir()):
        raise ValueError("certification root must be empty")
    root.mkdir(parents=True, exist_ok=True)

    manifest_path = repository / "certification/d11s/inputs/runtime-config.json"
    manifest_bytes = manifest_path.read_bytes()
    manifest_hash = sha256_bytes(manifest_bytes)
    if manifest_hash != plan.runtime_config_manifest_sha256:
        raise ValueError("plan runtime manifest hash does not match verified bytes")
    manifest = decode_runtime_config_manifest_bytes(manifest_bytes)
    verify_fixture_artifacts(manifest, repository)
    horizon_path = repository / f"certification/d11s/inputs/horizon-{plan.horizon_days}.json"
    horizon_bytes = horizon_path.read_bytes()
    template = decode_horizon_template_bytes(horizon_bytes)
    expected_plan = CertificationPlan(
        certification_id=template.certification_id,
        source_head=current_head,
        persona_version=template.persona_version,
        runtime_config_manifest_sha256=manifest_hash,
        horizon_days=template.horizon_days,
        started_at=template.started_at,
        events=template.events,
        checkpoint_interval=template.checkpoint_interval,
    )
    if plan != expected_plan:
        raise ValueError("plan must decode from the exact verified horizon bytes")

    compared_event = template.events[-1]
    seed_events = template.events[:-1]

    # 1. Seed: run every pre-turn event through the canonical composition to
    #    materialize the durable pre-turn snapshot.
    _run_seed(
        plan,
        root / "seed-run",
        repository,
        manifest_path,
        manifest_hash,
        seed_events,
    )

    # 2. Materialize the same snapshot into two separate stores.
    for side in ("left-run", "right-run"):
        _materialize_snapshot(root / "seed-run", root / side)

    # 3. Independently execute the compared turn on each side.
    left = _run_side(
        plan,
        left_agent,
        root / "left-run",
        repository,
        manifest_path,
        manifest_hash,
        compared_event,
    )
    right = _run_side(
        plan,
        right_agent,
        root / "right-run",
        repository,
        manifest_path,
        manifest_hash,
        compared_event,
    )
    left_records, left_expression, left_calls, left_context = (
        left.records,
        left.expression,
        left.calls,
        left.context,
    )
    right_records, right_expression, right_calls, right_context = (
        right.records,
        right.expression,
        right.calls,
        right.context,
    )

    left_context_bytes = canonical_json_bytes(left_context)
    right_context_bytes = canonical_json_bytes(right_context)
    provider_context_bytes_same = left_context_bytes == right_context_bytes
    _verify_swap_validity(
        left_calls=left_calls,
        right_calls=right_calls,
        left_context_bytes=left_context_bytes,
        right_context_bytes=right_context_bytes,
        left_expression=left_expression,
        right_expression=right_expression,
    )

    left_internal = replace(left_records, receipts=())
    right_internal = replace(right_records, receipts=())
    internal_digest = sha256_bytes(canonical_json_bytes(left_internal))
    internal_same = left_internal == right_internal
    return ModelSwapResult(
        expressions_differ=True,
        left_agent_called=left_calls,
        right_agent_called=right_calls,
        provider_context_bytes_same=provider_context_bytes_same,
        internal_transition_same=internal_same
        and left_records.transition_results == right_records.transition_results
        and left_records.canonical_states == right_records.canonical_states
        and left_records.state_transitions == right_records.state_transitions,
        intent_same=internal_same
        and left_records.current_intents == right_records.current_intents
        and left_records.intent_history == right_records.intent_history
        and left_records.intent_transitions == right_records.intent_transitions,
        policy_same=internal_same and left_records.policy_results == right_records.policy_results,
        left_expression=left_expression,
        right_expression=right_expression,
        internal_digest=internal_digest,
        provider_context_sha256=sha256_bytes(left_context_bytes),
    )


def _run_seed(
    plan: CertificationPlan,
    durable_root: Path,
    repository_root: Path,
    manifest_path: Path,
    manifest_hash: str,
    seed_events: tuple[SimulationEvent, ...],
) -> None:
    """Run every pre-turn event with day-boundary scheduler ticks.

    The loop mirrors the HorizonRunner day loop and runs through the final
    horizon boundary, so the materialized snapshot is the post-full-tick
    schedule state. Both sides copy the SAME snapshot, so the compared turn's
    invariance is unaffected by the tick schedule.
    """
    durable_root.mkdir(parents=True, exist_ok=True)
    clock = SimulationClock(plan.started_at)
    composition = build_composition(
        CertificationRuntimeConfig(
            repository_root=repository_root,
            manifest_path=manifest_path,
            manifest_sha256=manifest_hash,
            durable_paths=DurablePaths.under(durable_root),
            clock=clock,
            certification_id=plan.certification_id,
            agent=FakeAgent(("seed-prose",)),
        )
    )
    try:
        composition._verify_plan(plan)
        event_index = 0
        for virtual_day in range(plan.horizon_days + 1):
            boundary = plan.started_at + timedelta(days=virtual_day)
            while (
                event_index < len(seed_events)
                and plan.started_at + seed_events[event_index].at_offset <= boundary
            ):
                clock.advance_to(plan.started_at + seed_events[event_index].at_offset)
                composition.apply_event(seed_events[event_index])
                event_index += 1
            clock.advance_to(boundary)
            composition.tick()
    finally:
        composition.close()


def _materialize_snapshot(source_root: Path, target_root: Path) -> None:
    """Copy the four durable SQLite planes into a fresh side root."""
    target_root.mkdir(parents=True, exist_ok=True)
    source = DurablePaths.under(source_root)
    target = DurablePaths.under(target_root)
    for source_path, target_path in (
        (source.facts_db, target.facts_db),
        (source.state_db, target.state_db),
        (source.intents_db, target.intents_db),
        (source.checkpoints_db, target.checkpoints_db),
    ):
        shutil.copy2(source_path, target_path)


@dataclass(frozen=True, slots=True)
class _SideCapture:
    """One side's compared-turn capture: full authority records, the accepted
    expression, the provider call count, and the provider context."""

    records: _DailyAuthorityRecords
    expression: str
    calls: int
    context: object


def _run_side(
    plan: CertificationPlan,
    agent: AgentPort,
    durable_root: Path,
    repository_root: Path,
    manifest_path: Path,
    manifest_hash: str,
    compared_event: SimulationEvent,
) -> _SideCapture:
    """Execute the compared turn on one side and capture the authority records."""
    clock = SimulationClock(plan.started_at)
    composition = build_composition(
        CertificationRuntimeConfig(
            repository_root=repository_root,
            manifest_path=manifest_path,
            manifest_sha256=manifest_hash,
            durable_paths=DurablePaths.under(durable_root),
            clock=clock,
            certification_id=plan.certification_id,
            agent=agent,
        )
    )
    try:
        composition._verify_plan(plan)
        clock.advance_to(plan.started_at + compared_event.at_offset)
        composition.apply_event(compared_event)
        records = composition._capture_daily_records()
        expression = _capture_expression(composition.orchestrator.expression_outcome)
        calls = agent.call_count if isinstance(agent, FakeAgent) else _call_count(agent)
        context = agent.calls[0] if isinstance(agent, FakeAgent) else _only_call(agent)
        return _SideCapture(
            records=records,
            expression=expression,
            calls=calls,
            context=context,
        )
    finally:
        composition.close()


def _verify_swap_validity(
    *,
    left_calls: int,
    right_calls: int,
    left_context_bytes: bytes,
    right_context_bytes: bytes,
    left_expression: str,
    right_expression: str,
) -> None:
    """Fail closed when the paired swap did not run as certified."""
    if left_calls != 1 or right_calls != 1:
        raise ValueError("each compared AgentPort must be called exactly once")
    if left_context_bytes != right_context_bytes:
        raise ValueError("both providers must receive byte-identical contexts")
    if left_expression == right_expression:
        raise ValueError("the two accepted expressions must differ")
    if not left_expression.strip() or not right_expression.strip():
        raise ValueError("both providers must return a non-empty accepted expression")


def _capture_expression(outcome: object) -> str:
    """Extract the accepted expression, failing closed when the compared turn
    did not reach an accepted expression."""
    if outcome is None:
        raise ValueError("compared turn produced no expression outcome")
    accepted = getattr(outcome, "accepted_expression", None)
    if not isinstance(accepted, str) or not accepted:
        raise ValueError("compared turn produced no accepted expression")
    return accepted


def _call_count(agent: AgentPort) -> int:
    calls = getattr(agent, "call_count", None)
    if isinstance(calls, int) and not isinstance(calls, bool):
        return calls
    return len(_only_calls(agent))


def _only_calls(agent: AgentPort) -> tuple[object, ...]:
    calls = getattr(agent, "calls", ())
    return tuple(calls)


def _only_call(agent: AgentPort) -> object:
    calls = _only_calls(agent)
    if len(calls) != 1:
        raise ValueError("each compared AgentPort must be called exactly once")
    return calls[0]


def _current_source_head(repository_root: Path) -> str:
    return subprocess.run(
        ["git", "rev-parse", "--verify", "HEAD"],
        cwd=repository_root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(char in "0123456789abcdef" for char in value)
