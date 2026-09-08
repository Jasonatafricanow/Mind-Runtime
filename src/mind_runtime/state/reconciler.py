"""FactualReconciler: the D4 canonical state reconciler.

The reconciler is the only production path that turns typed state intents
into canonical state: it runs the validity pass (D4.2) first, then applies
each intent to the latest state of its ``(scope, dimension)``.

Lifecycle semantics (D4.3-D4.6):

- creation: a dimension with no current state gets a fresh ACTIVE state
  whose envelope follows the registered validity policy;
- reaffirm (D4.3): an intent whose value equals the current value refreshes
  the temporal envelope and keeps the state ACTIVE; event_only dimensions
  never refresh by reaffirm;
- categorical supersession (D4.4): a new value ends the old state as
  SUPERSEDED (terminal) and starts a fresh ACTIVE state — the dimension
  always has exactly one current state (single effective state);
- explicit terminal transitions (D4.4): a ``lifecycle`` intent
  (RESOLVED/COMPLETED/CANCELLED) turns the current state into that terminal
  record; repeating the same terminal intent is a no-op, and terminal ->
  different-terminal is illegal (fail closed);
- expired or terminal currents are not resurrected: a new observation after
  them starts a fresh ACTIVE state through a new transition (D4.4);
- delayed anti-rollback (D4.5): an intent whose ``observed_at`` is older
  than the current state's ``last_observed_at`` is deferred — it never
  supersedes or reaffirms a newer state (G9).
"""

from dataclasses import dataclass
from datetime import datetime

from mind_runtime.contracts import (
    Observation,
    RuntimeState,
    Scope,
    StateTransition,
    SyncFields,
)
from mind_runtime.providers.clock import Clock
from mind_runtime.state.definitions import (
    StateDefinitionRegistry,
    ValidityKind,
    ValidityPolicy,
)
from mind_runtime.state.ids import canonical_state_id
from mind_runtime.state.lifecycle import (
    StateLifecycle,
    is_current_like,
    is_known_lifecycle,
    is_terminal,
)
from mind_runtime.state.validity import evaluate_validity


@dataclass(frozen=True)
class StateIntent:
    """A typed state update derived from an observation (D4 input contract)."""

    dimension: str
    value: object
    observed_at: datetime
    scope: Scope
    origin_runtime_id: str
    evidence_refs: tuple[str, ...] = ()
    lifecycle: StateLifecycle | None = None


# The typed-observation key conventions (D4.8). A dimension-typed
# observation carries ``<domain>.<name>.observed`` for a value update and
# ``<domain>.<name>.<terminal>`` for an explicit terminal transition.
_VALUE_SUFFIX = "observed"
_TERMINAL_SUFFIXES = frozenset(
    {
        StateLifecycle.CANCELLED.value,
        StateLifecycle.COMPLETED.value,
        StateLifecycle.RESOLVED.value,
    }
)
_STATE_DOMAINS = frozenset({"user", "agent", "relationship", "interaction"})


def interpret_observation(observation: Observation) -> StateIntent | None:
    """Interpret a dimension-typed Observation into a StateIntent.

    The interpretation is structural (key convention only): policy and
    legality are decided by the reconciler/registry. Observations whose key
    does not follow the typed convention (e.g. the D3 source-typed
    ``<source_type>.observed``) yield None: semantic extraction into
    dimensions is a later gate (D8), not D4's job.
    """
    dimension, separator, suffix = observation.key.rpartition(".")
    if not separator or not dimension or suffix not in _TERMINAL_SUFFIXES | {_VALUE_SUFFIX}:
        return None
    prefix, dot, name = dimension.partition(".")
    if not dot or not name or prefix not in _STATE_DOMAINS:
        return None
    lifecycle = None if suffix == _VALUE_SUFFIX else StateLifecycle(suffix)
    return StateIntent(
        dimension=dimension,
        value=observation.value,
        observed_at=observation.observed_at,
        scope=observation.scope,
        origin_runtime_id=observation.origin_runtime_id,
        evidence_refs=observation.evidence_refs,
        lifecycle=lifecycle,
    )


@dataclass(frozen=True)
class ReconcileResult:
    """The outcome of one reconcile pass over the canonical snapshot."""

    canonical: tuple[RuntimeState, ...]
    transitions: tuple[StateTransition, ...]
    effective: tuple[RuntimeState, ...]
    deferred: tuple[StateIntent, ...] = ()

    def effective_for(self, dimension: str, scope: Scope) -> RuntimeState | None:
        for state in self.effective:
            if state.dimension == dimension and state.scope == scope:
                return state
        return None


class FactualReconciler:
    """Applies typed intents to canonical state with full lifecycle rules."""

    def __init__(self, *, clock: Clock, definitions: StateDefinitionRegistry) -> None:
        self._clock = clock
        self._definitions = definitions

    def apply(
        self,
        canonical: tuple[RuntimeState, ...],
        intents: tuple[StateIntent, ...],
    ) -> ReconcileResult:
        now = self._clock.now()
        currents: dict[tuple[Scope, str], RuntimeState] = {}
        order: list[tuple[Scope, str]] = []
        for state in canonical:
            key = (state.scope, state.dimension)
            if key not in currents:
                order.append(key)
            # The canonical snapshot holds one latest record per dimension;
            # a later occurrence wins (defensive against unordered input).
            currents[key] = state

        transitions: list[StateTransition] = []
        deferred: list[StateIntent] = []
        # Validity pass: time may expire current-like states before any
        # intent is applied (D4.2), never terminal states.
        for key in order:
            current = currents[key]
            outcome = evaluate_validity(current, now=now)
            if outcome.changed:
                currents[key] = outcome.state
                transitions.append(self._transition(current, outcome.state, now=now))

        for intent in intents:
            key = (intent.scope, intent.dimension)
            current_state = currents.get(key)
            if current_state is None:
                # Invariant: order mirrors currents, so a fresh dimension is
                # always appended here exactly once.
                currents[key] = self._create(intent, now=now)
                order.append(key)
                continue
            if intent.observed_at < current_state.last_observed_at:
                # D4.5 anti-rollback: an intent older than the state's last
                # observation must not change the newer state (G9). Ordering
                # information stays in the D3 provenance; the intent is
                # deferred (D5 may reconcile delayed events explicitly).
                deferred.append(intent)
                continue
            new_state, new_transitions = self._reconcile(current_state, intent, now=now)
            currents[key] = new_state
            transitions.extend(new_transitions)

        effective = tuple(currents[key] for key in order)
        return ReconcileResult(
            canonical=effective,
            transitions=tuple(transitions),
            effective=effective,
            deferred=tuple(deferred),
        )

    # --- per-intent reconciliation ---

    def _reconcile(
        self, current: RuntimeState, intent: StateIntent, *, now: datetime
    ) -> tuple[RuntimeState, tuple[StateTransition, ...]]:
        if intent.lifecycle is not None:
            return self._apply_terminal(current, intent, now=now)
        if is_terminal(current.status):
            # A terminal answers "what happened?"; a new observation after it
            # starts a fresh state instead of resurrecting the terminal.
            return self._fresh_after(current, intent, now=now)
        if not is_current_like(current.status):
            if is_known_lifecycle(current.status):
                # Expired current: the new observation supersedes it.
                return self._fresh_after(current, intent, now=now)
            raise ValueError(f"opaque status {current.status!r} cannot be reconciled")
        if intent.value == current.value:
            # Reaffirm: same value keeps the state current; the envelope
            # refreshes unless the policy forbids time-based refresh.
            policy = self._definitions.validity_policy(current.dimension)
            if policy.kind is ValidityKind.EVENT_ONLY:
                return current, ()
            refreshed = self._refresh(current, intent, policy, now=now)
            return refreshed, (self._transition(current, refreshed, now=now),)
        return self._supersede(current, intent, now=now)

    def _apply_terminal(
        self, current: RuntimeState, intent: StateIntent, *, now: datetime
    ) -> tuple[RuntimeState, tuple[StateTransition, ...]]:
        assert intent.lifecycle is not None
        if is_terminal(current.status):
            if current.status == intent.lifecycle.value:
                # Repeating the same terminal intent is idempotent.
                return current, ()
            raise ValueError(
                f"illegal terminal transition {current.status} -> {intent.lifecycle.value}"
            )
        terminal = self._terminal_record(current, intent.lifecycle, intent, now=now)
        return terminal, (self._transition(current, terminal, now=now),)

    def _supersede(
        self, current: RuntimeState, intent: StateIntent, *, now: datetime
    ) -> tuple[RuntimeState, tuple[StateTransition, ...]]:
        # Categorical supersession: the old value ends as SUPERSEDED, the new
        # value starts ACTIVE. Both records are immutable history; the
        # dimension keeps exactly one current state.
        superseded = self._terminal_record(current, StateLifecycle.SUPERSEDED, intent, now=now)
        fresh = self._fresh_state(
            current.scope,
            intent,
            now=now,
            version=superseded.version + 1,
            valid_from=now,
        )
        return fresh, (
            self._transition(current, superseded, now=now),
            self._transition(superseded, fresh, now=now),
        )

    def _fresh_after(
        self, current: RuntimeState, intent: StateIntent, *, now: datetime
    ) -> tuple[RuntimeState, tuple[StateTransition, ...]]:
        fresh = self._fresh_state(
            current.scope,
            intent,
            now=now,
            version=current.version + 1,
            valid_from=now,
        )
        return fresh, (self._transition(current, fresh, now=now),)

    # --- state construction ---

    def _create(self, intent: StateIntent, *, now: datetime) -> RuntimeState:
        return self._fresh_state(intent.scope, intent, now=now, version=1, valid_from=now)

    def _fresh_state(
        self,
        scope: Scope,
        intent: StateIntent,
        *,
        now: datetime,
        version: int,
        valid_from: datetime,
    ) -> RuntimeState:
        policy = self._definitions.validity_policy(intent.dimension)
        if policy.kind is ValidityKind.TTL:
            assert policy.ttl is not None
            valid_until = now + policy.ttl
        else:
            valid_until = None
        state_id = canonical_state_id(intent.dimension, version)
        return RuntimeState(
            state_id=state_id,
            scope=scope,
            dimension=intent.dimension,
            value=intent.value,
            status=StateLifecycle.ACTIVE.value,
            valid_from=valid_from,
            valid_until=valid_until,
            relevant_until=None,
            last_observed_at=now,
            evidence_refs=intent.evidence_refs,
            transition_refs=(),
            updated_at=now,
            origin_runtime_id=intent.origin_runtime_id,
            version=version,
            sync=SyncFields(
                scope,
                intent.origin_runtime_id,
                state_id,
                version,
                f"idem-{state_id}",
            ),
        )

    def _terminal_record(
        self,
        state: RuntimeState,
        lifecycle: StateLifecycle,
        intent: StateIntent,
        *,
        now: datetime,
    ) -> RuntimeState:
        version = state.version + 1
        state_id = canonical_state_id(state.dimension, version)
        return RuntimeState(
            state_id=state_id,
            scope=state.scope,
            dimension=state.dimension,
            value=state.value,
            status=lifecycle.value,
            valid_from=state.valid_from,
            valid_until=state.valid_until,
            relevant_until=state.relevant_until,
            last_observed_at=now,
            evidence_refs=state.evidence_refs + intent.evidence_refs,
            transition_refs=state.transition_refs,
            updated_at=now,
            origin_runtime_id=state.origin_runtime_id,
            version=version,
            sync=SyncFields(
                state.scope,
                state.origin_runtime_id,
                state_id,
                version,
                f"idem-{state_id}",
            ),
        )

    def _refresh(
        self,
        state: RuntimeState,
        intent: StateIntent,
        policy: ValidityPolicy,
        *,
        now: datetime,
    ) -> RuntimeState:
        version = state.version + 1
        state_id = canonical_state_id(state.dimension, version)
        valid_until: datetime | None
        if policy.kind is ValidityKind.TTL:
            assert policy.ttl is not None
            valid_until = now + policy.ttl
        else:
            valid_until = state.valid_until
        return RuntimeState(
            state_id=state_id,
            scope=state.scope,
            dimension=state.dimension,
            value=state.value,
            status=state.status,
            valid_from=state.valid_from,
            valid_until=valid_until,
            relevant_until=state.relevant_until,
            last_observed_at=now,
            evidence_refs=state.evidence_refs + intent.evidence_refs,
            transition_refs=state.transition_refs,
            updated_at=now,
            origin_runtime_id=state.origin_runtime_id,
            version=version,
            sync=SyncFields(
                state.scope,
                state.origin_runtime_id,
                state_id,
                version,
                f"idem-{state_id}",
            ),
        )

    def _transition(
        self, from_state: RuntimeState, to_state: RuntimeState, *, now: datetime
    ) -> StateTransition:
        transition_id = f"transition:{to_state.state_id}"
        return StateTransition(
            transition_id=transition_id,
            scope=from_state.scope,
            origin_runtime_id=to_state.origin_runtime_id,
            intent_id=f"intent:{to_state.state_id}",
            from_state=from_state,
            to_state=to_state,
            committed_at=now,
            sync=SyncFields(
                from_state.scope,
                to_state.origin_runtime_id,
                transition_id,
                1,
                f"idem-{transition_id}",
            ),
        )
