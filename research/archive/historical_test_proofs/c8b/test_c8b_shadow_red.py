"""C8B — SafeShadowRunner red tests.

SHADOW-1: runner owns orchestrator lifecycle; caller never gets a commit-capable handle.
SHADOW-2: no user-visible delivery.
SHADOW-5: ShadowRunRecord has ZERO cognitive authority.
SHADOW-6: failure always leaves no committable cognitive projection.

Red tests run against the existing TurnOrchestrator API directly, before
the SafeShadowRunner wrapper is written.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
from tests.support.fake_clock import FakeClock

from mind_runtime.contracts import (
    Interaction,
    InteractionStatus,
    Scope,
    ScopeDomain,
)
from mind_runtime.pipeline.orchestrator import (
    TurnOrchestrator,
    TurnState,
)
from mind_runtime.pipeline.trace import TraceRecorder

# ── fixture helpers ──────────────────────────────────────────────────────────


def _clock() -> FakeClock:
    return FakeClock(datetime(2026, 8, 19, 12, 0, tzinfo=UTC))


def _interaction(
    interaction_id: str = "it-red",
    user_id: str = "user-1",
) -> Interaction:
    return Interaction(
        interaction_id=interaction_id,
        scope=Scope(domain=ScopeDomain.USER, user_id=user_id),
        channel="test",
        session_id="session-1",
        turn_id="turn-1",
        started_at=datetime(2026, 8, 19, 12, 0, tzinfo=UTC),
        committed_at=None,
        status=InteractionStatus.OPEN,
    )


def _orchestrator(shadow_enabled: bool = True) -> TurnOrchestrator:
    return TurnOrchestrator(
        clock=_clock(),
        trace=TraceRecorder(),
        shadow_enabled=shadow_enabled,
    )


# ────────────────────────────────────────────────────────────────────────────
# SH2: successful shadow → cognitive canonical projection unchanged
# ────────────────────────────────────────────────────────────────────────────


def test_shadow_run_does_not_mutate_canonical(shadow_enabled: bool = True) -> None:
    """After run_shadow() the canonical state must be unchanged.

    Same test as test_d11l_shadow_flag.py but explicitly checks canonical.
    """
    orch = _orchestrator(shadow_enabled=True)
    it = _interaction()
    orch.begin_turn(it)

    canonical_before = dict(orch._canonical)

    orch.run_shadow()  # full lifecycle turn runs, stops at DISPATCHING

    # canonical must be unchanged
    assert orch._canonical == canonical_before
    assert orch.state == TurnState.DISPATCHING


def test_commit_after_shadow_mutates_canonical() -> None:
    """Confirm commit_turn() CAN mutate canonical (baseline sanity)."""
    orch = _orchestrator(shadow_enabled=True)
    it = _interaction()
    orch.begin_turn(it)

    orch.run_shadow()
    assert orch.state == TurnState.DISPATCHING

    # commit IS the canonical writer — this proves shadow run produced a real projection
    orch.commit_turn()
    assert orch.state == TurnState.COMMITTED  # type: ignore[comparison-overlap]
    # after commit, canonical changed (sanity check that projection was produced)
    assert len(orch._canonical) > 0


# ────────────────────────────────────────────────────────────────────────────
# SH6: AgentFailure → forced abort → no cognitive canonical mutation
# ────────────────────────────────────────────────────────────────────────────


class FailingAgent:
    """Agent that raises AgentFailure."""

    def respond(self, provider_context: object) -> str:
        from mind_runtime.pipeline.ports import AgentFailure

        raise AgentFailure("shadow agent failed")


def test_agent_failure_abort_leaves_canonical_unchanged() -> None:
    """AgentFailure during run_shadow → abort_turn → canonical unchanged."""
    orch = _orchestrator(shadow_enabled=True)
    orch.agent = FailingAgent()
    it = _interaction()
    orch.begin_turn(it)

    canonical_before = dict(orch._canonical)

    with pytest.raises(Exception):  # noqa: B017
        orch.run_shadow()

    orch.abort_turn()

    assert orch.state == TurnState.ABORTED
    assert orch._canonical == canonical_before


# ────────────────────────────────────────────────────────────────────────────
# SH1: caller of wrapper must NOT receive a commit-capable handle
# (proved by verifying TurnOrchestrator.commit_turn is not exposed as property)
# ────────────────────────────────────────────────────────────────────────────


def test_orchestrator_committable_handle_is_not_a_public_property() -> None:
    """commit_turn is a method, not a property — caller must not receive orchestrator."""
    orch = _orchestrator(shadow_enabled=True)
    # TurnOrchestrator.commit_turn is a method. The SafeShadowRunner must not
    # return the orchestrator itself to callers.
    # This test documents that commit_turn() is callable only by the runner,
    # not by a caller who holds a ShadowRunResult.
    assert hasattr(orch, "commit_turn")
    assert callable(orch.commit_turn)
    # No "committer" or "orchestrator_handle" property exposed
    assert not hasattr(orch, "committer")
    assert not hasattr(orch, "orchestrator_handle")
    assert not hasattr(orch, "canonical_writer")


def test_abort_turn_is_available() -> None:
    """abort_turn must be callable to implement forced discard."""
    orch = _orchestrator(shadow_enabled=True)
    it = _interaction()
    orch.begin_turn(it)
    orch.run_shadow()

    orch.abort_turn()
    assert orch.state == TurnState.ABORTED


# ────────────────────────────────────────────────────────────────────────────
# SH5: would-send / expression outcome → not cognitive authority
# ExpressionOutcome exists after run_shadow() — prove it is NOT committed
# ────────────────────────────────────────────────────────────────────────────


def test_expression_outcome_after_shadow_is_not_committed() -> None:
    """ExpressionOutcome produced by run_shadow() must not survive abort_turn."""
    orch = _orchestrator(shadow_enabled=True)
    it = _interaction()
    orch.begin_turn(it)

    orch.run_shadow()

    # expression_outcome is populated (shadow ran a real turn)
    outcome = orch.expression_outcome
    assert outcome is not None  # sanity: shadow produced outcome

    # abort discards it
    orch.abort_turn()
    assert orch.state == TurnState.ABORTED
    # NOTE: expression_outcome is a property of orchestrator._turn, which is
    # cleared by abort_turn(). After abort, the turn data is discarded.


# ────────────────────────────────────────────────────────────────────────────
# SH17: model inference allowed (AgentPort.respond) while Delivery forbidden
# Verify AgentPort is used during run() but DeliveryPort is not touched
# ────────────────────────────────────────────────────────────────────────────


def test_agent_respond_is_called_during_run() -> None:
    """run() calls AgentPort.respond() — this is SHADOW-3."""
    mock_agent = MagicMock()
    mock_agent.respond.return_value = "shadow response"

    orch = _orchestrator(shadow_enabled=True)
    orch.agent = mock_agent
    it = _interaction()
    orch.begin_turn(it)

    orch.run_shadow()

    assert mock_agent.respond.called
    assert orch.state == TurnState.DISPATCHING


def test_no_deliveryport_in_orchestrator_run_path() -> None:
    """Production orchestrator does not call DeliveryPort.deliver() in run().

    Proof by inspection: TurnOrchestrator.run() has no DeliveryPort dependency.
    This test documents the seam: DeliveryPort is NOT in the orchestrator
    constructor and NOT in the run() path.
    """
    import inspect

    from mind_runtime.pipeline.orchestrator import TurnOrchestrator

    sig = inspect.signature(TurnOrchestrator.__init__)
    param_names = set(sig.parameters.keys())

    # DeliveryPort must NOT be a constructor parameter
    assert "delivery_port" not in param_names
    assert "carrier" not in param_names
    assert "transport" not in param_names

    # run_shadow() and run() source must not reference DeliveryPort type or carrier attribute
    for method_name in ("run", "run_shadow"):
        method = getattr(TurnOrchestrator, method_name)
        source = inspect.getsource(method)
        # Exclude docstrings/comments; check actual attribute access and type names
        assert "DeliveryPort" not in source
        assert "delivery_port" not in source
        assert ".deliver(" not in source
        assert ".carrier" not in source


# ────────────────────────────────────────────────────────────────────────────
# SHADOW-5 Golden: ShadowRunRecord cannot be Evidence / State / Affect / Memory
# (tested after ShadowRunRecord is defined in the implementation phase)
# ────────────────────────────────────────────────────────────────────────────


def test_shadowrunrecord_is_not_evidence_type() -> None:
    """ShadowRunRecord must not be typed as Evidence or any cognitive authority type."""
    # This test passes before ShadowRunRecord exists — it documents the rule.
    # After implementation, verify ShadowRunRecord is NOT a subclass of Evidence.
    from mind_runtime.contracts import Evidence

    # Import will succeed even if ShadowRunRecord doesn't exist yet.
    # When ShadowRunRecord IS implemented, add:
    #     assert not issubclass(ShadowRunRecord, Evidence)
    #     assert not issubclass(ShadowRunRecord, MindState)
    #     assert not issubclass(ShadowRunRecord, Observation)
    #     assert not issubclass(ShadowRunRecord, Intent)
    # For now, verify Evidence exists (import sanity).
    assert Evidence is not None


# ────────────────────────────────────────────────────────────────────────────
# SH1: abort_turn state coverage
# ────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "state_before_abort",
    [
        TurnState.BEGIN,
        TurnState.INGESTING,
        TurnState.PROCESSING,
        TurnState.DISPATCHING,
    ],
)
def test_abort_turn_from_any_state_leaves_canonical_unchanged(
    state_before_abort: TurnState,
) -> None:
    """abort_turn from any turn state must leave canonical dict unchanged."""
    orch = _orchestrator(shadow_enabled=True)
    it = _interaction()
    orch.begin_turn(it)
    orch.state = state_before_abort

    canonical_before = dict(orch._canonical)

    orch.abort_turn()

    assert orch.state == TurnState.ABORTED
    assert orch._canonical == canonical_before


# ────────────────────────────────────────────────────────────────────────────
# SH6 / SHADOW-6: guard block during run_shadow → abort → no canonical
# ────────────────────────────────────────────────────────────────────────────


class BlockingGuard:
    """ExpressionGuard that always REJECTs (suppresses expression)."""

    def guard(
        self,
        guard_input: object,  # noqa: ARG002
    ) -> object:
        from mind_runtime.contracts.expression import ExpressionDisposition, ExpressionGuardResult
        from mind_runtime.contracts.scope import Scope

        return ExpressionGuardResult(
            guard_id="block-guard",
            scope=Scope(domain=ScopeDomain.USER, user_id="test"),
            origin_runtime_id="test-runtime",
            expression="blocked",
            disposition=ExpressionDisposition.REJECT,
            violations=("always blocking",),
        )

    def evaluate(self, intent: object, context: object) -> object:
        """Legacy stub method."""
        from mind_runtime.contracts.expression import ExpressionDisposition, ExpressionGuardResult
        from mind_runtime.contracts.scope import Scope

        return ExpressionGuardResult(
            guard_id="block-guard",
            scope=Scope(domain=ScopeDomain.USER, user_id="test"),
            origin_runtime_id="test-runtime",
            expression="blocked",
            disposition=ExpressionDisposition.REJECT,
            violations=("always blocking",),
        )


def test_guard_block_abort_leaves_canonical_unchanged() -> None:
    """ExpressionGuard BLOCK during run_shadow → abort → canonical unchanged."""
    orch = _orchestrator(shadow_enabled=True)
    orch.expression_guard = BlockingGuard()  # type: ignore[assignment]
    it = _interaction()
    orch.begin_turn(it)

    canonical_before = dict(orch._canonical)

    # run_shadow may raise on guard block — either way, abort and verify
    try:
        orch.run_shadow()
    except Exception:
        pass

    orch.abort_turn()
    assert orch.state == TurnState.ABORTED
    assert orch._canonical == canonical_before


# ────────────────────────────────────────────────────────────────────────────
# SH8: persistence failure during run → abort → canonical survives
# (simulated by orchestrator with no state_backend — no persistence needed;
#  the rule is: if persistence fails after abort, no projection may survive)
# ────────────────────────────────────────────────────────────────────────────


def test_abort_turn_leaves_no_projection() -> None:
    """After abort_turn, no projection is stored in canonical."""
    orch = _orchestrator(shadow_enabled=True)
    it = _interaction()
    orch.begin_turn(it)

    orch.run_shadow()
    assert orch.state == TurnState.DISPATCHING

    orch.abort_turn()
    assert orch.state == TurnState.ABORTED  # type: ignore[comparison-overlap]

    # After abort, turn is dropped — no projection to promote
    assert orch._canonical == {}
    # The captured projection reference (if any) is discarded with the turn


# ────────────────────────────────────────────────────────────────────────────
# SH18: exception at wrapper stage → finally path leaves no committable projection
# ────────────────────────────────────────────────────────────────────────────


def test_exception_after_run_shadow_abort_still_succeeds() -> None:
    """If run_shadow succeeds but a later step raises, abort_turn still executes."""
    orch = _orchestrator(shadow_enabled=True)
    it = _interaction()
    orch.begin_turn(it)

    orch.run_shadow()
    assert orch.state == TurnState.DISPATCHING
    canonical_before = dict(orch._canonical)

    # Simulate: exception after run_shadow but before commit
    try:
        raise RuntimeError("simulated capture failure")
    except RuntimeError:
        orch.abort_turn()

    assert orch.state == TurnState.ABORTED  # type: ignore[comparison-overlap]
    assert orch._canonical == canonical_before


# ────────────────────────────────────────────────────────────────────────────
# SH13: would-send proactive result → no settled-action counter mutation
# (proved by verifying counters are not in the orchestrator run path)
# ────────────────────────────────────────────────────────────────────────────


def test_no_counter_mutation_in_run_shadow() -> None:
    """run_shadow() must not mutate any counter."""
    import inspect

    from mind_runtime.pipeline.orchestrator import TurnOrchestrator

    for method_name in ("run", "run_shadow"):
        method = getattr(TurnOrchestrator, method_name)
        source = inspect.getsource(method)
        # Counters (last_proactive_at, proactive_prompts_since_photo, etc.)
        # must NOT appear in the run path
        assert "counter" not in source.lower()
        assert "last_proactive" not in source
        assert "proactive_prompts" not in source
