"""MR-RUNTIME-05: single-writer admission regression (converted R1 probes).

R1 (MR-RUNTIME-04-R1) probed and DOCUMENTED the broken pre-MR-05 reality:
two orchestrators on one namespace silently lost updates. This file now
asserts the CORRECTED behavior required by MR-RUNTIME-05:

  Probe 1 (identity level, unchanged fact): the binding manifest admits two
  full stacks over the same namespace with the same binding — but both
  stacks now share ONE process-local admission authority (identity ownership
  plus enforced single active admission sequence).

  Probe 2 (admission level, corrected): two orchestrators, same state DB,
  overlapping (B constructed before A commits, B admitted after A commits)
  now produce a legal serial execution: B's turn is based on A's committed
  canonical outcome (durable refresh at admission), both outcomes persist,
  nothing is silently lost, and memory equals a fresh reconstruction.

These are regression tests: if the silent-lost-update behavior returns, they
fail.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from mind_runtime.contracts import (
    Evidence,
    Interaction,
    InteractionStatus,
    Observation,
    SyncFields,
)
from mind_runtime.facts.ports import FactAdmissionDisposition, FactAdmissionResult
from mind_runtime.pipeline.orchestrator import TurnOrchestrator
from mind_runtime.pipeline.trace import TraceRecorder
from mind_runtime.runtime_admission import NamespaceAdmissionAuthority
from mind_runtime.shadow.runtime_loop import build_runtime_stack
from mind_runtime.state.ids import canonical_state_id
from mind_runtime.state.persistence import SqliteCommitMarkerStore, SqliteStateBackend
from tests.golden.fixtures.common import make_evidence, make_scope, make_state
from tests.support.fake_clock import FakeClock

NOW = datetime(2026, 9, 6, 12, 0, tzinfo=UTC)
DIM = "user.probe.signal"
# D4.5 anti-rollback: an intent older than the current state's
# last_observed_at is deferred, so every evidence timestamp in these probes
# must be strictly ordered: seed < A < (reconciler-stamped NOW) < B.
SEED_TIME = NOW - timedelta(hours=2)
A_TIME = NOW - timedelta(hours=1)
B_TIME = NOW + timedelta(hours=1)


class _TypedFactPort:
    """One dimension-typed observation per evidence (test_state_backend pattern)."""

    def __init__(self, *, value: object) -> None:
        self._value = value

    def admit(
        self,
        evidence: Evidence,
        *,
        interaction_id: str,
        writing_runtime: str,
        writing_persona_id: str | None,
    ) -> FactAdmissionResult:
        scope = evidence.scope
        observation_id = f"observation-{evidence.id}"
        observation = Observation(
            id=observation_id,
            interaction_id=interaction_id,
            scope=scope,
            origin_runtime_id=writing_runtime,
            type="factual",
            key="user.probe.signal.observed",
            value=self._value,
            confidence=1.0,
            observed_at=evidence.occurred_at,
            evidence_refs=(evidence.id,),
            sync=SyncFields(scope, writing_runtime, observation_id, 1, "idem"),
        )
        return FactAdmissionResult(observation, FactAdmissionDisposition.NEW)


def _interaction(interaction_id: str) -> Interaction:
    return Interaction(
        interaction_id=interaction_id,
        scope=make_scope(),
        channel="chat",
        session_id=f"session-{interaction_id}",
        turn_id=f"turn-{interaction_id}",
        started_at=NOW,
        committed_at=None,
        status=InteractionStatus.OPEN,
    )


def _orchestrator(
    state_db: Any,
    *,
    value: str,
    markers: Any,
    admission: NamespaceAdmissionAuthority | None = None,
) -> TurnOrchestrator:
    return TurnOrchestrator(
        clock=FakeClock(NOW),
        trace=TraceRecorder(),
        fact_ingest=_TypedFactPort(value=value),
        state_backend=SqliteStateBackend(state_db),
        commit_markers=markers,
        turn_admission=admission
        if admission is not None
        else NamespaceAdmissionAuthority.for_state_db(state_db),
    )


def _run_turn(
    orchestrator: TurnOrchestrator,
    interaction_id: str,
    text: str,
    *,
    occurred_at: datetime = NOW,
) -> None:
    orchestrator.begin_turn(_interaction(interaction_id))
    orchestrator.ingest(
        make_evidence(text=text, evidence_id=f"ev-{interaction_id}", occurred_at=occurred_at)
    )
    orchestrator.run()
    orchestrator.commit_turn()


def _current(orchestrator: TurnOrchestrator, dimension: str = DIM) -> Any:
    for state in orchestrator.canonical:
        if state.dimension == dimension:
            return state.value
    return None


def _durable_values(state_db: Any, dimension: str = DIM) -> dict[str, Any]:
    backend = SqliteStateBackend(state_db)
    try:
        return {
            s.state_id: s.value for s in backend.load_states() if s.dimension == dimension
        }
    finally:
        backend.close()


def _fingerprint(orchestrator: TurnOrchestrator) -> tuple[tuple[str, int], ...]:
    return tuple(sorted((s.state_id, s.version) for s in orchestrator.canonical))


def _seed(state_db: Any) -> None:
    backend = SqliteStateBackend(state_db)
    backend.save_state(
        make_state(
            dimension=DIM, value="seed", state_id=canonical_state_id(DIM, 1),
            now=SEED_TIME,
        )
    )
    backend.close()


# ---------------------------------------------------------------------------
# Probe 1 — identity ownership with a single shared admission authority
# ---------------------------------------------------------------------------


def test_probe_1_two_stacks_share_one_admission_authority(tmp_path: Any) -> None:
    from mind_runtime.runtime_binding import RuntimeBinding, RuntimeEnvironment, bind_storage

    binding = RuntimeBinding(
        persona_id="kayla_v0",
        agent_id="mr-lab",
        runtime_id="probe-runtime",
        storage_namespace="probe-shared",
        environment=RuntimeEnvironment.LAB,
    )
    paths_1 = bind_storage(binding, lab_root=tmp_path)
    paths_2 = bind_storage(binding, lab_root=tmp_path)
    assert paths_1.state_db == paths_2.state_db

    stack_a, _ = build_runtime_stack(
        clock=FakeClock(NOW),
        facts_db=paths_1.facts_db,
        state_db=paths_1.state_db,
        origin_runtime_id=binding.runtime_id,
        user_id="user",
    )
    stack_b, _ = build_runtime_stack(
        clock=FakeClock(NOW),
        facts_db=paths_2.facts_db,
        state_db=paths_2.state_db,
        origin_runtime_id=binding.runtime_id,
        user_id="user",
    )
    # Both stacks exist (identity ownership allows this) but they are enrolled
    # in the SAME process-local admission authority — they cannot become two
    # independent canonical writers.
    assert stack_a is not stack_b
    assert stack_a._turn_admission is stack_b._turn_admission
    stack_a._state_backend.close()
    stack_b._state_backend.close()


# ---------------------------------------------------------------------------
# Probe 2 — overlapping turns serialize; no silent loss; memory == durable
# ---------------------------------------------------------------------------


def test_probe_2_overlapping_turns_produce_legal_serialization(tmp_path: Any) -> None:
    state_db = tmp_path / "cognition_state.sqlite"
    state_db.parent.mkdir(parents=True, exist_ok=True)
    _seed(state_db)
    markers = SqliteCommitMarkerStore(state_db)

    # A and B construct from the same canonical S0 (both load version 1) —
    # exactly what two thread-local adapters over one namespace get.
    orch_a = _orchestrator(state_db, value="A", markers=markers)
    orch_b = _orchestrator(state_db, value="B", markers=markers)
    assert _current(orch_a) == "seed"
    assert _current(orch_b) == "seed"

    # A's complete turn (evidence newer than the seed, older than NOW).
    _run_turn(orch_a, "interaction-A", "A observed", occurred_at=A_TIME)
    assert _current(orch_a) == "A"

    # B's complete turn, admitted AFTER A committed. B's stale in-memory S0
    # must be refreshed at admission: B derives from A's committed outcome.
    _run_turn(orch_b, "interaction-B", "B observed", occurred_at=B_TIME)

    # Legal serialization serial(A, B): B's effective state is a NEW version
    # computed on top of A's — not a colliding duplicate of A's row.
    durable = _durable_values(state_db)
    versions = {
        int(state_id.rsplit(":", 1)[1]): value for state_id, value in durable.items()
    }
    a_version = max(v for v, val in versions.items() if val == "A")
    assert versions[a_version] == "A"
    # B's outcome must exist durably and strictly after A's — no silent loss.
    assert any(val == "B" for v, val in versions.items() if v > a_version)

    # No in-memory / DB divergence for the dimensions the turn affected
    # (MR-RUNTIME-05 §11). The stub plane (user.affect.stub) is excluded:
    # StubEmotionalTransition synthesizes a version-1 row per turn, so two
    # turns tie on (dimension, version) and a reconstruction keeps one — a
    # fixture artifact, not an admission-ordering property. The real
    # composition path derives projected versions from the refreshed
    # canonical base (base+1) and cannot tie under serialized admission.
    def _dim_view(orch: TurnOrchestrator) -> tuple[tuple[str, int, Any], ...]:
        return tuple(
            sorted(
                (s.state_id, s.version, s.value)
                for s in orch.canonical
                if s.dimension == DIM
            )
        )

    fresh = _orchestrator(state_db, value="ignored", markers=markers)
    assert _dim_view(orch_b) == _dim_view(fresh)

    # Both commit markers exist, and every user-plane projected state id they
    # reference is durably present (no false-positive markers).
    all_state_ids = {
        s.state_id for s in SqliteStateBackend(state_db).load_states()
    }
    marker_rows = list(
        markers._conn.execute(
            "SELECT interaction_id, projected_state_ids FROM commit_markers"
        )
    )
    assert {row[0] for row in marker_rows} >= {"interaction-A", "interaction-B"}
    for row in marker_rows:
        for state_id in str(row[1]).replace("[", " ").replace("]", " ").split(","):
            state_id = state_id.strip().strip('"').strip("'")
            if state_id.startswith("user."):
                assert state_id in all_state_ids, state_id

    orch_a._state_backend.close()
    orch_b._state_backend.close()
    fresh._state_backend.close()
    markers.close()
