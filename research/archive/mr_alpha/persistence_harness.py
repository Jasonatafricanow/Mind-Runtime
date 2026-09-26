"""MR-ALPHA-AS1: Persistence Harness — AS-04.

Verifies that slow-state accumulated during a trajectory actually persists
through a real persistence boundary (destroy-and-reconstruct orchestrator).
This is required by ticket §4: results through the same in-memory object
must NOT be mistaken for persistence.
"""

from __future__ import annotations

import gc
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Mapping as MappingT, Sequence

from mind_runtime.contracts import RuntimeState, ScopeDomain
from mind_runtime.state.persistence import SqliteStateBackend

# Canonical slow-state prefix (agent.slow.* dimensions).  Re-declared locally
# since the production writer no longer exports this constant.
SLOW_DIMENSION_PREFIX = "agent.slow."

__all__ = [
    "PersistenceHarness",
    "StateSnapshot",
    "PersistenceBoundaryResult",
    "StateDomain_",
    "classify_dimension",
]

# ── Classification helpers ───────────────────────────────────────────────────


class StateDomain_(StrEnum):
    """Classifier for state dimensions by namespace prefix."""

    WORKING = "working"           # in-memory working/context residue
    PENDING = "pending"           # C9-W1B pending overlay
    FAST = "fast"                 # agent.affect.*
    SLOW = "slow"                 # agent.slow.*
    UNKNOWN = "unknown"


def classify_dimension(dimension: str) -> StateDomain_:
    """Map a state dimension name to its domain classifier.

    Working and pending keys are identified by orchestrator namespaces;
    the canonical slow dimension prefix is shared with the writer.
    """
    if dimension.startswith(SLOW_DIMENSION_PREFIX):
        return StateDomain_.SLOW
    if dimension.startswith("agent.affect."):
        return StateDomain_.FAST
    if dimension.startswith("pending."):
        return StateDomain_.PENDING
    if dimension.startswith("working."):
        return StateDomain_.WORKING
    return StateDomain_.UNKNOWN


# ── StateSnapshot ────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class StateSnapshot:
    """One canonical-state snapshot for the persistence boundary test.

    Working and pending keys are captured as orchestrator-side residue;
    fast and slow keys come from the StateBackend.
    """

    label: str
    taken_at: datetime

    working_keys: tuple[str, ...]
    pending_keys: tuple[str, ...]
    fast_states: tuple[tuple[str, float], ...]   # (dimension, value)
    slow_states: tuple[tuple[str, float], ...]   # (dimension, value)
    slow_provenance: tuple[str, ...]              # aggregated evidence_refs
    version_counts: MappingT[str, int]

    @classmethod
    def capture(
        cls,
        label: str,
        backend: SqliteStateBackend,
        *,
        working_keys: Sequence[str] = (),
        pending_keys: Sequence[str] = (),
        at: datetime,
    ) -> "StateSnapshot":
        all_states = backend.load_states()
        fast: list[tuple[str, float]] = []
        slow: list[tuple[str, float]] = []
        versions: dict[str, int] = {}
        provenance: list[str] = []
        for state in all_states:
            cls_ = classify_dimension(state.dimension)
            if cls_ is StateDomain_.FAST and isinstance(state.value, (int, float)):
                fast.append((state.dimension, float(state.value)))
            elif cls_ is StateDomain_.SLOW and isinstance(state.value, (int, float)):
                slow.append((state.dimension, float(state.value)))
                provenance.extend(state.evidence_refs)
            versions[state.dimension] = max(
                versions.get(state.dimension, 0), state.version
            )
        return cls(
            label=label,
            taken_at=at,
            working_keys=tuple(working_keys),
            pending_keys=tuple(pending_keys),
            fast_states=tuple(sorted(fast)),
            slow_states=tuple(sorted(slow)),
            slow_provenance=tuple(dict.fromkeys(provenance)),
            version_counts=versions,
        )

    @classmethod
    def from_pairs(
        cls,
        *,
        slow_states: Sequence[tuple[str, float]] = (),
        slow_provenance: Sequence[str] = (),
        label: str = "test",
        at: datetime,
    ) -> "StateSnapshot":
        """Convenience constructor for tests: build a snapshot from raw pairs."""
        return cls(
            label=label,
            taken_at=at,
            working_keys=(),
            pending_keys=(),
            fast_states=(),
            slow_states=tuple(slow_states),
            slow_provenance=tuple(slow_provenance),
            version_counts={},
        )


# ── PersistenceBoundaryResult ────────────────────────────────────────────────


@dataclass(frozen=True)
class PersistenceBoundaryResult:
    """Verdict of one persistence-boundary test."""

    state_existed_before_boundary: bool
    state_survived_boundary: bool
    state_identity_preserved: bool  # provenance lineage intact
    pending_leaked_into_canonical: bool
    unexpected_state_lost: bool
    pre_snapshot: StateSnapshot
    post_snapshot: StateSnapshot
    failure_boundary: str | None  # human-readable

    @property
    def PASS(self) -> bool:  # noqa: N802 — intentional uppercase
        return all(
            [
                self.state_existed_before_boundary,
                self.state_survived_boundary,
                self.state_identity_preserved,
                not self.pending_leaked_into_canonical,
                not self.unexpected_state_lost,
            ]
        )


# ── PersistenceHarness ───────────────────────────────────────────────────────


class PersistenceHarness:
    """Run the persistence-boundary test for one trajectory."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path

    def run(
        self,
        trajectory_executor,
        # Callable: takes a fresh backend, executes trajectory, returns nothing
        # The executor must call orchestrator.commit_turn() at the end
        snapshot_taken_at: datetime,
    ) -> PersistenceBoundaryResult:
        # Execute trajectory with fresh orchestrator on a fresh backend
        backend_a = SqliteStateBackend(self._db_path)
        trajectory_executor(backend_a)

        pre = StateSnapshot.capture(
            label="pre_boundary",
            backend=backend_a,
            at=snapshot_taken_at,
        )

        # ── DESTROY orchestrator and in-process state ────────────────────────
        backend_a.close()
        del backend_a
        gc.collect()

        # ── REOPEN: same DB path, new connection = new in-process backend ────
        backend_b = SqliteStateBackend(self._db_path)
        post = StateSnapshot.capture(
            label="post_boundary",
            backend=backend_b,
            at=snapshot_taken_at,
        )
        backend_b.close()

        # ── Evaluate ─────────────────────────────────────────────────────────
        state_existed_before = bool(pre.slow_states)
        state_survived = pre.slow_states == post.slow_states
        # Identity preserved = provenance set is a superset of pre's set
        pre_prov = set(pre.slow_provenance)
        post_prov = set(post.slow_provenance)
        state_identity_preserved = pre_prov <= post_prov

        # Pending leakage: if pre.pending_keys exists, post.slow_states must not
        # contain pending.* dimension names
        pending_leaked = any(
            classify_dimension(dim) is StateDomain_.PENDING
            for dim, _ in post.fast_states + post.slow_states
        ) and bool(pre.pending_keys)

        # Unexpected state lost: dimensions that existed pre but vanished post
        pre_dims = {dim for dim, _ in pre.slow_states + pre.fast_states}
        post_dims = {dim for dim, _ in post.slow_states + post.fast_states}
        unexpected_lost = bool(pre_dims - post_dims) and state_existed_before

        failure_boundary: str | None = None
        if not state_existed_before:
            failure_boundary = (
                "FAILURE: No slow-state existed before boundary; trajectory "
                "produced no slow writes (write-off may have been active)."
            )
        elif not state_survived:
            failure_boundary = (
                "FAILURE: Slow-state survived in orchestrator but vanished after "
                "the persistence boundary — durability contract violated."
            )
        elif not state_identity_preserved:
            failure_boundary = (
                "FAILURE: Slow-state provenance lineage not preserved through "
                "the boundary — evidence_refs dropped or reordered."
            )
        elif pending_leaked:
            failure_boundary = (
                "FAILURE: Pending overlay leaked into canonical slow dimensions."
            )
        elif unexpected_lost:
            failure_boundary = (
                "FAILURE: Unexpected state lost — slow-state versions regressed."
            )

        return PersistenceBoundaryResult(
            state_existed_before_boundary=state_existed_before,
            state_survived_boundary=state_survived,
            state_identity_preserved=state_identity_preserved,
            pending_leaked_into_canonical=pending_leaked,
            unexpected_state_lost=unexpected_lost,
            pre_snapshot=pre,
            post_snapshot=post,
            failure_boundary=failure_boundary,
        )