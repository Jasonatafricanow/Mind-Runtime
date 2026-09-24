"""HI-1-R1: MindRuntimeHostAdapter — the production Host adapter.

The adapter is the single, thin wrapper that lets any Agent Host call
Mind Runtime through the `MindRuntimeHostPort` surface. It does NOT
duplicate domain logic: it converts Host requests into existing
production types (Interaction, Evidence) and delegates to the canonical
`TurnOrchestrator`. The orchestrator owns all cognitive authority.

Hard rules:

  1. No second pipeline, no second appraisal engine, no second memory
     writer. The orchestrator is the only consumer of facts, appraisal,
     intent, and dynamics.
  2. No Host-visible numeric affect, shock, timescale, persona mutation,
     appraisal verdict. The contract types carry refs only.
  3. Host-level replay/idempotency: a replayed `interaction_id` that is
     already terminal (committed or aborted) returns ALREADY_PROCESSED
     WITHOUT re-entering the cognition pipeline. The Host gets the
     previous terminal result. This is the at-least-once delivery
     contract.
  4. Fact-layer replay: a replayed `interaction_id` with identical
     evidence bytes is handled by the fact plane (REPLAY disposition);
     the adapter surfaces this as OK.
  5. Provider failure (timeout, invalid output, unavailable) is treated
     as FAILED. The Host is not crashed. No projection is promoted.
  6. Authority / binding / scope mismatches fail closed as FAILED.
  7. HostTurnResult.bounded_context exposes a HostDecisionContext
     (human-readable summaries) so the Host can compile the next
     reply LLM input. This is separate from `decision_context_ref`
     (OW correlation) and `debug_ref` (trace access).
"""

from __future__ import annotations

import logging
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

from mind_runtime.cognition.express import (
    ProactiveExpressionArtifact,
    ProactiveExpressionPreparer,
)
from mind_runtime.contracts import (
    ActionDecision,
    ActionPermission,
    ActionPolicyResult,
    Authority,
    AuthorityLevel,
    Evidence,
    ExpressionDisposition,
    IntentStatus,
    Interaction,
    InteractionStatus,
    ProjectedMindState,
    Situation,
    SyncFields,
)
from mind_runtime.contracts.host import (
    HostAbortReceipt,
    HostAbortRequest,
    HostCommitReceipt,
    HostCommitRequest,
    HostDecisionContext,
    HostInspectRequest,
    HostInspectResult,
    HostProactiveTurnResult,
    HostProviderProseRequest,
    HostProviderProseResult,
    HostStatus,
    HostTurnRequest,
    HostTurnResult,
    HostTurnStatus,
    HostWakeNotification,
)
from mind_runtime.contracts.intent import WakeSignal
from mind_runtime.pipeline.orchestrator import (
    StaleProjectionError,
    TurnOrchestrator,
    TurnState,
)
from mind_runtime.pipeline.trace import TraceRecorder

_logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _interaction_from_request(request: HostTurnRequest) -> Interaction:
    """Translate HostTurnRequest into a production Interaction."""
    return Interaction(
        interaction_id=request.interaction_id,
        scope=request.scope,
        channel=request.channel,
        session_id=request.session_id or request.interaction_id,
        turn_id=f"turn-{request.interaction_id}",
        started_at=request.occurred_at,
        committed_at=None,
        status=InteractionStatus.OPEN,
    )


def _evidence_from_request(request: HostTurnRequest) -> Evidence:
    """Translate HostTurnRequest into a single user-message Evidence.

    The Host contract carries one user message per turn. The Host
    cannot supply AppraisalResult, numeric affect, or any other
    authority-bearing payload — by construction.

    `received_at` is anchored to `occurred_at` (not wall-clock) so the
    evidence bytes are deterministic across a replayed HostTurnRequest
    with the same interaction_id + payload. This is what makes
    fact-plane REPLAY work for the idempotency contract.
    """
    evidence_id = f"evidence-{request.interaction_id}"
    sync = SyncFields(
        scope=request.scope,
        origin_runtime_id=request.runtime_id,
        object_id=evidence_id,
        version=1,
        idempotency_key=f"idem-{evidence_id}",
    )
    return Evidence(
        id=evidence_id,
        scope=request.scope,
        origin_runtime_id=request.runtime_id,
        source_type="user_message",
        source_id=f"host-{request.interaction_id}",
        authority_level=AuthorityLevel.ASSERTED,
        authority=Authority(
            scope=request.scope,
            level=AuthorityLevel.ASSERTED,
            source_id=f"host-{request.interaction_id}",
        ),
        occurred_at=request.occurred_at,
        received_at=request.occurred_at,
        payload={"text": request.user_message},
        sync=sync,
    )


def _decision_context_ref(orchestrator: TurnOrchestrator) -> str | None:
    ctx = orchestrator.decision_context
    return ctx.context_id if ctx is not None else None


def _expression_ref(orchestrator: TurnOrchestrator) -> str | None:
    outcome = orchestrator.expression_outcome
    return outcome.outcome_id if outcome is not None else None


def _projection_ref(orchestrator: TurnOrchestrator) -> str | None:
    projection = orchestrator.turn_projection
    return projection.projection_id if projection is not None else None


def _situation_ref(orchestrator: TurnOrchestrator) -> str | None:
    situation = orchestrator.situation
    return situation.situation_id if situation is not None else None


def _to_turn_status(state: TurnState) -> HostTurnStatus:
    if state is TurnState.BEGIN:
        return HostTurnStatus.BEGIN
    if state in (
        TurnState.INGESTING,
        TurnState.PROCESSING,
        TurnState.DISPATCHING,
        TurnState.AWAITING_COMMIT,
    ):
        return HostTurnStatus.PROCESSING
    if state is TurnState.COMMITTED:
        return HostTurnStatus.COMMITTED
    if state is TurnState.ABORTED:
        return HostTurnStatus.ABORTED
    return HostTurnStatus.FAILED


def _step_slow_state_summary(dctx) -> str | None:
    """Render the MR slow-state projection into a prompt-safe one-liner.

    C2 forwarding (STEP 2-B): the MR DecisionContext.expression_context already
    carries authoritative slow-state items (kind=INTERNAL_STATE, key prefix
    ``slow_``), e.g. ``slow_agent.longitudinal.relationship_security = 0.8``.
    We surface those verbatim (no numeric reinterpretation). Returns None when
    no slow-state item is present.
    """
    try:
        from mind_runtime.contracts.expression import ExpressionContextKind

        items = dctx.expression_context or ()
        slow = [
            it for it in items
            if it.kind is ExpressionContextKind.INTERNAL_STATE
            and it.key.startswith("slow_")
        ]
        if not slow:
            return None
        parts = [f"{it.key} = {it.value}" for it in slow]
        return "; ".join(parts)
    except Exception as exc:  # noqa: BLE001 — fail-soft, never break the Host
        _logger.warning("slow_state_summary failed: %s", exc)
        return None


def _bounded_context(orchestrator: TurnOrchestrator) -> HostDecisionContext | None:
    """Build a HostDecisionContext from the orchestrator's current state.

    Returns None if the orchestrator has no decision context yet.
    The summaries are human-readable strings, never numeric values.
    """
    ctx = orchestrator.decision_context
    if ctx is None:
        return None
    compiler = getattr(orchestrator, "decision_context_compiler", None)
    configured_surface = getattr(getattr(compiler, "_config", None), "mode", None) == "SURFACE_V1"
    if configured_surface or any(
        getattr(it, "kind", None) == "surface_guidance" for it in ctx.expression_context
    ):
        request = orchestrator.surface_handoff_request()
        if (
            request is None
            or request.surface_handoff is None
            or request.surface_handoff.context_id != ctx.context_id
        ):
            raise ValueError("SURFACE_V1 has no matching durable admitted handoff")
        envelope_text = request.payload_bytes.decode("utf-8", errors="strict")
        from mind_runtime.expression.renderer import DeterministicContextRenderer

        DeterministicContextRenderer.verify_provider_information_isolation(envelope_text)
        return HostDecisionContext(
            intent_summary=ctx.selected_intent_kind,
            emotional_state="admitted Surface expression guidance",
            situation_summary="admitted situation context",
            action_taken=ctx.selected_action_type,
            next_steps=None,
            provider_envelope_text=envelope_text,
        )
    # The selected_intent_kind is a stable enum-like string; safe to
    # surface. We never expose the underlying numeric affect, the
    # ResolvedAppraisal, or any other MR internal object.
    intent_summary = ctx.selected_intent_kind
    # Legacy C2 forwarding remains here. SURFACE_V1 already returned the
    # exact renderer-admitted C7 envelope above, so it cannot reconstruct a
    # parallel guidance string or restore Slow numeric state in this branch.
    slow_summary = _step_slow_state_summary(ctx)
    emotional_state = f"intent={ctx.selected_intent_kind}; attempt={ctx.attempt}"
    if slow_summary:
        emotional_state += f"; slow_state: {slow_summary}"
    situation_summary = f"situation_ref={ctx.situation_ref}"
    renderer = orchestrator.context_renderer
    meaning = renderer.render_cognitive_meaning(ctx) if hasattr(
        renderer, "render_cognitive_meaning"
    ) else None
    return HostDecisionContext(
        intent_summary=intent_summary,
        emotional_state=emotional_state,
        situation_summary=situation_summary,
        action_taken=ctx.selected_action_type,
        next_steps=None,
        cognitive_meaning=meaning,
    )


def _empty_bounded_context(reason: str) -> HostDecisionContext:
    """Return a minimal bounded context for replay/already-processed cases."""
    return HostDecisionContext(
        intent_summary=reason,
        emotional_state=reason,
        situation_summary=reason,
        action_taken=None,
        next_steps=None,
    )


# ---------------------------------------------------------------------------
# Replay / terminal-state store
# ---------------------------------------------------------------------------


class _TerminalRecord:
    """Record of a completed turn, kept in-memory for Host replay handling."""

    __slots__ = (
        "interaction_id",
        "user_message",
        "bounded_context",
        "turn_id",
        "terminal_status",
        "decision_context_ref",
        "expression_ref",
    )

    def __init__(
        self,
        interaction_id: str,
        user_message: str,
        bounded_context: HostDecisionContext | None,
        turn_id: str,
        terminal_status: HostTurnStatus,
        decision_context_ref: str | None,
        expression_ref: str | None,
    ) -> None:
        self.interaction_id = interaction_id
        self.user_message = user_message
        self.bounded_context = bounded_context
        self.turn_id = turn_id
        self.terminal_status = terminal_status
        self.decision_context_ref = decision_context_ref
        self.expression_ref = expression_ref


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------


class MindRuntimeHostAdapter:
    """Production implementation of `MindRuntimeHostPort`.

    Wraps one `TurnOrchestrator`. The adapter does not own a separate
    pipeline; it normalizes Host requests and delegates to the
    orchestrator's existing begin_turn / ingest / run / commit_turn /
    abort_turn / recover API.

    Host-level replay/idempotency is implemented via an in-memory
    terminal record store. When `begin_turn` is called with an
    `interaction_id` that is already terminal, the adapter returns
    ALREADY_PROCESSED without re-entering the cognition pipeline.
    """

    def __init__(
        self,
        *,
        orchestrator: TurnOrchestrator,
        trace: TraceRecorder | None = None,
        expression_preparer: ProactiveExpressionPreparer | None = None,
    ) -> None:
        if orchestrator is None:
            raise ValueError("orchestrator is required")
        self._orchestrator = orchestrator
        self._trace = trace or TraceRecorder()
        self._expression_preparer = expression_preparer
        self._consumed_wakes: dict[str, WakeSignal] = {}
        self._proactive_turn_results: dict[str, HostProactiveTurnResult] = {}
        self._pending_wake_contexts: dict[str, dict[str, Any]] = {}
        self._pending_exec_contexts: dict[str, Any] = {}
        # Terminal record store: interaction_id -> _TerminalRecord.
        # Populated at commit/abort time. Acts as the in-process
        # replay guard; the stored user_message is used for the
        # same-payload check on replay.
        self._terminal: dict[str, _TerminalRecord] = {}
        # Pending store: interaction_id -> user_message. Populated at
        # begin_turn time so commit/abort can finalize the terminal
        # record without reverse-lookup through Observation IDs or
        # FrozenMapping internals. Cleared when the terminal record
        # is written.
        self._pending_user_message: dict[str, str] = {}

    @property
    def orchestrator(self) -> TurnOrchestrator:
        """INTERNAL. The wrapped TurnOrchestrator. Tests use it; Hosts do not."""
        return self._orchestrator

    # ----- begin_turn --------------------------------------------------

    def begin_turn(self, request: HostTurnRequest) -> HostTurnResult:
        # REPLAY GUARD (Host-level idempotency).
        # If interaction_id is already terminal, return the previous
        # terminal result without re-entering the cognition pipeline.
        # This is the at-least-once delivery contract.
        terminal = self._terminal.get(request.interaction_id)
        if terminal is not None:
            return self._handle_replay(request, terminal)

        interaction = _interaction_from_request(request)
        evidence = _evidence_from_request(request)
        try:
            self._orchestrator.begin_turn(interaction)
            ingest_outcome = self._orchestrator.ingest(evidence)
            if ingest_outcome is None and evidence.id not in (
                ev.id for ev in self._orchestrator.observations
            ):
                # C9-W1B deferred admission: surface as DEGRADED so the
                # Host knows the evidence is pending and a follow-up
                # accept_pending is required. Hosts that do not use
                # the pending overlay can ignore this.
                outcome = HostStatus.DEGRADED
                reason_codes = ("fact_pending",)
            else:
                outcome = HostStatus.OK
                reason_codes = ("ingest_committed",)
            self._orchestrator.run()
            bounded = _bounded_context(self._orchestrator)
            # Stash the original user_message so commit/abort can later
            # finalize the _TerminalRecord. This avoids reverse-lookup
            # through Observation IDs or FrozenMapping internals.
            self._pending_user_message[request.interaction_id] = request.user_message
            return HostTurnResult(
                turn_id=interaction.turn_id,
                interaction_id=request.interaction_id,
                status=_to_turn_status(self._orchestrator.state),
                outcome=outcome,
                bounded_context=bounded,
                decision_context_ref=_decision_context_ref(self._orchestrator),
                expression_ref=_expression_ref(self._orchestrator),
                debug_ref=f"debug-{request.interaction_id}",
                reason_codes=reason_codes,
            )
        except Exception as exc:
            _logger.warning("HI-1 begin_turn failed: %s", exc)
            try:
                self._orchestrator.abort_turn()
            except Exception as _abort_err:
                _logger.debug("HI-1 abort_turn on begin_turn failure: %s", _abort_err)
            return HostTurnResult(
                turn_id=interaction.turn_id,
                interaction_id=request.interaction_id,
                status=HostTurnStatus.FAILED,
                outcome=HostStatus.FAILED,
                bounded_context=None,
                decision_context_ref=None,
                expression_ref=None,
                debug_ref=f"debug-{request.interaction_id}",
                reason_codes=("begin_failed", type(exc).__name__),
            )

    def _handle_replay(
        self, request: HostTurnRequest, terminal: _TerminalRecord
    ) -> HostTurnResult:
        """Handle a replay of a terminal interaction_id.

        - Same user_message: return ALREADY_PROCESSED + previous bounded
          context. No re-entry into the cognition pipeline.
        - Different user_message: fail closed with interaction_id_conflict.
        """
        if terminal.user_message != request.user_message:
            return HostTurnResult(
                turn_id=terminal.turn_id,
                interaction_id=request.interaction_id,
                status=terminal.terminal_status,
                outcome=HostStatus.FAILED,
                bounded_context=None,
                decision_context_ref=None,
                expression_ref=None,
                debug_ref=f"debug-{request.interaction_id}",
                reason_codes=("interaction_id_conflict", "payload_mismatch"),
            )
        # Compatible replay: return ALREADY_PROCESSED + previous result.
        return HostTurnResult(
            turn_id=terminal.turn_id,
            interaction_id=request.interaction_id,
            status=HostTurnStatus.ALREADY_PROCESSED,
            outcome=HostStatus.ALREADY_PROCESSED,
            bounded_context=terminal.bounded_context,
            decision_context_ref=terminal.decision_context_ref,
            expression_ref=terminal.expression_ref,
            debug_ref=f"debug-{request.interaction_id}",
            reason_codes=("replay", "no_reentry"),
        )

    # ----- commit_turn -------------------------------------------------

    def commit_turn(self, request: HostCommitRequest) -> HostCommitReceipt:
        if self._orchestrator.state is TurnState.COMMITTED:
            return HostCommitReceipt(
                turn_id=request.turn_id,
                interaction_id=request.interaction_id,
                status=HostStatus.OK,
                committed_at=datetime.now(UTC),
                projected_state_refs=(),
                commit_marker_ref=None,
                reason_codes=("already_committed",),
            )
        if self._orchestrator.state is TurnState.ABORTED:
            return HostCommitReceipt(
                turn_id=request.turn_id,
                interaction_id=request.interaction_id,
                status=HostStatus.FAILED,
                committed_at=datetime.now(UTC),
                reason_codes=("cannot_commit_aborted",),
            )
        try:
            if self._orchestrator.surface_handoff_request() is not None:
                self._orchestrator.acknowledge_surface_delivery()
            self._orchestrator.commit_turn()
        except (StaleProjectionError, RuntimeError, ValueError) as exc:
            _logger.warning("HI-1 commit_turn failed: %s", exc)
            # MR-RUNTIME-05: a failed admission must not leave the turn open
            # — abort (releasing the namespace admission lease) so other
            # consumers on the same runtime are never wedged.
            try:
                self._orchestrator.abort_turn()
            except Exception as _abort_err:
                _logger.debug("HI-1 abort on commit failure: %s", _abort_err)
            return HostCommitReceipt(
                turn_id=request.turn_id,
                interaction_id=request.interaction_id,
                status=HostStatus.FAILED,
                committed_at=datetime.now(UTC),
                reason_codes=("commit_failed", type(exc).__name__),
            )
        # Record the terminal state for future Host-level replays.
        self._record_terminal(request.interaction_id, committed=True)
        projection_ref = _projection_ref(self._orchestrator)
        return HostCommitReceipt(
            turn_id=request.turn_id,
            interaction_id=request.interaction_id,
            status=HostStatus.OK,
            committed_at=datetime.now(UTC),
            projected_state_refs=(projection_ref,) if projection_ref is not None else (),
            commit_marker_ref=f"commit-marker-{request.interaction_id}",
            reason_codes=("projection_committed",),
        )

    def guard_provider_prose(self, request: HostProviderProseRequest) -> HostProviderProseResult:
        """SURFACE_V1 Guard gate before the Host sends provider prose outward."""
        try:
            turn = self._orchestrator._require_turn()
            if (
                turn.interaction.interaction_id != request.interaction_id
                or turn.interaction.turn_id != request.turn_id
            ):
                raise ValueError("SURFACE_GUARD_TURN_MISMATCH")
            verdict = self._orchestrator.guard_surface_provider_prose(request.prose)
            return HostProviderProseResult(
                interaction_id=request.interaction_id,
                status=(HostStatus.OK if verdict.disposition is ExpressionDisposition.ACCEPT
                        else HostStatus.FAILED),
                reason_codes=tuple(verdict.violations),
            )
        except (ValueError, RuntimeError) as exc:
            return HostProviderProseResult(
                interaction_id=request.interaction_id,
                status=HostStatus.FAILED,
                reason_codes=(type(exc).__name__,),
            )

    # ----- abort_turn --------------------------------------------------

    def abort_turn(self, request: HostAbortRequest) -> HostAbortReceipt:
        if self._orchestrator.state is TurnState.ABORTED:
            return HostAbortReceipt(
                turn_id=request.turn_id,
                interaction_id=request.interaction_id,
                status=HostStatus.OK,
                aborted_at=datetime.now(UTC),
                ingested_facts_retained=True,
                reason_codes=("already_aborted",),
            )
        if self._orchestrator.state is TurnState.COMMITTED:
            return HostAbortReceipt(
                turn_id=request.turn_id,
                interaction_id=request.interaction_id,
                status=HostStatus.FAILED,
                aborted_at=datetime.now(UTC),
                ingested_facts_retained=True,
                reason_codes=("cannot_abort_committed",),
            )
        try:
            self._orchestrator.abort_turn()
        except (RuntimeError, ValueError) as exc:
            _logger.warning("HI-1 abort_turn failed: %s", exc)
            return HostAbortReceipt(
                turn_id=request.turn_id,
                interaction_id=request.interaction_id,
                status=HostStatus.FAILED,
                aborted_at=datetime.now(UTC),
                ingested_facts_retained=True,
                reason_codes=("abort_failed", type(exc).__name__),
            )
        # Record the terminal state for future Host-level replays.
        self._record_terminal(request.interaction_id, committed=False)
        return HostAbortReceipt(
            turn_id=request.turn_id,
            interaction_id=request.interaction_id,
            status=HostStatus.OK,
            aborted_at=datetime.now(UTC),
            ingested_facts_retained=True,
            reason_codes=("projection_discarded",),
        )

    # ----- inspect -----------------------------------------------------

    def inspect(self, request: HostInspectRequest) -> HostInspectResult:
        if request.include_trace:
            trace = self._trace.trace(request.interaction_id)
            trace_pairs = tuple(
                (entry.stage, entry.outcome, entry.ref, _iso(entry.at))
                for entry in trace
            )
        else:
            trace_pairs = ()
        recovery = None
        try:
            decision = self._orchestrator.recover(request.interaction_id)
            recovery = str(decision)
        except (RuntimeError, ValueError):
            recovery = None
        return HostInspectResult(
            interaction_id=request.interaction_id,
            turn_id=request.turn_id,
            turn_status=_to_turn_status(self._orchestrator.state),
            decision_context_ref=(
                _decision_context_ref(self._orchestrator)
                if request.include_decision_context
                else None
            ),
            situation_ref=_situation_ref(self._orchestrator),
            expression_ref=_expression_ref(self._orchestrator),
            projection_ref=(
                _projection_ref(self._orchestrator)
                if request.include_projection
                else None
            ),
            trace=trace_pairs,
            recovery_decision=recovery,
        )

    def consume_wake(self, wake: WakeSignal) -> HostWakeNotification:
        """HI-1: Smallest typed consumer of proactive wake signals at the Host boundary.

        Authoritatively validates wake lineage and records host admission.
        """
        if not isinstance(wake, WakeSignal):
            raise ValueError("wake must be a WakeSignal")

        # Replay guard check
        if wake.wake_id in self._consumed_wakes:
            prev = self._consumed_wakes[wake.wake_id]
            if prev == wake:
                return HostWakeNotification(
                    wake_id=wake.wake_id,
                    runtime_id=wake.runtime_id,
                    scope=wake.scope,
                    intent_id=wake.intent_id,
                    action_type=wake.action_type,
                    occurred_at=wake.woken_at,
                    eligible=True,
                    intent_version=wake.intent_version,
                    interaction_id=wake.interaction_id,
                    policy_decision_ref=wake.policy_decision_ref,
                    reason="already_consumed",
                )
            return HostWakeNotification(
                wake_id=wake.wake_id,
                runtime_id=wake.runtime_id,
                scope=wake.scope,
                intent_id=wake.intent_id,
                action_type=wake.action_type,
                occurred_at=wake.woken_at,
                eligible=False,
                intent_version=wake.intent_version,
                interaction_id=wake.interaction_id,
                policy_decision_ref=wake.policy_decision_ref,
                reason="rejected:conflicting_wake_payload",
            )

        # 1. Validate runtime_id
        orch_runtime_id = getattr(self._orchestrator, "runtime_id", None) or getattr(
            self._orchestrator, "_runtime_id", None
        )
        if orch_runtime_id and wake.runtime_id != orch_runtime_id:
            return HostWakeNotification(
                wake_id=wake.wake_id,
                runtime_id=wake.runtime_id,
                scope=wake.scope,
                intent_id=wake.intent_id,
                action_type=wake.action_type,
                occurred_at=wake.woken_at,
                eligible=False,
                intent_version=wake.intent_version,
                interaction_id=wake.interaction_id,
                policy_decision_ref=wake.policy_decision_ref,
                reason="rejected:runtime_id_mismatch",
            )

        # 2. Validate against intent lifecycle (FAIL CLOSED)
        components = getattr(self._orchestrator, "cognitive_tick_components", None) or {}
        lifecycle = (
            components.get("lifecycle")
            or components.get("intent_lifecycle")
            or getattr(self._orchestrator, "intent_lifecycle", None)
            or getattr(self._orchestrator, "_intent_lifecycle", None)
        )
        if lifecycle is None or not hasattr(lifecycle, "backend"):
            return HostWakeNotification(
                wake_id=wake.wake_id,
                runtime_id=wake.runtime_id,
                scope=wake.scope,
                intent_id=wake.intent_id,
                action_type=wake.action_type,
                occurred_at=wake.woken_at,
                eligible=False,
                intent_version=wake.intent_version,
                interaction_id=wake.interaction_id,
                policy_decision_ref=wake.policy_decision_ref,
                reason="rejected:intent_authority_unavailable",
            )

        # 3. Validate against action policy (FAIL CLOSED)
        action_policy = (
            components.get("policy")
            or components.get("action_policy")
            or getattr(self._orchestrator, "action_policy", None)
            or getattr(self._orchestrator, "_action_policy", None)
        )
        if action_policy is None or not hasattr(action_policy, "_rules"):
            return HostWakeNotification(
                wake_id=wake.wake_id,
                runtime_id=wake.runtime_id,
                scope=wake.scope,
                intent_id=wake.intent_id,
                action_type=wake.action_type,
                occurred_at=wake.woken_at,
                eligible=False,
                intent_version=wake.intent_version,
                interaction_id=wake.interaction_id,
                policy_decision_ref=wake.policy_decision_ref,
                reason="rejected:policy_authority_unavailable",
            )

        current_intent = None
        try:
            history = lifecycle.backend.history(wake.scope, wake.intent_id)
            if history:
                current_intent = history[-1]
        except Exception:
            current_intent = None

        if current_intent is None:
            exists_other_scope = False
            conn = getattr(lifecycle.backend, "_conn", None)
            if conn is not None:
                try:
                    row = conn.execute(
                        "SELECT 1 FROM intents WHERE intent_id = ? LIMIT 1",
                        (wake.intent_id,),
                    ).fetchone()
                    if row is not None:
                        exists_other_scope = True
                except Exception:
                    pass
            raw_hist = getattr(lifecycle.backend, "_history", None)
            if isinstance(raw_hist, dict):
                for (sc, i_id), _ in raw_hist.items():
                    if i_id == wake.intent_id and sc != wake.scope:
                        exists_other_scope = True
                        break

            reason = (
                "rejected:scope_mismatch"
                if exists_other_scope
                else "rejected:unknown_intent_id"
            )
            return HostWakeNotification(
                wake_id=wake.wake_id,
                runtime_id=wake.runtime_id,
                scope=wake.scope,
                intent_id=wake.intent_id,
                action_type=wake.action_type,
                occurred_at=wake.woken_at,
                eligible=False,
                intent_version=wake.intent_version,
                interaction_id=wake.interaction_id,
                policy_decision_ref=wake.policy_decision_ref,
                reason=reason,
            )

        # Validate intent status
        if current_intent.status is not IntentStatus.ALLOWED:
            return HostWakeNotification(
                wake_id=wake.wake_id,
                runtime_id=wake.runtime_id,
                scope=wake.scope,
                intent_id=wake.intent_id,
                action_type=wake.action_type,
                occurred_at=wake.woken_at,
                eligible=False,
                intent_version=wake.intent_version,
                interaction_id=wake.interaction_id,
                policy_decision_ref=wake.policy_decision_ref,
                reason="rejected:intent_not_allowed",
            )

        # Validate intent version
        if current_intent.sync.version != wake.intent_version:
            return HostWakeNotification(
                wake_id=wake.wake_id,
                runtime_id=wake.runtime_id,
                scope=wake.scope,
                intent_id=wake.intent_id,
                action_type=wake.action_type,
                occurred_at=wake.woken_at,
                eligible=False,
                intent_version=wake.intent_version,
                interaction_id=wake.interaction_id,
                policy_decision_ref=wake.policy_decision_ref,
                reason="rejected:intent_version_mismatch",
            )

        # Validate action_type
        rule = action_policy._rules.get(current_intent.kind)
        if rule is None:
            return HostWakeNotification(
                wake_id=wake.wake_id,
                runtime_id=wake.runtime_id,
                scope=wake.scope,
                intent_id=wake.intent_id,
                action_type=wake.action_type,
                occurred_at=wake.woken_at,
                eligible=False,
                intent_version=wake.intent_version,
                interaction_id=wake.interaction_id,
                policy_decision_ref=wake.policy_decision_ref,
                reason="rejected:unsupported_intent_action",
            )
        if wake.action_type != rule.action_type:
            return HostWakeNotification(
                wake_id=wake.wake_id,
                runtime_id=wake.runtime_id,
                scope=wake.scope,
                intent_id=wake.intent_id,
                action_type=wake.action_type,
                occurred_at=wake.woken_at,
                eligible=False,
                intent_version=wake.intent_version,
                interaction_id=wake.interaction_id,
                policy_decision_ref=wake.policy_decision_ref,
                reason="rejected:action_type_mismatch",
            )

        # Admitted!
        self._consumed_wakes[wake.wake_id] = wake
        if hasattr(self._orchestrator, "trace") and self._orchestrator.trace is not None:
            self._orchestrator.trace.record(
                wake.interaction_id,
                "host_wake_admitted",
                ref=wake.wake_id,
                outcome=wake.action_type,
                at=wake.woken_at,
            )
        return HostWakeNotification(
            wake_id=wake.wake_id,
            runtime_id=wake.runtime_id,
            scope=wake.scope,
            intent_id=wake.intent_id,
            action_type=wake.action_type,
            occurred_at=wake.woken_at,
            eligible=True,
            intent_version=wake.intent_version,
            interaction_id=wake.interaction_id,
            policy_decision_ref=wake.policy_decision_ref,
            reason="proactive_intent_allowed",
        )

    def _resolve_expression_preparer(self) -> ProactiveExpressionPreparer | None:
        if self._expression_preparer is not None:
            return self._expression_preparer
        direct = getattr(self._orchestrator, "proactive_expression_preparer", None)
        if direct is not None and isinstance(direct, ProactiveExpressionPreparer):
            return direct
        components = getattr(self._orchestrator, "cognitive_tick_components", None)
        if isinstance(components, dict):
            prep = components.get("expression_preparer")
            if isinstance(prep, ProactiveExpressionPreparer):
                return prep
        return None

    def _resolve_tick_context(self, wake: WakeSignal) -> dict[str, Any] | None:
        if wake.wake_id in self._pending_wake_contexts:
            return self._pending_wake_contexts[wake.wake_id]
        components = getattr(self._orchestrator, "cognitive_tick_components", None)
        if isinstance(components, dict):
            ticker = components.get("ticker")
            if ticker is not None and hasattr(ticker, "get_pending_wake_context"):
                ctx = ticker.get_pending_wake_context(wake.wake_id)
                if ctx is not None:
                    return ctx
        return None

    def begin_proactive_turn(self, wake: WakeSignal) -> HostProactiveTurnResult:
        """HI-1: Admit wake and prepare bounded execution context for external Body."""
        if not isinstance(wake, WakeSignal):
            raise ValueError("wake must be a WakeSignal")

        # Process-local replay check
        if wake.wake_id in self._proactive_turn_results:
            cached = self._proactive_turn_results[wake.wake_id]
            if wake.wake_id in self._consumed_wakes and self._consumed_wakes[wake.wake_id] != wake:
                return HostProactiveTurnResult(
                    wake_id=wake.wake_id,
                    interaction_id=wake.interaction_id,
                    status=HostTurnStatus.FAILED,
                    outcome=HostStatus.FAILED,
                    decision_context_ref=None,
                    expression_ref=None,
                    debug_ref=f"debug-{wake.interaction_id}",
                    reason_codes=("wake_conflict", "conflicting_wake_payload"),
                )
            return replace(
                cached,
                status=HostTurnStatus.ALREADY_PROCESSED,
                outcome=HostStatus.ALREADY_PROCESSED,
            )

        # Admission check
        notification = self.consume_wake(wake)
        if not notification.eligible:
            return HostProactiveTurnResult(
                wake_id=wake.wake_id,
                interaction_id=wake.interaction_id,
                status=HostTurnStatus.FAILED,
                outcome=HostStatus.FAILED,
                decision_context_ref=None,
                expression_ref=None,
                debug_ref=f"debug-{wake.interaction_id}",
                reason_codes=("wake_rejected", notification.reason),
            )

        now = wake.woken_at
        if hasattr(self._orchestrator, "trace") and self._orchestrator.trace is not None:
            self._orchestrator.trace.record(
                wake.interaction_id,
                "proactive_body_entry",
                ref=wake.wake_id,
                outcome=wake.action_type,
                at=now,
            )

        preparer = self._resolve_expression_preparer()
        if preparer is None:
            return HostProactiveTurnResult(
                wake_id=wake.wake_id,
                interaction_id=wake.interaction_id,
                status=HostTurnStatus.FAILED,
                outcome=HostStatus.FAILED,
                decision_context_ref=None,
                expression_ref=None,
                debug_ref=f"debug-{wake.interaction_id}",
                reason_codes=("unwired_expression_preparer",),
            )

        tick_ctx = self._resolve_tick_context(wake)
        if tick_ctx is None:
            return HostProactiveTurnResult(
                wake_id=wake.wake_id,
                interaction_id=wake.interaction_id,
                status=HostTurnStatus.FAILED,
                outcome=HostStatus.FAILED,
                decision_context_ref=None,
                expression_ref=None,
                debug_ref=f"debug-{wake.interaction_id}",
                reason_codes=("missing_authoritative_wake_context",),
            )

        self._pending_wake_contexts[wake.wake_id] = tick_ctx

        # Soul preparation (compile DecisionContext)
        exec_ctx = preparer.prepare_context(
            interaction_id=wake.interaction_id,
            intent=tick_ctx["intent"],
            policy_result=tick_ctx["policy_result"],
            situation=tick_ctx["situation"],
            projected=tick_ctx["projected"],
            assessment_trace_ref=tick_ctx.get("assessment_trace_ref", "none"),
            state_rows=tick_ctx["state_rows"],
            persona_ref=tick_ctx.get("persona_ref"),
            now=now,
            accepted_appraisals=tick_ctx.get("accepted_appraisals", ()),
            surface=tick_ctx.get("surface"),
            mode=tick_ctx.get("mode"),
            persona_version=tick_ctx.get("persona_version"),
            persona_content_digest=tick_ctx.get("persona_content_digest"),
        )
        if exec_ctx is None:
            return HostProactiveTurnResult(
                wake_id=wake.wake_id,
                interaction_id=wake.interaction_id,
                status=HostTurnStatus.FAILED,
                outcome=HostStatus.FAILED,
                decision_context_ref=None,
                expression_ref=None,
                debug_ref=f"debug-{wake.interaction_id}",
                reason_codes=("prepare_context_failed",),
            )

        self._pending_exec_contexts[wake.wake_id] = exec_ctx

        envelope_text = None
        renderer = getattr(self._orchestrator, "context_renderer", None)
        if renderer is not None and hasattr(renderer, "render_provider_envelope"):
            envelope_text = renderer.render_provider_envelope(exec_ctx.context)

        bounded = {
            "wake_id": wake.wake_id,
            "interaction_id": wake.interaction_id,
            "action_type": wake.action_type,
            "intent_kind": tick_ctx["intent"].kind,
            "provider_envelope_text": envelope_text,
            "intent_summary": f"proactive:{wake.action_type}",
        }

        result = HostProactiveTurnResult(
            wake_id=wake.wake_id,
            interaction_id=wake.interaction_id,
            status=HostTurnStatus.PROCESSING,
            outcome=HostStatus.OK,
            decision_context_ref=exec_ctx.context.context_id,
            expression_ref=None,
            debug_ref=f"debug-{wake.interaction_id}",
            bounded_context=bounded,
            reason_codes=(),
        )
        return result

    def guard_proactive_prose(self, wake_id: str, prose: str) -> HostProactiveTurnResult:
        """HI-1: Guard Body-generated prose against ExpressionGuard before delivery."""
        if not isinstance(wake_id, str) or not wake_id.strip():
            raise ValueError("wake_id must be a non-empty string")
        if not isinstance(prose, str):
            raise ValueError("prose must be a string")

        exec_ctx = self._pending_exec_contexts.get(wake_id)
        wake = self._consumed_wakes.get(wake_id)
        if exec_ctx is None or wake is None:
            return HostProactiveTurnResult(
                wake_id=wake_id,
                interaction_id=f"unknown-{wake_id}",
                status=HostTurnStatus.FAILED,
                outcome=HostStatus.FAILED,
                decision_context_ref=None,
                expression_ref=None,
                debug_ref=f"debug-{wake_id}",
                reason_codes=("missing_authoritative_wake_context",),
            )

        preparer = self._resolve_expression_preparer()
        guard = None
        if preparer is not None and hasattr(preparer, "_coordinator") and hasattr(preparer._coordinator, "_guard"):
            guard = preparer._coordinator._guard
        if guard is None:
            guard = getattr(self._orchestrator, "expression_guard", None)
        if guard is None:
            return HostProactiveTurnResult(
                wake_id=wake_id,
                interaction_id=wake.interaction_id,
                status=HostTurnStatus.FAILED,
                outcome=HostStatus.FAILED,
                decision_context_ref=exec_ctx.context.context_id,
                expression_ref=None,
                debug_ref=f"debug-{wake.interaction_id}",
                reason_codes=("guard_unavailable",),
            )

        from mind_runtime.expression.guards import ExpressionGuardInput
        guard_input = ExpressionGuardInput(
            draft_id=f"proactive-{wake_id}",
            decision_context=exec_ctx.context,
            expression=prose,
            attempt=exec_ctx.context.attempt,
        )
        guard_res = guard.guard(guard_input)

        if hasattr(self._orchestrator, "trace") and self._orchestrator.trace is not None:
            self._orchestrator.trace.record(
                wake.interaction_id,
                "expression_guard",
                ref=guard_res.guard_id if hasattr(guard_res, "guard_id") else None,
                outcome=guard_res.disposition.value,
                at=wake.woken_at,
            )

        if guard_res.disposition is ExpressionDisposition.ACCEPT:
            return HostProactiveTurnResult(
                wake_id=wake.wake_id,
                interaction_id=wake.interaction_id,
                status=HostTurnStatus.PROCESSING,
                outcome=HostStatus.OK,
                decision_context_ref=exec_ctx.context.context_id,
                expression_ref=getattr(guard_res, "guard_id", f"guard-{wake_id}"),
                debug_ref=f"debug-{wake.interaction_id}",
                disposition=ExpressionDisposition.ACCEPT,
                would_send=prose,
                reason_codes=(),
            )
        else:
            return HostProactiveTurnResult(
                wake_id=wake.wake_id,
                interaction_id=wake.interaction_id,
                status=HostTurnStatus.ABORTED,
                outcome=HostStatus.FAILED,
                decision_context_ref=exec_ctx.context.context_id,
                expression_ref=None,
                debug_ref=f"debug-{wake.interaction_id}",
                disposition=guard_res.disposition,
                would_send=None,
                reason_codes=tuple(guard_res.violations),
            )

    def commit_proactive_turn(self, wake_id: str) -> HostProactiveTurnResult:
        """HI-1: Complete proactive turn lifecycle following successful external delivery."""
        if not isinstance(wake_id, str) or not wake_id.strip():
            raise ValueError("wake_id must be a non-empty string")

        if wake_id in self._proactive_turn_results:
            cached = self._proactive_turn_results[wake_id]
            if cached.status is HostTurnStatus.COMMITTED:
                return replace(
                    cached,
                    status=HostTurnStatus.ALREADY_PROCESSED,
                    outcome=HostStatus.ALREADY_PROCESSED,
                )

        wake = self._consumed_wakes.get(wake_id)
        if wake is None:
            return HostProactiveTurnResult(
                wake_id=wake_id,
                interaction_id=f"unknown-{wake_id}",
                status=HostTurnStatus.FAILED,
                outcome=HostStatus.FAILED,
                decision_context_ref=None,
                expression_ref=None,
                debug_ref=f"debug-{wake_id}",
                reason_codes=("unknown_wake_id",),
            )

        components = getattr(self._orchestrator, "cognitive_tick_components", None) or {}
        lifecycle = (
            components.get("lifecycle")
            or components.get("intent_lifecycle")
            or getattr(self._orchestrator, "intent_lifecycle", None)
            or getattr(self._orchestrator, "_intent_lifecycle", None)
        )
        if lifecycle is None:
            return HostProactiveTurnResult(
                wake_id=wake_id,
                interaction_id=wake.interaction_id,
                status=HostTurnStatus.FAILED,
                outcome=HostStatus.FAILED,
                decision_context_ref=None,
                expression_ref=None,
                debug_ref=f"debug-{wake.interaction_id}",
                reason_codes=("intent_authority_unavailable",),
            )

        now = getattr(getattr(self._orchestrator, "clock", None), "now", lambda: datetime.now(UTC))()
        lifecycle.transition(
            scope=wake.scope,
            intent_id=wake.intent_id,
            to_status=IntentStatus.COMPLETED,
            reason_codes=("proactive_delivery_committed",),
            occurred_at=now,
            idempotency_key=f"proactive-commit-{wake.intent_id}-v{wake.intent_version}",
        )

        exec_ctx = self._pending_exec_contexts.pop(wake_id, None)
        self._pending_wake_contexts.pop(wake_id, None)
        ticker = components.get("ticker")
        if ticker is not None and hasattr(ticker, "_pending_wake_contexts"):
            ticker._pending_wake_contexts.pop(wake_id, None)

        if hasattr(self._orchestrator, "trace") and self._orchestrator.trace is not None:
            self._orchestrator.trace.record(
                wake.interaction_id,
                "proactive_turn_committed",
                ref=wake.wake_id,
                outcome="completed",
                at=now,
            )

        result = HostProactiveTurnResult(
            wake_id=wake.wake_id,
            interaction_id=wake.interaction_id,
            status=HostTurnStatus.COMMITTED,
            outcome=HostStatus.OK,
            decision_context_ref=exec_ctx.context.context_id if exec_ctx else None,
            expression_ref=None,
            debug_ref=f"debug-{wake.interaction_id}",
            reason_codes=("proactive_delivery_committed",),
        )
        self._proactive_turn_results[wake_id] = result
        return result

    def abort_proactive_turn(self, wake_id: str, reason: str = "") -> HostProactiveTurnResult:
        """HI-1: Abort proactive turn lifecycle on delivery failure."""
        if not isinstance(wake_id, str) or not wake_id.strip():
            raise ValueError("wake_id must be a non-empty string")

        if wake_id in self._proactive_turn_results:
            cached = self._proactive_turn_results[wake_id]
            if cached.status in (HostTurnStatus.COMMITTED, HostTurnStatus.ABORTED):
                return replace(
                    cached,
                    status=HostTurnStatus.ALREADY_PROCESSED,
                    outcome=HostStatus.ALREADY_PROCESSED,
                )

        wake = self._consumed_wakes.get(wake_id)
        if wake is None:
            return HostProactiveTurnResult(
                wake_id=wake_id,
                interaction_id=f"unknown-{wake_id}",
                status=HostTurnStatus.FAILED,
                outcome=HostStatus.FAILED,
                decision_context_ref=None,
                expression_ref=None,
                debug_ref=f"debug-{wake_id}",
                reason_codes=("unknown_wake_id",),
            )

        components = getattr(self._orchestrator, "cognitive_tick_components", None) or {}
        lifecycle = (
            components.get("lifecycle")
            or components.get("intent_lifecycle")
            or getattr(self._orchestrator, "intent_lifecycle", None)
            or getattr(self._orchestrator, "_intent_lifecycle", None)
        )
        if lifecycle is not None:
            now = getattr(getattr(self._orchestrator, "clock", None), "now", lambda: datetime.now(UTC))()
            try:
                lifecycle.transition(
                    scope=wake.scope,
                    intent_id=wake.intent_id,
                    to_status=IntentStatus.SUPERSEDED,
                    reason_codes=("proactive_delivery_aborted", reason or "host_abort"),
                    occurred_at=now,
                    idempotency_key=f"proactive-abort-{wake.intent_id}-v{wake.intent_version}",
                )
            except Exception:
                pass

        exec_ctx = self._pending_exec_contexts.pop(wake_id, None)
        self._pending_wake_contexts.pop(wake_id, None)
        ticker = components.get("ticker")
        if ticker is not None and hasattr(ticker, "_pending_wake_contexts"):
            ticker._pending_wake_contexts.pop(wake_id, None)

        result = HostProactiveTurnResult(
            wake_id=wake.wake_id,
            interaction_id=wake.interaction_id,
            status=HostTurnStatus.ABORTED,
            outcome=HostStatus.FAILED,
            decision_context_ref=exec_ctx.context.context_id if exec_ctx else None,
            expression_ref=None,
            debug_ref=f"debug-{wake.interaction_id}",
            reason_codes=("proactive_delivery_aborted", reason or "host_abort"),
        )
        self._proactive_turn_results[wake_id] = result
        return result

    def run_proactive_turn(self, wake: WakeSignal) -> HostProactiveTurnResult:
        """HI-1: Execute a proactive Body turn following wake admission."""
        prep_result = self.begin_proactive_turn(wake)
        if prep_result.status is not HostTurnStatus.PROCESSING or prep_result.outcome is not HostStatus.OK:
            return prep_result

        now = wake.woken_at
        preparer = self._resolve_expression_preparer()
        exec_ctx = self._pending_exec_contexts.get(wake.wake_id)
        if preparer is None or exec_ctx is None:
            return prep_result

        tick_ctx = self._pending_wake_contexts.get(wake.wake_id) or {}
        if tick_ctx.get("transition_result") is None:
            artifact = ProactiveExpressionArtifact(
                interaction_id=wake.interaction_id,
                intent_id=wake.intent_id,
                action_type=wake.action_type,
                context_id=exec_ctx.context.context_id,
                skip_reason="no_transition",
            )
            return HostProactiveTurnResult(
                wake_id=wake.wake_id,
                interaction_id=wake.interaction_id,
                status=HostTurnStatus.ABORTED,
                outcome=HostStatus.FAILED,
                decision_context_ref=exec_ctx.context.context_id,
                expression_ref=None,
                debug_ref=f"debug-{wake.interaction_id}",
                bounded_context=prep_result.bounded_context,
                proactive_expression=artifact,
                reason_codes=("no_transition",),
            )

        # Body execution (provider realization + guard)
        try:
            artifact = preparer.realize_after_wake(exec_ctx, now=now)
        except Exception as exc:
            artifact = ProactiveExpressionArtifact(
                interaction_id=wake.interaction_id,
                intent_id=wake.intent_id,
                action_type=wake.action_type,
                context_id=exec_ctx.context.context_id,
                skip_reason="agent_failure",
            )
            fail_result = HostProactiveTurnResult(
                wake_id=wake.wake_id,
                interaction_id=wake.interaction_id,
                status=HostTurnStatus.ABORTED,
                outcome=HostStatus.FAILED,
                decision_context_ref=exec_ctx.context.context_id,
                expression_ref=None,
                debug_ref=f"debug-{wake.interaction_id}",
                bounded_context=prep_result.bounded_context,
                proactive_expression=artifact,
                reason_codes=("agent_failure", str(exc)),
            )
            self._proactive_turn_results[wake.wake_id] = fail_result
            return fail_result

        turn_status = (
            HostTurnStatus.PROCESSING
            if artifact.disposition is ExpressionDisposition.ACCEPT
            else HostTurnStatus.ABORTED
        )
        outcome_status = (
            HostStatus.OK
            if artifact.disposition is ExpressionDisposition.ACCEPT
            else HostStatus.FAILED
        )
        result = HostProactiveTurnResult(
            wake_id=wake.wake_id,
            interaction_id=wake.interaction_id,
            status=turn_status,
            outcome=outcome_status,
            decision_context_ref=artifact.context_id,
            expression_ref=(
                artifact.outcome_id
                if artifact.disposition is ExpressionDisposition.ACCEPT
                else None
            ),
            debug_ref=f"debug-{wake.interaction_id}",
            bounded_context=prep_result.bounded_context,
            disposition=artifact.disposition,
            would_send=artifact.would_send,
            proactive_expression=artifact,
            reason_codes=(artifact.skip_reason,) if artifact.skip_reason else (),
        )
        self._proactive_turn_results[wake.wake_id] = result
        return result

    # ----- internal: terminal record management -----------------------

    def _record_terminal(self, interaction_id: str, *, committed: bool) -> None:
        """Record a terminal state for future Host-level replays.

        Uses the user_message stashed by begin_turn (pending store) as
        the replay-comparison key, so this method does not need to
        reverse-lookup the orchestrator's observations or the
        FrozenMapping private field.
        """
        bounded = _bounded_context(self._orchestrator)
        terminal_status = HostTurnStatus.COMMITTED if committed else HostTurnStatus.ABORTED
        user_message = self._pending_user_message.pop(interaction_id, "")
        self._terminal[interaction_id] = _TerminalRecord(
            interaction_id=interaction_id,
            user_message=user_message,
            bounded_context=bounded,
            turn_id=f"turn-{interaction_id}",
            terminal_status=terminal_status,
            decision_context_ref=_decision_context_ref(self._orchestrator),
            expression_ref=_expression_ref(self._orchestrator),
        )


def _iso(value: datetime) -> str:
    return value.isoformat()
