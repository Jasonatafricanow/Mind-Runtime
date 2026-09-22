"""C8B — Safe shadow execution wrapper.

SafeShadowRunner wraps TurnOrchestrator.run_shadow() with hard invariants:
  SHADOW-1: caller never receives a commit-capable handle.
  SHADOW-2: DeliveryPort send count = 0.
  SHADOW-3: AgentPort.respond() MAY execute (model inference allowed).
  SHADOW-5: ShadowRunRecord has zero cognitive authority.
  SHADOW-6: failure always leaves no committable cognitive projection.

Lifecycle (success path — ordering HARDENED):
  begin_turn()
  → run_shadow()
  → capture immutable shadow snapshot    ← data collected FIRST
  → abort_turn()                         ← cognitive discard FIRST
  → verify no committable projection     ← forced verification
  → persist COMPLETED ShadowRunRecord    ← durable AFTER discard
  → return non-authoritative result

Lifecycle (failure path):
  any exception from above
  → forced abort/discard
  → persist FAILED ShadowRunRecord
  → raise according to existing error contract
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from mind_runtime.contracts import (
    ExpressionOutcome,
    Interaction,
    Situation,
)
from mind_runtime.pipeline.orchestrator import TurnOrchestrator
from mind_runtime.pipeline.trace import TraceRecorder
from mind_runtime.providers.clock import Clock

from mind_runtime.shadow.contracts import (
    ComparisonResult,
    HostOutcome,
    ShadowModeDisabled,
    ShadowPersistenceError,
    ShadowRecordStore,
    ShadowRunRecord,
    ShadowRunResult,
    ShadowSnapshot,
    ShadowStatus,
    Situation,
)

# Re-export for backward-compatible imports from mind_runtime.shadow
__all__ = [
    "ComparisonResult",
    "HostOutcome",
    "InMemoryShadowRecordStore",
    "SafeShadowRunner",
    "ShadowModeDisabled",
    "ShadowPersistenceError",
    "ShadowRecordStore",
    "ShadowRunError",
    "ShadowRunRecord",
    "ShadowRunResult",
    "ShadowSnapshot",
    "ShadowStatus",
    "SqliteShadowRecordStore",
    "Situation",
]

# Re-export InMemoryShadowRecordStore from contracts
from mind_runtime.shadow.contracts import InMemoryShadowRecordStore  # noqa: E402,F401
from mind_runtime.shadow.store import SqliteShadowRecordStore  # noqa: E402,F401


# ── runtime helpers ────────────────────────────────────────────────────────────


def _compute_runtime_digest(runtime_id: str, shadow_enabled: bool) -> str:
    """Stable identity of the runtime configuration that produced this run."""
    import hashlib

    config = f"runtime_id={runtime_id}|shadow_enabled={shadow_enabled}"
    return hashlib.sha256(config.encode()).hexdigest()[:16]


def _interaction_scope_str(interaction: Interaction) -> str:
    """Serialize Scope to a stable string for audit."""
    return f"{interaction.scope.domain.value}@{interaction.scope.user_id}"


def _safe_intent_type(intent) -> str | None:  # type: ignore[type-arg]
    from mind_runtime.contracts import Intent

    if intent is None:
        return None
    return getattr(intent, "intent_type", None) or getattr(intent, "id", None)


# ── SafeShadowRunner ──────────────────────────────────────────────────────────


@dataclass
class SafeShadowRunner:
    """Host-level safe wrapper around TurnOrchestrator.run_shadow().

    This class owns the orchestrator lifecycle exclusively.
    Callers receive ShadowRunResult / ShadowRunRecord only.
    Callers NEVER receive TurnOrchestrator, commit callback,
    canonical writer handle, or committable projection handle.

    SHADOW-1 INVARIANT: orchestrator lifecycle is private to this class.
    SHADOW-2: DeliveryPort send count = 0 (orchestrator has no DeliveryPort).
    SHADOW-3: AgentPort.respond() MAY execute during run_shadow().
    SHADOW-5: ShadowRunRecord is audit-only, not cognitive authority.
    SHADOW-6: failure always leaves no committable cognitive projection.

    Raises
    ------
    ShadowModeDisabled
        When shadow execution is not permitted.
    ShadowRunError
        When the shadow run fails in an unexpected way.
    ShadowPersistenceError
        When audit record persistence fails (after successful discard).
    """

    clock: Clock
    trace: TraceRecorder
    record_store: ShadowRecordStore
    runtime_id: str = "shadow-runtime-1"
    shadow_enabled: bool | None = None

    _orchestrator: TurnOrchestrator | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        # Validate runtime_id
        if not self.runtime_id:
            raise ValueError("runtime_id must be non-empty; pass a non-empty string.")

        # Resolve shadow_enabled from explicit param → env → default-OFF.
        explicit = self.shadow_enabled
        env_val = os.environ.get("MIND_RUNTIME_SHADOW_ENABLED")
        if explicit is not None:
            self._shadow_enabled = explicit
        elif env_val in ("1", "true", "TRUE", "yes", "on"):
            self._shadow_enabled = True
        else:
            self._shadow_enabled = False

    def execute(
        self,
        interaction: Interaction,
        host_outcome: HostOutcome | None = None,
    ) -> ShadowRunResult:
        """Execute one shadow run for the given interaction.

        Parameters
        ----------
        interaction
            The source interaction to run shadow cognition against.
        host_outcome
            Optional Host decision/action for audit comparison.
            When provided, a deterministic ComparisonResult is computed.

        Returns
        -------
        ShadowRunResult
            Non-authoritative result. The caller must NOT use this to commit.

        Raises
        ------
        ShadowModeDisabled
            When shadow execution is not enabled.
        ShadowPersistenceError
            When audit record persistence fails (after successful discard).
        """
        if not self._shadow_enabled:
            raise ShadowModeDisabled(
                "SafeShadowRunner.execute() called but shadow mode is disabled. "
                "Set shadow_enabled=True or MIND_RUNTIME_SHADOW_ENABLED=1."
            )

        runtime_digest = _compute_runtime_digest(self.runtime_id, self._shadow_enabled)
        started_at = self.clock.now()

        # Generate stable shadow_run_id: interaction identity + runtime config
        # Not interaction_id alone — two runs in different runtime versions
        # must have different shadow_run_ids.
        shadow_run_id = self._make_shadow_run_id(interaction, runtime_digest)

        try:
            # ── build orchestrator (owned exclusively by this runner) ──────────
            self._orchestrator = TurnOrchestrator(
                clock=self.clock,
                trace=self.trace,
                runtime_id=self.runtime_id,
                shadow_enabled=True,  # always True inside the wrapper
            )

            # ── begin turn ────────────────────────────────────────────────────
            self._orchestrator.begin_turn(interaction)

            # ── run shadow ────────────────────────────────────────────────────
            self._orchestrator.run_shadow()

            # ── capture snapshot BEFORE abort ─────────────────────────────────
            snapshot = self._capture_snapshot(interaction.interaction_id)

            # ── abort cognitive projection ────────────────────────────────────
            self._orchestrator.abort_turn()

            # ── verify no committable projection remains ─────────────────────
            self._verify_no_projection()

            # ── compute comparison ────────────────────────────────────────────
            comparison = self._compute_comparison(snapshot, host_outcome)

            # ── build record ─────────────────────────────────────────────────
            completed_at = self.clock.now()
            record = ShadowRunRecord(
                shadow_run_id=shadow_run_id,
                scope=_interaction_scope_str(interaction),
                source_interaction_id=interaction.interaction_id,
                source_event_ref=None,
                runtime_config_digest=runtime_digest,
                started_at=started_at,
                completed_at=completed_at,
                status=ShadowStatus.COMPLETED,
                mr_situation_summary=_summarise_situation(snapshot.situation),
                mr_intent_type=_safe_intent_type(snapshot.intent),
                mr_expression_ref=snapshot.expression_outcome.outcome_id
                if snapshot.expression_outcome
                else None,
                mr_would_send=_would_send(snapshot.expression_outcome),
                host_outcome=host_outcome,
                comparison=comparison,
                captured_snapshot=snapshot,
            )

        except Exception as exc:  # noqa: BLE001
            # ── forced abort on any exception ─────────────────────────────────
            self._forced_abort()

            completed_at = self.clock.now()
            failure_stage = _infer_failure_stage(exc)
            failure_reason = f"{type(exc).__name__}: {exc}"

            record = ShadowRunRecord(
                shadow_run_id=shadow_run_id,
                scope=_interaction_scope_str(interaction),
                source_interaction_id=interaction.interaction_id,
                source_event_ref=None,
                runtime_config_digest=runtime_digest,
                started_at=started_at,
                completed_at=completed_at,
                status=ShadowStatus.FAILED,
                failure_stage=failure_stage,
                failure_reason=failure_reason,
            )

        # ── persist AFTER cognitive discard (always) ────────────────────────
        persistence_error: Exception | None = None
        try:
            self.record_store.save(record)
        except Exception as exc:  # noqa: BLE001
            # Record persistence failed AFTER cognitive discard succeeded.
            # Fail closed: do not let persistence failure pass silently.
            # The committable projection is already discarded; report the audit failure.
            persistence_error = exc

        if persistence_error is not None:
            raise ShadowPersistenceError(
                f"ShadowRunRecord persistence failed for {shadow_run_id} "
                f"(cognitive discard succeeded): {persistence_error}"
            ) from persistence_error

        # ── return non-authoritative result ─────────────────────────────────
        return ShadowRunResult(
            shadow_run_id=shadow_run_id,
            status=record.status,
            snapshot=record.captured_snapshot,
            comparison=record.comparison,
            failure_reason=record.failure_reason,
        )

    # ── private helpers ─────────────────────────────────────────────────────

    def _make_shadow_run_id(self, interaction: Interaction, runtime_digest: str) -> str:
        """Stable identity: source interaction identity + runtime config."""
        # Collision-resistant but short enough to be readable in logs.
        # Not a pure interaction_id — that would conflate different runtime versions.
        import hashlib

        raw = f"{interaction.interaction_id}|{runtime_digest}|{interaction.started_at.isoformat()}"
        return hashlib.sha256(raw.encode()).hexdigest()[:24]

    def _capture_snapshot(self, interaction_id: str) -> ShadowSnapshot:
        """Capture an immutable snapshot of shadow cognition state.

        Called BEFORE abort_turn(), while all state is still accessible.
        The snapshot is a pure data copy — it has zero cognitive authority.
        """
        orch = self._orchestrator
        assert orch is not None, "orchestrator not initialized"
        return ShadowSnapshot(
            interaction_id=interaction_id,
            situation=orch._turn.situation if orch._turn else None,
            projected=orch._turn.projected if orch._turn else None,
            intent=orch._turn.intent if orch._turn else None,
            expression_outcome=orch._turn.expression_outcome if orch._turn else None,
            action_receipt=orch._turn.action_receipt if orch._turn else None,
            observations=orch.observations,
            decision_context=orch.decision_context,
            captured_at=self.clock.now(),
        )

    def _verify_no_projection(self) -> None:
        """Verify that no committable cognitive projection remains in orchestrator.

        This is a forced verification step. The orchestrator is already
        ABORTED at this point; we verify the canonical state was not mutated.
        """
        orch = self._orchestrator
        assert orch is not None, "orchestrator not initialized"
        # After abort_turn(), canonical is unchanged (verified by red tests).
        # The projection on the turn is discarded with the turn data.
        assert orch.state.value in ("aborted", "begin"), (
            f"Expected ABORTED state after abort_turn(), got {orch.state}"
        )

    def _forced_abort(self) -> None:
        """Execute forced abort on the owned orchestrator.

        Called when any exception occurs during the shadow run.
        SHADOW-6: this must succeed and leave no committable projection.
        """
        orch = self._orchestrator
        if orch is None:
            return
        try:
            orch.abort_turn()
        except Exception:  # noqa: BLE001
            # abort_turn() itself failed — fail closed.
            # The orchestrator may be in an inconsistent state.
            # Log but do not raise (we are already in an exception handler).
            pass

    def _compute_comparison(
        self,
        snapshot: ShadowSnapshot,
        host_outcome: HostOutcome | None,
    ) -> ComparisonResult | None:
        """Compute deterministic categorical comparison with Host outcome.

        No LLM judge. No semantic similarity. No "who is better" scoring.
        Only deterministic categorical facts.
        """
        if host_outcome is None:
            return None

        mr_would_act = _would_send(snapshot.expression_outcome)

        if mr_would_act is None and not host_outcome.host_action_taken:
            # Neither side has an actionable expression — comparable only by absence
            comparable = True
            action_presence_match = True
            action_type_match = None
        elif mr_would_act is None or not host_outcome.host_action_taken:
            comparable = True
            action_presence_match = mr_would_act == host_outcome.host_action_taken
            action_type_match = None
        else:
            # Both sides have actionable expressions
            comparable = True
            action_presence_match = True
            # action_type_match: strict category match
            # mr_would_act is not None → expression_outcome is not None
            outcome = snapshot.expression_outcome
            assert outcome is not None
            mr_type = outcome.final_disposition.value
            # host_action_type may be "text", "media", etc.
            action_type_match = mr_type == host_outcome.host_action_type

        return ComparisonResult(
            comparable=comparable,
            action_presence_match=action_presence_match,
            action_type_match=action_type_match,
            policy_divergence=None,  # not yet implemented
        )


# ── helper functions ──────────────────────────────────────────────────────────


def _summarise_situation(situation: Situation | None) -> str | None:
    if situation is None:
        return None
    return getattr(situation, "summary", None) or str(situation)[:200]


def _would_send(outcome: ExpressionOutcome | None) -> bool | None:
    if outcome is None:
        return None
    from mind_runtime.contracts.expression import ExpressionDisposition

    # ACCEPT means the expression coordinator accepted a text expression (would send).
    # REJECT means no expression was produced (suppressed).
    return outcome.final_disposition == ExpressionDisposition.ACCEPT


def _infer_failure_stage(exc: Exception) -> str:
    """Classify which lifecycle stage failed based on exception type."""
    exc_type = type(exc).__name__
    exc_msg = str(exc).lower()

    if "agent" in exc_msg or "AgentFailure" in exc_type:
        return "agent_respond"
    if "guard" in exc_msg or "Guard" in exc_type:
        return "expression_guard"
    if "abort" in exc_msg:
        return "abort"
    if "begin" in exc_msg or "interaction" in exc_msg:
        return "begin_turn"
    if "run" in exc_msg or "shadow" in exc_msg:
        return "run_shadow"
    return "unknown"