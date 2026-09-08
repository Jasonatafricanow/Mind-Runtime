"""MR-C10-BW-R: Final production patch — explicit acceptance tests.

Ticket: C10-BW-R (FINAL PRODUCTION PATCH).

Each test corresponds to one of the BW-R1..BW-R20 acceptance items in the
ticket. Together with tests/mr_assembly_b/test_c10_bw_slow_writer.py these
cover all required behaviors. They are NOT new design — they are explicit
invariants over the existing canonical writer, configuration decoder, and
persistence backend that the ticket demands to be re-verified.

Forbidden surface (must remain absent):
  - learning_rate / alpha / LR  (any multiplicative constant other than salience)
  - prior-state blend (S_{t-1} read in the writer)
  - writer-side clamp (input contract only)
  - recency decay / EMA / time decay
  - empty-window → 0 (empty window = no write)

ADR-0017 (ACCEPTED) is the authority; this test file never overrides it.
"""

from __future__ import annotations

import inspect
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from mind_runtime.contracts import (
    RuntimeState,
    Scope,
    ScopeDomain,
    StateDefinition,
    SyncFields,
)
from mind_runtime.homeostasis.contracts import (
    CandidateStateDelta,
    HomeostasisDecision,
    HomeostasisDisposition,
)
from mind_runtime.slow_plasticity.writer import (
    SlowPlasticityWriter,
)
from mind_runtime.state.persistence import SqliteStateBackend
from mind_runtime.validation.composition import (
    _EXPECTED_TABLES,
)
from mind_runtime.validation.contracts import (
    SlowPlasticityConfig,
    _slow_plasticity,
)
from tests.support.fake_clock import FakeClock


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

AGENT_SCOPE_A = Scope(domain=ScopeDomain.AGENT, agent_id="bw-r-A", persona_id="bw-r-A")
AGENT_SCOPE_B = Scope(domain=ScopeDomain.AGENT, agent_id="bw-r-B", persona_id="bw-r-B")
USER_SCOPE = Scope(domain=ScopeDomain.USER, user_id="bw-r-user")
NOW = datetime(2026, 11, 1, 9, 0, tzinfo=UTC)
DIM = "agent.longitudinal.r-dim"
DIM_USER = "user.longitudinal.r-dim"


def make_decision(
    target_dimension: str,
    proposed_value: float,
    *,
    scope: Scope = AGENT_SCOPE_A,
    salience: float = 1.0,
    evidence_refs: tuple[str, ...] = (),
    decided_at: datetime | None = None,
    source_event_ref: str = "evt-bw-r",
    disposition: HomeostasisDisposition = HomeostasisDisposition.SLOW_ACCEPT,
) -> HomeostasisDecision:
    return HomeostasisDecision(
        candidate=CandidateStateDelta(
            target_dimension=target_dimension,
            proposed_value=proposed_value,
            scope=scope,
            evidence_refs=evidence_refs,
            source_event_ref=source_event_ref,
            salience=salience,
            confidence=1.0,
            observed_at=decided_at or NOW,
        ),
        prior_value=None,
        decision=disposition,
        reason_code="test-bw-r",
        decided_at=decided_at or NOW,
    )


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock(NOW)


# ---------------------------------------------------------------------------
# BW-R1 / BW-R2: production config injects window_size=8; missing fails
# ---------------------------------------------------------------------------


def _decode_slow(payload: dict) -> SlowPlasticityConfig:
    """Exercise the canonical `slow_plasticity` decoder directly."""
    return _slow_plasticity(payload)


def test_bw_r1_production_config_injects_window_size_eight() -> None:
    """BW-R1: production config decoder exposes window_size=8.

    The canonical payload is exercised here; the full closed manifest
    decoder is exercised by the existing d11s pipeline tests.
    """
    cfg = _decode_slow({"window_size": 8})
    assert cfg.window_size == 8
    # And the runtime config file currently carries 8 (production value).
    from pathlib import Path
    import json as _json
    rc_path = (
        Path(__file__).resolve().parents[2]
        / "certification/d11s/inputs/runtime-config.json"
    )
    rc = _json.loads(rc_path.read_text(encoding="utf-8"))
    slow = next(
        c for c in rc["components"] if c["component_id"] == "slow_plasticity"
    )
    assert slow["payload"]["window_size"] == 8
    # And the canonical hash for that payload matches the production value.
    assert slow["payload_sha256"] == (
        "3ab05b19f5786ecfcab15c7a40da8840fdf205f62f56850770fe1bca4228d748"
    )


def test_bw_r2_missing_window_size_fails_composition() -> None:
    """BW-R2: missing window_size must fail composition (decoder rejects)."""
    with pytest.raises((KeyError, ValueError)):
        _decode_slow({})


# ---------------------------------------------------------------------------
# BW-R3: window_size <= 0 fails validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad_value", [0, -1, -8])
def test_bw_r3_window_size_non_positive_fails_validation(
    bad_value: int,
) -> None:
    """BW-R3: window_size <= 0 must fail decoder validation."""
    with pytest.raises(ValueError):
        _decode_slow({"window_size": bad_value})


def test_bw_r3_invalid_type_fails_validation() -> None:
    """BW-R3 (extra): non-int window_size also fails."""
    for bad in (0.5, "8", None, True, [8]):
        with pytest.raises((TypeError, ValueError)):
            _decode_slow({"window_size": bad})


# ---------------------------------------------------------------------------
# BW-R4 / BW-R5: writer forbids learning_rate and prior-state blend
# ---------------------------------------------------------------------------


def test_bw_r4_writer_does_not_contain_or_use_learning_rate() -> None:
    """BW-R4: writer module has no learning_rate / alpha / LR symbol in source."""
    src = inspect.getsource(SlowPlasticityWriter)
    forbidden = (
        "learning_rate",
        "DEFAULT_LEARNING_RATE",
        "alpha",
        "lr",
    )
    for needle in forbidden:
        assert needle not in src, (
            f"writer must not reference {needle!r}; ADR-0017 forbids it"
        )


def test_bw_r5_writer_does_not_perform_additive_prior_state_update(
    tmp_path: Path, clock: FakeClock
) -> None:
    """BW-R5: writer never reads S_{t-1} into the new state value.

    ADR-0017 Step B: S_t(d) = A_t(d) (overwrite). Verify the new
    RuntimeState equals the weighted mean of the kept window, not the
    weighted mean blended with the prior state value.
    """
    backend = SqliteStateBackend(str(tmp_path / "bw_r5.db"))
    writer = SlowPlasticityWriter(
        backend=backend, runtime_id="r", window_size=3, clock=clock
    )

    clock.advance(timedelta(minutes=1))
    writer.accept(make_decision(DIM, proposed_value=10.0))
    writer.flush(AGENT_SCOPE_A)

    clock.advance(timedelta(minutes=1))
    writer.accept(make_decision(DIM, proposed_value=5.0))
    clock.advance(timedelta(minutes=1))
    writer.accept(make_decision(DIM, proposed_value=6.0))
    clock.advance(timedelta(minutes=1))
    writer.accept(make_decision(DIM, proposed_value=7.0))
    writer.flush(AGENT_SCOPE_A)

    states = backend.load_slow_states(AGENT_SCOPE_A, DIM)
    by_version = {s.version: s for s in states}
    # v2 must be the salience-weighted mean of the kept window (5,6,7) = 6.0
    # NOT 6.0 blended with v1's 10.0 (which would be ~8.5 or so depending on alpha).
    assert by_version[2].value == pytest.approx(6.0)
    backend.close()


# ---------------------------------------------------------------------------
# BW-R6: single qualifying contribution -> S = proposed_value
# ---------------------------------------------------------------------------


def test_bw_r6_single_qualifying_contribution_equals_proposed_value(
    tmp_path: Path, clock: FakeClock
) -> None:
    """BW-R6: weighted mean of one element = the element itself."""
    backend = SqliteStateBackend(str(tmp_path / "bw_r6.db"))
    writer = SlowPlasticityWriter(
        backend=backend, runtime_id="r", window_size=8, clock=clock
    )

    clock.advance(timedelta(minutes=1))
    writer.accept(make_decision(DIM, proposed_value=0.42, salience=0.7))
    writer.flush(AGENT_SCOPE_A)

    states = backend.load_slow_states(AGENT_SCOPE_A, DIM)
    assert len(states) == 1
    assert states[0].value == pytest.approx(0.42)
    backend.close()


# ---------------------------------------------------------------------------
# BW-R7: multiple contributions -> salience-weighted mean
# ---------------------------------------------------------------------------


def test_bw_r7_multiple_contributions_salience_weighted_mean(
    tmp_path: Path, clock: FakeClock
) -> None:
    """BW-R7: A_t = Σ(s_i * p_i) / Σ(s_i) over the window."""
    backend = SqliteStateBackend(str(tmp_path / "bw_r7.db"))
    writer = SlowPlasticityWriter(
        backend=backend, runtime_id="r", window_size=8, clock=clock
    )

    clock.advance(timedelta(minutes=1))
    writer.accept(make_decision(DIM, proposed_value=0.2, salience=0.5))
    clock.advance(timedelta(minutes=1))
    writer.accept(make_decision(DIM, proposed_value=0.9, salience=0.7))
    clock.advance(timedelta(minutes=1))
    writer.accept(make_decision(DIM, proposed_value=0.4, salience=0.3))
    writer.flush(AGENT_SCOPE_A)

    states = backend.load_slow_states(AGENT_SCOPE_A, DIM)
    expected = (0.2 * 0.5 + 0.9 * 0.7 + 0.4 * 0.3) / (0.5 + 0.7 + 0.3)
    assert states[-1].value == pytest.approx(expected, rel=1e-9)
    backend.close()


# ---------------------------------------------------------------------------
# BW-R8: more than N -> only latest N qualify
# ---------------------------------------------------------------------------


def test_bw_r8_more_than_n_keeps_only_latest_n(
    tmp_path: Path, clock: FakeClock
) -> None:
    """BW-R8: window_size=8; 10 contributions -> ledger has exactly 8 rows."""
    backend = SqliteStateBackend(str(tmp_path / "bw_r8.db"))
    writer = SlowPlasticityWriter(
        backend=backend, runtime_id="r", window_size=8, clock=clock
    )

    for i in range(10):
        clock.advance(timedelta(minutes=1))
        writer.accept(make_decision(DIM, proposed_value=float(i)))

    writer.flush(AGENT_SCOPE_A)

    ledger = backend.load_slow_window(AGENT_SCOPE_A, DIM)
    assert len(ledger) == 8
    # The latest 8 of [0..9] are [2..9].
    assert [r["proposed_value"] for r in ledger] == [2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0]
    backend.close()


# ---------------------------------------------------------------------------
# BW-R9: SLOW_REJECT does not enter ledger
# ---------------------------------------------------------------------------


def test_bw_r9_slow_reject_does_not_enter_ledger(
    tmp_path: Path, clock: FakeClock
) -> None:
    """BW-R9: non-SLOW_ACCEPT decisions are dropped at the writer qualifier."""
    backend = SqliteStateBackend(str(tmp_path / "bw_r9.db"))
    writer = SlowPlasticityWriter(
        backend=backend, runtime_id="r", window_size=8, clock=clock
    )

    for disp in (
        HomeostasisDisposition.SLOW_DAMP,
        HomeostasisDisposition.FAST_APPLY,
        HomeostasisDisposition.FAST_ONLY,
        HomeostasisDisposition.REJECT,
    ):
        clock.advance(timedelta(minutes=1))
        rec = writer.accept(make_decision(DIM, proposed_value=1.0, disposition=disp))
        assert rec is None, f"writer must drop non-SLOW_ACCEPT: {disp}"

    writer.flush(AGENT_SCOPE_A)
    assert backend.load_slow_window(AGENT_SCOPE_A, DIM) == ()
    assert backend.load_slow_states(AGENT_SCOPE_A, DIM) == ()
    backend.close()


# ---------------------------------------------------------------------------
# BW-R10: salience=None does not enter ledger
# ---------------------------------------------------------------------------


def test_bw_r10_salience_none_does_not_enter_ledger(
    tmp_path: Path, clock: FakeClock
) -> None:
    """BW-R10: salience=None is rejected at writer ingest."""
    backend = SqliteStateBackend(str(tmp_path / "bw_r10.db"))
    writer = SlowPlasticityWriter(
        backend=backend, runtime_id="r", window_size=8, clock=clock
    )

    clock.advance(timedelta(minutes=1))
    rec = writer.accept(
        make_decision(DIM, proposed_value=0.5, salience=None)  # type: ignore[arg-type]
    )
    assert rec is None

    writer.flush(AGENT_SCOPE_A)
    assert backend.load_slow_window(AGENT_SCOPE_A, DIM) == ()
    backend.close()


# ---------------------------------------------------------------------------
# BW-R11: salience=0 does not enter ledger (duplicate of existing test)
# ---------------------------------------------------------------------------


def test_bw_r11_salience_zero_does_not_enter_ledger(
    tmp_path: Path, clock: FakeClock
) -> None:
    """BW-R11: salience=0 is rejected at writer ingest."""
    backend = SqliteStateBackend(str(tmp_path / "bw_r11.db"))
    writer = SlowPlasticityWriter(
        backend=backend, runtime_id="r", window_size=8, clock=clock
    )

    clock.advance(timedelta(minutes=1))
    rec = writer.accept(make_decision(DIM, proposed_value=2.0, salience=0.0))
    assert rec is None
    writer.flush(AGENT_SCOPE_A)
    assert backend.load_slow_window(AGENT_SCOPE_A, DIM) == ()
    backend.close()


# ---------------------------------------------------------------------------
# BW-R12: empty qualifying window causes no write
# ---------------------------------------------------------------------------


def test_bw_r12_empty_qualifying_window_no_write(
    tmp_path: Path, clock: FakeClock
) -> None:
    """BW-R12: no qualifying contributions -> no state row, no ledger row."""
    backend = SqliteStateBackend(str(tmp_path / "bw_r12.db"))
    writer = SlowPlasticityWriter(
        backend=backend, runtime_id="r", window_size=8, clock=clock
    )

    writer.flush(AGENT_SCOPE_A)
    assert backend.load_slow_states(AGENT_SCOPE_A, DIM) == ()
    assert backend.load_slow_window(AGENT_SCOPE_A, DIM) == ()
    backend.close()


# ---------------------------------------------------------------------------
# BW-R13: window and RuntimeState commit atomically
# ---------------------------------------------------------------------------


def test_bw_r13_window_and_state_commit_atomically(
    tmp_path: Path, clock: FakeClock
) -> None:
    """BW-R13: ledger rows and RuntimeState appear together (or not at all).

    We exercise the production `commit_slow_window_update` directly to
    observe the single-transaction guarantee. After commit, ledger size
    and state count must be coherent: 3 ledger rows, 1 state row.
    """
    backend = SqliteStateBackend(str(tmp_path / "bw_r13.db"))
    scope = AGENT_SCOPE_A
    clock.advance(timedelta(minutes=1))
    now = clock.now()
    state = RuntimeState(
        state_id=f"{DIM}:1:atomic",
        scope=scope,
        dimension=DIM,
        value=4.0,
        status="active",
        valid_from=now,
        valid_until=None,
        relevant_until=None,
        last_observed_at=now,
        evidence_refs=(),
        transition_refs=(),
        updated_at=now,
        origin_runtime_id="r",
        version=1,
        sync=SyncFields(scope, "r", f"{DIM}:1:atomic", 1, "idem"),
    )
    rows = (
        {"sequence": 1, "accepted_at": now, "proposed_value": 3.0,
         "salience": 1.0, "evidence_refs": (), "source_event_ref": None,
         "source_decision_id": "slow-r-1"},
        {"sequence": 2, "accepted_at": now, "proposed_value": 5.0,
         "salience": 1.0, "evidence_refs": (), "source_event_ref": None,
         "source_decision_id": "slow-r-2"},
        {"sequence": 3, "accepted_at": now, "proposed_value": 4.0,
         "salience": 1.0, "evidence_refs": (), "source_event_ref": None,
         "source_decision_id": "slow-r-3"},
    )
    ok = backend.commit_slow_window_update(
        state=state, new_rows=rows, trim_keys=(scope, DIM), window_size=8
    )
    assert ok is True
    assert len(backend.load_slow_window(scope, DIM)) == 3
    assert len(backend.load_slow_states(scope, DIM)) == 1
    backend.close()


# ---------------------------------------------------------------------------
# BW-R14: rollback/error does not leave one changed without the other
# ---------------------------------------------------------------------------


def test_bw_r14_integrity_error_rolls_back_window_and_state_atomically(
    tmp_path: Path, clock: FakeClock
) -> None:
    """BW-R14: a duplicate UNIQUE (sequence) conflict must not leave a half-state.

    We pre-seed a row with sequence=1 for the (scope, dim), then attempt
    an atomic commit that re-inserts the same sequence. The whole
    transaction must be rejected (no partial state row, no partial ledger).
    """
    backend = SqliteStateBackend(str(tmp_path / "bw_r14.db"))
    scope = AGENT_SCOPE_A
    clock.advance(timedelta(minutes=1))
    now = clock.now()

    # Pre-seed one ledger row at sequence=1.
    backend.commit_slow_window_update(
        state=RuntimeState(
            state_id=f"{DIM}:1:seed",
            scope=scope,
            dimension=DIM,
            value=1.0,
            status="active",
            valid_from=now,
            valid_until=None,
            relevant_until=None,
            last_observed_at=now,
            evidence_refs=(),
            transition_refs=(),
            updated_at=now,
            origin_runtime_id="r",
            version=1,
            sync=SyncFields(scope, "r", f"{DIM}:1:seed", 1, "idem-seed"),
        ),
        new_rows=(
            {"sequence": 1, "accepted_at": now, "proposed_value": 1.0,
             "salience": 1.0, "evidence_refs": (), "source_event_ref": None,
             "source_decision_id": "slow-r-seed"},
        ),
        trim_keys=(scope, DIM),
        window_size=8,
    )
    pre_ledger = backend.load_slow_window(scope, DIM)
    pre_states = backend.load_slow_states(scope, DIM)
    assert len(pre_ledger) == 1 and len(pre_states) == 1

    # Now attempt a second commit that collides on sequence=1.
    # The transaction should fail; both tables must remain unchanged.
    duplicate = RuntimeState(
        state_id=f"{DIM}:2:collision",
        scope=scope,
        dimension=DIM,
        value=2.0,
        status="active",
        valid_from=now,
        valid_until=None,
        relevant_until=None,
        last_observed_at=now,
        evidence_refs=(),
        transition_refs=(),
        updated_at=now,
        origin_runtime_id="r",
        version=2,
        sync=SyncFields(scope, "r", f"{DIM}:2:collision", 2, "idem-collision"),
    )
    duplicate_rows = (
        {"sequence": 1, "accepted_at": now, "proposed_value": 99.0,
         "salience": 1.0, "evidence_refs": (), "source_event_ref": None,
         "source_decision_id": "slow-r-collide"},
    )
    ok = backend.commit_slow_window_update(
        state=duplicate, new_rows=duplicate_rows, trim_keys=(scope, DIM), window_size=8
    )
    # The duplicate-key path returns False (IntegrityError caught).
    # No half-write should be observed.
    assert ok is False
    post_ledger = backend.load_slow_window(scope, DIM)
    post_states = backend.load_slow_states(scope, DIM)
    assert len(post_ledger) == 1
    assert len(post_states) == 1
    # The original row's proposed_value is intact (not overwritten with 99.0).
    assert post_ledger[0]["proposed_value"] == 1.0
    assert post_states[0].value == pytest.approx(1.0)
    backend.close()


# ---------------------------------------------------------------------------
# BW-R15 / BW-R16: restart reloads exact latest-N window; restart+next ==
# continuous execution
# ---------------------------------------------------------------------------


def test_bw_r15_restart_reloads_exact_latest_n_window(
    tmp_path: Path, clock: FakeClock
) -> None:
    """BW-R15: post-restart load() rebuilds W_t(d) verbatim from the ledger."""
    db_path = str(tmp_path / "bw_r15.db")
    backend_a = SqliteStateBackend(db_path)

    writer_a = SlowPlasticityWriter(
        backend=backend_a, runtime_id="r", window_size=8, clock=clock
    )
    for i in range(10):
        clock.advance(timedelta(minutes=1))
        writer_a.accept(make_decision(DIM, proposed_value=float(i)))
    writer_a.flush(AGENT_SCOPE_A)
    backend_a.close()

    backend_b = SqliteStateBackend(db_path)
    writer_b = SlowPlasticityWriter(
        backend=backend_b, runtime_id="r", window_size=8,
        clock=FakeClock(NOW + timedelta(hours=1)),
    )
    writer_b.load(AGENT_SCOPE_A)

    win = writer_b.current_window(AGENT_SCOPE_A, DIM)
    assert win is not None
    # 10 contributions, N=8, kept = 2..9.
    assert [r.proposed_value for r in win.contributions] == [
        2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0,
    ]
    backend_b.close()


def test_bw_r16_restart_then_next_equals_continuous_execution(
    tmp_path: Path, clock: FakeClock
) -> None:
    """BW-R16: process A processes 1..11 in one session.
    Process B processes 1..10, restarts, then processes 11.
    Both end states must be identical.
    """
    db_path = str(tmp_path / "bw_r16.db")

    # ----- Continuous execution (process A) -----
    backend_a = SqliteStateBackend(db_path)
    writer_a = SlowPlasticityWriter(
        backend=backend_a, runtime_id="r", window_size=8, clock=clock
    )
    for i in range(1, 12):  # 1..11 inclusive
        clock.advance(timedelta(minutes=1))
        writer_a.accept(
            make_decision(DIM, proposed_value=float(i) / 10.0, salience=1.0)
        )
    writer_a.flush(AGENT_SCOPE_A)
    continuous_state = backend_a.load_slow_states(AGENT_SCOPE_A, DIM)[-1]
    continuous_ledger = backend_a.load_slow_window(AGENT_SCOPE_A, DIM)
    backend_a.close()

    # ----- Restart at 10; then contribution 11 (process B) -----
    # Use the SAME DB so the ledger persists across the restart.
    backend_pre = SqliteStateBackend(db_path)
    writer_pre = SlowPlasticityWriter(
        backend=backend_pre, runtime_id="r", window_size=8, clock=clock
    )
    for i in range(1, 11):  # 1..10
        clock.advance(timedelta(minutes=1))
        writer_pre.accept(
            make_decision(DIM, proposed_value=float(i) / 10.0, salience=1.0)
        )
    writer_pre.flush(AGENT_SCOPE_A)
    backend_pre.close()

    # Re-open the DB in a "fresh process" (the restart simulation).
    backend_b = SqliteStateBackend(db_path)
    writer_b = SlowPlasticityWriter(
        backend=backend_b, runtime_id="r", window_size=8,
        clock=FakeClock(NOW + timedelta(hours=2)),
    )
    writer_b.load(AGENT_SCOPE_A)

    clock.advance(timedelta(minutes=1))
    writer_b.accept(
        make_decision(DIM, proposed_value=11.0 / 10.0, salience=1.0)
    )
    writer_b.flush(AGENT_SCOPE_A)
    restarted_state = backend_b.load_slow_states(AGENT_SCOPE_A, DIM)[-1]
    restarted_ledger = backend_b.load_slow_window(AGENT_SCOPE_A, DIM)
    backend_b.close()

    # Identical window membership/order:
    # 11 contributions; N=8; both processes should retain the latest 8
    # (i.e. contributions 4..11).
    expected_window = [4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0, 11.0]
    assert [r["proposed_value"] for r in continuous_ledger] == [
        v / 10.0 for v in expected_window
    ]
    assert [r["proposed_value"] for r in restarted_ledger] == [
        v / 10.0 for v in expected_window
    ]
    # And the final state value matches between continuous and restart runs.
    assert continuous_state.value == pytest.approx(restarted_state.value)
    # Final aggregate = sum(4..11)/8 / 10.0 = 7.5 / 10 = 0.75.
    assert continuous_state.value == pytest.approx(0.75)


# ---------------------------------------------------------------------------
# BW-R17: scope A and scope B windows remain isolated
# ---------------------------------------------------------------------------


def test_bw_r17_scope_isolation(
    tmp_path: Path, clock: FakeClock
) -> None:
    """BW-R17: two scopes do not see each other's windows or state values."""
    backend = SqliteStateBackend(str(tmp_path / "bw_r17.db"))
    writer = SlowPlasticityWriter(
        backend=backend, runtime_id="r", window_size=8, clock=clock
    )

    clock.advance(timedelta(minutes=1))
    writer.accept(make_decision(DIM, proposed_value=0.3, scope=AGENT_SCOPE_A))
    clock.advance(timedelta(minutes=1))
    writer.accept(make_decision(DIM, proposed_value=0.9, scope=AGENT_SCOPE_B))
    clock.advance(timedelta(minutes=1))
    writer.accept(make_decision(DIM_USER, proposed_value=0.5, scope=USER_SCOPE))
    writer.flush(AGENT_SCOPE_A)
    writer.flush(AGENT_SCOPE_B)
    writer.flush(USER_SCOPE)

    a_ledger = backend.load_slow_window(AGENT_SCOPE_A, DIM)
    b_ledger = backend.load_slow_window(AGENT_SCOPE_B, DIM)
    u_ledger = backend.load_slow_window(USER_SCOPE, DIM_USER)
    assert len(a_ledger) == 1 and a_ledger[0]["proposed_value"] == 0.3
    assert len(b_ledger) == 1 and b_ledger[0]["proposed_value"] == 0.9
    assert len(u_ledger) == 1 and u_ledger[0]["proposed_value"] == 0.5
    backend.close()


# ---------------------------------------------------------------------------
# BW-R18: dimension A and dimension B windows remain isolated
# (covered by existing test_distinct_dimensions_get_distinct_windows;
#  duplicated here for the explicit R18 ticket item)
# ---------------------------------------------------------------------------


def test_bw_r18_dimension_isolation(
    tmp_path: Path, clock: FakeClock
) -> None:
    """BW-R18: two dimensions do not share ledger or state rows."""
    backend = SqliteStateBackend(str(tmp_path / "bw_r18.db"))
    writer = SlowPlasticityWriter(
        backend=backend, runtime_id="r", window_size=8, clock=clock
    )
    dim1 = "agent.longitudinal.dim-A"
    dim2 = "agent.longitudinal.dim-B"

    clock.advance(timedelta(minutes=1))
    writer.accept(make_decision(dim1, proposed_value=0.2))
    writer.accept(make_decision(dim2, proposed_value=0.8))
    writer.flush(AGENT_SCOPE_A)

    a_ledger = backend.load_slow_window(AGENT_SCOPE_A, dim1)
    b_ledger = backend.load_slow_window(AGENT_SCOPE_A, dim2)
    assert len(a_ledger) == 1 and len(b_ledger) == 1
    assert a_ledger[0]["proposed_value"] == 0.2
    assert b_ledger[0]["proposed_value"] == 0.8
    backend.close()


# ---------------------------------------------------------------------------
# BW-R19: canonical 0.0 proposed_value remains valid (not clamped, not dropped)
# ---------------------------------------------------------------------------


def test_bw_r19_zero_proposed_value_persists_unchanged(
    tmp_path: Path, clock: FakeClock
) -> None:
    """BW-R19: a valid 0.0 proposed_value is accepted and persisted as-is."""
    backend = SqliteStateBackend(str(tmp_path / "bw_r19.db"))
    writer = SlowPlasticityWriter(
        backend=backend, runtime_id="r", window_size=8, clock=clock
    )

    clock.advance(timedelta(minutes=1))
    rec = writer.accept(make_decision(DIM, proposed_value=0.0, salience=1.0))
    assert rec is not None
    writer.flush(AGENT_SCOPE_A)

    states = backend.load_slow_states(AGENT_SCOPE_A, DIM)
    assert len(states) == 1
    assert states[0].value == pytest.approx(0.0)
    backend.close()


# ---------------------------------------------------------------------------
# BW-R20: D11S exact state schema inventory passes with fourth table
# ---------------------------------------------------------------------------


def test_bw_r20_d11s_state_inventory_includes_slow_window_table(
    tmp_path: Path,
) -> None:
    """BW-R20: state plane now has exactly the four-table set + sqlite_sequence.

    Required: {slow_contribution_window, sqlite_sequence, state_definitions,
    state_transitions, states}.
    """
    backend = SqliteStateBackend(str(tmp_path / "bw_r20.db"))
    actual = backend.table_names()
    expected = _EXPECTED_TABLES["state"]
    assert actual == expected
    assert "slow_contribution_window" in expected
    backend.close()


def test_bw_r20_d11s_inventory_membership_exact() -> None:
    """BW-R20: the inventory list itself is exactly the 4-table set."""
    state_tables = _EXPECTED_TABLES["state"]
    assert state_tables == (
        "slow_contribution_window",
        "sqlite_sequence",
        "state_definitions",
        "state_transitions",
        "states",
    )


# ---------------------------------------------------------------------------
# Additional invariants called out by §4 / §5 (regression guardrails)
# ---------------------------------------------------------------------------


def test_bw_r_no_separate_slow_plasticity_db(tmp_path: Path) -> None:
    """The rolling window lives in the state DB — no separate slow_window.db.

    `SqliteStateBackend` opens one file. The `slow_contribution_window`
    table is created from the same `_SCHEMA` script as `states` and
    `state_transitions`.
    """
    backend = SqliteStateBackend(str(tmp_path / "bw_r_one.db"))
    tables = backend.table_names()
    assert "slow_contribution_window" in tables
    assert "states" in tables
    # The backend is a single connection / single file.
    assert backend._path == str(tmp_path / "bw_r_one.db")  # noqa: SLF001
    backend.close()


def test_bw_r_window_size_is_not_stored_in_state_definition() -> None:
    """window_size is config-owned, not StateDefinition-owned.

    `StateDefinition` does not carry a `window_size` field; the value
    flows through `runtime_config -> SlowPlasticityConfig -> writer`.
    """
    fields = {f for f in StateDefinition.__dataclass_fields__}
    assert "window_size" not in fields
    assert "dynamics_policy" in fields


def test_bw_r_value_validation_upstream_is_not_writer_clamped(
    tmp_path: Path, clock: FakeClock
) -> None:
    """Writer does not min/max clamp proposed_value.

    A value outside [0,1] is preserved verbatim if upstream supplies it
    (the writer trusts the input contract; bounds are a runtime-config
    concern, not a writer concern).
    """
    backend = SqliteStateBackend(str(tmp_path / "bw_r_clamp.db"))
    writer = SlowPlasticityWriter(
        backend=backend, runtime_id="r", window_size=8, clock=clock
    )

    clock.advance(timedelta(minutes=1))
    writer.accept(make_decision(DIM, proposed_value=1.5, salience=1.0))
    writer.flush(AGENT_SCOPE_A)

    states = backend.load_slow_states(AGENT_SCOPE_A, DIM)
    assert states[0].value == pytest.approx(1.5), (
        "writer must not clamp; ADR-0017 forbids writer-side clamp"
    )
    backend.close()
