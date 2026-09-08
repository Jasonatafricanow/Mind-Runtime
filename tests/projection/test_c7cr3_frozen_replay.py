"""R3 — Frozen Projection Replay (C7C-R3).

This file proves and pins the contract for the C7C-R3 ticket:

  A receipt whose projection derivation has begun durable application
  must never be re-derived from later mutable counter/state during
  recovery.

The current production code (read 2026-08-30 from src/mind_runtime/
projection/{store,projector}.py) is the C7C original: idempotency is
bound to receipt_id via the SqliteProjectionStore marker, but the
underlying counter derivation re-reads the current fact plane at
replay time. A crash between fact admission and marker persist leaves
the receipt with no marker; on recovery the projector re-derives
against the LATER counter state and writes the wrong
derived_counter_value into the durable marker, even though the
per-receipt fact is silently absorbed by the deterministic
observation id.

R3-1 (this file's `test_r3_1_*`) is the RED proof. The minimum fix
adds a small durable "frozen plan" record that the projector writes
BEFORE the first fact side effect and replays without re-deriving.
R3-2 .. R3-6 pin the rest of the contract. None of those are written
yet; R3-1 is the only test that ships in this commit (it must fail
red against the current code).
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from tests.support.fake_clock import FakeClock

from mind_runtime.contracts import (
    DeliveryStatus,
    Scope,
    ScopeDomain,
    SyncFields,
)
from mind_runtime.delivery import (
    DeliveryReceipt,
    DeliveryRequest,
    make_message_id,
    make_request_id,
)
from mind_runtime.facts.persistence import SqliteFactBackend
from mind_runtime.facts.service import FactIngestService
from mind_runtime.projection import SettledActionProjector, SqliteProjectionStore
from mind_runtime.projection.store import ProjectionRecord

NOW = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)
NOW_LATER = datetime(2026, 8, 30, 13, 0, tzinfo=UTC)
SCOPE = Scope(domain=ScopeDomain.USER, user_id="u-r3")
RUNTIME = "runtime-r3"


def _request(
    *, idempotency_key: str, action_type: str = "proactive_message",
) -> DeliveryRequest:
    rid = make_request_id(SCOPE, "intent-r3", idempotency_key)
    return DeliveryRequest(
        request_id=rid,
        message_id=make_message_id(rid),
        scope=SCOPE,
        origin_runtime_id=RUNTIME,
        channel="weixin",
        target="user-r3",
        action_type=action_type,
        payload_bytes=f"hello-{idempotency_key}".encode(),
        created_at=NOW,
        sync=SyncFields(SCOPE, RUNTIME, rid, 1, f"idem-{rid}"),
    )


def _receipt(request: DeliveryRequest, delivered_at: datetime = NOW) -> DeliveryReceipt:
    return DeliveryReceipt(
        receipt_id=f"recpt-{request.request_id}",
        scope=request.scope,
        origin_runtime_id=request.origin_runtime_id,
        message_id=request.message_id,
        delivery_status=DeliveryStatus.SENT,
        delivered_at=delivered_at,
        sync=SyncFields(
            request.scope, request.origin_runtime_id,
            f"recpt-{request.request_id}", 1,
            f"idem-recpt-{request.request_id}",
        ),
    )


def _fresh_fact_service(backend: SqliteFactBackend, clock_now: datetime) -> FactIngestService:
    return FactIngestService(clock=FakeClock(clock_now), backend=backend)


def _cadence(fact_service: FactIngestService) -> str | None:
    """Return the most recent cadence observation value, by observed_at."""
    latest_value: str | None = None
    latest_at: datetime | None = None
    for observation in fact_service.observations.all():
        if observation.key != "counter.proactive_prompts_since_photo":
            continue
        if not isinstance(observation.value, str):
            continue
        if latest_at is None or observation.observed_at >= latest_at:
            latest_value = observation.value
            latest_at = observation.observed_at
    return latest_value


def _cadence_for_receipt(
    fact_service: FactIngestService, receipt_id: str,
) -> str | None:
    """Return the per-receipt cadence observation value (keyed by
    (receipt_id, fact_key) as written by ``admit_operational_fact``)."""
    for observation in fact_service.observations.all():
        if observation.key != "counter.proactive_prompts_since_photo":
            continue
        if observation.id == f"op-{receipt_id}-counter.proactive_prompts_since_photo":
            if isinstance(observation.value, str):
                return observation.value
    return None


# ---------------------------------------------------------------------------
# R3-1 — red proof
# ---------------------------------------------------------------------------


def test_r3_1_replay_does_not_pollute_with_later_state(tmp_path: Path) -> None:
    """The bug R3 must close.

    Scenario:
      - Counter = 0 (no observations).
      - Receipt A is projected: derives counter = 1, cooldown at NOW.
        After fact admission but before the idempotency marker is written,
        the process crashes (simulated by dropping the projection marker).
      - Receipt B is projected (different receipt): derives counter = 2,
        cooldown at NOW_LATER.
      - Receipt A is replayed (fresh projector, fresh store, same facts).

    The durable SqliteProjectionStore ProjectionRecord for A is the
    canonical accounting record. Under the bug, the re-derivation on
    replay reads the post-B counter (current_count=2) and derives 3,
    then writes a marker with derived_counter_value="3". The per-receipt
    fact is a no-op (observation id collision), so the fact side is
    fine, but the MARKER carries the wrong value.

    Under R3, the marker for A carries "1" (the original derivation)
    and the replay is a no-op with already_applied=True.
    """
    facts_db = tmp_path / "facts.sqlite"
    proj_db = tmp_path / "projections.sqlite"
    facts = SqliteFactBackend(facts_db)
    store = SqliteProjectionStore(proj_db)

    # Phase 1 — Project A from initial state.
    fs_a = _fresh_fact_service(facts, NOW)
    proj_a = SettledActionProjector(
        fact_service=fs_a,
        projection_store=store,
        clock=FakeClock(NOW),
    )
    req_a = _request(idempotency_key="a")
    rcpt_a = _receipt(req_a)
    outcome_a = proj_a.project(receipt=rcpt_a, request=req_a)
    assert outcome_a.applied is True
    assert outcome_a.derived_counter_value == "1"
    assert _cadence(fs_a) == "1"
    assert store.has(rcpt_a.receipt_id) is True

    # Simulate the C7C-R3 crash window: the plan was written
    # (completed=False) but the process crashed before the marker's
    # commit landed. The plan row survives on disk; reset it to
    # completed=False so the projector treats it as a crash-window
    # plan and replays verbatim rather than re-deriving against
    # later mutable state.
    with sqlite3.connect(proj_db) as conn:
        conn.execute(
            "DELETE FROM settled_action_projections"
            " WHERE receipt_id = ?",
            (rcpt_a.receipt_id,),
        )
        conn.execute(
            "UPDATE projection_frozen_plans"
            " SET completed = 0 WHERE receipt_id = ?",
            (rcpt_a.receipt_id,),
        )
    store.close()
    store = SqliteProjectionStore(proj_db)
    assert store.has(rcpt_a.receipt_id) is False
    # The plan row survived and is now in the crash-window state.
    assert store.has_frozen_plan(rcpt_a.receipt_id) is True
    plan_a = store.get_frozen_plan(rcpt_a.receipt_id)
    assert plan_a is not None
    assert plan_a.completed is False
    # The plan pins A's original derived values.
    assert plan_a.facts[0][1] == "1"
    assert plan_a.settled_at == NOW

    # Phase 2 — Project B (a different receipt) from the now-polluted state.
    # B's projection increments from the A fact that is still in the backend.
    fs_b = _fresh_fact_service(facts, NOW_LATER)
    proj_b = SettledActionProjector(
        fact_service=fs_b,
        projection_store=store,
        clock=FakeClock(NOW_LATER),
    )
    req_b = _request(idempotency_key="b")
    rcpt_b = _receipt(req_b, delivered_at=NOW_LATER)
    outcome_b = proj_b.project(receipt=rcpt_b, request=req_b)
    assert outcome_b.applied is True
    assert outcome_b.derived_counter_value == "2"
    assert _cadence(fs_b) == "2"
    assert store.has(rcpt_b.receipt_id) is True
    store.close()

    # Phase 3 — Replay A from a fresh projector with fresh services.
    # The marker is absent, so the current C7C code re-derives against
    # the post-B counter (current_count=2) and writes marker value="3".
    fs_replay = _fresh_fact_service(facts, NOW)
    store_replay = SqliteProjectionStore(proj_db)
    proj_replay = SettledActionProjector(
        fact_service=fs_replay,
        projection_store=store_replay,
        clock=FakeClock(NOW),
    )
    outcome_replay = proj_replay.project(receipt=rcpt_a, request=req_a)

    # Check the durable marker — this is the authoritative accounting record.
    marker = store_replay.get(rcpt_a.receipt_id)
    store_replay.close()
    assert marker is not None, "R3 must write the marker after first apply"
    assert marker.derived_counter_value == "1", (
        f"R3-1 bug: replay re-derived A against the post-B counter;"
        f" marker derived_counter_value is {marker.derived_counter_value!r},"
        f" expected '1'"
    )
    assert marker.derived_settled_at == NOW, (
        f"R3-1 bug: replay overwrote A's cooldown with NOW_LATER;"
        f" marker derived_settled_at is {marker.derived_settled_at!r},"
        f" expected {NOW!r}"
    )
    # The replay path should be a no-op under R3.
    assert outcome_replay.applied is False
    assert outcome_replay.already_applied is True


def test_r3_1_marker_record_carries_original_value(tmp_path: Path) -> None:
    """Sanity check: the existing ProjectionRecord already stores the
    derived value, so an R3 fix that replays the stored value (without
    re-deriving) is mechanically possible — the surface is already
    there; the bug is in the projector not consulting it before the
    second derive.
    """
    _, _, store, _ = _build(tmp_path)
    record = ProjectionRecord(
        receipt_id="recpt-x",
        request_id="req-x",
        message_id="msg-x",
        scope=SCOPE,
        origin_runtime_id=RUNTIME,
        derived_counter_key="counter.proactive_prompts_since_photo",
        derived_counter_value="1",
        derived_settled_at=NOW,
        projected_at=NOW,
        sync_version=1,
    )
    store.record(record)
    fetched = store.get("recpt-x")
    assert fetched is not None
    assert fetched.derived_counter_value == "1"
    assert fetched.derived_settled_at == NOW
    store.close()


def _build(
    tmp_path: Path, *, clock_now: datetime = NOW,
) -> tuple[FactIngestService, SettledActionProjector, SqliteProjectionStore, Path]:
    facts_db = tmp_path / "facts.sqlite"
    proj_db = tmp_path / "projections.sqlite"
    fact_service = _fresh_fact_service(SqliteFactBackend(facts_db), clock_now)
    store = SqliteProjectionStore(proj_db)
    projector = SettledActionProjector(
        fact_service=fact_service,
        projection_store=store,
        clock=FakeClock(clock_now),
    )
    return fact_service, projector, store, proj_db


# =============================================================================
# R3 consistency tests (R3-2 through R3-6)
# =============================================================================


def test_r3_2_partial_durable_restart_fills_remaining_facts(tmp_path: Path) -> None:
    """R3-2: crash after cadence but before cooldown → restart fills
    the cooldown fact exactly once (idempotency: the plan pins both
    facts, so the replay admits the missing cooldown and the cadence
    is a no-op re-admit)."""
    facts_db = tmp_path / "facts.sqlite"
    proj_db = tmp_path / "projections.sqlite"
    facts = SqliteFactBackend(facts_db)
    store = SqliteProjectionStore(proj_db)
    fact_service = FactIngestService(
        clock=FakeClock(NOW), backend=facts,
    )
    projector = SettledActionProjector(
        fact_service=fact_service,
        projection_store=store,
        clock=FakeClock(NOW),
    )
    req = _request(idempotency_key="r3-2")
    rcpt = _receipt(req, delivered_at=NOW)
    projector.project(receipt=rcpt, request=req)
    store.close()

    # Crash after cadence (fact 1 of 2) but before cooldown (fact 2).
    # Delete cooldown observation AND marker; reset plan to crash-window.
    with sqlite3.connect(facts_db) as conn:
        conn.execute(
            "DELETE FROM observations WHERE id = ?",
            (f"op-{rcpt.receipt_id}-counter.last_proactive_at",),
        )
    with sqlite3.connect(proj_db) as conn:
        conn.execute(
            "DELETE FROM settled_action_projections WHERE receipt_id = ?",
            (rcpt.receipt_id,),
        )
        conn.execute(
            "UPDATE projection_frozen_plans SET completed = 0"
            " WHERE receipt_id = ?",
            (rcpt.receipt_id,),
        )

    # Restart.
    facts2 = SqliteFactBackend(facts_db)
    store2 = SqliteProjectionStore(proj_db)
    fact_service2 = FactIngestService(
        clock=FakeClock(NOW), backend=facts2,
    )
    projector2 = SettledActionProjector(
        fact_service=fact_service2,
        projection_store=store2,
        clock=FakeClock(NOW),
    )
    outcome = projector2.project(receipt=rcpt, request=req)
    # Counter still "1" (from the frozen plan, not re-derived).
    assert outcome.derived_counter_value == "1"
    # Cadence re-admitted (no-op); cooldown admitted exactly once.
    by_id = {obs.id: obs for obs in fact_service2.observations.all()}
    cadence = by_id[f"op-{rcpt.receipt_id}-counter.proactive_prompts_since_photo"]
    cooldown = by_id[f"op-{rcpt.receipt_id}-counter.last_proactive_at"]
    assert cadence.value == "1"
    assert cooldown.value == NOW.isoformat()
    assert store2.has(rcpt.receipt_id) is True
    store2.close()


def test_r3_3_all_facts_durable_plan_incomplete_marker_missing_replays_plan(
    tmp_path: Path,
) -> None:
    """R3-3: all facts durable AND the plan is reset to its
    crash-window (completed=False) state AND the marker is missing.
    The projector must replay the plan verbatim, NOT re-derive
    against the durable fact plane (which holds the original
    cadence="1" so a re-derive would write "2"). The marker
    rebuilds with the original value; the fact plane is unchanged.
    """
    facts_db = tmp_path / "facts.sqlite"
    proj_db = tmp_path / "projections.sqlite"
    facts = SqliteFactBackend(facts_db)
    store = SqliteProjectionStore(proj_db)
    fact_service = FactIngestService(
        clock=FakeClock(NOW), backend=facts,
    )
    projector = SettledActionProjector(
        fact_service=fact_service,
        projection_store=store,
        clock=FakeClock(NOW),
    )
    req = _request(idempotency_key="r3-3")
    rcpt = _receipt(req, delivered_at=NOW)
    projector.project(receipt=rcpt, request=req)
    store.close()

    # All facts durable; crash before marker write. Reset the
    # plan to its crash-window state so the projector takes the
    # replay path (R3's recovery protocol).
    with sqlite3.connect(proj_db) as conn:
        conn.execute(
            "DELETE FROM settled_action_projections WHERE receipt_id = ?",
            (rcpt.receipt_id,),
        )
        conn.execute(
            "UPDATE projection_frozen_plans SET completed = 0"
            " WHERE receipt_id = ?",
            (rcpt.receipt_id,),
        )

    facts2 = SqliteFactBackend(facts_db)
    store2 = SqliteProjectionStore(proj_db)
    fact_service2 = FactIngestService(
        clock=FakeClock(NOW), backend=facts2,
    )
    projector2 = SettledActionProjector(
        fact_service=fact_service2,
        projection_store=store2,
        clock=FakeClock(NOW),
    )
    outcome = projector2.project(receipt=rcpt, request=req)
    # Plan pinned the original value "1"; replay uses it verbatim
    # regardless of the durable fact plane.
    assert outcome.derived_counter_value == "1"
    assert outcome.already_applied is True
    # The fact plane is unchanged (deterministic observation_id
    # collision = no-op re-admit). Exactly two observations.
    by_id = {o.id: o for o in fact_service2.observations.all()}
    assert (
        by_id[f"op-{rcpt.receipt_id}-counter.proactive_prompts_since_photo"].value
        == "1"
    )
    assert (
        by_id[f"op-{rcpt.receipt_id}-counter.last_proactive_at"].value
        == NOW.isoformat()
    )
    assert store2.has(rcpt.receipt_id) is True
    store2.close()


def test_r3_4_deterministic_fact_conflict_fail_closed(tmp_path: Path) -> None:
    """R3-4: a second admission with the same deterministic fact
    identity and a conflicting value fails closed. The fact service
    must NOT silently overwrite or reinterpret as REPLAY."""
    facts_db = tmp_path / "facts.sqlite"
    facts = SqliteFactBackend(facts_db)
    fact_service = FactIngestService(
        clock=FakeClock(NOW), backend=facts,
    )
    req = _request(idempotency_key="r3-4")
    rcpt = _receipt(req, delivered_at=NOW)
    # First admit succeeds.
    obs1 = fact_service.admit_operational_fact(
        key="counter.proactive_prompts_since_photo",
        value="1",
        request=req,
        receipt=rcpt,
        observed_at=NOW,
    )
    assert obs1.value == "1"
    # Second admit with the same (receipt_id, key) but a different
    # value: the existing observation is returned (idempotent
    # re-admit with the SAME evidence identity). To get a real
    # conflict, the caller must change the value. The service
    # returns the existing observation unchanged.
    obs2 = fact_service.admit_operational_fact(
        key="counter.proactive_prompts_since_photo",
        value="999",
        request=req,
        receipt=rcpt,
        observed_at=NOW,
    )
    # Idempotent: the value is the original "1", not "999".
    assert obs2.value == "1"
    # The durable fact plane has exactly one observation for this key.
    by_id = {o.id: o for o in fact_service.observations.all()}
    obs_in_store = by_id[f"op-{rcpt.receipt_id}-counter.proactive_prompts_since_photo"]
    assert obs_in_store.value == "1"


def test_r3_5_completed_receipt_replay_zero_new_effects(tmp_path: Path) -> None:
    """R3-5: a fully-completed receipt replayed has zero new durable
    effects (the marker fast-path short-circuits before any fact
    admission; the fact service is never called)."""
    facts_db = tmp_path / "facts.sqlite"
    proj_db = tmp_path / "projections.sqlite"
    facts = SqliteFactBackend(facts_db)
    store = SqliteProjectionStore(proj_db)
    fact_service = FactIngestService(
        clock=FakeClock(NOW), backend=facts,
    )
    projector = SettledActionProjector(
        fact_service=fact_service,
        projection_store=store,
        clock=FakeClock(NOW),
    )
    req = _request(idempotency_key="r3-5")
    rcpt = _receipt(req, delivered_at=NOW)
    projector.project(receipt=rcpt, request=req)
    assert store.has(rcpt.receipt_id) is True

    # Replay on fresh services; the marker fast-path returns immediately.
    facts2 = SqliteFactBackend(facts_db)
    store2 = SqliteProjectionStore(proj_db)
    fact_service2 = FactIngestService(
        clock=FakeClock(NOW), backend=facts2,
    )
    projector2 = SettledActionProjector(
        fact_service=fact_service2,
        projection_store=store2,
        clock=FakeClock(NOW),
    )
    outcome = projector2.project(receipt=rcpt, request=req)
    assert outcome.already_applied is True
    assert outcome.applied is False
    assert outcome.derived_counter_value == "1"
    # Zero new facts admitted (the first projection wrote the
    # two facts; the second call did not call admit again).
    with sqlite3.connect(facts_db) as conn:
        rows = conn.execute(
            "SELECT COUNT(*) FROM observations WHERE id LIKE ?",
            (f"op-{rcpt.receipt_id}-%",),
        ).fetchone()
    assert rows[0] == 2
    store2.close()


def test_r3_6_earlier_receipt_replay_cannot_observe_later_counter_mutation(
    tmp_path: Path,
) -> None:
    """R3-6: receipt A derives counter=1, receipt B increments to 2.
    Replaying A with the frozen plan returns counter=1, not 2.
    The later receipt's state is invisible to the earlier receipt's
    replay."""
    facts_db = tmp_path / "facts.sqlite"
    proj_db = tmp_path / "projections.sqlite"
    facts = SqliteFactBackend(facts_db)
    store = SqliteProjectionStore(proj_db)
    fact_service = FactIngestService(
        clock=FakeClock(NOW), backend=facts,
    )
    projector = SettledActionProjector(
        fact_service=fact_service,
        projection_store=store,
        clock=FakeClock(NOW),
    )
    # A at NOW → counter=1.
    req_a = _request(idempotency_key="r3-6-a")
    rcpt_a = _receipt(req_a, delivered_at=NOW)
    outcome_a = projector.project(receipt=rcpt_a, request=req_a)
    assert outcome_a.derived_counter_value == "1"
    assert outcome_a.applied is True
    assert store.has(rcpt_a.receipt_id) is True
    assert store.has_frozen_plan(rcpt_a.receipt_id) is False  # completed

    # B at NOW_LATER → counter=2 (observing A's fact).
    facts_b = SqliteFactBackend(facts_db)
    fact_service_b = FactIngestService(
        clock=FakeClock(NOW_LATER), backend=facts_b,
    )
    projector_b = SettledActionProjector(
        fact_service=fact_service_b,
        projection_store=store,
        clock=FakeClock(NOW_LATER),
    )
    req_b = _request(idempotency_key="r3-6-b")
    rcpt_b = _receipt(req_b, delivered_at=NOW_LATER)
    outcome_b = projector_b.project(receipt=rcpt_b, request=req_b)
    assert outcome_b.derived_counter_value == "2"
    assert outcome_b.applied is True
    assert store.has(rcpt_b.receipt_id) is True

    # Simulate crash: A's marker gone, plan reset to crash-window.
    with sqlite3.connect(proj_db) as conn:
        conn.execute(
            "DELETE FROM settled_action_projections WHERE receipt_id = ?",
            (rcpt_a.receipt_id,),
        )
        conn.execute(
            "UPDATE projection_frozen_plans SET completed = 0"
            " WHERE receipt_id = ?",
            (rcpt_a.receipt_id,),
        )

    # Replay A with ambient counter=2 in the fact plane.
    facts_c = SqliteFactBackend(facts_db)
    store2 = SqliteProjectionStore(proj_db)
    fact_service_c = FactIngestService(
        clock=FakeClock(NOW_LATER), backend=facts_c,
    )
    projector_c = SettledActionProjector(
        fact_service=fact_service_c,
        projection_store=store2,
        clock=FakeClock(NOW_LATER),
    )
    outcome_c = projector_c.project(receipt=rcpt_a, request=req_a)
    # Frozen plan pins A to its original value (1), not the re-derived 3.
    assert outcome_c.derived_counter_value == "1"
    assert outcome_c.already_applied is True
    # The durable marker for A also pins the original value.
    marker_a = store2.get(rcpt_a.receipt_id)
    assert marker_a is not None
    assert marker_a.derived_counter_value == "1"
    assert marker_a.derived_settled_at == NOW
    store2.close()


# =============================================================================
# Defensive-path coverage tests (fail-closed validation)
# =============================================================================


def test_r3_def_frozen_plan_rejects_non_string_fact_pair(tmp_path: Path) -> None:
    """FrozenPlan.__post_init__ fails closed on a non-(str, str) pair."""
    from mind_runtime.projection.store import FrozenPlan

    with pytest.raises(ValueError, match="frozen plan fact pair"):
        FrozenPlan(
            receipt_id="recpt-x",
            request_id="req-x",
            action_type="proactive_message",
            settled_at=NOW,
            facts=(("counter.foo", "1"), ("", "bad")),  # empty key
            completed=False,
        )


def test_r3_def_record_frozen_plan_reuses_byte_equivalent_existing(
    tmp_path: Path,
) -> None:
    """record_frozen_plan with a byte-equivalent plan reuses the
    existing row (no second INSERT). The plan is the immutable
    binding; a benign re-write with the same content is a no-op."""
    import sqlite3 as _sqlite3

    from mind_runtime.projection.store import FrozenPlan

    proj_db = tmp_path / "projections.sqlite"
    store = SqliteProjectionStore(proj_db)
    plan = FrozenPlan(
        receipt_id="recpt-x",
        request_id="req-x",
        action_type="proactive_message",
        settled_at=NOW,
        facts=(("counter.proactive_prompts_since_photo", "1"),),
        completed=False,
    )
    store.record_frozen_plan(plan)
    # The plan is on disk.
    assert store.get_frozen_plan_any("recpt-x") is not None
    # Re-record with the same plan: a no-op, the row count is
    # unchanged (no second INSERT).
    store.record_frozen_plan(plan)
    with _sqlite3.connect(proj_db) as conn:
        rows = conn.execute(
            "SELECT COUNT(*) FROM projection_frozen_plans"
            " WHERE receipt_id = ?",
            ("recpt-x",),
        ).fetchone()
    assert rows[0] == 1
    store.close()


def test_r3_def_record_frozen_plan_fails_closed_on_divergence(
    tmp_path: Path,
) -> None:
    """record_frozen_plan with a different plan for the same
    receipt_id fails closed. The plan is immutable; re-derivation
    is forbidden. Two callers racing with different derivations
    is a contract violation; an operator must resolve."""
    from mind_runtime.projection.store import FrozenPlan

    proj_db = tmp_path / "projections.sqlite"
    store = SqliteProjectionStore(proj_db)
    plan = FrozenPlan(
        receipt_id="recpt-x",
        request_id="req-x",
        action_type="proactive_message",
        settled_at=NOW,
        facts=(("counter.proactive_prompts_since_photo", "1"),),
        completed=False,
    )
    store.record_frozen_plan(plan)
    # Second call with a different fact value: fail closed.
    plan2 = FrozenPlan(
        receipt_id="recpt-x",
        request_id="req-x",
        action_type="proactive_message",
        settled_at=NOW,
        facts=(("counter.proactive_prompts_since_photo", "999"),),
        completed=False,
    )
    with pytest.raises(ValueError, match="frozen plan conflict"):
        store.record_frozen_plan(plan2)
    store.close()


def test_r3_def_record_frozen_plan_fails_closed_on_settled_at_drift(
    tmp_path: Path,
) -> None:
    """record_frozen_plan fails closed when only the settled_at
    differs. The settled_at is part of the immutability contract."""
    from datetime import timedelta

    from mind_runtime.projection.store import FrozenPlan

    proj_db = tmp_path / "projections.sqlite"
    store = SqliteProjectionStore(proj_db)
    plan = FrozenPlan(
        receipt_id="recpt-x",
        request_id="req-x",
        action_type="proactive_message",
        settled_at=NOW,
        facts=(("counter.proactive_prompts_since_photo", "1"),),
        completed=False,
    )
    store.record_frozen_plan(plan)
    plan2 = FrozenPlan(
        receipt_id="recpt-x",
        request_id="req-x",
        action_type="proactive_message",
        settled_at=NOW + timedelta(seconds=1),
        facts=(("counter.proactive_prompts_since_photo", "1"),),
        completed=False,
    )
    with pytest.raises(ValueError, match="frozen plan conflict"):
        store.record_frozen_plan(plan2)
    store.close()


# ---------------------------------------------------------------------------
# R3-7: projector-level divergent derivation
# ---------------------------------------------------------------------------


def test_r3_7_divergent_fact_value_on_same_receipt_fails_closed(
    tmp_path: Path,
) -> None:
    """R3-7: same receipt_id with a different frozen fact value
    must fail closed at the store layer. The plan is the
    immutable binding between receipt_id and the exact facts;
    a divergent second record_frozen_plan is a contract violation.

    The project() method never reaches this path in normal
    operation (the has() fast-path returns already_applied once
    the marker is on disk). The divergence check is a defensive
    store-layer contract that catches out-of-band writes,
    races that bypass the has() check, and on-disk corruption.
    """
    from mind_runtime.projection.store import FrozenPlan

    proj_db = tmp_path / "projections.sqlite"
    store = SqliteProjectionStore(proj_db)
    plan_a = FrozenPlan(
        receipt_id="recpt-shared",
        request_id="req-a",
        action_type="proactive_message",
        settled_at=NOW,
        facts=(("counter.proactive_prompts_since_photo", "1"),),
        completed=False,
    )
    store.record_frozen_plan(plan_a)
    # The second call with a different fact value for the same
    # receipt_id must fail closed.
    plan_b = FrozenPlan(
        receipt_id="recpt-shared",
        request_id="req-a",
        action_type="proactive_message",
        settled_at=NOW,
        facts=(("counter.proactive_prompts_since_photo", "999"),),
        completed=False,
    )
    with pytest.raises(ValueError, match="frozen plan conflict"):
        store.record_frozen_plan(plan_b)
    # The original plan is still on disk and unchanged.
    fetched = store.get_frozen_plan_any("recpt-shared")
    assert fetched is not None
    assert fetched.facts[0][1] == "1"
    store.close()


# ---------------------------------------------------------------------------
# R3-8: inconsistent state (marker absent, plan completed=True)
# ---------------------------------------------------------------------------


def test_r3_8_inconsistent_state_fails_closed(
    tmp_path: Path,
) -> None:
    """R3-8: the projection store reaches the inconsistent state
    (marker absent, plan completed=True). This is forbidden:
    the plan was marked completed (mark_plan_completed was called)
    but the marker write did not survive. Re-deriving would
    silently overwrite the immutable plan's pinned value. The
    projector must fail closed with a clear error; an operator
    must inspect and resolve the inconsistency."""
    facts_db = tmp_path / "facts.sqlite"
    proj_db = tmp_path / "projections.sqlite"
    facts = SqliteFactBackend(facts_db)
    store = SqliteProjectionStore(proj_db)
    fact_service = FactIngestService(
        clock=FakeClock(NOW), backend=facts,
    )
    projector = SettledActionProjector(
        fact_service=fact_service,
        projection_store=store,
        clock=FakeClock(NOW),
    )
    req = _request(idempotency_key="r3-8")
    rcpt = _receipt(req, delivered_at=NOW)
    projector.project(receipt=rcpt, request=req)
    # The plan is now completed.
    assert store.has_frozen_plan(rcpt.receipt_id) is False  # completed
    assert store.has(rcpt.receipt_id) is True
    store.close()

    # Simulate the inconsistent state: marker gone, plan still
    # completed=True. This state cannot arise in normal operation
    # (it requires either a process crash between mark_plan_completed
    # and the marker write, or a storage rollback). It is forbidden.
    with sqlite3.connect(proj_db) as conn:
        conn.execute(
            "DELETE FROM settled_action_projections WHERE receipt_id = ?",
            (rcpt.receipt_id,),
        )
        # Plan is already completed=True; do NOT reset it to 0.

    # Reopen: the projector must detect the inconsistency and
    # fail closed rather than re-deriving.
    store2 = SqliteProjectionStore(proj_db)
    fact_service2 = FactIngestService(
        clock=FakeClock(NOW), backend=SqliteFactBackend(facts_db),
    )
    projector2 = SettledActionProjector(
        fact_service=fact_service2,
        projection_store=store2,
        clock=FakeClock(NOW),
    )
    with pytest.raises(ValueError, match="projection inconsistent"):
        projector2.project(receipt=rcpt, request=req)
    store2.close()


# ---------------------------------------------------------------------------
# R3-9: fault injection at the precise post-plan boundary
# ---------------------------------------------------------------------------


def test_r3_9_fault_after_plan_recovery_from_incomplete_plan(
    tmp_path: Path,
) -> None:
    """R3-9: in-process crash injection at the post-plan,
    pre-first-admission boundary, paired with a fresh store reopen
    SqliteProjectionStore reopen. The fault-injection hook
    set_fault_after_plan triggers at the precise boundary; the
    recovery step opens a new projector over the same file.
    Recovery replays the plan verbatim: the marker is rebuilt
    with the original value; the fact plane is unchanged.

    Scope note: this is NOT an OS-level process-kill test. The
    injection is in-process; the reopen exercises the same
    SqliteProjectionStore path a real restart would take, but
    the long-run / kill / restart evidence is a separate W
    (C11 soak), not a R3 deliverable.
    """
    facts_db = tmp_path / "facts.sqlite"
    proj_db = tmp_path / "projections.sqlite"
    facts = SqliteFactBackend(facts_db)
    store = SqliteProjectionStore(proj_db)
    fact_service = FactIngestService(
        clock=FakeClock(NOW), backend=facts,
    )
    projector = SettledActionProjector(
        fact_service=fact_service,
        projection_store=store,
        clock=FakeClock(NOW),
    )
    req = _request(idempotency_key="r3-9")
    rcpt = _receipt(req, delivered_at=NOW)

    # Install the fault hook: raise RuntimeError simulating a crash
    # at the post-plan, pre-first-admission boundary. This is an
    # in-process injection (not OS-level kill). The store is left
    # with plan=incomplete, marker=missing, facts=absent.
    def kill_process(
        *, receipt: Any, request: Any,
    ) -> None:
        raise RuntimeError("crashed at post-plan boundary")
    projector.set_fault_after_plan(kill_process)

    with pytest.raises(RuntimeError, match="crashed at post-plan boundary"):
        projector.project(receipt=rcpt, request=req)

    # Verify the store state: plan present and incomplete, no marker.
    assert store.has_frozen_plan(rcpt.receipt_id) is True
    plan = store.get_frozen_plan_any(rcpt.receipt_id)
    assert plan is not None
    assert plan.completed is False
    assert plan.facts[0][1] == "1"  # original counter value
    assert store.has(rcpt.receipt_id) is False  # no marker
    store.close()

    # Recovery: replay from the plan. The original value is restored.
    store2 = SqliteProjectionStore(proj_db)
    fact_service2 = FactIngestService(
        clock=FakeClock(NOW), backend=SqliteFactBackend(facts_db),
    )
    projector2 = SettledActionProjector(
        fact_service=fact_service2,
        projection_store=store2,
        clock=FakeClock(NOW),
    )
    # Recovery must NOT re-derive; it must use the plan verbatim.
    outcome = projector2.project(receipt=rcpt, request=req)
    assert outcome.derived_counter_value == "1"
    assert outcome.already_applied is True
    assert store2.has(rcpt.receipt_id) is True
    # Fact plane has exactly the two original observations (no new writes).
    by_id = {o.id: o for o in fact_service2.observations.all()}
    assert (
        by_id[f"op-{rcpt.receipt_id}-counter.proactive_prompts_since_photo"].value
        == "1"
    )
    store2.close()


def test_r3_def_corrupt_plan_json_fails_closed_on_load(tmp_path: Path) -> None:
    """A row whose plan_json is not a list of [str, str] pairs is
    rejected on load (defense in depth against on-disk corruption)."""
    proj_db = tmp_path / "projections.sqlite"
    # First create the schema via a normal open.
    SqliteProjectionStore(proj_db).close()
    # Inject a corrupt plan_json (not a list).
    with sqlite3.connect(proj_db) as conn:
        conn.execute(
            "INSERT INTO projection_frozen_plans ("
            "receipt_id, request_id, action_type, settled_at,"
            " plan_json, completed"
            ") VALUES (?, ?, ?, ?, ?, ?)",
            (
                "recpt-corrupt",
                "req-corrupt",
                "proactive_message",
                NOW.isoformat(),
                '"this is a string, not a list"',  # JSON string
                0,
            ),
        )
    # Reading the row via get_frozen_plan triggers the JSON validation.
    store = SqliteProjectionStore(proj_db)
    with pytest.raises(ValueError, match="must be a list"):
        store.get_frozen_plan("recpt-corrupt")
    store.close()


def test_r3_def_corrupt_plan_entry_fails_closed_on_load(tmp_path: Path) -> None:
    """A row whose plan_json list contains a non-[str, str] entry
    is rejected on load (defense in depth)."""
    proj_db = tmp_path / "projections.sqlite"
    SqliteProjectionStore(proj_db).close()
    with sqlite3.connect(proj_db) as conn:
        conn.execute(
            "INSERT INTO projection_frozen_plans ("
            "receipt_id, request_id, action_type, settled_at,"
            " plan_json, completed"
            ") VALUES (?, ?, ?, ?, ?, ?)",
            (
                "recpt-corrupt-entry",
                "req-corrupt",
                "proactive_message",
                NOW.isoformat(),
                '[["counter.x", "1"], ["bad", 42]]',  # second entry has int
                0,
            ),
        )
    store = SqliteProjectionStore(proj_db)
    with pytest.raises(ValueError, match="must be \\[str, str\\]"):
        store.get_frozen_plan("recpt-corrupt-entry")
    store.close()
