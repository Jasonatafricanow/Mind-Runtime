"""Coverage-fill tests for the C7C settled-action projection.

The CP1-CP12 cases cover the happy paths and the public contract.
This file fills the remaining coverage gaps: defensive checks
(constructor validation, type guards, delivered_at fallback, empty
action_type, observation iteration, int-parse failures).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

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
from mind_runtime.projection import (
    SettledActionProjector,
    SqliteProjectionStore,
)

NOW = datetime(2026, 8, 28, 12, 0, tzinfo=UTC)
SCOPE = Scope(domain=ScopeDomain.USER, user_id="u-c7c-cov")
RUNTIME = "runtime-c7c-cov"


# ---- helpers ---------------------------------------------------------------


def _build_request(
    *, idempotency_key: str = "k1", action_type: str = "proactive_message",
    created_at: datetime = NOW,
) -> DeliveryRequest:
    rid = make_request_id(SCOPE, "intent-cov", idempotency_key)
    return DeliveryRequest(
        request_id=rid,
        message_id=make_message_id(rid),
        scope=SCOPE,
        origin_runtime_id=RUNTIME,
        channel="weixin",
        target="user-c7c-cov",
        action_type=action_type,
        payload_bytes=b"hi",
        created_at=created_at,
        sync=SyncFields(SCOPE, RUNTIME, rid, 1, f"idem-{rid}"),
    )


def _accepted_receipt(
    request: DeliveryRequest,
    *,
    delivered_at: datetime | None = NOW,
    status: DeliveryStatus = DeliveryStatus.SENT,
) -> DeliveryReceipt:
    return DeliveryReceipt(
        receipt_id=f"recpt-{request.request_id}",
        scope=request.scope,
        origin_runtime_id=request.origin_runtime_id,
        message_id=request.message_id,
        delivery_status=status,
        delivered_at=delivered_at,
        sync=SyncFields(
            request.scope, request.origin_runtime_id,
            f"recpt-{request.request_id}", 1, f"idem-recpt-{request.request_id}",
        ),
    )


def _build_stack(
    tmp_path: Path,
) -> tuple[FactIngestService, SettledActionProjector, SqliteProjectionStore]:
    return _build_stack_with_path(tmp_path, tmp_path / "p.sqlite")


def _build_stack_with_path(
    tmp_path: Path, store_path: Path,
) -> tuple[FactIngestService, SettledActionProjector, SqliteProjectionStore]:
    fact_service = FactIngestService(
        clock=FakeClock(NOW), backend=SqliteFactBackend(tmp_path / "f.sqlite"),
    )
    store = SqliteProjectionStore(store_path)
    projector = SettledActionProjector(
        fact_service=fact_service,
        projection_store=store,
        clock=FakeClock(NOW),
        runtime_id=RUNTIME,
    )
    return fact_service, projector, store


# ---- projector constructor fail-closed ----------------------------------


def test_projection_constructor_fails_closed(tmp_path: Path) -> None:
    from mind_runtime.facts.service import FactIngestService
    from mind_runtime.projection.projector import SettledActionProjector

    fact_service = FactIngestService(clock=FakeClock(NOW))
    store = SqliteProjectionStore(tmp_path / "p.sqlite")

    with pytest.raises(ValueError, match="fact_service"):
        SettledActionProjector(
            fact_service=object(),  # type: ignore[arg-type]
            projection_store=store,
            clock=FakeClock(NOW),
        )
    with pytest.raises(ValueError, match="projection_store"):
        SettledActionProjector(
            fact_service=fact_service,
            projection_store=object(),  # type: ignore[arg-type]
            clock=FakeClock(NOW),
        )
    with pytest.raises(ValueError, match="runtime_id"):
        SettledActionProjector(
            fact_service=fact_service,
            projection_store=store,
            clock=FakeClock(NOW),
            runtime_id="",
        )
    # Naive datetime clock is rejected.
    from datetime import datetime as _dt

    class _NaiveClock:
        def now(self) -> _dt:
            return _dt(2026, 1, 1, 0, 0, 0)

    with pytest.raises(ValueError, match="aware UTC"):
        SettledActionProjector(
            fact_service=fact_service,
            projection_store=store,
            clock=_NaiveClock(),
        )


# ---- projector input type guards ------------------------------------------


def test_projection_rejects_non_delivery_receipt(tmp_path: Path) -> None:
    _, projector, store = _build_stack(tmp_path)
    request = _build_request()

    with pytest.raises(ValueError, match="receipt must be a DeliveryReceipt"):
        projector.project(receipt=object(), request=request)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="request must be a DeliveryRequest"):
        projector.project(
            receipt=_accepted_receipt(request),
            request=object(),  # type: ignore[arg-type]
        )
    store.close()


# ---- projector delivered_at fallback (SENT without delivered_at) -----------


def test_projection_fails_closed_when_receipt_delivered_at_missing(
    tmp_path: Path,
) -> None:
    """C7C-R: a SENT receipt with delivered_at=None fails closed. The
    settled-delivery authority contract requires delivered_at; the
    projector does NOT silently fall back to request.created_at. The
    old C7C defensive fallback was a fail-soft that the C7C-R
    contract explicitly forbids (no silent default to a counter
    action)."""
    _, projector, store = _build_stack(tmp_path)
    request = _build_request(idempotency_key="k-fb", created_at=NOW)
    # SENT with delivered_at=None — must refuse.
    receipt = _accepted_receipt(request, delivered_at=None)
    assert receipt.delivery_status is DeliveryStatus.SENT
    assert receipt.delivered_at is None
    with pytest.raises(ValueError, match="receipt.delivered_at"):
        projector.project(receipt=receipt, request=request)
    store.close()


# ---- projector empty action_type ------------------------------------------


def test_projection_unknown_action_type_is_noop(tmp_path: Path) -> None:
    """An action_type we do not recognise fails closed (C7C-R): the
    settled-action projector refuses to fabricate a default. A legacy
    "" action_type is also fail-closed (no silent backfill to
    proactive_message)."""
    fact_service, projector, store = _build_stack(tmp_path)
    # An unknown action_type fails closed (raises), it does not
    # noop silently.
    request_unknown = _build_request(idempotency_key="k-u", action_type="unknown_kind")
    receipt = _accepted_receipt(request_unknown)
    with pytest.raises(ValueError, match="not a known typed action"):
        projector.project(receipt=receipt, request=request_unknown)
    # A legacy "" action_type also fails closed.
    request_legacy = _build_request(idempotency_key="k-l", action_type="")
    receipt_legacy = _accepted_receipt(request_legacy)
    with pytest.raises(ValueError, match="legacy unknown"):
        projector.project(receipt=receipt_legacy, request=request_legacy)
    # No counter facts admitted.
    assert all(
        obs.key not in {
            "counter.proactive_prompts_since_photo",
            "counter.last_proactive_at",
        }
        for obs in fact_service.observations.all()
    )
    store.close()


# ---- projector SEND_PHOTO path (no cooldown fact) ---------------------------


def test_projection_send_photo_emits_only_cadence_counter_not_cooldown(
    tmp_path: Path,
) -> None:
    fact_service, projector, store = _build_stack(tmp_path)
    request = _build_request(
        idempotency_key="k-photo", action_type="send_photo",
    )
    receipt = _accepted_receipt(request)
    outcome = projector.project(receipt=receipt, request=request)
    assert outcome.applied is True
    # Only the cadence counter is emitted; cooldown is NOT (per工单
    # STEP 5: SEND_PHOTO resets the count, not the cooldown).
    keys = {obs.key for obs in fact_service.observations.all()}
    assert "counter.proactive_prompts_since_photo" in keys
    assert "counter.last_proactive_at" not in keys
    store.close()


# ---- projector int-parse failure (counter starts non-numeric) -------------


def test_projection_handles_non_numeric_existing_counter(tmp_path: Path) -> None:
    """If the existing fact plane has a non-numeric counter value
    (e.g. operator-edited), the next projection must treat it as zero
    rather than crashing the read-modify-write."""
    from mind_runtime.contracts import (
        Observation,
        SyncFields,
    )

    fact_service, projector, store = _build_stack(tmp_path)
    # Seed a non-numeric fact directly into the observation store
    # (bypassing the public admit API, which is the only valid
    # caller for a settled-action projection).
    obs = Observation(
        id="op-seed-misformat-counter.proactive_prompts_since_photo",
        interaction_id="i-seed",
        scope=SCOPE,
        origin_runtime_id=RUNTIME,
        type="operational",
        key="counter.proactive_prompts_since_photo",
        value="not-a-number",
        confidence=1.0,
        observed_at=NOW,
        evidence_refs=("seed",),
        sync=SyncFields(
            SCOPE, RUNTIME,
            "op-seed-misformat-counter.proactive_prompts_since_photo", 1,
            "idem-seed",
        ),
    )
    fact_service._observations.append(obs)
    request = _build_request(idempotency_key="k1")
    receipt = _accepted_receipt(request)
    # Must not raise on the non-numeric read.
    outcome = projector.project(receipt=receipt, request=request)
    # Treated as 0 → +1 → 1.
    assert outcome.derived_counter_value == "1"
    store.close()


# ---- projector observation iteration skip (different key/scope) ----------


def test_projection_skips_unrelated_observations(tmp_path: Path) -> None:
    """Observations under a different key or a different scope do not
    participate in the counter read-modify-write."""
    from mind_runtime.contracts import (
        Observation,
        SyncFields,
    )

    other_scope = Scope(domain=ScopeDomain.USER, user_id="u-other")
    fact_service, projector, store = _build_stack(tmp_path)
    # Seed an observation for a different key in the SAME scope
    # (bypassing the public admit API; the C7C-R contract
    # restricts admit_operational_fact to the settled-action
    # projector).
    obs_other_key = Observation(
        id="op-seed-other-some.other.counter",
        interaction_id="i-seed-other",
        scope=SCOPE,
        origin_runtime_id=RUNTIME,
        type="operational",
        key="some.other.counter",
        value="999",
        confidence=1.0,
        observed_at=NOW,
        evidence_refs=("seed-other",),
        sync=SyncFields(SCOPE, RUNTIME, "op-seed-other-some.other.counter", 1, "idem-other"),
    )
    fact_service._observations.append(obs_other_key)
    # Seed an observation for the cadence key in a DIFFERENT scope.
    obs_other_scope = Observation(
        id="op-seed-other-scope-counter.proactive_prompts_since_photo",
        interaction_id="i-seed-other-scope",
        scope=other_scope,
        origin_runtime_id=RUNTIME,
        type="operational",
        key="counter.proactive_prompts_since_photo",
        value="999",
        confidence=1.0,
        observed_at=NOW,
        evidence_refs=("seed-other-scope",),
        sync=SyncFields(
            other_scope, RUNTIME,
            "op-seed-other-scope-counter.proactive_prompts_since_photo", 1,
            "idem-osc",
        ),
    )
    fact_service._observations.append(obs_other_scope)
    request = _build_request(idempotency_key="k1")
    receipt = _accepted_receipt(request)
    outcome = projector.project(receipt=receipt, request=request)
    # The seeded observations for SCOPE=other_scope and key=other are
    # both ignored; the counter starts at 0 and is incremented to 1.
    assert outcome.derived_counter_value == "1"
    store.close()


# ---- store: collision + row-load ------------------------------------------


def test_projection_store_rejects_duplicate_record(tmp_path: Path) -> None:
    """Recording two ProjectionRecord with the same receipt_id raises."""
    from mind_runtime.projection.store import ProjectionRecord

    store = SqliteProjectionStore(tmp_path / "p.sqlite")
    record = ProjectionRecord(
        receipt_id="recpt-dup",
        request_id="req-dup",
        message_id="msg-dup",
        scope=SCOPE,
        origin_runtime_id=RUNTIME,
        derived_counter_key="counter.proactive_prompts_since_photo",
        derived_counter_value="1",
        derived_settled_at=NOW,
        projected_at=NOW,
        sync_version=1,
    )
    store.record(record)
    with pytest.raises(ValueError, match="already exists"):
        store.record(record)
    assert store.has("recpt-dup")
    # get returns the stored record.
    loaded = store.get("recpt-dup")
    assert loaded is not None
    assert loaded.derived_counter_value == "1"
    # Missing key returns None.
    assert store.get("not-there") is None
    store.close()


# ---- store: malformed row JSON fails closed on reopen --------------------


def test_projection_store_reopen_malformed_json_fails_closed(
    tmp_path: Path,
) -> None:
    """A corrupted row in settled_action_projections fails closed
    on reopen (defense in depth, matching the C7B delivery backend
    pattern)."""
    import sqlite3


    path = tmp_path / "p.sqlite"
    fact_service, projector, store = _build_stack_with_path(tmp_path, path)
    # Persist one ACCEPTED projection so the on-disk file has a row.
    request = _build_request(idempotency_key="k-c")
    receipt = _accepted_receipt(request)
    projector.project(receipt=receipt, request=request)
    store.close()

    # Manually corrupt the receipt_id column of the persisted row.
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            "UPDATE settled_action_projections SET receipt_id = ?"
            " WHERE receipt_id != ''",
            ("",),
        )
        conn.commit()
    finally:
        conn.close()

    # Reopen fails closed.
    with pytest.raises(ValueError, match="empty or non-string field"):
        SqliteProjectionStore(path)


# ---- projector: clock-now must be timezone aware on every call ------------


def test_projection_rejects_non_utc_observation_timestamp_on_replay(
    tmp_path: Path,
) -> None:
    """The projector asserts clock.now() is timezone-aware every time
    it stamps the projection. A clock that returns a naive datetime
    triggers a fail-closed ValueError (the receive-side invariant
    that no operational fact can be admitted with a naive
    observed_at)."""
    from mind_runtime.projection.projector import SettledActionProjector

    fact_service = FactIngestService(clock=FakeClock(NOW))
    store = SqliteProjectionStore(tmp_path / "p.sqlite")

    class _NaiveAwareClock:
        """A clock that returns timezone-aware datetimes on the
        first two calls (construction + first project) and a NAIVE
        datetime on the third call (so the second project stamping
        fails closed)."""

        def __init__(self) -> None:
            self._calls = 0

        def now(self) -> datetime:
            self._calls += 1
            if self._calls <= 2:
                return NOW
            return datetime(2026, 1, 1, 0, 0, 0)  # naive

    clock = _NaiveAwareClock()
    projector = SettledActionProjector(
        fact_service=fact_service, projection_store=store, clock=clock,
        runtime_id=RUNTIME,
    )
    # First project() call uses NOW (UTC-aware) — construction OK.
    request = _build_request(idempotency_key="k1")
    receipt = _accepted_receipt(request)
    projector.project(receipt=receipt, request=request)
    # Second call: clock returns naive datetime -> projection stamping
    # fails closed.
    request2 = _build_request(idempotency_key="k2")
    receipt2 = _accepted_receipt(request2)
    with pytest.raises(ValueError, match="aware UTC"):
        projector.project(receipt=receipt2, request=request2)
    store.close()


# ---- additional coverage-fill tests for the remaining gaps -------------


def test_projection_skips_non_string_observation_value(tmp_path: Path) -> None:
    """An observation whose value is not a string is skipped by the
    counter read-modify-write (defense in depth: a malformed fact
    must not crash the projector)."""
    from mind_runtime.contracts import (
        Observation,
        SyncFields,
    )

    fact_service, projector, store = _build_stack(tmp_path)
    # Seed an observation whose value is an integer (not a string).
    obs = Observation(
        id="obs-malformed",
        interaction_id="i-mal",
        scope=SCOPE,
        origin_runtime_id=RUNTIME,
        type="factual",
        key="counter.proactive_prompts_since_photo",
        value=42,  # not a string
        confidence=1.0,
        observed_at=NOW,
        evidence_refs=("seed",),
        sync=SyncFields(SCOPE, RUNTIME, "obs-malformed", 1, "idem-mal"),
    )
    fact_service._observations.append(obs)
    request = _build_request(idempotency_key="k1")
    receipt = _accepted_receipt(request)
    outcome = projector.project(receipt=receipt, request=request)
    # The integer-valued observation is skipped; the counter starts at 0.
    assert outcome.derived_counter_value == "1"
    store.close()


def test_projection_two_observations_takes_both_latest_at_branches(
    tmp_path: Path,
) -> None:
    """Two matching observations exercise BOTH sides of the
    `latest_at is None or observation.observed_at >= latest_at`
    short-circuit: the first observation takes the None branch
    (latest_at is None), the second takes the >= branch
    (latest_at is not None, comparison is evaluated)."""
    from mind_runtime.contracts import (
        Observation,
        SyncFields,
    )

    fact_service, projector, store = _build_stack(tmp_path)
    later = NOW + timedelta(minutes=5)
    # Seed TWO matching observations with strictly increasing
    # observed_at so the for-loop body exercises BOTH sides of the
    # `latest_at is None or observation.observed_at >= latest_at`
    # short-circuit.
    obs_first = Observation(
        id="obs-1",
        interaction_id="i-1",
        scope=SCOPE,
        origin_runtime_id=RUNTIME,
        type="factual",
        key="counter.proactive_prompts_since_photo",
        value="3",
        confidence=1.0,
        observed_at=NOW,
        evidence_refs=("seed-1",),
        sync=SyncFields(SCOPE, RUNTIME, "obs-1", 1, "idem-1"),
    )
    obs_second = Observation(
        id="obs-2",
        interaction_id="i-2",
        scope=SCOPE,
        origin_runtime_id=RUNTIME,
        type="factual",
        key="counter.proactive_prompts_since_photo",
        value="7",
        confidence=1.0,
        observed_at=later,
        evidence_refs=("seed-2",),
        sync=SyncFields(SCOPE, RUNTIME, "obs-2", 1, "idem-2"),
    )
    fact_service._observations.append(obs_first)
    fact_service._observations.append(obs_second)
    request = _build_request(idempotency_key="k1")
    receipt = _accepted_receipt(request)
    outcome = projector.project(receipt=receipt, request=request)
    # The second observation (value=7) is the latest; +1 from the
    # projection makes it 8.
    assert outcome.derived_counter_value == "8"
    store.close()


def test_projection_skips_earlier_second_observation(tmp_path: Path) -> None:
    """When two matching observations are in the fact plane and the
    second is OLDER (smaller observed_at) than the first, the
    read-modify-write keeps the newer one. The `latest_at is None`
    branch (taken for the first observation) and the
    `observation.observed_at >= latest_at` branch (taken and found
    false for the second) are both exercised.
    """
    from mind_runtime.contracts import (
        Observation,
        SyncFields,
    )

    fact_service, projector, store = _build_stack(tmp_path)
    earlier = NOW - timedelta(minutes=5)
    later = NOW
    # Seed an OLDER observation first; the projection will see it,
    # then a NEWER one. The newer wins.
    obs_older = Observation(
        id="obs-older",
        interaction_id="i-older",
        scope=SCOPE,
        origin_runtime_id=RUNTIME,
        type="factual",
        key="counter.proactive_prompts_since_photo",
        value="9",
        confidence=1.0,
        observed_at=earlier,
        evidence_refs=("seed-older",),
        sync=SyncFields(SCOPE, RUNTIME, "obs-older", 1, "idem-older"),
    )
    obs_newer = Observation(
        id="obs-newer",
        interaction_id="i-newer",
        scope=SCOPE,
        origin_runtime_id=RUNTIME,
        type="factual",
        key="counter.proactive_prompts_since_photo",
        value="5",
        confidence=1.0,
        observed_at=later,
        evidence_refs=("seed-newer",),
        sync=SyncFields(SCOPE, RUNTIME, "obs-newer", 1, "idem-newer"),
    )
    # Seed a NEWER observation FIRST, then an OLDER one — the older
    # must be skipped (its observed_at < the current latest_at, so
    # the false branch of the short-circuit is taken). The newer
    # wins.
    fact_service._observations.append(obs_newer)
    fact_service._observations.append(obs_older)
    request = _build_request(idempotency_key="k1")
    receipt = _accepted_receipt(request)
    outcome = projector.project(receipt=receipt, request=request)
    # 5 + 1 = 6 (the newer 5 wins; the older 9 is skipped).
    assert outcome.derived_counter_value == "6"
    store.close()


def test_admit_operational_fact_is_idempotent_on_same_id(tmp_path: Path) -> None:
    """Re-projection of the same receipt is a no-op on the fact plane
    (the deterministic observation_id makes the admit idempotent).
    The projection's read-modify-write re-derives from the durable
    observation so the counter still advances — the
    NO-NEW-DURABLE-EFFECTS invariant applies to the row count, not
    to the derived counter value.
    """
    fact_service, projector, store = _build_stack(tmp_path)
    request = _build_request(idempotency_key="k1")
    receipt = _accepted_receipt(request)
    # First call establishes the durable marker.
    projector.project(receipt=receipt, request=request)
    # A second call of project() with the same receipt_id is the
    # same observable event: the projection marker is durable, so
    # the projector returns already_applied=True (no fact re-admit,
    # no marker re-write).
    second = projector.project(receipt=receipt, request=request)
    assert second.applied is False
    assert second.already_applied is True
    # Only ONE observation was actually admitted in the durable
    # fact plane (cadence + cooldown, exactly two rows for the
    # two facts; the second call's re-admits are no-ops).
    cadence_rows = [
        o for o in fact_service.observations.all()
        if o.key == "counter.proactive_prompts_since_photo"
    ]
    cooldown_rows = [
        o for o in fact_service.observations.all()
        if o.key == "counter.last_proactive_at"
    ]
    assert len(cadence_rows) == 1
    assert len(cooldown_rows) == 1
    store.close()


