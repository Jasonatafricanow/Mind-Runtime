"""Host-level autonomous cognition coordination (C5B).

ADR-0004 compressed topology: one deterministic emotional transition, one
Intent authority, one ActionPolicy authority. This module adds the missing
host seam only — coordination of EXISTING components for clock-only passes.
It owns no new cognition rules, writes nothing to the factual plane, and
never fabricates an inbound turn (ADR-0010 preserved by construction).

Wall-clock chain enabled by the C5A audit gap:

    Clock -> CognitiveTicker.tick(scope, now)
        |- load durable canonical affect (state backend truth)
        |- advance Dynamics with elapsed wall-clock (once per instant)
        |- evaluate the existing deterministic IntentEngine
        |- IntentScheduler.tick (only expire / wake, never execute)
        |- ActionPolicy on new candidates + wake reconsiderations
        |- persist lifecycle transitions + tick projection rows

Idempotency: every derived identity binds the tick instant deterministically
(``cognitive-tick-<aware ISO instant>``), so re-driving the same ``now``
proves a no-op (CT2/CT11) and a future instant advances exactly once (CT3).

Counter-fact convention (C5B): an admitted Observation produced from a
``system_counter`` Evidence carries ``key="system_counter.observed"`` and a
mapping payload ``{"key": <fact key>, "value": <str value>}``. The default
fact reader surfaces the latest such admitted facts per scope. Counters
therefore always enter through the REAL authority/idempotency admission
path — the tick never fabricates policy inputs.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Any, Protocol

from mind_runtime.cognition.express import (
    ProactiveExpressionArtifact,
    ProactiveExpressionPreparer,
)
from mind_runtime.contracts import (
    ActionDecision,
    ActionPolicyInput,
    ActionPolicyResult,
    EmotionalTransitionInput,
    EmotionalTransitionResult,
    Intent,
    IntentEngineInput,
    IntentStatus,
    PolicyResources,
    ProjectedMindState,
    RuntimeState,
    Scope,
    ScopeDomain,
    Situation,
    SurfaceProjectionPort,
    SyncFields,
    WakeSignal,
)
from mind_runtime.dynamics.persona import PersonaProfile
from mind_runtime.intents.engine import DeterministicIntentEngine
from mind_runtime.intents.lifecycle import IntentLifecycleService
from mind_runtime.intents.policy import DeterministicActionPolicy
from mind_runtime.intents.scheduler import IntentScheduler
from mind_runtime.pipeline.orchestrator import TurnOrchestrator
from mind_runtime.pipeline.ports import AgentFailure
from mind_runtime.situation.derived import media_photo_cadence_eligible
from mind_runtime.situation.temporal import daypart
from mind_runtime.state.persistence import StateBackend
from mind_runtime.surface import project_surface_for_cognition

TICK_INTERACTION_PREFIX = "cognitive-tick-"
COUNTER_OBSERVATION_KEY = "system_counter.observed"
CADENCE_COUNTER_FACT = "counter.proactive_prompts_since_photo"
MEDIA_ELIGIBILITY_FACT = "media.photo_frequency_eligible"
_STATE_BACKEND_ATTRS = ("state_backend", "_state_backend")


def _counter_int(facts: list[tuple[str, str]], key: str) -> int | None:
    """Read one host-owned counter; missing or unreadable fails closed."""

    for fact_key, value in facts:
        if fact_key == key:
            try:
                parsed = int(value)
            except ValueError:
                return None
            return parsed if parsed >= 0 else None
    return None


@dataclass(frozen=True)
class CognitiveTickConfig:
    """Deployment-owned proactive behavior configuration (never persona affect).

    ``photo_cadence_threshold`` is the configured 1-per-N proactive prompt
    cadence for image eligibility (legacy gap #6). ``None`` — the generic
    runtime default — disables the cadence feature entirely: a runtime that
    does not configure it never inherits one deployment's 1-per-3 rule.
    The algorithm is generic; the numbers are deployment configuration.
    """

    photo_cadence_threshold: int | None = None

    def __post_init__(self) -> None:
        threshold = self.photo_cadence_threshold
        if threshold is None:
            return
        if isinstance(threshold, bool) or not isinstance(threshold, int) or threshold < 1:
            raise ValueError("photo_cadence_threshold must be a positive integer or None")


class PolicyFactReader(Protocol):
    """Read already-admitted facts for policy/situation inputs (fail-open)."""

    def facts(self, scope: Scope) -> tuple[tuple[str, str], ...]:
        """Return stored fact pairs for one scope; empty when unknown."""
        ...


def observation_fact_reader(orchestrator: TurnOrchestrator) -> PolicyFactReader:
    """Build a fact reader over the orchestrator's durable fact service.

    Only observations that already passed admission (authority, ownership,
    idempotency) are read; the tick never fabricates facts to feed policy.
    """

    class _Reader:
        def facts(self, scope: Scope) -> tuple[tuple[str, str], ...]:
            service = orchestrator.fact_ingest
            observations = getattr(service, "observations", None)
            if observations is None:
                return ()
            latest_by_key: dict[str, tuple[datetime, str, str]] = {}
            for observation in observations.all():
                if observation.scope != scope:
                    continue
                value = observation.value
                # Counter-fact convention: a typed-event observation whose
                # payload maps {"key", "value"} pairs (admitted through the
                # REAL factual authority, shape-checked here). Frozen
                # payloads implement Mapping, not dict.
                if not isinstance(value, Mapping):
                    continue
                fact_key = value.get("key")
                fact_value = value.get("value")
                if not isinstance(fact_key, str) or not isinstance(fact_value, str):
                    continue
                if not fact_key.startswith(("counter.", "conversation.")):
                    continue
                known = latest_by_key.get(fact_key)
                # Authority order: observed_at first; exact ties fall back to
                # the evidence ref, then nothing — never iteration order.
                last_ref = observation.evidence_refs[-1] if observation.evidence_refs else ""
                rank = (observation.observed_at, last_ref)
                known_rank = (known[0], known[2]) if known is not None else None
                if known is None or known_rank is None or rank >= known_rank:
                    latest_by_key[fact_key] = (observation.observed_at, fact_value, last_ref)
            return tuple(sorted((key, item) for key, (_at, item, _ref) in latest_by_key.items()))

    return _Reader()


@dataclass(frozen=True)
class CognitiveTickReport:
    """Operability counters for one host-level cognitive tick."""

    tick_ref: str
    interaction_id: str
    scope: Scope
    now: datetime
    elapsed: timedelta
    intent_candidates_generated: int = 0
    candidates_admitted: int = 0
    intents_expired: int = 0
    wakes: int = 0
    policy_allowed: int = 0
    policy_deferred: int = 0
    policy_denied: int = 0
    superseded: int = 0
    state_rows_persisted: int = 0
    persistent_duplicates_skipped: int = 0
    proactive_expression: ProactiveExpressionArtifact | None = None
    wake_signal: WakeSignal | None = None

    @property
    def proactive_wake(self) -> WakeSignal | None:
        return self.wake_signal

    def as_dict(self) -> dict[str, object]:
        return {
            "tick_ref": self.tick_ref,
            "interaction_id": self.interaction_id,
            "elapsed_seconds": self.elapsed.total_seconds(),
            "intent_candidates_generated": self.intent_candidates_generated,
            "candidates_admitted": self.candidates_admitted,
            "intents_expired": self.intents_expired,
            "wakes": self.wakes,
            "policy_allowed": self.policy_allowed,
            "policy_deferred": self.policy_deferred,
            "policy_denied": self.policy_denied,
            "superseded": self.superseded,
            "state_rows_persisted": self.state_rows_persisted,
            "persistent_duplicates_skipped": self.persistent_duplicates_skipped,
            "proactive_expression": (
                self.proactive_expression.as_dict()
                if self.proactive_expression is not None
                else None
            ),
            "wake_signal": (
                self.wake_signal.as_dict()
                if self.wake_signal is not None
                else None
            ),
            "wake_id": (
                self.wake_signal.wake_id
                if self.wake_signal is not None
                else None
            ),
        }


class CognitiveTicker:
    """Coordinate one autonomous cognition pass without an inbound turn.

    The ticker reads/writes the orchestrator's durable state backend and an
    explicitly injected Intent lifecycle; it never calls ``begin_turn``/
    ``run`` and never creates Evidence, so generated Intents cite the tick
    projection, and the tick projection cites canonical state that exists
    independently of it. The C2.10 turn path stays byte-for-byte frozen.
    """

    surface_projection_port: SurfaceProjectionPort | None = None

    def __init__(
        self,
        *,
        orchestrator: TurnOrchestrator,
        persona: PersonaProfile,
        intent_engine: DeterministicIntentEngine,
        action_policy: DeterministicActionPolicy,
        policy_resources: PolicyResources,
        intent_lifecycle: IntentLifecycleService,
        runtime_id: str,
        fact_reader: PolicyFactReader | None = None,
        projection_scope: Scope | None = None,
        expression: ProactiveExpressionPreparer | None = None,
        config: CognitiveTickConfig | None = None,
        surface_projection_port: SurfaceProjectionPort | None = None,
    ) -> None:
        composed_surface_port = getattr(orchestrator, "surface_projection_port", None)
        if (
            surface_projection_port is not None
            and surface_projection_port is not composed_surface_port
        ):
            raise ValueError("ticker Surface port must be the composed turn Surface authority")
        self.surface_projection_port = composed_surface_port
        self._orchestrator = orchestrator
        self._persona = persona
        self._intent_lifecycle = intent_lifecycle
        self._scheduler = IntentScheduler(intent_lifecycle)
        self._intent_engine = intent_engine
        self._action_policy = action_policy
        self._policy_resources = policy_resources
        self._runtime_id = runtime_id
        self._fact_reader = fact_reader
        self._projection_scope = projection_scope
        if expression is not None and not isinstance(expression, ProactiveExpressionPreparer):
            raise ValueError("expression must be a ProactiveExpressionPreparer")
        self._expression = expression
        if config is not None and not isinstance(config, CognitiveTickConfig):
            raise ValueError("config must be a CognitiveTickConfig")
        self._config = config or CognitiveTickConfig()
        self._state_backend = _resolve_state_backend(orchestrator)
        if intent_engine._runtime_id != runtime_id:
            raise ValueError("intent engine runtime_id must match ticker runtime_id")
        self._pending_wake_contexts: dict[str, dict[str, Any]] = {}

    def get_pending_wake_context(self, wake_id: str) -> dict[str, Any] | None:
        return self._pending_wake_contexts.get(wake_id)

    # ── public entrypoint ────────────────────────────────────────────────

    def tick(self, *, scope: Scope, now: datetime) -> CognitiveTickReport:
        """Run one clock-only cognition pass; safe to re-drive the same now."""
        interaction_id = f"{TICK_INTERACTION_PREFIX}{now.isoformat()}"
        current_affect = self._current_affect(scope=self._affect_scope())
        elapsed = self._elapsed_since(current_affect, now=now)

        expired_before = self._count_status(scope, IntentStatus.EXPIRED)
        wakes = self._scheduler.tick(scope, now)
        expired_after = self._count_status(scope, IntentStatus.EXPIRED)

        situation = self._tick_situation(scope=scope, interaction_id=interaction_id, now=now)
        projected, transition_result = self._advance(
            policy_scope=scope,
            affect_scope=self._affect_scope(),
            current_affect=current_affect,
            elapsed=elapsed,
            interaction_id=interaction_id,
            situation=situation,
            now=now,
        )
        surface_result = project_surface_for_cognition(
            surface_port=self.surface_projection_port,
            persona=self._persona,
            projected=projected,
            runtime_id=self._runtime_id,
            scope=projected.scope,
            interaction_or_tick_ref=f"tick:{interaction_id}",
        )
        engine_result = self._intent_engine.evaluate(
            IntentEngineInput(
                interaction_id=interaction_id,
                scope=scope,
                origin_runtime_id=self._runtime_id,
                context=situation,
                projected=projected,
                accepted_events=(),
                clock=now,
                surface=surface_result,
                persona_version=self._persona.version,
                persona_content_digest=self._persona.persona_content_digest,
            )
        )
        persisted_rows = self._persist_projection(projected)
        counters = _MutableCounters(
            interaction_id=interaction_id,
            elapsed=elapsed,
            generated=len(engine_result.candidates),
            wakes=len(wakes),
            expired=max(expired_after - expired_before, 0),
            persisted_rows=persisted_rows,
        )
        selection = self._decide(
            scope=scope,
            now=now,
            situation=situation,
            candidates=engine_result.candidates,
            counters=counters,
            interaction_id=interaction_id,
        )
        expression_artifact: ProactiveExpressionArtifact | None = None
        if self._expression is not None:
            expression_artifact = self._prepare_expression(
                selection=selection,
                situation=situation,
                projected=projected,
                transition_result=transition_result,
                interaction_id=interaction_id,
                now=now,
                surface=surface_result,
            )
        wake_signal: WakeSignal | None = None
        if selection is not None:
            intent, policy_result = selection
            if policy_result.decision is ActionDecision.ALLOW:
                permission = policy_result.permission
                action_type = permission.action_type if permission is not None else intent.kind
                wake_signal = WakeSignal(
                    wake_id=f"wake-{interaction_id}",
                    runtime_id=self._runtime_id,
                    scope=scope,
                    intent_id=intent.intent_id,
                    action_type=action_type,
                    policy_decision_ref=policy_result.policy_id,
                    interaction_id=interaction_id,
                    woken_at=now,
                    reason="proactive_intent_allowed",
                    intent_version=intent.sync.version if intent.sync else 1,
                )
                counters.wake_signal = wake_signal
                self._orchestrator.trace.record(
                    interaction_id,
                    "wake_created",
                    ref=wake_signal.wake_id,
                    outcome=action_type,
                    at=now,
                )
                self._orchestrator.trace.record(
                    interaction_id,
                    "proactive_wake_dispatched",
                    ref=wake_signal.wake_id,
                    outcome=action_type,
                    at=now,
                )
                self._pending_wake_contexts[wake_signal.wake_id] = {
                    "intent": intent,
                    "policy_result": policy_result,
                    "situation": situation,
                    "projected": projected,
                    "transition_result": transition_result,
                    "assessment_trace_ref": (
                        transition_result.assessment_trace.trace_id
                        if transition_result is not None
                        else "none"
                    ),
                    "accepted_appraisals": (
                        transition_result.accepted_appraisals
                        if transition_result is not None
                        else ()
                    ),
                    "surface": surface_result,
                    "state_rows": self._load_state_rows(),
                    "persona_ref": self._persona.persona_id,
                    "persona_version": self._persona.version,
                    "persona_content_digest": self._persona.persona_content_digest,
                    "now": now,
                }
        self._orchestrator.trace.record(
            interaction_id,
            "cognitive_tick",
            outcome=f"allowed={counters.allowed};deferred={counters.deferred};"
            f"denied={counters.denied}",
            at=now,
        )
        return counters.freeze(
            scope=scope,
            now=now,
            tick_ref=interaction_id,
            expression=expression_artifact,
            wake_signal=wake_signal,
        )

    # ── stage 1: durable affect + elapsed wall-clock truth ───────────────

    def _affect_scope(self) -> Scope:
        return self._projection_scope or self._fallback_scope()

    def _fallback_scope(self) -> Scope:
        raise ValueError("cognitive tick requires an explicit affect projection scope")

    def _current_affect(self, *, scope: Scope) -> tuple[RuntimeState, ...]:
        dimension_names = {profile.dimension for profile in self._persona.dimensions}
        rows = self._load_state_rows()
        latest: dict[str, RuntimeState] = {}
        for state in rows:
            if state.scope != scope or state.dimension not in dimension_names:
                continue
            if not isinstance(state.value, (int, float)) or isinstance(state.value, bool):
                continue
            known = latest.get(state.dimension)
            if known is None or state.version > known.version:
                latest[state.dimension] = state
        return tuple(sorted(latest.values(), key=lambda state: state.dimension))

    def _load_state_rows(self) -> tuple[RuntimeState, ...]:
        if self._state_backend is not None:
            return tuple(self._state_backend.load_states())
        return tuple(self._orchestrator.canonical)

    @staticmethod
    def _elapsed_since(current_affect: tuple[RuntimeState, ...], *, now: datetime) -> timedelta:
        """Wall-clock truth since the last affect update (CT2/CT3 core)."""
        if not current_affect:
            return timedelta(0)
        latest = max(state.updated_at for state in current_affect)
        if latest > now:
            raise ValueError("current affect updated_at must not be in the future")
        return now - latest

    # ── stage 2: Dynamics advance (idempotent per instant) ───────────────

    def _advance(
        self,
        *,
        policy_scope: Scope,
        affect_scope: Scope,
        current_affect: tuple[RuntimeState, ...],
        elapsed: timedelta,
        interaction_id: str,
        situation: Situation,
        now: datetime,
    ) -> tuple[ProjectedMindState, EmotionalTransitionResult | None]:
        """Advance dynamics once for this instant; None result = no transition."""

        if elapsed <= timedelta(0) or not current_affect:
            return (
                self._wrapper_projection(
                    affect_scope,
                    current_affect,
                    interaction_id=interaction_id,
                    now=now,
                ),
                None,
            )
        transition_result = self._orchestrator.emotional_transition.transition(
            EmotionalTransitionInput(
                interaction_id=interaction_id,
                scope=policy_scope,
                origin_runtime_id=self._runtime_id,
                context=situation,
                current_affect=current_affect,
                elapsed=elapsed,
                persona_id=self._persona.persona_id,
                persona_version=self._persona.version,
                persona=self._persona.dimensions,
                observations=(),
                semantic_candidates=(),
                history_context=None,
                clock=now,
                projection_scope=self._projection_scope,
            )
        )
        return transition_result.projected, transition_result

    def _wrapper_projection(
        self,
        scope: Scope,
        current_affect: tuple[RuntimeState, ...],
        *,
        interaction_id: str,
        now: datetime,
    ) -> ProjectedMindState:
        """Reuse current affect values when this instant advances nothing."""
        states = current_affect or self._initial_states(
            scope, interaction_id=interaction_id, now=now
        )
        projection_scope = states[0].scope
        projection_id = f"projection-{interaction_id}"
        return ProjectedMindState(
            projection_id=projection_id,
            scope=projection_scope,
            origin_runtime_id=self._runtime_id,
            projected_states=states,
            sync=SyncFields(
                projection_scope,
                self._runtime_id,
                projection_id,
                1,
                f"idem-{projection_id}",
            ),
            committed=False,
        )

    def _initial_states(
        self, scope: Scope, *, interaction_id: str, now: datetime
    ) -> tuple[RuntimeState, ...]:
        """Deterministic version-one affect rows from persona initial values."""
        states: list[RuntimeState] = []
        for profile in sorted(self._persona.dimensions, key=lambda item: item.dimension):
            state_id = f"{profile.dimension}:1:projected-{interaction_id}"
            states.append(
                RuntimeState(
                    state_id=state_id,
                    scope=scope,
                    origin_runtime_id=self._runtime_id,
                    dimension=profile.dimension,
                    value=profile.initial_value,
                    status="active",
                    valid_from=now,
                    valid_until=None,
                    relevant_until=None,
                    last_observed_at=now,
                    evidence_refs=(),
                    transition_refs=(),
                    updated_at=now,
                    version=1,
                    sync=SyncFields(scope, self._runtime_id, state_id, 1, f"idem-{state_id}"),
                )
            )
        return tuple(states)

    def _persist_projection(self, projected: ProjectedMindState) -> int:
        """Persist tick-projected affect rows; return rows actually new.

        Deterministic identity binding keeps replay idempotent: re-driving
        the same ``now`` produces the exact same state ids, which the
        append-only backend absorbs. A projection that changes no value
        (equilibrium) writes nothing.
        """
        if self._state_backend is None:
            return 0
        existing = {state.state_id: state for state in self._state_backend.load_states()}
        written = 0
        for state in projected.projected_states:
            new_value = _as_float(state.value)
            before = existing.get(state.state_id)
            if before is not None and math.isclose(_as_float(before.value), new_value):
                continue
            if self._state_backend.save_state(state):
                written += 1
        return written

    # ── stage 3: tick Situation (no inbound Interaction, no Evidence) ────

    def _tick_situation(self, *, scope: Scope, interaction_id: str, now: datetime) -> Situation:
        facts = list(self._fact_reader.facts(scope)) if self._fact_reader is not None else []
        facts.append(("time.tick_ref", interaction_id))
        # D6 temporal owner reuse: the guard chain's temporal grounding and
        # the bounded provider view consume the frozen daypart vocabulary.
        facts.append(("time.daypart", daypart(now).value))
        # C6B legacy gap #6 read half: derive photo cadence eligibility from
        # the host-owned settled-action counter. Read-only; a missing or
        # unreadable counter fails closed ("false") and nothing is fabricated.
        # The threshold is deployment configuration (None = feature off) —
        # a runtime without explicit configuration never inherits a
        # deployment-specific 1-per-3 rule.
        cadence_eligible = media_photo_cadence_eligible(
            _counter_int(facts, CADENCE_COUNTER_FACT),
            threshold=self._config.photo_cadence_threshold,
        )
        facts.append((MEDIA_ELIGIBILITY_FACT, "true" if cadence_eligible else "false"))
        return Situation(
            situation_id=f"situation-{interaction_id}",
            scope=scope,
            origin_runtime_id=self._runtime_id,
            derived_facts=tuple(facts),
            effective_state_ref="none",
            observed_at=now,
            historical_context=None,
            persona_id=None,
            relationship_ids=(),
            evidence_refs=(),
        )

    # ── stage 4: ActionPolicy decisions + lifecycle persistence ──────────

    def _decide(
        self,
        *,
        scope: Scope,
        now: datetime,
        situation: Situation,
        candidates: tuple[Intent, ...],
        counters: _MutableCounters,
        interaction_id: str | None = None,
    ) -> tuple[Intent, ActionPolicyResult] | None:
        """Run the policy gate; return the ALLOW selection for expression."""
        actual_interaction_id = interaction_id or getattr(counters, "interaction_id", "")
        lifecycle = self._intent_lifecycle
        selection: tuple[Intent, ActionPolicyResult] | None = None
        before_status = {
            intent.intent_id: intent.status for intent in lifecycle.backend.current(scope)
        }
        candidate_ids = {candidate.intent_id for candidate in candidates}
        # Persistent-condition dedupe (C5B addendum): a continuous affect
        # condition would re-cross the threshold on every tick; while an
        # intent of the same kind is still active, later ticks must not
        # spawn duplicate candidates for the same condition.
        active_kinds = {
            intent.kind
            for intent in lifecycle.backend.current(scope)
            if intent.status
            in {IntentStatus.CANDIDATE, IntentStatus.DEFERRED, IntentStatus.ALLOWED}
        }
        admitted: list[Intent] = []
        for candidate in candidates:
            if not lifecycle.is_initial_candidate(candidate):
                raise ValueError("intent engine must return version-one candidate Intents")
            known_status = before_status.get(candidate.intent_id)
            if known_status is not None:
                # Orphan recovery (CT11a): a candidate admitted by a crashed
                # pass of this instant is still CANDIDATE — it must be
                # decided now, never deduped away. An identity that already
                # progressed past CANDIDATE is a same-instant replay: skip.
                if known_status is IntentStatus.CANDIDATE:
                    admitted.append(candidate)
                continue
            # Persistent-condition dedupe (C5B addendum): a continuous
            # affect condition would re-cross the threshold on every tick;
            # while an intent of the same kind is still active, later ticks
            # must not spawn duplicate candidates for the same condition.
            if candidate.kind in active_kinds:
                counters.deduped += 1
                continue
            admitted.append(lifecycle.admit(candidate))
        counters.admitted = len(admitted)
        # Wake reconsiderations: intents the scheduler promoted (or prior
        # ticks left) in CANDIDATE status, re-entering the policy gate.
        reconsidered = tuple(
            intent
            for intent in lifecycle.backend.current(scope)
            if intent.status is IntentStatus.CANDIDATE and intent.intent_id not in candidate_ids
        )
        ordered = sorted(
            admitted + list(reconsidered),
            key=lambda intent: (-intent.strength, intent.intent_id),
        )
        for index, candidate in enumerate(ordered):
            policy_result = self._action_policy.policy(
                ActionPolicyInput(
                    intent=candidate,
                    context=situation,
                    scope=scope,
                    clock=now,
                    resources=self._policy_resources,
                )
            )
            if policy_result.decision is ActionDecision.DEFER:
                lifecycle.transition(
                    scope,
                    candidate.intent_id,
                    IntentStatus.DEFERRED,
                    policy_result.reason_codes,
                    now,
                    f"tick-policy-defer-{candidate.intent_id}-v{candidate.sync.version}",
                )
                counters.deferred += 1
            elif policy_result.decision is ActionDecision.DENY:
                lifecycle.transition(
                    scope,
                    candidate.intent_id,
                    IntentStatus.BLOCKED,
                    policy_result.reason_codes,
                    now,
                    f"tick-policy-deny-{candidate.intent_id}-v{candidate.sync.version}",
                )
                counters.denied += 1
            else:
                allowed_intent = lifecycle.transition(
                    scope,
                    candidate.intent_id,
                    IntentStatus.ALLOWED,
                    policy_result.reason_codes,
                    now,
                    f"tick-policy-allow-{candidate.intent_id}-v{candidate.sync.version}",
                )
                counters.allowed += 1
                selection = (allowed_intent, policy_result)
                self._orchestrator.trace.record(
                    actual_interaction_id,
                    "policy_allow",
                    ref=candidate.intent_id,
                    outcome=candidate.kind,
                    at=now,
                )
                for lower in ordered[index + 1 :]:
                    lifecycle.transition(
                        lower.scope,
                        lower.intent_id,
                        IntentStatus.SUPERSEDED,
                        ("lower_than_selected_candidate",),
                        now,
                        f"tick-policy-supersede-{lower.intent_id}-v{lower.sync.version}",
                    )
                    counters.superseded += 1
                break
        return selection

    def _prepare_expression(
        self,
        *,
        selection: tuple[Intent, ActionPolicyResult] | None,
        situation: Situation,
        projected: ProjectedMindState,
        transition_result: EmotionalTransitionResult | None,
        interaction_id: str,
        now: datetime,
        surface: object | None = None,
    ) -> ProactiveExpressionArtifact | None:
        """Prepare the would-send artifact for a proactive ALLOW (C5C).

        Fail-closed: unwired seam -> None; a pass without a real
        EmotionalTransition skips (no honest assessment trace to cite);
        agent failure is recorded and never corrupts state. Preparation
        never writes facts — counter facts stay read-only inputs.
        """

        preparer = self._expression
        if selection is None or preparer is None:
            return None
        intent, policy_result = selection
        if not preparer.handles(policy_result=policy_result):
            return None
        permission = policy_result.permission
        base = ProactiveExpressionArtifact(
            interaction_id=interaction_id,
            intent_id=intent.intent_id,
            action_type=permission.action_type if permission is not None else "",
        )
        if transition_result is None:
            self._orchestrator.trace.record(
                interaction_id,
                "proactive_expression",
                outcome="skipped:no_transition",
                at=now,
            )
            return replace(base, skip_reason="no_transition")
        try:
            return preparer.prepare(
                interaction_id=interaction_id,
                intent=intent,
                policy_result=policy_result,
                situation=situation,
                projected=projected,
                assessment_trace_ref=transition_result.assessment_trace.trace_id,
                state_rows=self._load_state_rows(),
                persona_ref=self._persona.persona_id,
                now=now,
                accepted_appraisals=transition_result.accepted_appraisals,
                surface=surface,  # type: ignore[arg-type]
                persona_version=self._persona.version,
                persona_content_digest=self._persona.persona_content_digest,
            )
        except AgentFailure:
            self._orchestrator.trace.record(
                interaction_id,
                "proactive_expression",
                outcome="agent_failure",
                at=now,
            )
            return replace(base, skip_reason="agent_failure")

    def _count_status(self, scope: Scope, status: IntentStatus) -> int:
        return sum(
            1 for intent in self._intent_lifecycle.backend.current(scope) if intent.status is status
        )


class _MutableCounters:
    """Accumulate one tick's counters before freezing them into the report."""

    def __init__(
        self,
        *,
        interaction_id: str,
        elapsed: timedelta,
        generated: int,
        wakes: int,
        expired: int,
        persisted_rows: int,
    ) -> None:
        self.interaction_id = interaction_id
        self.elapsed = elapsed
        self.generated = generated
        self.admitted = 0
        self.wakes = wakes
        self.expired = expired
        self.persisted_rows = persisted_rows
        self.allowed = 0
        self.deferred = 0
        self.denied = 0
        self.superseded = 0
        self.deduped = 0
        self.wake_signal: WakeSignal | None = None

    def freeze(
        self,
        *,
        scope: Scope,
        now: datetime,
        tick_ref: str,
        expression: ProactiveExpressionArtifact | None = None,
        wake_signal: WakeSignal | None = None,
    ) -> CognitiveTickReport:
        return CognitiveTickReport(
            tick_ref=tick_ref,
            interaction_id=self.interaction_id,
            scope=scope,
            now=now,
            elapsed=self.elapsed,
            intent_candidates_generated=self.generated,
            candidates_admitted=self.admitted,
            intents_expired=self.expired,
            wakes=self.wakes,
            policy_allowed=self.allowed,
            policy_deferred=self.deferred,
            policy_denied=self.denied,
            superseded=self.superseded,
            state_rows_persisted=self.persisted_rows,
            persistent_duplicates_skipped=self.deduped,
            proactive_expression=expression,
            wake_signal=wake_signal if wake_signal is not None else self.wake_signal,
        )


def _as_float(value: object) -> float:
    """Narrow a frozen state value to float (values are numeric by filter)."""

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("state value must be a finite number")
    return float(value)


def _resolve_state_backend(orchestrator: TurnOrchestrator) -> StateBackend | None:
    backend: object | None = None
    for attr in _STATE_BACKEND_ATTRS:
        backend = getattr(orchestrator, attr, None)
        if backend is not None:
            break
    if isinstance(backend, StateBackend):
        return backend
    return None


def build_cognitive_ticker(
    *,
    orchestrator: TurnOrchestrator,
    persona: PersonaProfile,
    intent_engine: DeterministicIntentEngine,
    action_policy: DeterministicActionPolicy,
    policy_resources: PolicyResources,
    intent_lifecycle: IntentLifecycleService,
    runtime_id: str,
    fact_reader: PolicyFactReader | None = None,
    expression: ProactiveExpressionPreparer | None = None,
    config: CognitiveTickConfig | None = None,
) -> CognitiveTicker:
    """Assemble a ticker from explicitly injected real components.

    Fail-closed by construction: the caller must supply the persona, the
    deterministic IntentEngine, the deterministic ActionPolicy with explicit
    PolicyResources, and a durable Intent lifecycle. The turn orchestrator's
    own stub ports are never repurposed — the C2.10 turn path stays frozen.
    The optional C5C ``expression`` seam (ProactiveExpressionPreparer) adds
    would-send preparation after the policy gate; without it the tick is
    the C5B behavior.
    """
    if not isinstance(persona, PersonaProfile):
        raise ValueError("cognitive tick requires a PersonaProfile")
    if not isinstance(intent_engine, DeterministicIntentEngine):
        raise ValueError("cognitive tick requires a DeterministicIntentEngine")
    if not isinstance(action_policy, DeterministicActionPolicy):
        raise ValueError("cognitive tick requires a DeterministicActionPolicy")
    if not isinstance(intent_lifecycle, IntentLifecycleService):
        raise ValueError("cognitive tick requires an IntentLifecycleService")
    prefixes = {profile.dimension.partition(".")[0] for profile in persona.dimensions}
    if prefixes == {"agent"}:
        projection_scope: Scope | None = Scope(
            domain=ScopeDomain.AGENT,
            agent_id=persona.persona_id,
            persona_id=persona.persona_id,
        )
    elif prefixes == {"user"}:
        projection_scope = None
    else:
        raise ValueError("persona dimensions must be uniformly agent.* or user.*")
    return CognitiveTicker(
        orchestrator=orchestrator,
        persona=persona,
        intent_engine=intent_engine,
        action_policy=action_policy,
        policy_resources=policy_resources,
        intent_lifecycle=intent_lifecycle,
        runtime_id=runtime_id,
        fact_reader=fact_reader or observation_fact_reader(orchestrator),
        projection_scope=projection_scope,
        expression=expression,
        config=config,
    )
