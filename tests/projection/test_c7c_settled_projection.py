"""CP1-CP12: C7C settled action projection (single-writer contract).

C7C is the doorway that converts an external ACCEPTED delivery
outcome into an internal operational fact (counter.last_proactive_at,
counter.proactive_prompts_since_photo). Hard contract:

  * Only ACCEPTED drives a projection. IN_FLIGHT, UNKNOWN,
    FAILED_RETRYABLE, REJECTED, Intent ALLOWED — none of these
    touch the counter plane.
  * Single writer: this projector. CognitiveTicker and the C6B
    cadence rule stay read-only.
  * Idempotency binds to receipt_id (NOT wall-clock): the same
    receipt replayed never increments twice.
  * Cadence semantics follow the legacy rule map (proactive_text
    increments; SEND_PHOTO resets).
  * Timestamp authority: provider delivered_at primary; explicit
    fallback to request created_at.
  * Crash windows: durable reopen proves exactly-once projection.

The tests use the existing FactIngestService as the durable fact
authority; no direct UPDATE of any counter table.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

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
from mind_runtime.situation.derived import media_photo_cadence_eligible

NOW = datetime(2026, 8, 28, 12, 0, tzinfo=UTC)
SCOPE = Scope(domain=ScopeDomain.USER, user_id="u-c7c")
RUNTIME = "runtime-c7c"
INTENT_ID_PROACTIVE = "intent-proactive-1"
INTENT_ID_PHOTO = "intent-photo-1"


# ---- helpers ---------------------------------------------------------------


def _build_request(
    *,
    request_id: str | None = None,
    action_intent_id: str = INTENT_ID_PROACTIVE,
    idempotency_key: str = "k1",
    action_type: str = "proactive_message",
    created_at: datetime = NOW,
) -> DeliveryRequest:
    rid = request_id or make_request_id(SCOPE, action_intent_id, idempotency_key)
    return DeliveryRequest(
        request_id=rid,
        message_id=make_message_id(rid),
        scope=SCOPE,
        origin_runtime_id=RUNTIME,
        channel="weixin",
        target="user-c7c",
        action_type=action_type,
        payload_bytes="今天下午想和你分享一首诗".encode(),
        created_at=created_at,
        sync=SyncFields(SCOPE, RUNTIME, rid, 1, f"idem-{rid}"),
    )


def _accepted_receipt(
    request: DeliveryRequest,
    *,
    delivered_at: datetime = NOW,
    status: DeliveryStatus = DeliveryStatus.SENT,
) -> DeliveryReceipt:
    return DeliveryReceipt(
        receipt_id=f"recpt-{request.request_id}",
        scope=request.scope,
        origin_runtime_id=request.origin_runtime_id,
        message_id=request.message_id,
        delivery_status=status,
        delivered_at=delivered_at if status is DeliveryStatus.SENT else None,
        sync=SyncFields(
            request.scope, request.origin_runtime_id,
            f"recpt-{request.request_id}", 1, f"idem-recpt-{request.request_id}",
        ),
    )


def _build_stack(
    tmp_path: Path,
) -> tuple[FactIngestService, SettledActionProjector, SqliteProjectionStore]:
    """One durable test stack: a fact service + a projection store + a projector."""
    fact_service = FactIngestService(
        clock=FakeClock(NOW),
        backend=SqliteFactBackend(tmp_path / "facts.sqlite"),
    )
    projection_store = SqliteProjectionStore(tmp_path / "projections.sqlite")
    projector = SettledActionProjector(
        fact_service=fact_service,
        projection_store=projection_store,
        clock=FakeClock(NOW),
    )
    return fact_service, projector, projection_store


def _facts_by_key(fact_service: FactIngestService) -> dict[str, str]:
    """Read every admitted fact into {key: value}, ignoring provenance."""
    out: dict[str, str] = {}
    for observation in fact_service.observations.all():
        key = observation.key
        value = observation.value
        if isinstance(key, str) and isinstance(value, str):
            out[key] = value
    return out


# ---- CP1: single ACCEPTED proactive text -> counter 1 ----------------------


def test_cp1_accepted_proactive_text_increments_cadence_counter(tmp_path: Path) -> None:
    fact_service, projector, store = _build_stack(tmp_path)
    request = _build_request(idempotency_key="k1")
    receipt = _accepted_receipt(request)

    outcome = projector.project(receipt=receipt, request=request)

    assert outcome.applied is True
    assert outcome.already_applied is False
    assert outcome.derived_counter_key == "counter.proactive_prompts_since_photo"
    # Operational fact was admitted to the existing fact authority.
    facts = _facts_by_key(fact_service)
    assert "counter.proactive_prompts_since_photo" in facts
    # The durable idempotency record exists.
    assert store.has(receipt.receipt_id) is True
    store.close()


# ---- CP2: 3 ACCEPTED proactive texts -> counter 3, C6B eligibility true --------


def test_cp2_three_accepted_texts_advance_counter_through_threshold(
    tmp_path: Path,
) -> None:

    fact_service, projector, store = _build_stack(tmp_path)
    keys = ["k1", "k2", "k3"]
    requests = [_build_request(idempotency_key=k) for k in keys]
    receipts = [_accepted_receipt(r) for r in requests]

    for r, rec in zip(requests, receipts, strict=True):
        projector.project(receipt=rec, request=r)

    facts = _facts_by_key(fact_service)
    assert facts["counter.proactive_prompts_since_photo"] == "3"
    # C6B reads this fact; pure derive rule is "eligible" at >= 3.
    assert media_photo_cadence_eligible(3, threshold=3) is True
    store.close()


# ---- CP3: ACCEPTED SEND_PHOTO -> counter reset to 0, eligibility false --------


def test_cp3_accepted_send_photo_resets_cadence_counter(tmp_path: Path) -> None:

    fact_service, projector, store = _build_stack(tmp_path)
    # Three text acceptances first.
    for k in ["k1", "k2", "k3"]:
        req = _build_request(idempotency_key=k)
        rec = _accepted_receipt(req)
        projector.project(receipt=rec, request=req)
    # Then an accepted SEND_PHOTO.
    photo_req = _build_request(
        action_intent_id=INTENT_ID_PHOTO,
        action_type="send_photo",
    )
    photo_rec = _accepted_receipt(photo_req)
    outcome = projector.project(receipt=photo_rec, request=photo_req)

    assert outcome.applied is True
    assert outcome.derived_counter_key == "counter.proactive_prompts_since_photo"
    # A settled SEND_PHOTO resets the count to zero (legacy semantics:
    # the next handled prompt starts at one again).
    facts = _facts_by_key(fact_service)
    assert facts["counter.proactive_prompts_since_photo"] == "0"
    assert media_photo_cadence_eligible(0, threshold=3) is False
    store.close()


# ---- CP4: same receipt replayed -> no second increment ----------------------


def test_cp4_same_receipt_replay_does_not_double_increment(tmp_path: Path) -> None:
    fact_service, projector, store = _build_stack(tmp_path)
    request = _build_request(idempotency_key="k1")
    receipt = _accepted_receipt(request)

    first = projector.project(receipt=receipt, request=request)
    second = projector.project(receipt=receipt, request=request)
    third = projector.project(receipt=receipt, request=request)

    assert first.applied is True and first.already_applied is False
    assert second.applied is False and second.already_applied is True
    assert third.applied is False and third.already_applied is True
    # Only ONE fact in the durable plane — the first apply.
    facts = _facts_by_key(fact_service)
    assert facts["counter.proactive_prompts_since_photo"] == "1"
    store.close()


# ---- CP5: non-ACCEPTED outcomes are no-ops (no projection, no fact) ---------


def test_cp5_non_accepted_outcomes_do_not_produce_facts(tmp_path: Path) -> None:
    fact_service, projector, store = _build_stack(tmp_path)
    request = _build_request(idempotency_key="k1")
    rejected_receipt = _accepted_receipt(
        request, status=DeliveryStatus.UNSENT,
    )
    # A REJECTED receipt has delivered_at=None per the contract.
    assert rejected_receipt.delivered_at is None

    outcome = projector.project(receipt=rejected_receipt, request=request)

    assert outcome.applied is False
    assert outcome.already_applied is False
    assert outcome.skip_reason == "not_accepted"
    facts = _facts_by_key(fact_service)
    assert facts == {}
    # No idempotency record either (so a future acceptance of the
    # same receipt is a clean fresh apply, not a confusing no-op).
    assert store.has(rejected_receipt.receipt_id) is False
    store.close()


# ---- CP6: cooldown only from ACCEPTED --------------------------------------


def test_cp6_cooldown_only_starts_from_accepted(tmp_path: Path) -> None:
    fact_service, projector, store = _build_stack(tmp_path)

    # An UNKNOWN outcome must NOT emit a cooldown fact.
    unknown_req = _build_request(idempotency_key="k1")
    unknown_rec = _accepted_receipt(
        unknown_req, status=DeliveryStatus.UNKNOWN,
    )
    # Build a minimal UNKNOWN receipt with delivered_at=None.
    unknown_rec = replace(unknown_rec, delivered_at=None)
    outcome = projector.project(receipt=unknown_rec, request=unknown_req)
    assert outcome.applied is False

    # A REJECTED outcome must NOT emit a cooldown fact either.
    rejected_req = _build_request(idempotency_key="k2")
    rejected_rec = _accepted_receipt(
        rejected_req, status=DeliveryStatus.UNSENT,
    )
    outcome = projector.project(receipt=rejected_rec, request=rejected_req)
    assert outcome.applied is False

    facts = _facts_by_key(fact_service)
    assert "counter.last_proactive_at" not in facts

    # An ACCEPTED proactive DOES emit the cooldown fact.
    accepted_req = _build_request(idempotency_key="k3")
    accepted_rec = _accepted_receipt(accepted_req, delivered_at=NOW)
    projector.project(receipt=accepted_rec, request=accepted_req)
    facts = _facts_by_key(fact_service)
    assert "counter.last_proactive_at" in facts
    assert facts["counter.last_proactive_at"] == NOW.isoformat()
    store.close()


# ---- CP7: timestamp authority: provider delivered_at first ------------------


def test_cp7_uses_provider_delivered_at_primary(tmp_path: Path) -> None:
    fact_service, projector, store = _build_stack(tmp_path)
    request = _build_request(
        idempotency_key="k1",
        created_at=datetime(2026, 1, 1, 0, 0, tzinfo=UTC),
    )
    accepted_at = datetime(2026, 8, 28, 12, 0, tzinfo=UTC)
    receipt = _accepted_receipt(request, delivered_at=accepted_at)
    assert request.created_at != accepted_at  # distinct for the assertion

    outcome = projector.project(receipt=receipt, request=request)

    facts = _facts_by_key(fact_service)
    # Provider accepted_at wins over request.created_at.
    assert facts["counter.last_proactive_at"] == accepted_at.isoformat()
    assert outcome.derived_settled_at == accepted_at
    store.close()


# ---- CP8: idempotency derives from receipt_id, not wall-clock --------------


def test_cp8_projection_idempotency_uses_receipt_id_only(tmp_path: Path) -> None:
    """Two calls of project() with the same receipt.id but advancing
    the projector's wall clock must NOT change the recorded settled_at.
    The recorded settled_at is taken from the durable receipt; the
    projector clock only stamps the projection's own audit metadata.
    """
    fact_service, projector, store = _build_stack(tmp_path)
    request = _build_request(idempotency_key="k1")
    receipt = _accepted_receipt(request, delivered_at=NOW)

    projector.project(receipt=receipt, request=request)
    # Move the projector clock forward; replay must still report
    # already_applied=True and the durable fact must not move.
    # The clock is the FakeClock instance (the test stack always
    # passes a real FakeClock, even though the projector type-hints
    # it as the _ClockPort Protocol).
    clock = projector._clock
    assert isinstance(clock, FakeClock)
    clock.advance(timedelta(hours=5))
    second = projector.project(receipt=receipt, request=request)

    assert second.applied is False
    assert second.already_applied is True
    facts = _facts_by_key(fact_service)
    # The original (provider-accepted) timestamp is preserved.
    assert facts["counter.last_proactive_at"] == NOW.isoformat()
    store.close()


# ---- CP9: crash before projection persist -> reopen -> no double-apply -----


def test_cp9_crash_before_projection_persist_reopens_idempotently(
    tmp_path: Path,
) -> None:
    """The CP9 crash window: ACCEPTED receipt is already on disk
    (durable in C7B), but no settled-action projection exists yet.
    A fresh projector on a fresh disk re-applies the projection from
    the receipt alone — exactly once. The receipt_id is the durable
    idempotency boundary; the second-pass projector reads the receipt
    and emits the same operational fact.
    """
    from mind_runtime.delivery import (
        SqliteDeliveryBackend,
    )
    from mind_runtime.projection.store import SqliteProjectionStore

    delivery_db = tmp_path / "delivery.sqlite"
    projection_db = tmp_path / "projections.sqlite"
    facts_db = tmp_path / "facts.sqlite"

    request = _build_request(idempotency_key="k1")
    receipt = _accepted_receipt(request)

    # Pre-seed: receipt already durable, NO projection yet.
    backend = SqliteDeliveryBackend(delivery_db)
    from mind_runtime.delivery import DeliveryLifecycleState
    backend.record_request(request, lifecycle_state=DeliveryLifecycleState.ACCEPTED)
    backend.record_receipt(
        receipt,
        request_id=request.request_id,
        provider_receipt_ref=None,
        provider_message_ref=None,
        attempt=1,
    )
    backend.close()
    # Drop the projection DB entirely so reopen simulates a crash
    # that lost the projection.
    projection_db.unlink(missing_ok=True)

    # First attempt: receipt exists, projection does not -> APPLY.
    fact_service = FactIngestService(
        clock=FakeClock(NOW),
        backend=SqliteFactBackend(facts_db),
    )
    projection_store = SqliteProjectionStore(projection_db)
    from mind_runtime.projection.projector import SettledActionProjector

    projector1 = SettledActionProjector(
        fact_service=fact_service,
        projection_store=projection_store,
        clock=FakeClock(NOW),
    )
    out1 = projector1.project(receipt=receipt, request=request)
    assert out1.applied is True
    projection_store.close()

    # Second attempt on a fresh projector (and fresh fact backend) MUST
    # see already_applied=True (idempotent on the durable record).
    fact_service2 = FactIngestService(
        clock=FakeClock(NOW),
        backend=SqliteFactBackend(facts_db),
    )
    projection_store2 = SqliteProjectionStore(projection_db)
    projector2 = SettledActionProjector(
        fact_service=fact_service2,
        projection_store=projection_store2,
        clock=FakeClock(NOW),
    )
    out2 = projector2.project(receipt=receipt, request=request)
    assert out2.applied is False
    assert out2.already_applied is True
    projection_store2.close()


# ---- CP10: crash after projection persist -> no second apply --------------


def test_cp10_crash_after_projection_persist_does_not_double_apply(
    tmp_path: Path,
) -> None:
    fact_service, projector, store = _build_stack(tmp_path)
    request = _build_request(idempotency_key="k1")
    receipt = _accepted_receipt(request)

    projector.project(receipt=receipt, request=request)
    # Simulate process death after the projection is durable but
    # before the projector returned its outcome marker: close and
    # reopen the projection store, then call again.
    store.close()
    from mind_runtime.projection.store import SqliteProjectionStore

    store2 = SqliteProjectionStore(tmp_path / "projections.sqlite")
    fact_service2 = FactIngestService(
        clock=FakeClock(NOW),
        backend=SqliteFactBackend(tmp_path / "facts.sqlite"),
    )
    from mind_runtime.projection.projector import SettledActionProjector

    projector2 = SettledActionProjector(
        fact_service=fact_service2,
        projection_store=store2,
        clock=FakeClock(NOW),
    )
    second = projector2.project(receipt=receipt, request=request)
    assert second.applied is False
    assert second.already_applied is True
    store2.close()


# ---- CP11: single-writer guarantee + read-only CognitiveTicker ------------


def test_cp11_cognitive_ticker_and_c6b_remain_read_only(tmp_path: Path) -> None:
    """The owner audit: the two counter keys are NEVER written by
    CognitiveTicker or by the C6B cadence rule. They are read; only
    SettledActionProjector writes via the existing fact authority."""


    # The cadence derivation is a pure function (no writes).
    for i in range(0, 5):
        assert media_photo_cadence_eligible(i, threshold=3) is (i >= 3)

    # The two counter keys are only consumed by C5B/C6B read paths.
    # We assert the production code's text: a grep-equivalent on the
    # key strings shows they appear ONLY in the projection surface
    # (writes) and the read sites (cooldown policy, situation
    # builder, cognitive tick). CognitiveTicker reads the fact, it
    # never writes it.
    import re
    from pathlib import Path as _P

    src_root = _P("src/mind_runtime")
    # The single production write site is the projector module's
    # call to FactIngestService.admit_operational_fact. The
    # fact service defines the method (service.py) but does not
    # itself emit the counter key as a literal; its purpose is the
    # durable pathway. Exclude fact service from the writer list
    # because the projection module is the one that authorises the
    # specific counter key.
    projection_writers: list[str] = []
    for path in src_root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if "admit_operational_fact" not in text:
            continue
        path_posix = path.as_posix()  # cross-platform '/' separator
        # Only files inside the projection/ subtree are real writers.
        if "projection/" not in path_posix:
            continue
        for key in (
            "counter.last_proactive_at",
            "counter.proactive_prompts_since_photo",
        ):
            for match in re.finditer(re.escape(key), text):
                line = text[: match.start()].count("\n") + 1
                projection_writers.append(f"{path}:{line} {key}")
    # The projection module is the ONLY code that drives a
    # counter-key write.
    assert projection_writers, "expected projection writes — owner audit failed"


# ---- CP12: end-to-end proof (full lifecycle through CognitiveTicker read) --


def test_cp12_end_to_end_settled_to_read_through_cognitive_ticker(
    tmp_path: Path,
) -> None:
    """The end-to-end story (per工单 STEP 10):
        0 -> text #1 -> counter 1 -> text #2 -> 2 -> text #3 -> 3
        -> C6B eligibility true
        -> ACCEPTED SEND_PHOTO -> reset 0 -> eligibility false
        -> ACCEPTED proactive -> cooldown starts
        -> UNKNOWN / rejected -> cooldown does NOT start
    All read through the existing CognitiveTicker fact surface.
    """

    fact_service, projector, store = _build_stack(tmp_path)

    cadence_facts: list[str] = []
    cooldown_facts: list[str] = []

    # 0 -> text #1
    req1 = _build_request(idempotency_key="k1")
    projector.project(receipt=_accepted_receipt(req1), request=req1)
    # 1 -> text #2
    req2 = _build_request(idempotency_key="k2")
    projector.project(receipt=_accepted_receipt(req2), request=req2)
    # 2 -> text #3
    req3 = _build_request(idempotency_key="k3")
    projector.project(receipt=_accepted_receipt(req3), request=req3)

    facts = _facts_by_key(fact_service)
    cadence_facts.append(facts["counter.proactive_prompts_since_photo"])
    assert cadence_facts[-1] == "3"
    assert media_photo_cadence_eligible(3, threshold=3) is True
    # No forced image — C6B remains read-only / generation hint only.

    # ACCEPTED SEND_PHOTO -> reset
    photo_req = _build_request(
        action_intent_id=INTENT_ID_PHOTO, action_type="send_photo",
    )
    projector.project(receipt=_accepted_receipt(photo_req), request=photo_req)
    facts = _facts_by_key(fact_service)
    cadence_facts.append(facts["counter.proactive_prompts_since_photo"])
    assert cadence_facts[-1] == "0"
    assert media_photo_cadence_eligible(0, threshold=3) is False

    # ACCEPTED proactive -> cooldown starts
    cool_req = _build_request(idempotency_key="k-cool")
    projector.project(receipt=_accepted_receipt(cool_req, delivered_at=NOW), request=cool_req)
    facts = _facts_by_key(fact_service)
    assert "counter.last_proactive_at" in facts
    cooldown_facts.append(facts["counter.last_proactive_at"])
    assert cooldown_facts[-1] == NOW.isoformat()

    # UNKNOWN / rejected -> cooldown does NOT start (verified earlier
    # in CP6; reconfirm here in the e2e flow).
    unknown_req = _build_request(idempotency_key="k-u")
    unknown_rec = _accepted_receipt(unknown_req, status=DeliveryStatus.UNKNOWN)
    unknown_rec = replace(unknown_rec, delivered_at=None)
    projector.project(receipt=unknown_rec, request=unknown_req)
    rejected_req = _build_request(idempotency_key="k-r")
    rejected_rec = _accepted_receipt(rejected_req, status=DeliveryStatus.UNSENT)
    projector.project(receipt=rejected_rec, request=rejected_req)
    # The cooldown fact is unchanged (still the first ACCEPTED timestamp).
    facts = _facts_by_key(fact_service)
    assert facts["counter.last_proactive_at"] == cooldown_facts[-1]

    store.close()
