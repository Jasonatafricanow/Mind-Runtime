"""MR-ALPHA-AS1: Synthetic SlowStateAdapter — harness validation only.

NOT production code.  Results through this adapter do NOT count as MR Alpha
evidence.  This adapter is used solely to validate the Alpha Platform harness
(runner, trace, persistence harness, probes, ablations, scoring, report).

The synthetic adapter mimics the SlowPlasticityWriter + SlowStateBackend surface:
  - accept(decision)    : record a synthetic slow-write
  - flush(scope)         : write synthetic agent.slow.* RuntimeState to backend
  - load()               : restore from backend at startup
  - reset_to(values)     : STATE_RESET ablation support
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime

from mind_runtime.contracts import RuntimeState, Scope, ScopeDomain, SyncFields
from mind_runtime.homeostasis.contracts import HomeostasisDecision
from mind_runtime.slow_plasticity.writer import SlowStateBackend


@dataclass
class AccumulatedSlowState:
    """Test-adapter cache record: accumulated slow-state snapshot per dimension.

    Defined locally here (not imported from the writer) because the production
    writer no longer exports this type.
    """

    dimension: str
    value: float
    version: int
    contribution_count: int
    last_contribution_at: datetime
    provenance: tuple[str, ...] = field(default_factory=tuple)
    writer_version: int = 1

# Canonical slow-state prefix (agent.slow.* dimensions).  Re-declared locally
# since the production writer no longer exports this constant.
SLOW_DIMENSION_PREFIX = "agent.slow."

__all__ = ["SyntheticSlowStateAdapter", "SLOW_ADAPTER_VERSION", "make_slow_runtime_state", "SLOW_DIMENSION_PREFIX"]

SLOW_ADAPTER_VERSION = "synth-v1"
_RUNTIME_ID = "alpha-synth"


def make_slow_runtime_state(
    dimension: str,
    value: float,
    version: int,
    scope: Scope,
    evidence_refs: tuple[str, ...] = (),
    *,
    origin_runtime_id: str = _RUNTIME_ID,
    transition_refs: tuple[str, ...] = (),
    now: datetime | None = None,
    source_refs: tuple[str, ...] = ("synthetic_slow_adapter",),
) -> RuntimeState:
    """Factory for valid RuntimeState in the agent.slow.* namespace."""
    ts = now or datetime.now(tz=UTC)
    return RuntimeState(
        state_id=f"{dimension}:{version}:{origin_runtime_id}",
        scope=scope,
        dimension=dimension,
        value=value,
        status="active",
        valid_from=ts,
        valid_until=None,
        relevant_until=None,
        last_observed_at=ts,
        evidence_refs=evidence_refs,
        transition_refs=transition_refs,
        updated_at=ts,
        origin_runtime_id=origin_runtime_id,
        version=version,
        sync=SyncFields(
            scope=scope,
            origin_runtime_id=origin_runtime_id,
            object_id=f"{dimension}:{version}:{origin_runtime_id}",
            version=version,
            idempotency_key=f"idem-{dimension}:{version}",
        ),
    )


# ── Internal record ──────────────────────────────────────────────────────────

@dataclass
class _SyntheticRecord:
    slow_dimension: str
    amount: float
    scope: Scope                     # scope routing per production accept()
    evidence_refs: tuple[str, ...]
    accepted_at: datetime


# ── SyntheticSlowStateAdapter ────────────────────────────────────────────────

class SyntheticSlowStateAdapter:
    """Synthetic stand-in for SlowPlasticityWriter — harness validation only.

    Implements the same interface as the production writer but produces
    deterministic accumulated state in ``agent.slow.*`` dimensions without
    consulting any production policy.  The goal is to exercise the harness
    pipeline, not to validate accumulation semantics.
    """

    def __init__(
        self,
        backend: SlowStateBackend,
        *,
        runtime_id: str = _RUNTIME_ID,
    ) -> None:
        self._backend = backend
        self._runtime_id = runtime_id
        self._pending: list[_SyntheticRecord] = []
        self._accumulated: dict[str, AccumulatedSlowState] = {}
        self._flush_count = 0
        self._accepted_count = 0

    def accept(
        self,
        decision: HomeostasisDecision,
        *,
        target_scope: Scope | None = None,
    ) -> None:
        """Mirror production SlowPlasticityWriter.accept() signature and scope
        routing: ``scope = target_scope or candidate.scope``.  The target_scope
        is the orchestrator-derived AGENT slow scope; falling back to the
        candidate's own scope keeps the synthetic adapter semantics aligned.
        """
        if decision.decision.value != "slow_accept":
            return
        candidate = decision.candidate
        scope = target_scope if target_scope is not None else candidate.scope
        raw = candidate.target_dimension
        suffix = raw[len("agent.affect."):] if raw.startswith("agent.affect.") else raw
        slow_dim = f"{SLOW_DIMENSION_PREFIX}{suffix}"
        self._pending.append(
            _SyntheticRecord(
                slow_dimension=slow_dim,
                amount=candidate.proposed_value,
                scope=scope,
                evidence_refs=tuple(candidate.evidence_refs),
                accepted_at=decision.decided_at,
            )
        )
        self._accepted_count += 1

    def flush(self, scope: Scope) -> tuple[RuntimeState, ...]:
        # Scope-isolated flush (mirror production): only pending records
        # belonging to this scope are flushed.  Other scopes' pending stay
        # buffered for a later flush with their own scope.
        scoped_pending = [r for r in self._pending if r.scope == scope]
        by_dim: dict[str, list[_SyntheticRecord]] = {}
        for rec in scoped_pending:
            by_dim.setdefault(rec.slow_dimension, []).append(rec)

        new_states: list[RuntimeState] = []
        for slow_dim, recs in by_dim.items():
            current = self._accumulated.get(slow_dim)
            old_value = current.value if current else 0.0
            old_version = current.version if current else 0
            old_provenance: tuple[str, ...] = current.provenance if current else ()

            new_value = old_value + sum(r.amount for r in recs)
            new_value = max(0.0, min(1.0, new_value))
            new_version = old_version + 1
            new_provenance = old_provenance + tuple(
                ref for rec in recs for ref in rec.evidence_refs
            )
            last_at = max((r.accepted_at for r in recs), default=datetime.now(tz=UTC))

            self._accumulated[slow_dim] = AccumulatedSlowState(
                dimension=slow_dim,
                value=new_value,
                version=new_version,
                contribution_count=(current.contribution_count if current else 0) + len(recs),
                last_contribution_at=last_at,
                provenance=new_provenance,
                writer_version=SLOW_ADAPTER_VERSION,
            )

            new_state = make_slow_runtime_state(
                dimension=slow_dim,
                value=new_value,
                version=new_version,
                scope=scope,
                evidence_refs=new_provenance,
                origin_runtime_id=self._runtime_id,
                now=last_at,
                source_refs=("synthetic_slow_adapter",),
            )
            new_states.append(new_state)
            self._flush_count += 1

        for state in new_states:
            self._backend.save_state(state)

        # Scope-isolated clear: only drop records that were flushed for this
        # scope.  Other scopes' pending remain buffered.
        self._pending = [r for r in self._pending if r.scope != scope]
        return tuple(new_states)

    def load(self, scope: Scope | None = None) -> None:
        """Restore accumulated state from backend.  scope argument is accepted
        for compatibility with the SlowPlasticityWriter interface but is ignored
        because the adapter loads all slow states (not scope-scoped)."""
        all_states = self._backend.load_states()
        for state in all_states:
            if not state.dimension.startswith(SLOW_DIMENSION_PREFIX):
                continue
            current = self._accumulated.get(state.dimension)
            if current is None or state.version > current.version:
                self._accumulated[state.dimension] = AccumulatedSlowState(
                    dimension=state.dimension,
                    value=float(state.value),
                    version=state.version,
                    contribution_count=current.contribution_count if current else 0,
                    last_contribution_at=state.updated_at,
                    provenance=tuple(state.evidence_refs),
                    writer_version=SLOW_ADAPTER_VERSION,
                )

    def reset_to(self, values: Mapping[str, float]) -> tuple[RuntimeState, ...]:
        now = datetime.now(tz=UTC)
        # Infer a suitable agent scope from any existing accumulated state
        scope = self._infer_agent_scope()
        new_states: list[RuntimeState] = []
        for dim, baseline in values.items():
            current = self._accumulated.get(dim)
            old_version = current.version if current else 0
            old_provenance: tuple[str, ...] = current.provenance if current else ()
            new_version = old_version + 1

            self._accumulated[dim] = AccumulatedSlowState(
                dimension=dim,
                value=baseline,
                version=new_version,
                contribution_count=current.contribution_count if current else 0,
                last_contribution_at=now,
                provenance=old_provenance,
                writer_version=SLOW_ADAPTER_VERSION,
            )

            new_state = make_slow_runtime_state(
                dimension=dim,
                value=baseline,
                version=new_version,
                scope=scope,
                evidence_refs=old_provenance,
                origin_runtime_id=self._runtime_id,
                now=now,
                source_refs=("synthetic_slow_adapter_reset",),
            )
            new_states.append(new_state)

        for state in new_states:
            self._backend.save_state(state)
        return tuple(new_states)

    def _infer_agent_scope(self) -> Scope:
        """Try to recover a Scope from existing accumulated state via backend."""
        all_states = self._backend.load_states()
        for s in all_states:
            if s.dimension.startswith(SLOW_DIMENSION_PREFIX):
                return s.scope
        return Scope(
            domain=ScopeDomain.AGENT,
            agent_id="mr-alpha-as1",
            persona_id="mr-alpha-as1",
        )

    # ── Inspection ──────────────────────────────────────────────────────────
    @property
    def accumulated(self) -> dict[str, AccumulatedSlowState]:
        return dict(self._accumulated)

    @property
    def accepted_count(self) -> int:
        return self._accepted_count

    @property
    def flush_count(self) -> int:
        return self._flush_count

    @property
    def pending_count(self) -> int:
        return len(self._pending)