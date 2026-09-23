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
from datetime import UTC, datetime

from mind_runtime.contracts import (
    Authority,
    AuthorityLevel,
    Evidence,
    ExpressionDisposition,
    Interaction,
    InteractionStatus,
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
    HostProviderProseRequest,
    HostProviderProseResult,
    HostStatus,
    HostTurnRequest,
    HostTurnResult,
    HostTurnStatus,
)
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
        if request is None or request.surface_handoff.context_id != ctx.context_id:
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
    ) -> None:
        if orchestrator is None:
            raise ValueError("orchestrator is required")
        self._orchestrator = orchestrator
        self._trace = trace or TraceRecorder()
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
