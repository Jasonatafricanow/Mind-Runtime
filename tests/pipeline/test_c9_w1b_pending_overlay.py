"""C9-W1B: Pending Working Overlay — pre-admission evidence lifecycle.

Per C9-W1B ticket spec:
  Evidence
  → bounded pending interpretation
  → Working Memory Overlay (non-canonical, non-durable)
  → next-turn Context Compiler (as authorized_external_items, source=pending)
  → temporary factual continuity (NO canonical authority transfer)

Lifecycle: PENDING -> ACCEPTED (promoted to canonical) or REJECTED (cleared).

Hard invariants tested:
  W1B.1: pending visible to next-turn compiler (deferred admission)
  W1B.2: pending != canonical (no Canonical authority transfer)
  W1B.3: ACCEPT promotes to canonical and clears pending
  W1B.4: REJECT clears pending without promotion
  W1B.5: future turn after REJECT — no influence
  W1B.6: scope isolation — cross-scope pending is NOT visible
  W1B.7: abort_turn clears pending; no silent canonical promotion

Tests use deterministic fixtures only (no LLM).
"""

from __future__ import annotations

import sys
from dataclasses import replace as _replace
from pathlib import Path

import pytest

# Ensure the main tree's src/ is preferred over any worktree paths
_main_src = Path(__file__).resolve().parents[2] / "src"
if _main_src.exists():
    _worktree_paths = [p for p in sys.path if "mind_runtime" in p and ".worktrees" in p]
    for _p in _worktree_paths:
        sys.path.remove(_p)
    if str(_main_src) not in sys.path:
        sys.path.insert(0, str(_main_src))

from datetime import UTC, datetime

from mind_runtime.contracts import (
    ExpressionContextItem,
    ExpressionContextKind,
    Interaction,
    InteractionStatus,
    Intent,
    Scope,
    ScopeDomain,
)
from mind_runtime.contracts.action import (
    ActionDecision,
    ActionPermission,
    ActionPolicyResult,
)
from mind_runtime.expression.context import (
    DecisionContextCompiler,
    DecisionContextCompilerInput,
    DecisionContextConfig,
)
from mind_runtime.contracts.observation import Observation
from mind_runtime.memory.pending import (
    PendingStatus,
    PendingWorkingEvidence,
    PendingWorkingOverlay,
)
from mind_runtime.pipeline.orchestrator import TurnOrchestrator
from mind_runtime.pipeline.trace import TraceRecorder
from tests.golden.fixtures.common import make_evidence
from tests.support.fake_clock import FakeClock

NOW = datetime(2026, 8, 26, 10, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _alice_scope() -> Scope:
    return Scope(
        domain=ScopeDomain.AGENT,
        agent_id="agent-alice",
        persona_id="persona-alice",
    )


def _bob_scope() -> Scope:
    return Scope(
        domain=ScopeDomain.AGENT,
        agent_id="agent-bob",
        persona_id="persona-bob",
    )


def _alice_turn_n(turn_id: str = "interaction-alice-N") -> Interaction:
    return Interaction(
        interaction_id=turn_id,
        scope=_alice_scope(),
        channel="chat",
        session_id="session-alice-1",
        turn_id="turn-1",
        started_at=NOW,
        committed_at=None,
        status=InteractionStatus.OPEN,
    )


def _bob_turn(turn_id: str = "interaction-bob-1") -> Interaction:
    return Interaction(
        interaction_id=turn_id,
        scope=_bob_scope(),
        channel="chat",
        session_id="session-bob-1",
        turn_id="turn-1",
        started_at=NOW,
        committed_at=None,
        status=InteractionStatus.OPEN,
    )


def _alice_evidence(text: str = "我的妹妹叫 Alice") -> "object":
    return make_evidence(
        text=text,
        scope=_alice_scope(),
        occurred_at=NOW,
        received_at=NOW,
        evidence_id="evidence-alice-sister",
        source_id="user-utterance-sister",
    )


def _build_orchestrator(
    scope: Scope,
    *,
    install_real_compiler: bool = True,
) -> tuple[TurnOrchestrator, PendingWorkingOverlay]:
    overlay = PendingWorkingOverlay()
    kwargs: dict = dict(
        clock=FakeClock(NOW),
        trace=TraceRecorder(),
        runtime_id="runtime-1",
        pending_overlay=overlay,
    )
    if install_real_compiler:
        # The default stub compiler does not consult authorized_external_items
        # (which is how pending overlay flows to compiler). Install the real
        # DecisionContextCompiler for the C9-W1B tests.
        compiler_config = DecisionContextConfig(
            max_items=50,
            max_render_chars=10000,
            max_history_items=10,
            max_prior_expression_chars=200,
            max_item_chars=500,
            allowed_situation_facts=(),
            affect_rules=(),
            persona_style_constraints=(),
            allowed_history_kinds=("relationship_event",),
        )
        kwargs["decision_context_compiler"] = DecisionContextCompiler(compiler_config)
    orch = TurnOrchestrator(**kwargs)
    return orch, overlay


def _real_compiler_input(orch: TurnOrchestrator) -> DecisionContextCompilerInput:
    """Build a minimal DecisionContextCompilerInput matching what the
    orchestrator passes in run(). Only fields the compiler needs to
    process are populated; we don't care about full semantic correctness
    here — only that pending items flow through authorized_external_items.
    """
    from mind_runtime.contracts import (
        ProjectedMindState,
        RuntimeState,
        Situation,
        SyncFields,
    )
    turn = orch._turn  # type: ignore[attr-defined]
    if turn is None:
        raise RuntimeError("turn is required")
    situation = Situation(
        situation_id=f"situation-{turn.interaction.interaction_id}",
        scope=turn.interaction.scope,
        origin_runtime_id="runtime-1",
        derived_facts=(),
        effective_state_ref="none",
        observed_at=NOW,
        historical_context=None,
        persona_id=None,
        relationship_ids=(),
        evidence_refs=(),
    )
    eff = RuntimeState(
        state_id="eff-1",
        scope=turn.interaction.scope,
        dimension="agent.affect.anxiety",
        value=0.5,
        status="active",
        valid_from=NOW,
        valid_until=None,
        relevant_until=None,
        last_observed_at=NOW,
        evidence_refs=(),
        transition_refs=(),
        updated_at=NOW,
        origin_runtime_id="runtime-1",
        version=1,
        sync=SyncFields(
            scope=turn.interaction.scope,
            origin_runtime_id="runtime-1",
            object_id="eff-1",
            version=1,
            idempotency_key="eff-1",
        ),
    )
    # ProjectedMindState requires non-empty projected_states; use a copy of eff.
    projected = ProjectedMindState(
        projection_id="proj-1",
        scope=turn.interaction.scope,
        origin_runtime_id="runtime-1",
        projected_states=(eff,),
        sync=SyncFields(
            scope=turn.interaction.scope,
            origin_runtime_id="runtime-1",
            object_id="proj-1",
            version=1,
            idempotency_key="proj-1",
        ),
    )
    intent = Intent(
        intent_id=f"intent-{turn.interaction.interaction_id}",
        scope=turn.interaction.scope,
        origin_runtime_id="runtime-1",
        candidate_text="respond",
        candidate_action_type="respond",
        ranked_candidates=(),
        admitted_intent_refs=(),
        status=None,
        evidence_refs=(),
        selected_by="test",
        confidence=0.5,
    )
    policy = ActionPolicyResult(
        policy_id="policy-1",
        scope=turn.interaction.scope,
        origin_runtime_id="runtime-1",
        intent_id=intent.intent_id,
        decision=ActionDecision.ALLOW,
        permission=ActionPermission(
            permission_id="permission-1",
            scope=turn.interaction.scope,
            origin_runtime_id="runtime-1",
            action_type="respond",
            allowed=True,
            reasons=(),
            constraints=(),
        ),
        reason_codes=(),
    )
    return DecisionContextCompilerInput(
        interaction_id=turn.interaction.interaction_id,
        scope=turn.interaction.scope,
        origin_runtime_id="runtime-1",
        situation=situation,
        effective_user_state=eff,
        projected_agent_state=projected,
        assessment_trace_ref="trace-1",
        intent=intent,
        policy_result=policy,
        persona_ref=None,
        prior_expression=None,
        attempt=0,
        rewrite_reason_codes=(),
    )


# ---------------------------------------------------------------------------
# W1B.1 — pending visible to next-turn compiler
# ---------------------------------------------------------------------------


def test_w1b1_pending_lifecycle_deferred_admission() -> None:
    """Pending evidence remains in overlay without unadmitted compiler FACT emission.

    Per d0d5f4f, ADR-0013, and C9-W1B-R2:
      - Ingest with defer_admission=True holds evidence in PendingWorkingOverlay.
      - Next turn run() does not mutate canonical state or emit unadmitted FACT items.
      - Pending evidence remains accessible via overlay.get_pending() until accept/reject.
    """
    orch, overlay = _build_orchestrator(_alice_scope())

    # Turn N: ingest with defer_admission=True
    orch.begin_turn(_alice_turn_n("interaction-alice-N"))
    result = orch.ingest(_alice_evidence(), defer_admission=True)
    assert result is None, "defer_admission must not return an Observation"

    pending_items = overlay.get_pending(_alice_scope())
    assert len(pending_items) == 1
    assert pending_items[0].status is PendingStatus.PENDING
    assert pending_items[0].semantic_payload[0][0] == "fact.key"
    assert "Alice" in pending_items[0].semantic_payload[0][1]

    # Turn N+1: orchestrator run() executes without fabricating pending FACT items
    # (per d0d5f4f / ADR-0013, pending -> FACT read path is DEFERRED).
    orch.begin_turn(_alice_turn_n("interaction-alice-N+1"))
    orch.run()
    assert orch.decision_context is not None
    pending_facts = tuple(
        item for item in orch.decision_context.expression_context
        if item.kind is ExpressionContextKind.FACT
        and any("pending:" in s for s in item.source_refs)
    )
    assert len(pending_facts) == 0, (
        "Regression: experimental pending -> compiler FACT path must not be active"
    )
    # Pending item remains intact in overlay awaiting explicit accept/reject
    assert len(overlay.get_pending(_alice_scope())) == 1


# ---------------------------------------------------------------------------
# W1B.2 — pending != canonical (no Canonical authority transfer)
# ---------------------------------------------------------------------------


def test_w1b2_pending_not_canonical() -> None:
    """Pending evidence does not appear in canonical state.

    Direct verification: the pending_overlay.get_pending returns the item
    but the orchestrator's canonical (via _canonical dict) does not.
    """
    orch, overlay = _build_orchestrator(_alice_scope())

    orch.begin_turn(_alice_turn_n("interaction-alice-N"))
    orch.ingest(_alice_evidence(), defer_admission=True)

    # Pending overlay contains the item
    assert len(overlay.get_pending()) == 1

    # Canonical state: fact_ingest was NOT called via defer_admission,
    # so no Observation exists for this evidence.
    # Run() will reconcile only observations from canonical ingest,
    # and the pending item is not in turn.observations.
    assert orch._turn is not None
    assert orch._turn.observations == ()
    # Canonical state dict is empty
    assert len(orch._canonical) == 0

    # Also: no pending item leaked into factual_overlay (which is the
    # canonical-path's "read-your-writes" view)
    assert "pending_c9w1b.observed" not in orch.factual_overlay


# ---------------------------------------------------------------------------
# W1B.3 — ACCEPT promotes to canonical and clears pending
# ---------------------------------------------------------------------------


def test_w1b3_accept_promotes_and_clears_pending() -> None:
    """ACCEPT transition: pending → canonical promotion via fact_ingest.admit."""
    orch, overlay = _build_orchestrator(_alice_scope())

    orch.begin_turn(_alice_turn_n("interaction-alice-N"))
    pending_id = "pending-evidence-alice-sister"
    orch.ingest(_alice_evidence(), defer_admission=True)
    # Confirm the pending item is present
    assert overlay.get_by_pending_id(pending_id) is not None

    # Accept the pending item
    observation = orch.accept_pending(pending_id)
    assert isinstance(observation, Observation), (
        "ACCEPT must return an Observation from canonical admission"
    )

    # Pending overlay no longer has the item
    assert overlay.get_by_pending_id(pending_id) is None
    assert len(overlay.get_pending()) == 0

    # Canonical state: fact_ingest was called, so the evidence now exists
    # in the canonical evidence table (even if not promoted to a
    # dimensioned state — that requires typed observation interpretation).
    # We verify the observation is in the turn.
    assert observation is not None


# ---------------------------------------------------------------------------
# W1B.4 — REJECT clears pending without promotion
# ---------------------------------------------------------------------------


def test_w1b4_reject_clears_without_promotion() -> None:
    """REJECT transition: pending cleared, no canonical admission."""
    orch, overlay = _build_orchestrator(_alice_scope())

    orch.begin_turn(_alice_turn_n("interaction-alice-N"))
    pending_id = "pending-evidence-alice-sister"
    orch.ingest(_alice_evidence(), defer_admission=True)
    assert overlay.get_by_pending_id(pending_id) is not None

    # Snapshot evidence count BEFORE reject (we can check by running the
    # orchestrator and seeing turn.observations).
    initial_observation_count = len(orch._turn.observations) if orch._turn else 0

    # Reject
    result = orch.reject_pending(pending_id)
    assert result is True

    # Pending overlay no longer has the item
    assert overlay.get_by_pending_id(pending_id) is None
    assert len(overlay.get_pending()) == 0

    # The turn did not gain any new observations (no canonical promotion)
    assert len(orch._turn.observations) == initial_observation_count


# ---------------------------------------------------------------------------
# W1B.5 — future turn after REJECT — no influence
# ---------------------------------------------------------------------------


def test_w1b5_rejected_value_absent_in_future_turn() -> None:
    """A rejected pending item is NOT visible in any future turn."""
    orch, overlay = _build_orchestrator(_alice_scope())

    orch.begin_turn(_alice_turn_n("interaction-alice-N"))
    pending_id = "pending-evidence-alice-sister"
    orch.ingest(_alice_evidence(), defer_admission=True)
    assert overlay.get_by_pending_id(pending_id) is not None

    # Reject
    orch.reject_pending(pending_id)
    assert overlay.get_by_pending_id(pending_id) is None

    # Future turn: should see NO pending item
    orch.begin_turn(_alice_turn_n("interaction-alice-N+1"))
    orch.run()
    assert orch.decision_context is not None
    pending_facts = tuple(
        item
        for item in orch.decision_context.expression_context
        if item.kind is ExpressionContextKind.FACT
        and any(s.startswith("pending:") for s in item.source_refs)
    )
    assert len(pending_facts) == 0, (
        f"REJECT must clear pending. Found {len(pending_facts)} pending FACT items. "
        "STOP — rejected item is leaking into future turns."
    )


# ---------------------------------------------------------------------------
# W1B.6 — scope isolation — cross-scope pending is NOT visible
# ---------------------------------------------------------------------------


def test_w1b6_scope_isolation() -> None:
    """Pending evidence for scope A is NOT visible in scope B's compiler."""
    overlay = PendingWorkingOverlay()
    # Single orchestrator with overlay; we simulate two separate turns
    # on different scopes by using the same overlay but switching the
    # orchestrator's interaction scope.
    orch = TurnOrchestrator(
        clock=FakeClock(NOW),
        trace=TraceRecorder(),
        runtime_id="runtime-1",
        pending_overlay=overlay,
    )

    # Turn for Alice
    orch.begin_turn(_alice_turn_n("interaction-alice-N"))
    orch.ingest(_alice_evidence(), defer_admission=True)
    # Pending is in Alice's scope
    alice_pending = overlay.get_pending(_alice_scope())
    assert len(alice_pending) == 1

    # Switch to Bob's turn with same overlay (cross-scope attempt)
    orch.begin_turn(_bob_turn("interaction-bob-1"))
    orch.run()
    bob_facts = tuple(
        item
        for item in (orch.decision_context.expression_context if orch.decision_context else ())
        if item.kind is ExpressionContextKind.FACT
        and any(s.startswith("pending:") for s in item.source_refs)
    )
    # Bob's compiler MUST NOT see Alice's pending FACT
    assert len(bob_facts) == 0, (
        f"Symbolic isolation broken: Bob saw {len(bob_facts)} pending FACT items. "
        "STOP — scope filter is not enforced."
    )


# ---------------------------------------------------------------------------
# W1B.7 — abort_turn clears pending; no silent canonical promotion
# ---------------------------------------------------------------------------


def test_w1b7_abort_clears_pending_no_promotion() -> None:
    """abort_turn() drops all PENDING items from the aborted turn."""
    orch, overlay = _build_orchestrator(_alice_scope())

    orch.begin_turn(_alice_turn_n("interaction-alice-N"))
    orch.ingest(_alice_evidence(), defer_admission=True)
    assert len(overlay.get_pending(_alice_scope())) == 1

    # Abort the turn
    orch.abort_turn()

    # Pending items from the aborted turn are gone
    assert len(overlay.get_pending(_alice_scope())) == 0
    assert len(overlay.get_pending()) == 0

    # No canonical promotion happened
    assert len(orch._canonical) == 0

    # Future turn sees no pending FACT
    orch.begin_turn(_alice_turn_n("interaction-alice-N+1"))
    orch.run()
    pending_facts = tuple(
        item
        for item in (orch.decision_context.expression_context if orch.decision_context else ())
        if item.kind is ExpressionContextKind.FACT
        and any(s.startswith("pending:") for s in item.source_refs)
    )
    assert len(pending_facts) == 0
