"""MR-ASSEMBLY-B C10-B-W: SlowPlasticityWriter contract tests.

These tests verify the SlowPlasticityWriter against the ADR-0017 (ACCEPTED)
contract:

  Decision 1 — Window authority:  writer only
  Decision 2 — window_size is configuration-owned (>= 1, passed at ctor)
  Decision 3 — W_t(d) = last N SLOW_ACCEPT contributions (rolling window)
  Decision 4 — A_t(d) = sum(s_i * p_i) / sum(s_i)  (salience-weighted mean)
  Decision 5 — S_t(d) = A_t(d)  (overwrite; no prior-state blend)
  Decision 6 — Empty W_t(d) -> NO WRITE
  Decision 7 — Atomic: ledger + state in one transaction
  Decision 8 — Restart: load() rebuilds window from ledger

No learning_rate, no alpha, no multiplicative decay, no prior-state blend.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from mind_runtime.contracts import (
    Scope,
    ScopeDomain,
    SyncFields,
)
from mind_runtime.homeostasis.contracts import (
    CandidateStateDelta,
    HomeostasisDecision,
    HomeostasisDisposition,
)
from mind_runtime.slow_plasticity.writer import (
    SlowContributionRecord,
    SlowPlasticityWriter,
    SlowStateBackend,
)
from mind_runtime.state.persistence import SqliteStateBackend
from tests.support.fake_clock import FakeClock

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

AGENT_SCOPE = Scope(domain=ScopeDomain.AGENT, agent_id="bw-test", persona_id="bw-test")
NOW = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)
DIM = "agent.longitudinal.test-dim"


def make_decision(
    target_dimension: str,
    proposed_value: float,
    evidence_refs: tuple[str, ...] = (),
    decided_at: datetime | None = None,
    salience: float = 1.0,
    source_event_ref: str = "evt-bw-test",
) -> HomeostasisDecision:
    """Build a SLOW_ACCEPT HomeostasisDecision for testing.

    The candidate's salience defaults to 1.0; pass salience=0 to test the
    zero-salience qualifier path. The writer reads salience from the
    candidate, not from a separate argument.
    """
    return HomeostasisDecision(
        candidate=CandidateStateDelta(
            target_dimension=target_dimension,
            proposed_value=proposed_value,
            scope=AGENT_SCOPE,
            evidence_refs=evidence_refs,
            source_event_ref=source_event_ref,
            salience=salience,
            confidence=1.0,
            observed_at=decided_at or NOW,
        ),
        prior_value=None,
        decision=HomeostasisDisposition.SLOW_ACCEPT,
        reason_code="test-slow-accept",
        decided_at=decided_at or NOW,
    )


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock(NOW)


# ---------------------------------------------------------------------------
# Construction & validation
# ---------------------------------------------------------------------------

def test_rejects_window_size_zero(tmp_path: Path) -> None:
    backend = SqliteStateBackend(str(tmp_path / "w0.db"))
    with pytest.raises(ValueError, match="window_size must be >= 1"):
        SlowPlasticityWriter(backend=backend, runtime_id="r1", window_size=0)
    backend.close()


def test_rejects_window_size_negative(tmp_path: Path) -> None:
    backend = SqliteStateBackend(str(tmp_path / "wn.db"))
    with pytest.raises(ValueError, match="window_size must be >= 1"):
        SlowPlasticityWriter(backend=backend, runtime_id="r1", window_size=-1)
    backend.close()


def test_window_size_is_exposed(tmp_path: Path) -> None:
    backend = SqliteStateBackend(str(tmp_path / "expose.db"))
    writer = SlowPlasticityWriter(
        backend=backend, runtime_id="r1", window_size=5
    )
    assert writer.window_size == 5
    backend.close()


# ---------------------------------------------------------------------------
# Rolling window trim  (Decision 3)
# ---------------------------------------------------------------------------

def test_rolling_window_keeps_only_last_n(
    tmp_path: Path,
    clock: FakeClock,
) -> None:
    """N=3; 5 contributions -> only the last 3 survive in the ledger after
    flush (trim happens at flush time, keeping the latest window_size)."""
    backend = SqliteStateBackend(str(tmp_path / "rolling.db"))
    writer = SlowPlasticityWriter(
        backend=backend,
        runtime_id="r1",
        window_size=3,
        clock=clock,
    )

    for i in range(5):
        clock.advance(timedelta(minutes=1))
        writer.accept(make_decision(DIM, proposed_value=float(i)))

    writer.flush(AGENT_SCOPE)

    # After flush, the DB ledger has been trimmed to the latest N=3.
    ledger_rows = backend.load_slow_window(AGENT_SCOPE, DIM)
    assert len(ledger_rows) == 3, (
        f"expected 3 ledger rows after trim (window_size=3); got {len(ledger_rows)}"
    )
    # The kept rows are the latest 3 by accepted_at: 2, 3, 4.
    assert [r["proposed_value"] for r in ledger_rows] == [2.0, 3.0, 4.0]

    # Only one slow-state record exists (the latest flush).
    slow_states = backend.load_slow_states(AGENT_SCOPE, DIM)
    assert len(slow_states) == 1
    # A_t over the kept window = (2+3+4)/3 = 3.0
    assert slow_states[0].value == pytest.approx(3.0)

    backend.close()


# ---------------------------------------------------------------------------
# Salience-weighted mean  (Decision 4)
# ---------------------------------------------------------------------------

def test_at_mean_is_salience_weighted(
    tmp_path: Path,
    clock: FakeClock,
) -> None:
    """A_t = sum(s_i * p_i) / sum(s_i)."""
    backend = SqliteStateBackend(str(tmp_path / "mean.db"))
    writer = SlowPlasticityWriter(
        backend=backend,
        runtime_id="r1",
        window_size=5,
        clock=clock,
    )

    clock.advance(timedelta(minutes=1))
    # (p=0.2, s=0.5) and (p=0.9, s=0.7)
    # weighted sum = 0.2*0.5 + 0.9*0.7 = 0.10 + 0.63 = 0.73
    # salience sum = 0.5 + 0.7 = 1.2
    # A_t = 0.73 / 1.2 = 0.6083...
    writer.accept(make_decision(DIM, proposed_value=0.2, salience=0.5))
    clock.advance(timedelta(minutes=1))
    writer.accept(make_decision(DIM, proposed_value=0.9, salience=0.7))

    writer.flush(AGENT_SCOPE)

    persisted = backend.load_slow_states(AGENT_SCOPE, DIM)
    assert len(persisted) == 1
    expected = (0.2 * 0.5 + 0.9 * 0.7) / (0.5 + 0.7)
    assert persisted[0].value == pytest.approx(expected, rel=1e-9)

    backend.close()


def test_at_ignores_zero_salience_records(
    tmp_path: Path,
    clock: FakeClock,
) -> None:
    """salience=0 is excluded by the writer qualifier. The record is
    dropped from the pending batch and the ledger is empty."""
    backend = SqliteStateBackend(str(tmp_path / "zero_sal.db"))
    writer = SlowPlasticityWriter(
        backend=backend,
        runtime_id="r1",
        window_size=5,
        clock=clock,
    )

    clock.advance(timedelta(minutes=1))
    rec = writer.accept(make_decision(DIM, proposed_value=2.0, salience=0.0))
    assert rec is None, "writer must reject salience=0 (zero weight = drop)"

    clock.advance(timedelta(minutes=1))
    writer.accept(make_decision(DIM, proposed_value=8.0, salience=1.0))
    writer.flush(AGENT_SCOPE)

    # Only one slow-state record (the 8.0 contribution).
    persisted = backend.load_slow_states(AGENT_SCOPE, DIM)
    assert len(persisted) == 1
    assert persisted[0].value == pytest.approx(8.0)

    # Ledger has only one row.
    ledger = backend.load_slow_window(AGENT_SCOPE, DIM)
    assert len(ledger) == 1

    backend.close()


# ---------------------------------------------------------------------------
# Overwrite, no prior-state blend  (Decision 5)
# ---------------------------------------------------------------------------

def test_st_overwrites_not_blends(
    tmp_path: Path,
    clock: FakeClock,
) -> None:
    """S_t = A_t, not S_t-1 + alpha * (A_t - S_t-1)."""
    backend = SqliteStateBackend(str(tmp_path / "overwrite.db"))
    writer = SlowPlasticityWriter(
        backend=backend,
        runtime_id="r1",
        window_size=3,
        clock=clock,
    )

    # First flush: one contribution.
    clock.advance(timedelta(minutes=1))
    writer.accept(make_decision(DIM, proposed_value=10.0))
    writer.flush(AGENT_SCOPE)
    persisted_v1 = backend.load_slow_states(AGENT_SCOPE, DIM)
    assert len(persisted_v1) == 1
    assert persisted_v1[0].value == pytest.approx(10.0)
    assert persisted_v1[0].version == 1

    # Second flush: 3 contributions (values 5, 6, 7). Window is N=3, so
    # the previous 10.0 record drops out.
    clock.advance(timedelta(minutes=1))
    writer.accept(make_decision(DIM, proposed_value=5.0))
    clock.advance(timedelta(minutes=1))
    writer.accept(make_decision(DIM, proposed_value=6.0))
    clock.advance(timedelta(minutes=1))
    writer.accept(make_decision(DIM, proposed_value=7.0))
    writer.flush(AGENT_SCOPE)

    all_states = backend.load_slow_states(AGENT_SCOPE, DIM)
    # Both v1 and v2 exist in the DB.
    assert len(all_states) == 2
    # v1 = 10.0 (single contribution), v2 = (5+6+7)/3 = 6.0 (window of 3).
    by_version = {s.version: s for s in all_states}
    assert by_version[1].value == pytest.approx(10.0)
    # S_t for v2 is A_t (overwrite, not blend with v1). 6.0, not 9.6.
    assert by_version[2].value == pytest.approx(6.0)

    backend.close()


# ---------------------------------------------------------------------------
# Empty window -> no write  (Decision 6)
# ---------------------------------------------------------------------------

def test_empty_window_no_write(tmp_path: Path, clock: FakeClock) -> None:
    """flush() with no pending contributions for a dimension -> no DB write."""
    backend = SqliteStateBackend(str(tmp_path / "empty.db"))
    writer = SlowPlasticityWriter(
        backend=backend,
        runtime_id="r1",
        window_size=5,
        clock=clock,
    )

    writer.flush(AGENT_SCOPE)

    persisted = backend.load_slow_states(AGENT_SCOPE, DIM)
    assert len(persisted) == 0
    ledger = backend.load_slow_window(AGENT_SCOPE, DIM)
    assert len(ledger) == 0

    backend.close()


def test_zero_salience_is_rejected_by_accept(
    tmp_path: Path, clock: FakeClock
) -> None:
    """salience=0 records are rejected at ingest (writer qualifier); nothing
    is written to the ledger or slow-state."""
    backend = SqliteStateBackend(str(tmp_path / "zero_sal.db"))
    writer = SlowPlasticityWriter(
        backend=backend,
        runtime_id="r1",
        window_size=5,
        clock=clock,
    )

    clock.advance(timedelta(minutes=1))
    rec = writer.accept(make_decision(DIM, proposed_value=99.0, salience=0.0))
    assert rec is None, "salience=0 must be rejected at ingest"
    rec = writer.accept(make_decision(DIM, proposed_value=1.0, salience=0.0))
    assert rec is None, "salience=0 must be rejected at ingest"

    # Nothing pending; flush is a no-op.
    writer.flush(AGENT_SCOPE)

    persisted = backend.load_slow_states(AGENT_SCOPE, DIM)
    assert persisted == ()
    ledger = backend.load_slow_window(AGENT_SCOPE, DIM)
    assert ledger == ()

    backend.close()


# ---------------------------------------------------------------------------
# Atomic persistence  (Decision 7)
# ---------------------------------------------------------------------------

def test_flush_is_atomic(tmp_path: Path, clock: FakeClock) -> None:
    """flush() writes both ledger rows and slow-state record atomically."""
    backend = SqliteStateBackend(str(tmp_path / "atomic.db"))
    writer = SlowPlasticityWriter(
        backend=backend,
        runtime_id="r1",
        window_size=3,
        clock=clock,
    )

    clock.advance(timedelta(minutes=1))
    writer.accept(make_decision(DIM, proposed_value=3.0))
    clock.advance(timedelta(minutes=1))
    writer.accept(make_decision(DIM, proposed_value=5.0))
    writer.flush(AGENT_SCOPE)

    ledger = backend.load_slow_window(AGENT_SCOPE, DIM)
    assert len(ledger) == 2

    slow_states = backend.load_slow_states(AGENT_SCOPE, DIM)
    assert len(slow_states) == 1
    assert slow_states[0].value == pytest.approx(4.0)

    backend.close()


# ---------------------------------------------------------------------------
# Restart: load() rebuilds window from ledger  (Decision 8)
# ---------------------------------------------------------------------------

def test_load_rebuilds_window_from_ledger(
    tmp_path: Path,
    clock: FakeClock,
) -> None:
    """load(scope) reconstructs in-memory windows from the persisted ledger."""
    db_path = str(tmp_path / "restart.db")
    backend_a = SqliteStateBackend(db_path)

    # First session: write 4 contributions (N=3, keep last 3).
    writer_a = SlowPlasticityWriter(
        backend=backend_a,
        runtime_id="r1",
        window_size=3,
        clock=clock,
    )
    for i in range(4):
        clock.advance(timedelta(minutes=1))
        writer_a.accept(make_decision(DIM, proposed_value=float(i)))
    writer_a.flush(AGENT_SCOPE)
    backend_a.close()

    # Second session: fresh writer loads from ledger.
    backend_b = SqliteStateBackend(db_path)
    clock_b = FakeClock(NOW + timedelta(minutes=10))
    writer_b = SlowPlasticityWriter(
        backend=backend_b,
        runtime_id="r1",
        window_size=3,
        clock=clock_b,
    )
    writer_b.load(AGENT_SCOPE)

    # In-memory window should contain the last 3 contributions from ledger
    # (the trim kept the 3 latest in the DB).
    win = writer_b.current_window(AGENT_SCOPE, DIM)
    assert win is not None
    assert len(win.contributions) == 3
    assert [r.proposed_value for r in win.contributions] == [1.0, 2.0, 3.0]

    # A next accept should advance the rolling window.
    clock_b.advance(timedelta(minutes=1))
    writer_b.accept(make_decision(DIM, proposed_value=4.0))
    writer_b.flush(AGENT_SCOPE)

    # Ledger should now have the latest 3 rows.
    ledger = backend_b.load_slow_window(AGENT_SCOPE, DIM)
    assert len(ledger) == 3, (
        f"expected 3 ledger rows after second flush; got {len(ledger)}"
    )

    # Window: 2, 3, 4 (newest) -> mean = 3.0
    win_final = writer_b.current_window(AGENT_SCOPE, DIM)
    assert win_final is not None
    assert len(win_final.contributions) == 3
    assert [r.proposed_value for r in win_final.contributions] == [2.0, 3.0, 4.0]

    backend_b.close()


def test_load_empty_ledger_is_noop(
    tmp_path: Path,
    clock: FakeClock,
) -> None:
    """load() on a dimension with no ledger rows leaves the window absent."""
    backend = SqliteStateBackend(str(tmp_path / "load_empty.db"))
    writer = SlowPlasticityWriter(
        backend=backend,
        runtime_id="r1",
        window_size=3,
        clock=clock,
    )

    writer.load(AGENT_SCOPE)

    win = writer.current_window(AGENT_SCOPE, DIM)
    assert win is None

    backend.close()


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------

def test_distinct_dimensions_get_distinct_windows(
    tmp_path: Path,
    clock: FakeClock,
) -> None:
    """The same source_event_ref targeting two different dimensions produces
    two separate ledger rows and two separate slow-state records."""
    backend = SqliteStateBackend(str(tmp_path / "two_dim.db"))
    writer = SlowPlasticityWriter(
        backend=backend,
        runtime_id="r1",
        window_size=5,
        clock=clock,
    )

    dim2 = "agent.longitudinal.dim2"
    writer.accept(make_decision(DIM, proposed_value=1.0))
    writer.accept(make_decision(dim2, proposed_value=2.0))
    writer.flush(AGENT_SCOPE)

    ledger = backend.load_slow_window(AGENT_SCOPE, DIM)
    assert len(ledger) == 1
    ledger2 = backend.load_slow_window(AGENT_SCOPE, dim2)
    assert len(ledger2) == 1

    # Two slow-state records, one per dimension.
    states = backend.load_slow_states(AGENT_SCOPE, DIM)
    assert len(states) == 1
    assert states[0].value == pytest.approx(1.0)
    states2 = backend.load_slow_states(AGENT_SCOPE, dim2)
    assert len(states2) == 1
    assert states2[0].value == pytest.approx(2.0)

    backend.close()


# ---------------------------------------------------------------------------
# Runtime state field contract
# ---------------------------------------------------------------------------

def test_persisted_state_has_correct_origin_runtime_id(
    tmp_path: Path,
    clock: FakeClock,
) -> None:
    """The persisted RuntimeState's origin_runtime_id matches the writer's."""
    backend = SqliteStateBackend(str(tmp_path / "origin.db"))
    writer = SlowPlasticityWriter(
        backend=backend,
        runtime_id="my-runtime-id",
        window_size=3,
        clock=clock,
    )

    clock.advance(timedelta(minutes=1))
    writer.accept(make_decision(DIM, proposed_value=2.5))
    writer.flush(AGENT_SCOPE)

    persisted = backend.load_slow_states(AGENT_SCOPE, DIM)
    assert len(persisted) == 1
    assert persisted[0].origin_runtime_id == "my-runtime-id"

    backend.close()


def test_persisted_state_version_increments(
    tmp_path: Path,
    clock: FakeClock,
) -> None:
    """Each flush for a dimension increments the version counter."""
    backend = SqliteStateBackend(str(tmp_path / "versions.db"))
    writer = SlowPlasticityWriter(
        backend=backend,
        runtime_id="r1",
        window_size=3,
        clock=clock,
    )

    for i in range(3):
        clock.advance(timedelta(minutes=1))
        writer.accept(make_decision(DIM, proposed_value=float(i)))
        writer.flush(AGENT_SCOPE)

    persisted = backend.load_slow_states(AGENT_SCOPE, DIM)
    # Each flush writes a new RuntimeState with version N+1.
    assert len(persisted) == 3, (
        f"expected 3 state records (v1, v2, v3); got {[s.version for s in persisted]}"
    )
    assert [s.version for s in persisted] == [1, 2, 3]

    backend.close()


def test_source_decision_id_is_unique_per_accept(
    tmp_path: Path,
    clock: FakeClock,
) -> None:
    """Each accept generates a unique source_decision_id."""
    backend = SqliteStateBackend(str(tmp_path / "unique_id.db"))
    writer = SlowPlasticityWriter(
        backend=backend,
        runtime_id="r1",
        window_size=5,
        clock=clock,
    )

    for i in range(5):
        clock.advance(timedelta(minutes=1))
        writer.accept(make_decision(DIM, proposed_value=float(i)))

    writer.flush(AGENT_SCOPE)
    ledger = backend.load_slow_window(AGENT_SCOPE, DIM)
    ledger_ids = {row["source_decision_id"] for row in ledger}
    assert len(ledger_ids) == 5, (
        f"expected 5 unique source_decision_id values; got {ledger_ids}"
    )
    # All ids should follow the expected pattern.
    for sid in ledger_ids:
        assert sid.startswith("slow-r1-"), f"unexpected id format: {sid}"

    backend.close()


# ---------------------------------------------------------------------------
# Evidence aggregation
# ---------------------------------------------------------------------------

def test_evidence_refs_are_aggregated_across_window(
    tmp_path: Path,
    clock: FakeClock,
) -> None:
    """The persisted state's evidence_refs are the union of all evidence_refs
    across the kept window."""
    backend = SqliteStateBackend(str(tmp_path / "evidence.db"))
    writer = SlowPlasticityWriter(
        backend=backend,
        runtime_id="r1",
        window_size=2,
        clock=clock,
    )

    clock.advance(timedelta(minutes=1))
    writer.accept(
        make_decision(DIM, proposed_value=1.0, evidence_refs=("ev-a", "ev-b"))
    )
    clock.advance(timedelta(minutes=1))
    writer.accept(
        make_decision(DIM, proposed_value=3.0, evidence_refs=("ev-b", "ev-c"))
    )
    writer.flush(AGENT_SCOPE)

    persisted = backend.load_slow_states(AGENT_SCOPE, DIM)
    assert len(persisted) == 1
    assert set(persisted[0].evidence_refs) == {"ev-a", "ev-b", "ev-c"}

    backend.close()
