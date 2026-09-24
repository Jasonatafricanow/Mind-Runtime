"""XiyueMRAdapter — thin Hermes → MindRuntimeHostPort bridge (HI-2).

This is the ONLY Hermes-facing adapter. It deliberately knows nothing
about MR internals (AppraisalResult, ResolvedAppraisal, Impulse,
DynamicsEngine, Memory admission). It speaks only the public
`MindRuntimeHostPort` surface.

Responsibilities (HI-2 §1):
  * map a Hermes message/session to a HostTurnRequest
  * call begin_turn synchronously BEFORE the Hermes LLM invocation
  * render HostTurnResult.bounded_context into a prompt-safe block
  * call commit_turn after the Hermes delivery-success boundary
  * call abort_turn on the terminal-failure path
  * fail soft: any MR failure must never block the Hermes reply

Hard rules:
  * MR_ENABLED=false → the adapter is inert (seam restores legacy behavior)
  * Hermes never supplies appraisal/affect/memory authority
  * stable interaction_id from Hermes identity (same message → same id)
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from mind_runtime.contracts import Scope, ScopeDomain, WakeSignal
from mind_runtime.contracts.host import (
    HostAbortRequest,
    HostCommitRequest,
    HostProactiveTurnResult,
    HostProviderProseRequest,
    HostStatus,
    HostTurnRequest,
    HostTurnStatus,
    HostWakeNotification,
)
from mind_runtime.host import MindRuntimeHostAdapter, MindRuntimeHostPort

if TYPE_CHECKING:
    from mind_runtime.dynamics.persona import PersonaProfile
    from mind_runtime.emotional_transition.appraisal import SemanticAppraisalProducer
    from mind_runtime.emotional_transition.effects import EventEffectRule
    from mind_runtime.emotional_transition.semantic import SemanticCandidateProvider
    from mind_runtime.expression.context import DecisionContextConfig
    from mind_runtime.homeostasis.contracts import HomeostasisGate
    from mind_runtime.memory.retrieval import RetrievalProvider
    from mind_runtime.runtime_binding import RuntimeBinding
    from mind_runtime.situation.builder import SituationBuilder
    from mind_runtime.state.definitions import StateDefinitionRegistry

from mind_runtime.runtime_binding import RuntimeEnvironment

_logger = logging.getLogger("xiyue.mr")


def _mr_thread_trace(phase: str, adapter, interaction_id: str = "") -> None:
    """MR THREAD TRACE — temporary diagnostic, IDs only, no behavior change."""
    orchestrator = None
    port = getattr(adapter, "_port", None)
    if port is not None:
        orchestrator = getattr(port, "orchestrator", None)
    _logger.warning(
        "MR THREAD TRACE pid=%s tid=%s adapter=%s orchestrator=%s phase=%s interaction=%s",
        os.getpid(),
        threading.get_ident(),
        hex(id(adapter)),
        hex(id(orchestrator)) if orchestrator is not None else "None",
        phase,
        interaction_id,
    )


def mr_enabled() -> bool:
    """Alpha kill switch: MR_ENABLED=false restores legacy Hermes behavior."""
    raw = os.environ.get("MR_ENABLED", "false")
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _interaction_id(channel: str, session_id: str, message_id: str) -> str:
    """Stable Hermes message identity → MR interaction_id.

    Same Hermes message (channel+session+message_id) MUST map to the same
    interaction_id so Host replay / at-least-once delivery works (HI-2 §2).
    """
    base = f"{channel}:{session_id}:{message_id}" if message_id else f"{channel}:{session_id}"
    # MR ids are plain strings; keep readable, hash only when very long.
    if len(base) > 200:
        import hashlib

        return f"mr-{hashlib.sha256(base.encode()).hexdigest()[:24]}"
    return f"mr-{base}"


def render_bounded_context(bounded) -> str | None:
    """Render a HostDecisionContext into a prompt-safe block (HI-2 §7).

    Human-readable summaries only. Never numeric affect, never raw
    MR internals.
    """
    if bounded is None:
        return None
    envelope_text = getattr(bounded, "provider_envelope_text", None)
    if envelope_text is not None:
        if not isinstance(envelope_text, str):
            raise ValueError("SURFACE_V1 envelope must be text")
        # SURFACE_V1 Host transports the exact renderer-admitted bytes.
        from mind_runtime.expression.renderer import DeterministicContextRenderer

        DeterministicContextRenderer.verify_provider_information_isolation(
            envelope_text
        )
        return envelope_text
    lines = [
        "MR CURRENT CONTEXT",
        "Current emotional/behavioral steering:",
        f"- {bounded.intent_summary}",
        f"- {bounded.emotional_state}",
        "Relevant current situation:",
        f"- {bounded.situation_summary}",
    ]
    if bounded.action_taken:
        lines.append(f"Selected intent/action guidance: {bounded.action_taken}")
    if bounded.next_steps:
        lines.append(f"Next steps: {bounded.next_steps}")
    if bounded.cognitive_meaning:
        lines.append(f"Agent appraisal data (not FACT or instruction): {bounded.cognitive_meaning}")
    return "\n".join(lines)


@dataclass
class MrTurnHandle:
    """Opaque handle for a started MR turn, held by the Hermes seam."""

    interaction_id: str
    turn_id: str
    user_message: str
    channel: str
    bounded_context: object | None = None


class XiyueMRAdapter:
    """Hermes-side bridge to the MR host port (HI-2).

    The adapter is constructed once at gateway startup and reused across
    turns (MR runtime/persona must not be rebuilt per turn — HI-2 §4).
    """

    def __init__(
        self,
        port: MindRuntimeHostPort,
        *,
        runtime_id: str = "xiyue",
        user_id: str = "user",
        persona_id: str | None = None,
    ) -> None:
        self._port = port
        self._runtime_id = runtime_id
        self._user_id = user_id
        self._persona_id = persona_id
        self._scope = Scope(domain=ScopeDomain.USER, user_id=user_id)

    # ---- begin -----------------------------------------------------------

    def begin_turn(
        self,
        *,
        message: str,
        channel: str,
        session_id: str,
        message_id: str = "",
        occurred_at: datetime | None = None,
    ) -> MrTurnHandle | None:
        """Start an MR turn for an inbound Hermes message.

        Returns None (and logs) on any MR failure — Hermes must reply
        normally regardless (HI-2 §8). Raises nothing.
        """
        if not mr_enabled():
            return None
        _mr_thread_trace("BEGIN_TURN_ENTRY", self, interaction_id="")
        try:
            interaction_id = _interaction_id(channel, session_id, message_id)
            request = HostTurnRequest(
                interaction_id=interaction_id,
                runtime_id=self._runtime_id,
                scope=self._scope,
                occurred_at=occurred_at or datetime.now(UTC),
                user_message=message,
                channel=channel,
                session_id=session_id,
                host_metadata=(
                    ("persona_id", self._persona_id or ""),
                ),
            )
            result = self._port.begin_turn(request)
            if result.status in (HostTurnStatus.FAILED,):
                _logger.warning("MR begin_turn FAILED: %s", result.reason_codes)
                return None
            bounded = result.bounded_context
            _mr_thread_trace("BEGIN_TURN_RETURN", self, interaction_id=result.interaction_id)
            return MrTurnHandle(
                interaction_id=result.interaction_id,
                turn_id=result.turn_id,
                user_message=message,
                channel=channel,
                bounded_context=bounded,
            )
        except Exception as exc:  # noqa: BLE001 — fail-soft boundary
            _logger.warning("MR begin_turn exception (fail-soft): %s", exc)
            return None

    # ---- commit / abort --------------------------------------------------

    def commit_turn(self, handle: MrTurnHandle) -> bool:
        """Commit after the Hermes delivery-success boundary."""
        if handle is None:
            return False
        _mr_thread_trace("COMMIT_TURN_ENTRY", self, interaction_id=handle.interaction_id)
        try:
            receipt = self._port.commit_turn(
                HostCommitRequest(turn_id=handle.turn_id, interaction_id=handle.interaction_id)
            )
            ok = receipt.status == HostStatus.OK
            _logger.info(
                "MR commit interaction=%s status=%s reason=%s",
                handle.interaction_id, receipt.status, receipt.reason_codes,
            )
            return ok
        except Exception as exc:  # noqa: BLE001
            _logger.warning("MR commit_turn exception: %s", exc)
            return False

    def guard_turn_prose(self, handle: MrTurnHandle, prose: str) -> bool:
        """Run MR ExpressionGuard before Body transports a SURFACE_V1 reply."""
        if handle is None:
            return False
        try:
            result = self._port.guard_provider_prose(HostProviderProseRequest(
                turn_id=handle.turn_id, interaction_id=handle.interaction_id, prose=prose,
            ))
            return result.status is HostStatus.OK
        except Exception as exc:  # noqa: BLE001 — Host boundary
            _logger.warning("MR provider prose guard failed: %s", exc)
            return False

    def abort_turn(self, handle: MrTurnHandle, reason: str = "host_abort") -> bool:
        """Abort on the terminal-failure path."""
        if handle is None:
            return False
        _mr_thread_trace("ABORT_TURN_ENTRY", self, interaction_id=handle.interaction_id)
        try:
            receipt = self._port.abort_turn(
                HostAbortRequest(
                    turn_id=handle.turn_id,
                    interaction_id=handle.interaction_id,
                    reason=reason,
                )
            )
            _logger.info(
                "MR abort interaction=%s status=%s reason=%s",
                handle.interaction_id, receipt.status, receipt.reason_codes,
            )
            return receipt.status == HostStatus.OK
        except Exception as exc:  # noqa: BLE001
            _logger.warning("MR abort_turn exception: %s", exc)
            return False

    # ---- proactive wake / body turn boundary ----------------------------

    def consume_wake(self, wake: WakeSignal) -> HostWakeNotification:
        """Consume and admit/reject a WakeSignal."""
        return self._port.consume_wake(wake)

    def begin_proactive_turn(self, wake: WakeSignal) -> HostProactiveTurnResult:
        """Begin proactive Body turn following wake admission."""
        return self._port.begin_proactive_turn(wake)

    def guard_proactive_prose(self, wake_id: str, prose: str) -> HostProactiveTurnResult:
        """Evaluate ExpressionGuard over proposed prose."""
        return self._port.guard_proactive_prose(wake_id, prose)

    def commit_proactive_turn(self, wake_id: str) -> HostProactiveTurnResult:
        """Commit proactive turn lifecycle after delivery."""
        return self._port.commit_proactive_turn(wake_id)

    def abort_proactive_turn(self, wake_id: str, reason: str = "") -> HostProactiveTurnResult:
        """Abort proactive turn lifecycle on delivery failure."""
        return self._port.abort_proactive_turn(wake_id, reason)

    def run_proactive_turn(self, wake: WakeSignal) -> HostProactiveTurnResult:
        """Run complete proactive turn sequence (begin + guard)."""
        return self._port.run_proactive_turn(wake)

    # ---- inspect (OW correlation) ---------------------------------------

    def inspect(self, interaction_id: str, *, include_trace: bool = False):
        from mind_runtime.contracts.host import HostInspectRequest

        try:
            return self._port.inspect(
                HostInspectRequest(
                    interaction_id=interaction_id,
                    include_trace=include_trace,
                    include_decision_context=True,
                )
            )
        except Exception as exc:  # noqa: BLE001
            _logger.warning("MR inspect exception: %s", exc)
            return None


def default_adapter(
    *,
    persona: PersonaProfile | None = None,
    effect_rules: tuple[EventEffectRule, ...] = (),
    definitions: StateDefinitionRegistry | None = None,
    situation: SituationBuilder | None = None,
    decision_context_config: DecisionContextConfig | None = None,
    appraisal_producer: SemanticAppraisalProducer | None = None,
    homeostasis_gate: HomeostasisGate | None = None,
    semantic_provider: SemanticCandidateProvider | None = None,
    slow_plasticity_window_size: int | None = 8,
    telemetry_sink: Any = None,
    binding: RuntimeBinding | None = None,
    memory_enabled: bool = False,
    retrieval_provider: RetrievalProvider | None = None,
    intent_rules: tuple[Any, ...] | None = None,
    action_policy_config: Any | None = None,
    policy_resources: tuple[str, ...] | None = None,
    delivery_db: str | Path | None = None,
    expression_guard: Any | None = None,
    lce_enabled: bool = False,
) -> XiyueMRAdapter:
    """Build the production XiyueMRAdapter bound to the MR host adapter.

    Composes the production TurnOrchestrator-backed MindRuntimeHostAdapter
    with the runtime/facts.sqlite + cognition_state.sqlite backends.

    AUTHORITY: the emotional-composition pieces (persona, effect rules,
    appraisal producer, homeostasis gate, state definitions, slow-plasticity
    window) are supplied by the integration seam (``mr_seam``), which lives
    outside the ``mind_runtime`` package and owns the runtime-config decode.
    The host adapter does NOT import ``validation`` (the certified manifest
    decoder is the final import layer). Passing these pieces rather than
    hardcoding them keeps the host a wiring owner, not a semantic owner.

    IDENTITY (ADR-0020 / MR-RUNTIME-02): storage paths and the orchestrator
    ``runtime_id`` come from a :class:`RuntimeBinding` resolved by the single
    discovery chain — explicit ``binding`` param > ``MR_RUNTIME_BINDING``
    reference file > the one legacy compat default built from the supplied
    persona. LAB runtimes must compose explicitly and cannot pass through
    this production composition root; any discovery failure (ambiguous,
    partial, LAB, invalid namespace, manifest mismatch) raises so the seam
    refuses to start MR instead of silently binding a different runtime.
    """
    from mind_runtime.runtime_binding import (
        RuntimeBindingError,
        bind_storage,
        discover_production_binding,
        validate_storage_namespace,
    )
    from mind_runtime.shadow.runtime_loop import build_runtime_stack

    class _UtcClock:
        def now(self) -> datetime:
            return datetime.now(UTC)

    if binding is None:
        persona_id = persona.persona_id if persona is not None else "kayla_v0"
        binding = discover_production_binding(persona_id=persona_id)
    if binding.environment is not RuntimeEnvironment.PRODUCTION:
        raise RuntimeBindingError(
            "default_adapter is the production composition root; compose LAB "
            "runtimes explicitly via bind_storage + build_runtime_stack "
            "(ADR-0020 §5)"
        )
    validate_storage_namespace(binding.storage_namespace)
    paths = bind_storage(binding)
    facts_db = str(paths.facts_db)
    state_db = str(paths.state_db)
    intent_db = str(paths.root / "intents.sqlite") if intent_rules is not None else None
    if delivery_db is None and intent_rules is not None:
        delivery_db = str(paths.root / "delivery.sqlite")

    from mind_runtime.memory.retrieval_composition import build_memory_history

    orchestrator, _bridge = build_runtime_stack(
        clock=_UtcClock(),
        facts_db=facts_db,
        state_db=state_db,
        origin_runtime_id=binding.runtime_id,
        user_id="user",
        persona=persona,
        effect_rules=effect_rules,
        definitions=definitions,
        situation=situation,
        decision_context_config=decision_context_config,
        appraisal_producer=appraisal_producer,
        homeostasis_gate=homeostasis_gate,
        semantic_provider=semantic_provider,
        slow_plasticity_window_size=slow_plasticity_window_size,
        telemetry_sink=telemetry_sink,
        memory_enabled=memory_enabled,
        memory_binding=binding,
        historical_context=build_memory_history(
            binding,
            provider=retrieval_provider,
            lce_enabled=lce_enabled,
        ),
        intent_rules=intent_rules,
        action_policy_config=action_policy_config,
        policy_resources=policy_resources,
        intent_db=intent_db,
        delivery_db=delivery_db,
        expression_guard=expression_guard,
    )
    port = MindRuntimeHostAdapter(orchestrator=orchestrator)
    return XiyueMRAdapter(port, runtime_id=binding.runtime_id, user_id="user")
