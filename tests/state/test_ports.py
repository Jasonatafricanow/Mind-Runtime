"""D4.7 port wiring and raw-status audit tests."""

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from mind_runtime.contracts import RuntimeState
from mind_runtime.pipeline.orchestrator import TurnOrchestrator
from mind_runtime.pipeline.trace import TraceRecorder
from mind_runtime.state.definitions import StateDefinitionRegistry
from mind_runtime.state.ports import ResolverEffectiveStatePort
from mind_runtime.state.resolver import EffectiveStateResolver
from tests.golden.fixtures.common import make_evidence, make_scope, make_state
from tests.support.fake_clock import FakeClock

NOW = datetime(2026, 8, 21, 21, 0, tzinfo=UTC)


def make_orchestrator(**kwargs: Any) -> TurnOrchestrator:
    return TurnOrchestrator(clock=FakeClock(NOW), trace=TraceRecorder(), **kwargs)


def make_port() -> ResolverEffectiveStatePort:
    return ResolverEffectiveStatePort(
        resolver=EffectiveStateResolver(definitions=StateDefinitionRegistry())
    )


def state_with_refs(refs: tuple[str, ...], **kwargs: Any) -> RuntimeState:
    return replace(make_state(**kwargs), evidence_refs=refs)


def test_orchestrator_default_effective_state_is_resolver_backed() -> None:
    orchestrator = make_orchestrator()
    assert isinstance(orchestrator.effective_state, ResolverEffectiveStatePort)


def test_orchestrator_accepts_injected_effective_state() -> None:
    from mind_runtime.pipeline.stubs import StubEffectiveState

    orchestrator = make_orchestrator(effective_state=StubEffectiveState())
    assert isinstance(orchestrator.effective_state, StubEffectiveState)


def test_port_returns_state_matching_turn_evidence_refs() -> None:
    port = make_port()
    target = state_with_refs(
        ("evidence-9",),
        dimension="user.sleep.phase",
        value="awake",
        status="active",
        state_id="s-9",
    )
    other = state_with_refs(
        ("evidence-1",),
        dimension="user.health.headache",
        value="active",
        status="active",
        state_id="s-1",
    )
    result = port.effective(
        interaction_id="interaction-1",
        evidence_refs=("evidence-9",),
        canonical_snapshot=(other, target),
        scope=make_scope(),
        clock=NOW,
    )
    assert result is target


def test_port_falls_back_to_first_scope_state() -> None:
    port = make_port()
    first = make_state(dimension="user.sleep.phase", value="awake", status="active", state_id="s-1")
    result = port.effective(
        interaction_id="interaction-1",
        evidence_refs=("evidence-zz",),
        canonical_snapshot=(first,),
        scope=make_scope(),
        clock=NOW,
    )
    assert result is first


def test_port_skips_foreign_scope_states() -> None:
    """The port never returns another scope's effective state."""
    port = make_port()
    foreign = make_state(
        dimension="user.sleep.phase",
        value="awake",
        status="active",
        state_id="foreign",
        scope=make_scope(user_id="user-other"),
    )
    mine = make_state(
        dimension="user.sleep.phase",
        value="awake",
        status="active",
        state_id="mine",
    )
    result = port.effective(
        interaction_id="interaction-1",
        evidence_refs=("evidence-zz",),  # no ref match -> fallback loop
        canonical_snapshot=(foreign, mine),
        scope=make_scope(),
        clock=NOW,
    )
    assert result is mine


def test_port_synthesizes_passthrough_when_no_effective_state() -> None:
    port = make_port()
    result = port.effective(
        interaction_id="interaction-1",
        evidence_refs=("evidence-1",),
        canonical_snapshot=(),
        scope=make_scope(),
        clock=NOW,
    )
    assert isinstance(result, RuntimeState)
    assert result.evidence_refs == ("evidence-1",)


def test_orchestrator_run_uses_resolver_port_end_to_end() -> None:
    from mind_runtime.contracts import Interaction, InteractionStatus

    orchestrator = make_orchestrator()
    scope = make_scope()
    orchestrator.begin_turn(
        Interaction(
            interaction_id="interaction-1",
            scope=scope,
            channel="chat",
            session_id="session-1",
            turn_id="turn-1",
            started_at=NOW,
            committed_at=None,
            status=InteractionStatus.OPEN,
        )
    )
    orchestrator.ingest(make_evidence(text="我刚睡醒"))
    orchestrator.run()
    assert orchestrator.decision_context is not None
    assert orchestrator.decision_context.effective_user_state_ref


def test_no_raw_status_filtering_in_pipeline_package() -> None:
    """D4.7 audit point: business modules must not read raw state status.

    The pipeline package may only consume effective state; any ``.status``
    attribute read would be a raw-state bypass. (Stub construction uses the
    ``status=`` keyword, which is not a read.)

    The orchestrator has two pre-existing lifecycle guards on Pending objects
    (accept_pending/reject_pending). Those are execution-control checks, not
    reads of canonical RuntimeState, so this audit recognizes their semantic
    shape rather than fragile source line numbers.
    """
    pipeline_dir = Path("src/mind_runtime/pipeline")
    offenders: list[str] = []
    for path in sorted(pipeline_dir.glob("*.py")):
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("#") or stripped.startswith('"""'):
                continue
            if ".status" in stripped:
                loc = f"{path.name}:{lineno}"
                is_pending_lifecycle_guard = (
                    path.name == "orchestrator.py"
                    and (
                        stripped == "if pending.status is not PendingStatus.PENDING:"
                        or stripped.startswith('f"accept_pending requires PENDING status; got ')
                        or stripped.startswith('f"reject_pending requires PENDING status; got ')
                    )
                )
                if is_pending_lifecycle_guard:
                    continue
                offenders.append(f"{loc}: {stripped}")
    assert offenders == [], f"raw status reads in pipeline package: {offenders}"


def test_orchestrator_exposes_canonical_unchanged_with_resolver() -> None:
    canonical = make_state(
        dimension="user.sleep.phase", value="sleeping", status="active", state_id="s-1"
    )
    orchestrator = make_orchestrator(canonical_snapshot=(canonical,))
    assert orchestrator.canonical == (canonical,)
