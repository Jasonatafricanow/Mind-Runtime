"""Rolling-window writer for longitudinal state.

Implements ADR-0017 (ACCEPTED):

  W_t(d) = last N qualifying SLOW_ACCEPT contributions for dimension d
           (rolling, ordered by accepted_at)
  A_t(d) = Σ (salience_i * proposed_value_i) / Σ salience_i
  S_t(d) = A_t(d)                                 (Step B = overwrite)

  Empty W_t(d) → NO WRITE.

Explicitly absent (forbidden by ADR-0017):
  - learning_rate / LR / alpha (any multiplicative constant other than salience)
  - prior-state blend (no S_{t-1} read in the writer)
  - writer-side clamp (bounds are input contract, not writer concern)
  - recency bias / EMA / time decay
  - empty-window → 0 (empty window = no write)

Persistence:
  - The rolling window of qualifying contributions is persisted in the
    shared state.sqlite DB as the `slow_contribution_window` table.
  - Each flush inserts the new ledger rows, trims the window to the
    configuration-owned `window_size`, and writes a new canonical
    RuntimeState row (S_t = A_t) — all in one SQLite transaction.
  - Restart equivalence: the in-memory cache is rebuilt from the persisted
    ledger on `load()`. The same W_t(d) is reconstructed, the same A_t(d)
    is computed, the same S_t(d) is produced.

The writer is the SINGLE AUTHORITATIVE writer for registered longitudinal
dimensions. The orchestrator seam in `commit_turn()` calls this writer
exactly once per turn with the SLOW_ACCEPT decisions produced by the
StateUpdatePolicy. The writer does not call any LLM, does not infer
contributions, does not strip or rewrite target_dimension strings, and
does not mutate `agent.affect.*` state.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from mind_runtime.contracts import (
    RuntimeState,
    Scope,
    SyncFields,
)
from mind_runtime.homeostasis.contracts import (
    CandidateStateDelta,
    StateUpdateDecision,
    StateUpdateDisposition,
)


# ============================================================================
# SlowContributionRecord — one qualifying SLOW_ACCEPT contribution
# ============================================================================


@dataclass(frozen=True, slots=True)
class SlowContributionRecord:
    """One qualifying SLOW_ACCEPT contribution in the rolling window.

    The record is constructed from a StateUpdateDecision accepted by the
    StateUpdatePolicy. It carries the full audit-trail identity bundle so
    the writer can persist the rolling window verbatim and recompute A_t(d)
    on restart without losing lineage.
    """

    target_dimension: str
    proposed_value: float
    salience: float
    evidence_refs: tuple[str, ...]
    source_event_ref: str | None
    source_decision_id: str
    accepted_at: datetime


# ============================================================================
# SlowWindowSnapshot — the writer's in-memory view of one (scope, dimension)
# ============================================================================


@dataclass(frozen=True, slots=True)
class SlowWindowSnapshot:
    """The in-memory view of one (scope, dimension) rolling window."""

    scope: Scope
    target_dimension: str
    contributions: tuple[SlowContributionRecord, ...]
    last_state_version: int | None
    last_state_value: float | None
    last_state_state_id: str | None


@dataclass(frozen=True, slots=True)
class SlowFlushPlan:
    """Prepared, immutable execution plan for one (scope, dimension) slow update.

    Contains all computed values and parameters required to execute the durable
    write inside an atomic transaction without modifying in-memory state.
    """

    scope: Scope
    target_dimension: str
    state: RuntimeState
    new_rows: tuple[dict, ...]
    trim_keys: tuple[Scope, str]
    window_size: int
    kept_records: tuple[SlowContributionRecord, ...]
    new_version: int
    a_t: float


# ============================================================================
# Backend protocol — the persistence boundary
# ============================================================================


class SlowStateBackend(Protocol):
    """Persistence protocol for slow-state records and the rolling window.

    The same SQLite connection is used for the rolling window and the
    canonical RuntimeState so they can be committed in one transaction.
    """

    def load_slow_window(
        self,
        scope: Scope,
        target_dimension: str,
    ) -> tuple[dict, ...]: ...

    def list_slow_window_dimensions(
        self, scope: Scope
    ) -> tuple[tuple[Scope, str], ...]: ...

    def max_slow_window_sequence(
        self, scope: Scope, target_dimension: str
    ) -> int: ...

    def commit_slow_window_update(
        self,
        *,
        state: RuntimeState,
        new_rows: tuple[dict, ...],
        trim_keys: tuple[Scope, str],
        window_size: int,
    ) -> bool: ...


# ============================================================================
# Clock abstraction (allows deterministic clock injection in tests)
# ============================================================================


class _IClock(Protocol):
    def now(self) -> datetime: ...


class _RealClock:
    def now(self) -> datetime:
        from datetime import UTC

        return datetime.now(UTC)


# ============================================================================
# LongitudinalStateWriter — the single authoritative slow-state writer
# ============================================================================


class LongitudinalStateWriter:
    """C10-B-W: the authoritative slow-plasticity writer (ADR-0017).

    Accepts qualifying StateUpdateDecision records from the orchestrator,
    maintains a rolling window of the last `window_size` qualifying
    contributions per (scope, dimension), and atomically writes the
    salience-weighted mean (A_t) to the canonical RuntimeState table.

    Configuration:
        window_size: integer >= 1; required; production-owned. The writer
            has no default. Pass it explicitly.

    Usage:
        writer = LongitudinalStateWriter(
            backend=state_backend, runtime_id="runtime-1", window_size=8
        )
        writer.load()  # rebuild in-memory view from persisted ledger
        for decision in slow_accept_decisions:
            writer.accept(decision)  # qualifier: SLOW_ACCEPT, salience > 0,
                                     # registered longitudinal dimension
        writer.flush(slow_scope)
    """

    def __init__(
        self,
        backend: SlowStateBackend,
        runtime_id: str = "runtime-1",
        window_size: int = 0,
        clock: _IClock | None = None,
    ) -> None:
        if window_size < 1:
            raise ValueError(
                f"window_size must be >= 1 (configuration-owned); got {window_size}"
            )
        self._backend = backend
        self._runtime_id = runtime_id
        self._window_size = int(window_size)
        self._clock = clock or _RealClock()
        # (scope, target_dimension) -> SlowWindowSnapshot.
        self._windows: dict[tuple[Scope, str], SlowWindowSnapshot] = {}
        # Pending contributions keyed by (scope, target_dimension).
        self._pending: dict[tuple[Scope, str], list[SlowContributionRecord]] = {}
        # Monotonic counter for unique source_decision_id values.
        self._seq_counter = 0

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    @property
    def window_size(self) -> int:
        """Configuration-owned window size. Immutable after construction."""
        return self._window_size

    # ------------------------------------------------------------------
    # Restart equivalence
    # ------------------------------------------------------------------

    def load(self, scope: Scope) -> None:
        """Rebuild the in-memory window view from the persisted ledger.

        Called on startup so a post-restart writer recomputes A_t(d) from the
        exact same W_t(d). Only dimensions with persisted rows are loaded.

        Production path: pass the AGENT scope (or whatever scope the slow
        state is scoped to) so the writer only loads relevant windows.
        """
        self._windows.clear()
        self._pending.clear()
        for loaded_scope, dim in self._backend.list_slow_window_dimensions(scope):
            rows = self._backend.load_slow_window(loaded_scope, dim)
            self._ingest_persisted_rows(loaded_scope, dim, rows)

    # ------------------------------------------------------------------
    # Decision ingestion
    # ------------------------------------------------------------------

    def accept(
        self,
        decision: StateUpdateDecision,
        *,
        target_scope: Scope | None = None,
    ) -> SlowContributionRecord | None:
        """Accept one StateUpdateDecision if it qualifies for slow state.

        Qualifying (per ADR-0017):
          - decision.decision == SLOW_ACCEPT
          - candidate.salience is not None
          - candidate.salience > 0   (zero salience → no weight, drop)

        Returns:
            SlowContributionRecord if accepted, else None.

        Non-qualifying decisions are silently dropped. The orchestrator seam
        is responsible for routing only SLOW_ACCEPT decisions to the writer.
        """
        if decision.decision != StateUpdateDisposition.SLOW_ACCEPT:
            return None
        if not isinstance(decision.candidate, CandidateStateDelta):
            return None
        candidate: CandidateStateDelta = decision.candidate
        if candidate.salience is None:
            return None
        salience = float(candidate.salience)
        if salience <= 0.0:
            return None
        scope = target_scope if target_scope is not None else candidate.scope

        self._seq_counter += 1
        record = SlowContributionRecord(
            target_dimension=candidate.target_dimension,
            proposed_value=float(candidate.proposed_value),
            salience=salience,
            evidence_refs=tuple(candidate.evidence_refs),
            source_event_ref=candidate.source_event_ref,
            source_decision_id=f"slow-{self._runtime_id}-{self._seq_counter}",
            accepted_at=self._clock.now(),
        )
        key = (scope, record.target_dimension)
        self._pending.setdefault(key, []).append(record)
        return record

    # ------------------------------------------------------------------
    # Durable persistence
    # ------------------------------------------------------------------

    def prepare_flush(self, scope: Scope) -> tuple[SlowFlushPlan, ...]:
        """Prepare execution plans for all pending contributions in scope.

        Computes the new rolling window, salience-weighted mean A_t,
        canonical RuntimeState (S_t = A_t), and new ledger rows without
        modifying in-memory window snapshots or draining pending records.
        """
        if not isinstance(scope, Scope):
            raise TypeError(
                f"prepare_flush() requires a Scope instance; got {type(scope).__name__}"
            )
        plans: list[SlowFlushPlan] = []

        for (pending_scope, dimension), pending in list(self._pending.items()):
            if pending_scope != scope:
                continue
            if not pending:
                continue

            # 1. Load persisted window.
            persisted_rows = self._backend.load_slow_window(scope, dimension)
            persisted_records = tuple(
                SlowContributionRecord(
                    target_dimension=dimension,
                    proposed_value=float(row["proposed_value"]),
                    salience=float(row["salience"]),
                    evidence_refs=tuple(row["evidence_refs"]),
                    source_event_ref=row["source_event_ref"],
                    source_decision_id=row["source_decision_id"],
                    accepted_at=row["accepted_at"],
                )
                for row in persisted_rows
            )

            # 2. Combine persisted + pending, sort by accepted_at.
            combined: list[SlowContributionRecord] = (
                list(persisted_records) + list(pending)
            )
            combined.sort(key=lambda r: (r.accepted_at, r.source_decision_id))

            # 3. Rolling trim: keep only the latest `window_size`.
            kept = combined[-self._window_size :]

            if not kept:
                # Empty window -> no write (ADR-0017).
                continue

            # 4. A_t = sum(s_i * p_i) / sum(s_i).
            weighted_sum = sum(r.salience * r.proposed_value for r in kept)
            salience_sum = sum(r.salience for r in kept)
            if salience_sum <= 0.0:
                # All saliences are zero -> effectively empty window. No write.
                continue

            a_t = weighted_sum / salience_sum

            # 5. Build canonical RuntimeState (S_t = A_t).
            prior = self._windows.get((scope, dimension))
            prior_state_id = (
                prior.last_state_state_id if prior is not None else None
            )
            prior_version = (
                prior.last_state_version if prior is not None else None
            )
            new_version = (prior_version or 0) + 1
            now = self._clock.now()
            state_id = (
                f"{dimension}:{new_version}:slow-{self._runtime_id}"
                f"-{now.strftime('%Y%m%d%H%M%S%f')}"
            )

            # Evidence = union of evidence_refs across the kept window.
            aggregated_evidence: tuple[str, ...] = tuple(
                dict.fromkeys(
                    ref for r in kept for ref in r.evidence_refs
                )
            )
            transition_refs: tuple[str, ...] = (
                (prior_state_id,) if prior_state_id is not None else ()
            )

            state = RuntimeState(
                state_id=state_id,
                scope=scope,
                dimension=dimension,
                value=a_t,
                status="active",
                valid_from=now,
                valid_until=None,
                relevant_until=None,
                last_observed_at=now,
                evidence_refs=aggregated_evidence,
                transition_refs=transition_refs,
                updated_at=now,
                origin_runtime_id=self._runtime_id,
                version=new_version,
                sync=SyncFields(
                    scope,
                    self._runtime_id,
                    state_id,
                    new_version,
                    f"idem-{state_id}",
                ),
            )

            # Ledger rows to insert: only the pending records.
            base_seq = self._backend.max_slow_window_sequence(scope, dimension)
            new_ledger_rows: tuple[dict, ...] = tuple(
                {
                    "sequence": base_seq + 1 + idx,
                    "accepted_at": r.accepted_at,
                    "proposed_value": r.proposed_value,
                    "salience": r.salience,
                    "evidence_refs": r.evidence_refs,
                    "source_event_ref": r.source_event_ref,
                    "source_decision_id": r.source_decision_id,
                }
                for idx, r in enumerate(pending)
            )

            plans.append(
                SlowFlushPlan(
                    scope=scope,
                    target_dimension=dimension,
                    state=state,
                    new_rows=new_ledger_rows,
                    trim_keys=(scope, dimension),
                    window_size=self._window_size,
                    kept_records=tuple(kept),
                    new_version=new_version,
                    a_t=a_t,
                )
            )

        return tuple(plans)

    def execute_flush_plan(self, plan: SlowFlushPlan) -> None:
        """Execute durable writes for one SlowFlushPlan inside the active transaction."""
        ok = self._backend.commit_slow_window_update(
            state=plan.state,
            new_rows=plan.new_rows,
            trim_keys=plan.trim_keys,
            window_size=plan.window_size,
        )
        if not ok:
            raise RuntimeError(
                f"slow_contribution_window update failed for dimension {plan.target_dimension!r}"
            )

    def apply_flush_plan(
        self, plans: tuple[SlowFlushPlan, ...]
    ) -> tuple[RuntimeState, ...]:
        """Update in-memory snapshots and drain pending state after COMMIT."""
        written: list[RuntimeState] = []
        for plan in plans:
            self._windows[(plan.scope, plan.target_dimension)] = SlowWindowSnapshot(
                scope=plan.scope,
                target_dimension=plan.target_dimension,
                contributions=plan.kept_records,
                last_state_version=plan.new_version,
                last_state_value=plan.a_t,
                last_state_state_id=plan.state.state_id,
            )
            # Drain flushed pending contributions
            self._pending.pop((plan.scope, plan.target_dimension), None)
            written.append(plan.state)
        return tuple(written)

    def discard_pending(self, scope: Scope) -> None:
        """Discard uncommitted pending contributions for the given scope."""
        for k in list(self._pending.keys()):
            if k[0] == scope:
                del self._pending[k]

    def flush(self, scope: Scope) -> tuple[RuntimeState, ...]:
        """Flush all pending qualifying contributions to durable state.

        Backward-compatible orchestration: prepare -> execute -> apply.
        """
        if not isinstance(scope, Scope):
            raise TypeError(
                f"flush() requires a Scope instance; got {type(scope).__name__}"
            )
        plans = self.prepare_flush(scope)
        if not plans:
            return ()

        if hasattr(self._backend, "transaction"):
            with self._backend.transaction():
                for plan in plans:
                    self.execute_flush_plan(plan)
        else:
            for plan in plans:
                self.execute_flush_plan(plan)

        return self.apply_flush_plan(plans)

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def accumulated_state(
        self, scope: Scope, target_dimension: str
    ) -> SlowWindowSnapshot | None:
        """Return the in-memory window snapshot for one (scope, dimension)."""
        return self._windows.get((scope, target_dimension))

    def current_window(
        self, scope: Scope, target_dimension: str
    ) -> SlowWindowSnapshot | None:
        """Alias for accumulated_state. Returns the current in-memory rolling
        window for one (scope, dimension), or None if absent."""
        return self._windows.get((scope, target_dimension))

    def accumulated_dimensions(self, scope: Scope) -> frozenset[str]:
        """Return the set of dimensions with windows for the given scope."""
        return frozenset(
            dim for (s, dim) in self._windows if s == scope
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _ingest_persisted_rows(
        self,
        scope: Scope,
        dimension: str,
        rows: tuple[dict, ...],
    ) -> None:
        """Rebuild an in-memory window snapshot from persisted rows."""
        if not rows:
            return
        # Sort by accepted_at and keep latest N.
        ordered = sorted(rows, key=lambda r: (r["accepted_at"], r["id"]))
        kept = ordered[-self._window_size :]
        records = tuple(
            SlowContributionRecord(
                target_dimension=dimension,
                proposed_value=float(r["proposed_value"]),
                salience=float(r["salience"]),
                evidence_refs=tuple(r["evidence_refs"]),
                source_event_ref=r["source_event_ref"],
                source_decision_id=r["source_decision_id"],
                accepted_at=r["accepted_at"],
            )
            for r in kept
        )
        max_id = kept[-1]["id"]
        self._windows[(scope, dimension)] = SlowWindowSnapshot(
            scope=scope,
            target_dimension=dimension,
            contributions=records,
            last_state_version=len(kept),
            last_state_value=None,  # recomputed on next flush
            last_state_state_id=f"{dimension}:{len(kept)}:slow-restored-{max_id}",
        )


__all__ = [
    "SlowContributionRecord",
    "SlowWindowSnapshot",
    "LongitudinalStateWriter",
    "SlowStateBackend",
]
\n# Backward-compatible public name.\nSlowPlasticityWriter = LongitudinalStateWriter\n