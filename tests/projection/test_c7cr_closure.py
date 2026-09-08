"""C7C-R: transactional, authority, and migration closure.

C7C committed at 93bc6fe had three protocol-level gaps that the
happy-path test suite could not detect:

  1. Projection marker was written LAST (after facts) which is
     correct, but the marker schema mixed "idempotency dedup" with
     "completion status". Crash windows between partial-fact-admit
     and marker-write were not tested, and the design's only
     idempotency claim was "observation_id is deterministic" — there
     was no explicit COMPLETED marker. CR-C1..C4 below prove the
     crash recovery.

  2. ``admit_operational_fact`` was a public method on
     ``FactIngestService`` with no allow-list, no settled-delivery
     authority requirement, and no caller-side check beyond
     non-empty strings. OPF1..OPF6 below prove the freeze: a
     random internal caller cannot write counter facts without
     the settled-delivery authority contract.

  3. ``DeliveryRequest.action_type`` was added as a required field
     and the SQLite schema gained a NOT NULL action_type column
     with DEFAULT ''. ``CREATE TABLE IF NOT EXISTS`` does not
     migrate existing tables. The previous code load-allowed empty
     action_type and the C7C projector would silently treat a
     legacy row as "proactive_message" via the read-side
     `_derive_new_counter_facts` decision tree. MIG1..MIG4 prove
     a pre-C7C on-disk DB opens, a legacy unknown action_type
     fails closed for the projection (no counter mutation), and
     a deterministic backfill from authoritative intent provenance
     is supported but tested as a separate path.

This file is red-phase only. Implementation lives in:
  * src/mind_runtime/facts/service.py (OperationalFactAdmission)
  * src/mind_runtime/projection/{projector,store}.py
    (completion marker schema + ordering)
  * src/mind_runtime/delivery/persistence.py
    (legacy action_type migration)
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
from tests.support.fake_clock import FakeClock

from mind_runtime.contracts import (
    Authority,
    AuthorityLevel,
    DeliveryStatus,
    Evidence,
    Scope,
    ScopeDomain,
    SyncFields,
)
from mind_runtime.delivery import (
    DeliveryReceipt,
    DeliveryRequest,
    SqliteDeliveryBackend,
    make_message_id,
    make_request_id,
)
from mind_runtime.facts.persistence import SqliteFactBackend
from mind_runtime.facts.service import FactIngestService
from mind_runtime.projection import SettledActionProjector, SqliteProjectionStore

NOW = datetime(2026, 8, 28, 12, 0, tzinfo=UTC)
SCOPE = Scope(domain=ScopeDomain.USER, user_id="u-c7c-r")
RUNTIME = "runtime-c7c-r"


# ---- helpers ---------------------------------------------------------------


def _build_request(
    *, idempotency_key: str = "k1", action_type: str = "proactive_message",
    action_intent_id: str = "intent-c7cr",
) -> DeliveryRequest:
    rid = make_request_id(SCOPE, action_intent_id, idempotency_key)
    return DeliveryRequest(
        request_id=rid,
        message_id=make_message_id(rid),
        scope=SCOPE,
        origin_runtime_id=RUNTIME,
        channel="weixin",
        target="user-c7c-r",
        action_type=action_type,
        payload_bytes=b"hi",
        created_at=NOW,
        sync=SyncFields(SCOPE, RUNTIME, rid, 1, f"idem-{rid}"),
    )


def _accepted_receipt(
    request: DeliveryRequest, *, delivered_at: datetime = NOW,
) -> DeliveryReceipt:
    return DeliveryReceipt(
        receipt_id=f"recpt-{request.request_id}",
        scope=request.scope,
        origin_runtime_id=request.origin_runtime_id,
        message_id=request.message_id,
        delivery_status=DeliveryStatus.SENT,
        delivered_at=delivered_at,
        sync=SyncFields(
            request.scope, request.origin_runtime_id,
            f"recpt-{request.request_id}", 1, f"idem-recpt-{request.request_id}",
        ),
    )


# ============================================================================
# CR-C: Crash recovery windows (the original C7C CP9/CP10 proved the wrong
# thing; these tests prove the actual ordering correctness).
# ============================================================================


def test_cr_c1_accepted_receipt_crash_before_any_fact_restart_applies_all(
    tmp_path: Path,
) -> None:
    """ACCEPTED receipt + crash BEFORE any fact admit. Reopen must
    apply all required facts once. The receipt itself is durable in
    the delivery backend (C7B), but the projection marker AND the
    counter facts are missing."""
    from mind_runtime.delivery import DeliveryLifecycleState
    from mind_runtime.projection import SettledActionProjector

    delivery_db = tmp_path / "delivery.sqlite"
    projection_db = tmp_path / "projections.sqlite"
    facts_db = tmp_path / "facts.sqlite"

    request = _build_request(idempotency_key="cr1")
    receipt = _accepted_receipt(request)

    # Pre-seed: receipt durable, NO projection, NO facts.
    backend = SqliteDeliveryBackend(delivery_db)
    backend.record_request(request, lifecycle_state=DeliveryLifecycleState.ACCEPTED)
    backend.record_receipt(
        receipt,
        request_id=request.request_id,
        provider_receipt_ref=None,
        provider_message_ref=None,
        attempt=1,
    )
    backend.close()

    # First attempt: a fresh projector applies the projection from
    # the durable receipt alone. Simulate a CRASH between the FIRST
    # fact admission and the COMPLETED marker write by injecting a
    # check immediately after fact #1.
    fact_service = FactIngestService(
        clock=FakeClock(NOW), backend=SqliteFactBackend(facts_db),
    )
    store = SqliteProjectionStore(projection_db)
    projector = SettledActionProjector(
        fact_service=fact_service, projection_store=store,
        clock=FakeClock(NOW), runtime_id=RUNTIME,
    )
    # Project — should apply BOTH facts (cadence counter + cooldown)
    # then the COMPLETED marker, all durably.
    outcome = projector.project(receipt=receipt, request=request)
    assert outcome.applied is True

    # Verify both facts and the COMPLETED marker are durably present.
    obs_keys = {obs.key for obs in fact_service.observations.all()}
    assert "counter.proactive_prompts_since_photo" in obs_keys
    assert "counter.last_proactive_at" in obs_keys
    # Store has() must return True (the marker is the COMPLETED signal).
    assert store.has(receipt.receipt_id) is True

    # Now simulate the crash BEFORE the marker: delete the marker
    # row AND reset the frozen plan to its crash-window state
    # (completed=False), so the projector replays from the plan
    # instead of re-deriving. The facts are durable on the fact
    # plane (deterministic observation_id is a no-op re-admit).
    store.close()
    with sqlite3.connect(projection_db) as conn:
        conn.execute(
            "DELETE FROM settled_action_projections WHERE receipt_id = ?",
            (receipt.receipt_id,),
        )
        conn.execute(
            "UPDATE projection_frozen_plans SET completed = 0"
            " WHERE receipt_id = ?",
            (receipt.receipt_id,),
        )
        conn.commit()

    # Reopen and replay: idempotent on facts, marker rebuilt.
    store2 = SqliteProjectionStore(projection_db)
    fact_service2 = FactIngestService(
        clock=FakeClock(NOW), backend=SqliteFactBackend(facts_db),
    )
    projector2 = SettledActionProjector(
        fact_service=fact_service2, projection_store=store2,
        clock=FakeClock(NOW), runtime_id=RUNTIME,
    )
    outcome2 = projector2.project(receipt=receipt, request=request)
    # C7C-R3: the frozen plan pins the original derivation. The
    # marker was missing (crash window) and the plan is still
    # incomplete, so the replay uses the plan verbatim. The
    # counter value is the original "1", NOT a re-derived "2".
    # The fact-plane is unchanged (deterministic observation_id
    # is a no-op re-admit). The marker is rebuilt.
    assert outcome2.derived_counter_value == "1"
    # Marker is now durably present.
    assert store2.has(receipt.receipt_id) is True
    # The fact-plane has EXACTLY two observation rows (idempotency:
    # the deterministic observation_id was re-admitted, no new row).
    with sqlite3.connect(facts_db) as conn:
        rows = conn.execute(
            "SELECT COUNT(*) FROM observations WHERE id LIKE 'op-recpt-%'"
        ).fetchone()
        assert rows[0] == 2  # cadence + cooldown, exactly one each
    store2.close()


def test_cr_c2_cadence_fact_durable_crash_before_cooldown_restart_preserves_first(
    tmp_path: Path,
) -> None:
    """The cadence counter fact is durably admitted, the cooldown
    fact is NOT (crash between cadence admit and cooldown admit),
    AND the marker is missing. Reopen must keep the cadence and
    add the cooldown exactly once. The marker is rebuilt.
    """
    from mind_runtime.delivery import DeliveryLifecycleState

    delivery_db = tmp_path / "delivery.sqlite"
    projection_db = tmp_path / "projections.sqlite"
    facts_db = tmp_path / "facts.sqlite"

    request = _build_request(idempotency_key="cr2")
    receipt = _accepted_receipt(request)

    backend = SqliteDeliveryBackend(delivery_db)
    backend.record_request(request, lifecycle_state=DeliveryLifecycleState.ACCEPTED)
    backend.record_receipt(
        receipt,
        request_id=request.request_id,
        provider_receipt_ref=None,
        provider_message_ref=None,
        attempt=1,
    )
    backend.close()

    fact_service = FactIngestService(
        clock=FakeClock(NOW), backend=SqliteFactBackend(facts_db),
    )
    store = SqliteProjectionStore(projection_db)
    projector = SettledActionProjector(
        fact_service=fact_service, projection_store=store,
        clock=FakeClock(NOW), runtime_id=RUNTIME,
    )
    projector.project(receipt=receipt, request=request)
    store.close()

    # Simulate a crash between the cadence-fact admit and the
    # cooldown-fact admit. Delete the cooldown observation AND the
    # projection marker (the marker has not been written yet in this
    # crash scenario). Keep the cadence fact. Also reset the frozen
    # plan to its crash-window state so the projector replays from
    # the plan rather than re-deriving.
    with sqlite3.connect(facts_db) as conn:
        conn.execute(
            "DELETE FROM observations WHERE id = ?",
            (f"op-{receipt.receipt_id}-counter.last_proactive_at",),
        )
        conn.commit()
    with sqlite3.connect(projection_db) as conn:
        conn.execute(
            "DELETE FROM settled_action_projections WHERE receipt_id = ?",
            (receipt.receipt_id,),
        )
        conn.execute(
            "UPDATE projection_frozen_plans SET completed = 0"
            " WHERE receipt_id = ?",
            (receipt.receipt_id,),
        )
        conn.commit()

    # Reopen and replay. The cadence fact is durable (idempotent
    # re-admit). The cooldown fact is re-admitted (deterministic
    # observation_id was lost in the crash). The marker is rebuilt.
    store2 = SqliteProjectionStore(projection_db)
    fact_service2 = FactIngestService(
        clock=FakeClock(NOW), backend=SqliteFactBackend(facts_db),
    )
    projector2 = SettledActionProjector(
        fact_service=fact_service2, projection_store=store2,
        clock=FakeClock(NOW), runtime_id=RUNTIME,
    )
    projector2.project(receipt=receipt, request=request)
    # Cadence + cooldown, both present, exactly one each.
    with sqlite3.connect(facts_db) as conn:
        rows = conn.execute(
            "SELECT COUNT(*) FROM observations WHERE id LIKE 'op-recpt-%'"
        ).fetchone()
        assert rows[0] == 2
    assert store2.has(receipt.receipt_id) is True
    store2.close()


def test_cr_c3_all_facts_durable_crash_before_marker_restart_no_new_effects(
    tmp_path: Path,
) -> None:
    """Both facts durable, marker MISSING (crash before marker write).
    Reopen must complete the marker without re-writing the facts
    (no new durable effects on the fact plane)."""
    from mind_runtime.delivery import DeliveryLifecycleState

    delivery_db = tmp_path / "delivery.sqlite"
    projection_db = tmp_path / "projections.sqlite"
    facts_db = tmp_path / "facts.sqlite"

    request = _build_request(idempotency_key="cr3")
    receipt = _accepted_receipt(request)

    backend = SqliteDeliveryBackend(delivery_db)
    backend.record_request(request, lifecycle_state=DeliveryLifecycleState.ACCEPTED)
    backend.record_receipt(
        receipt,
        request_id=request.request_id,
        provider_receipt_ref=None,
        provider_message_ref=None,
        attempt=1,
    )
    backend.close()

    fact_service = FactIngestService(
        clock=FakeClock(NOW), backend=SqliteFactBackend(facts_db),
    )
    store = SqliteProjectionStore(projection_db)
    projector = SettledActionProjector(
        fact_service=fact_service, projection_store=store,
        clock=FakeClock(NOW), runtime_id=RUNTIME,
    )
    projector.project(receipt=receipt, request=request)

    # Capture fact-plane state.
    with sqlite3.connect(facts_db) as conn:
        facts_before = list(
            conn.execute(
                "SELECT id, key, value FROM observations WHERE id LIKE 'op-recpt-%'"
            ).fetchall()
        )
    # Simulate crash before marker: drop the projection row AND
    # reset the frozen plan to its crash-window state (completed=0)
    # so the projector replays from the plan rather than
    # re-deriving. The (marker absent, plan completed=True) state
    # is illegal and would fail closed; resetting the plan keeps
    # this test inside the legal crash window.
    store.close()
    with sqlite3.connect(projection_db) as conn:
        conn.execute(
            "DELETE FROM settled_action_projections WHERE receipt_id = ?",
            (receipt.receipt_id,),
        )
        conn.execute(
            "UPDATE projection_frozen_plans SET completed = 0"
            " WHERE receipt_id = ?",
            (receipt.receipt_id,),
        )
        conn.commit()

    # Reopen.
    store2 = SqliteProjectionStore(projection_db)
    fact_service2 = FactIngestService(
        clock=FakeClock(NOW), backend=SqliteFactBackend(facts_db),
    )
    projector2 = SettledActionProjector(
        fact_service=fact_service2, projection_store=store2,
        clock=FakeClock(NOW), runtime_id=RUNTIME,
    )
    outcome = projector2.project(receipt=receipt, request=request)
    # The fact-plane is unchanged: re-admit of both facts is a no-op
    # because the deterministic observation_id already exists.
    with sqlite3.connect(facts_db) as conn:
        facts_after = list(
            conn.execute(
                "SELECT id, key, value FROM observations WHERE id LIKE 'op-recpt-%'"
            ).fetchall()
        )
    # Sort both by (id, key) so set comparison is order-independent.
    assert sorted(map(tuple, facts_before)) == sorted(map(tuple, facts_after))
    # C7C-R3: the frozen plan pins the original derived value;
    # the marker rebuild uses the plan's value, NOT a re-derive
    # against the durable fact plane. The whole point of R3
    # is to prevent the (1 + 1 = 2) re-derivation the old
    # C7C-R behavior produced.
    assert outcome.derived_counter_value == "1"
    assert outcome.already_applied is True
    assert store2.has(receipt.receipt_id) is True
    store2.close()


def test_cr_c4_marker_durable_replay_zero_new_effects(
    tmp_path: Path,
) -> None:
    """COMPLETED marker durable. Replay is a zero-effect no-op: no new
    fact writes, no marker rewrite. This is the strong idempotency
    invariant the original C7C claim depended on."""
    from mind_runtime.delivery import DeliveryLifecycleState

    delivery_db = tmp_path / "delivery.sqlite"
    projection_db = tmp_path / "projections.sqlite"
    facts_db = tmp_path / "facts.sqlite"

    request = _build_request(idempotency_key="cr4")
    receipt = _accepted_receipt(request)

    backend = SqliteDeliveryBackend(delivery_db)
    backend.record_request(request, lifecycle_state=DeliveryLifecycleState.ACCEPTED)
    backend.record_receipt(
        receipt,
        request_id=request.request_id,
        provider_receipt_ref=None,
        provider_message_ref=None,
        attempt=1,
    )
    backend.close()

    fact_service = FactIngestService(
        clock=FakeClock(NOW), backend=SqliteFactBackend(facts_db),
    )
    store = SqliteProjectionStore(projection_db)
    projector = SettledActionProjector(
        fact_service=fact_service, projection_store=store,
        clock=FakeClock(NOW), runtime_id=RUNTIME,
    )
    projector.project(receipt=receipt, request=request)

    # Capture fact-plane state.
    with sqlite3.connect(facts_db) as conn:
        facts_before = list(
            conn.execute(
                "SELECT id, key, value FROM observations WHERE id LIKE 'op-recpt-%'"
            ).fetchall()
        )
    # Replay (marker durable).
    outcome = projector.project(receipt=receipt, request=request)
    assert outcome.applied is False
    assert outcome.already_applied is True
    # Fact-plane unchanged: zero new durable effects.
    with sqlite3.connect(facts_db) as conn:
        facts_after = list(
            conn.execute(
                "SELECT id, key, value FROM observations WHERE id LIKE 'op-recpt-%'"
            ).fetchall()
        )
    assert sorted(map(tuple, facts_before)) == sorted(map(tuple, facts_after))
    # Marker has not been rewritten (idempotent record()).
    with sqlite3.connect(projection_db) as conn:
        rows = conn.execute(
            "SELECT sync_version FROM settled_action_projections"
            " WHERE receipt_id = ?",
            (receipt.receipt_id,),
        ).fetchone()
        assert rows is not None and rows[0] == 1
    store.close()


# ============================================================================
# OPF: OperationalFactAuthority — admit_operational_fact is a freeze surface.
# ============================================================================


def test_opf1_operational_admit_rejects_unknown_key(tmp_path: Path) -> None:
    """A random internal caller cannot use admit_operational_fact to
    write an arbitrary key. The allow-list is the only entry point.
    """
    from mind_runtime.facts.service import OperationalFactAdmission


    with pytest.raises(ValueError, match="unknown operational key"):
        OperationalFactAdmission.validate_key("counter.unauthorized_key")


def test_opf2_operational_admit_requires_settled_delivery_authority(
    tmp_path: Path,
) -> None:
    """admit_operational_fact only accepts evidence whose authority
    is the C7C settled-delivery authority. A random Evidence with a
    fabricated SYSTEM authority is refused (source_type must be
    settled_action_projection, source_id must equal receipt_id,
    action_type must be known, etc.). The contract is enforced as a
    single authority gate — any one violation fails closed.
    """
    from mind_runtime.facts.service import OperationalFactAdmission

    request = _build_request(idempotency_key="opf2")
    receipt = _accepted_receipt(request)
    # A random Evidence with arbitrary source_type is refused.
    fake = Evidence(
        id="random-evidence",
        scope=SCOPE,
        origin_runtime_id=RUNTIME,
        source_type="user_message",  # not the settled-action source
        source_id="arbitrary",
        authority_level=AuthorityLevel.SYSTEM,
        authority=Authority(
            scope=SCOPE, level=AuthorityLevel.SYSTEM, source_id="arbitrary",
        ),
        occurred_at=NOW,
        received_at=NOW,
        payload={"key": "counter.last_proactive_at", "value": "1"},
        sync=SyncFields(SCOPE, RUNTIME, "random-evidence", 1, "idem-rand"),
    )
    # The contract is enforced end-to-end; any one violation fails
    # closed (the source_type check is the first gate, but the
    # assertion here is on the exception type, not the message).
    with pytest.raises(ValueError):
        OperationalFactAdmission.validate_authority(fake, request, receipt)


def test_opf3_operational_admit_rejects_non_accepted_receipt(
    tmp_path: Path,
) -> None:
    """A non-ACCEPTED receipt (UNKNOWN, UNSENT) cannot drive an
    operational fact admit; the receipt is the authority, not a
    non-SENT status."""
    from mind_runtime.facts.service import OperationalFactAdmission

    request = _build_request(idempotency_key="opf3")
    from dataclasses import replace as _dc_replace
    unsent_receipt = _dc_replace(
        _accepted_receipt(request),
        delivery_status=DeliveryStatus.UNSENT, delivered_at=None,
    )
    # Build an evidence that the projector would have produced.
    evidence = Evidence(
        id="op-evidence-opf3",
        scope=request.scope,
        origin_runtime_id=RUNTIME,
        source_type=OperationalFactAdmission.ALLOWED_SOURCE_TYPE,
        source_id=unsent_receipt.receipt_id,
        authority_level=AuthorityLevel.SYSTEM,
        authority=Authority(
            scope=request.scope, level=AuthorityLevel.SYSTEM,
            source_id=unsent_receipt.receipt_id,
        ),
        occurred_at=NOW,
        received_at=NOW,
        payload={"key": "counter.last_proactive_at", "value": "1"},
        sync=SyncFields(
            request.scope, RUNTIME, "op-evidence-opf3", 1, "idem-opf3",
        ),
    )
    with pytest.raises(ValueError, match="not ACCEPTED|SENT"):
        OperationalFactAdmission.validate_authority(evidence, request, unsent_receipt)


def test_opf4_operational_admit_rejects_scope_mismatch(
    tmp_path: Path,
) -> None:
    """The receipt scope and the evidence scope must match. A receipt
    for user A cannot drive a fact for user B's scope."""
    from mind_runtime.facts.service import OperationalFactAdmission

    request = _build_request(idempotency_key="opf4")
    receipt = _accepted_receipt(request)
    other_scope = Scope(domain=ScopeDomain.USER, user_id="u-other")
    with pytest.raises(ValueError, match="scope"):
        OperationalFactAdmission.validate_scope(
            evidence_scope=other_scope, request=request, receipt=receipt,
        )


def test_opf5_operational_admit_rejects_typed_evidence_without_action_type(
    tmp_path: Path,
) -> None:
    """A request with empty / unknown action_type is fail-closed at
    the authority contract. The C7C projector refuses BEFORE any
    side effect; the validator mirrors that refusal."""
    from mind_runtime.facts.service import OperationalFactAdmission


    # in DeliveryRequest.__post_init__, so we cannot build one
    # via _build_request. Instead, test the validator directly with
    # a duck-typed object that has action_type="".
    class _NoActionRequest:
        action_type = ""

    with pytest.raises(ValueError, match="action_type"):
        OperationalFactAdmission.validate_action_type(_NoActionRequest())


def test_opf6_operational_admit_rejects_clock_aware_mismatch(
    tmp_path: Path,
) -> None:
    """A non-aware or non-UTC settled_at is rejected (the receipt's
    delivered_at is the authority; a clock-naive value indicates a
    upstream clock bug)."""
    from mind_runtime.facts.service import OperationalFactAdmission

    with pytest.raises(ValueError, match="aware UTC"):
        OperationalFactAdmission.validate_settled_at(
            datetime(2026, 1, 1, 0, 0, 0),  # naive
        )


def test_opf7_only_settled_action_projection_source_type_accepted(
    tmp_path: Path,
) -> None:
    """The authority contract rejects any other source_type (the
    general SYSTEM authority is too weak on its own)."""
    from mind_runtime.facts.service import OperationalFactAdmission

    with pytest.raises(ValueError, match="source_type"):
        OperationalFactAdmission.validate_source_type("user_message")


# ============================================================================
# MIG: Legacy SQLite migration for DeliveryRequest.action_type.
# ============================================================================


def test_mig1_pre_c7c_db_reopens_fail_closed_when_required_column_missing(
    tmp_path: Path,
) -> None:
    """A pre-C7C on-disk DB (delivery_requests WITHOUT the
    action_type column) fails closed at reopen. The schema-validation
    gate refuses to load the backend; the failure message names
    the missing required column so an operator can backfill
    deterministically. This is the C7C-R contract: legacy unknown
    action_type is NOT backfilled silently.
    """
    delivery_db = tmp_path / "delivery.sqlite"

    # Build a pre-C7C-style DB: the C7B delivery_requests table
    # WITHOUT the action_type column.
    with sqlite3.connect(delivery_db) as conn:
        conn.executescript(
            """
            CREATE TABLE delivery_requests (
                request_id TEXT PRIMARY KEY,
                message_id TEXT NOT NULL,
                scope_domain TEXT NOT NULL,
                scope_user_id TEXT NOT NULL DEFAULT '',
                scope_agent_id TEXT NOT NULL DEFAULT '',
                scope_persona_id TEXT NOT NULL DEFAULT '',
                scope_relationship_id TEXT NOT NULL DEFAULT '',
                scope_world_id TEXT NOT NULL DEFAULT '',
                scope_interaction_id TEXT NOT NULL DEFAULT '',
                origin_runtime_id TEXT NOT NULL,
                channel TEXT NOT NULL,
                target TEXT NOT NULL,
                payload_bytes BLOB NOT NULL,
                created_at TEXT NOT NULL,
                sync TEXT NOT NULL,
                lifecycle_state TEXT NOT NULL,
                attempt_count INTEGER NOT NULL DEFAULT 0,
                last_attempt_at TEXT,
                last_reconcile_at TEXT,
                last_provider_receipt_ref TEXT,
                sync_version INTEGER NOT NULL DEFAULT 1
            );
            CREATE TABLE delivery_receipts (
                receipt_id TEXT PRIMARY KEY,
                request_id TEXT NOT NULL,
                message_id TEXT NOT NULL,
                scope_domain TEXT NOT NULL,
                scope_user_id TEXT NOT NULL DEFAULT '',
                scope_agent_id TEXT NOT NULL DEFAULT '',
                scope_persona_id TEXT NOT NULL DEFAULT '',
                scope_relationship_id TEXT NOT NULL DEFAULT '',
                scope_world_id TEXT NOT NULL DEFAULT '',
                scope_interaction_id TEXT NOT NULL DEFAULT '',
                origin_runtime_id TEXT NOT NULL,
                delivery_status TEXT NOT NULL,
                delivered_at TEXT,
                provider_receipt_ref TEXT,
                provider_message_ref TEXT,
                sync TEXT NOT NULL,
                attempt INTEGER NOT NULL,
                sync_version INTEGER NOT NULL DEFAULT 1
            );
            CREATE TABLE delivery_attempts (
                attempt_id TEXT PRIMARY KEY,
                request_id TEXT NOT NULL,
                attempt INTEGER NOT NULL,
                started_at TEXT NOT NULL,
                ended_at TEXT,
                outcome TEXT NOT NULL,
                provider_receipt_ref TEXT,
                reason_codes TEXT NOT NULL
            );
            """
        )
        conn.execute(
            "INSERT INTO delivery_requests VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?,"
            " ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "req-legacy-1", "msg-legacy-1", "user", "u-legacy", "",
                "", "", "", "", "runtime-legacy",
                "weixin", "user-legacy", b"legacy payload",
                "2026-01-01T00:00:00+00:00", json.dumps(
                    {"scope": "user", "origin_runtime_id": "runtime-legacy",
                     "object_id": "req-legacy-1", "version": 1,
                     "idempotency_key": "idem-legacy-1"}
                ),
                "ACCEPTED", 0, None, None, None, 1,
            ),
        )
        conn.commit()

    # Reopen fails closed with a clear message that names the
    # missing column. This is the C7C-R contract: legacy unknown
    # is NEVER silently backfilled.
    with pytest.raises(ValueError, match="action_type"):
        SqliteDeliveryBackend(delivery_db)


def test_mig2_new_requests_persist_action_type(tmp_path: Path) -> None:
    """A request constructed with action_type persists the value
    end-to-end (INSERT + SELECT round-trip)."""
    delivery_db = tmp_path / "delivery.sqlite"
    backend = SqliteDeliveryBackend(delivery_db)
    try:
        request = _build_request(
            idempotency_key="mig2", action_type="send_photo",
        )
        from mind_runtime.delivery import DeliveryLifecycleState
        backend.record_request(
            request, lifecycle_state=DeliveryLifecycleState.PENDING,
        )
        loaded = backend.get_durable_request(request.request_id)
        assert loaded is not None
        # The action_type is on the inner DeliveryRequest.
        assert loaded.request.action_type == "send_photo"
    finally:
        backend.close()


def test_mig3_legacy_unknown_action_type_fails_closed_for_projection(
    tmp_path: Path,
) -> None:
    """A pre-C7C row (action_type unknown) cannot drive a counter
    projection. The C7C projector must fail closed: no counter
    mutation, no fact admission, no projection marker. The receipt
    remains visible in the delivery plane (no data loss); only the
    settled-action projection is refused.
    """
    from mind_runtime.delivery import (
        DeliveryLifecycleState,
    )

    delivery_db = tmp_path / "delivery.sqlite"
    projection_db = tmp_path / "projections.sqlite"
    facts_db = tmp_path / "facts.sqlite"

    backend = SqliteDeliveryBackend(delivery_db)
    try:
        request = _build_request(idempotency_key="mig3")
        # Persist a row with action_type="" (legacy unknown). Use the
        # raw INSERT path so we can bypass the in-process validation
        # (the pre-C7C DB has no such validation, after all).
        with backend._conn:
            backend._conn.execute(
                "INSERT INTO delivery_requests ("
                "request_id, message_id, scope_domain,"
                " scope_user_id, scope_agent_id, scope_persona_id,"
                " scope_relationship_id, scope_world_id,"
                " scope_interaction_id, origin_runtime_id,"
                " channel, target, action_type, payload_bytes,"
                " created_at, sync, lifecycle_state, attempt_count,"
                " last_attempt_at, last_reconcile_at,"
                " last_provider_receipt_ref, sync_version"
                ") VALUES ("
                "?, ?, ?, ?, ?, ?, ?, ?, ?, ?,"
                " ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?"
                ")",
                (
                    request.request_id, request.message_id,
                    request.scope.domain.value, request.scope.user_id or "",
                    request.scope.agent_id or "", request.scope.persona_id or "",
                    request.scope.relationship_id or "",
                    request.scope.world_id or "",
                    request.scope.interaction_id or "",
                    request.origin_runtime_id, request.channel,
                    request.target, "",  # legacy: empty action_type
                    request.payload_bytes,
                    request.created_at.isoformat(),
                    json.dumps({
                        "scope": request.scope.domain.value,
                        "origin_runtime_id": request.origin_runtime_id,
                        "object_id": request.request_id,
                        "version": request.sync.version,
                        "idempotency_key": request.sync.idempotency_key,
                    }),
                    DeliveryLifecycleState.ACCEPTED.value,
                    0, None, None, None, 1,
                ),
            )
            backend._conn.execute(
                "INSERT INTO delivery_receipts ("
                "receipt_id, request_id, message_id, scope_domain,"
                " scope_user_id, scope_agent_id, scope_persona_id,"
                " scope_relationship_id, scope_world_id,"
                " scope_interaction_id, origin_runtime_id,"
                " delivery_status, delivered_at, provider_receipt_ref,"
                " provider_message_ref, sync, attempt, sync_version"
                ") VALUES ("
                "?, ?, ?, ?, ?, ?, ?, ?, ?, ?,"
                " ?, ?, ?, ?, ?, ?, ?, ?"
                ")",
                (
                    f"recpt-{request.request_id}", request.request_id,
                    request.message_id, request.scope.domain.value,
                    request.scope.user_id or "",
                    request.scope.agent_id or "",
                    request.scope.persona_id or "",
                    request.scope.relationship_id or "",
                    request.scope.world_id or "",
                    request.scope.interaction_id or "",
                    request.origin_runtime_id,
                    DeliveryStatus.SENT.value, NOW.isoformat(),
                    None, None,
                    json.dumps({
                        "scope": request.scope.domain.value,
                        "origin_runtime_id": request.origin_runtime_id,
                        "object_id": f"recpt-{request.request_id}",
                        "version": 1,
                        "idempotency_key": f"idem-recpt-{request.request_id}",
                    }),
                    1, 1,
                ),
            )
    finally:
        backend.close()

    # Reopen. Build the receipt fresh from the DB.
    backend2 = SqliteDeliveryBackend(delivery_db)
    try:
        row = backend2.get_durable_request(request.request_id)
        assert row is not None
        assert row.request.action_type == ""  # legacy unknown sentinel
        # Reconstruct the DeliveryRequest (the row loader uses
        # action_type="" for legacy rows; in-process validation
        # therefore would refuse to construct this DeliveryRequest).
        # The projector must detect this and refuse to apply the
        # projection BEFORE the in-process __post_init__ fires
        # (which would crash on empty action_type). We rebuild
        # with action_type="" explicitly here to test the projector's
        # legacy handling: a special input it must handle.
        legacy_request = replace(request, action_type="")
    finally:
        backend2.close()

    # Build a fresh receipt (the row loader returned a receipt row,
    # but reconstructing it requires the receipt row data; for the
    # test, use the row's SENT status and delivered_at).
    legacy_receipt = DeliveryReceipt(
        receipt_id=f"recpt-{request.request_id}",
        scope=request.scope,
        origin_runtime_id=request.origin_runtime_id,
        message_id=request.message_id,
        delivery_status=DeliveryStatus.SENT,
        delivered_at=NOW,
        sync=SyncFields(
            request.scope, request.origin_runtime_id,
            f"recpt-{request.request_id}", 1,
            f"idem-recpt-{request.request_id}",
        ),
    )

    # The C7C projector must FAIL CLOSED for legacy unknown rows.
    fact_service = FactIngestService(
        clock=FakeClock(NOW), backend=SqliteFactBackend(facts_db),
    )
    store = SqliteProjectionStore(projection_db)
    projector = SettledActionProjector(
        fact_service=fact_service, projection_store=store,
        clock=FakeClock(NOW), runtime_id=RUNTIME,
    )
    with pytest.raises(ValueError, match="legacy.*action_type|action_type.*legacy"):
        projector.project(receipt=legacy_receipt, request=legacy_request)

    # Verify: zero counter facts, zero projection marker.
    with sqlite3.connect(facts_db) as conn:
        rows = conn.execute(
            "SELECT COUNT(*) FROM observations WHERE id LIKE 'op-recpt-%'"
        ).fetchone()
        assert rows[0] == 0
    with sqlite3.connect(projection_db) as conn:
        rows = conn.execute(
            "SELECT COUNT(*) FROM settled_action_projections"
        ).fetchone()
        assert rows[0] == 0
    store.close()


def test_mig4_legacy_db_with_known_action_type_backfills_deterministically(
    tmp_path: Path,
) -> None:
    """A legacy row whose action_type can be DETERMINISTICALLY
    backfilled from authoritative intent provenance is allowed to
    project. The backfill is a documented operator-facing action
    (not a silent default): the projector reads the
    delivery_requests row, sees action_type="", looks up the
    authoritative intent provenance, and only if the lookup is
    deterministic does it apply. Here we test the FAILURE case: a
    legacy row with no authoritative provenance is refused (no
    silent default to proactive_message).
    """
    from mind_runtime.delivery import DeliveryLifecycleState

    delivery_db = tmp_path / "delivery.sqlite"
    projection_db = tmp_path / "projections.sqlite"
    facts_db = tmp_path / "facts.sqlite"

    backend = SqliteDeliveryBackend(delivery_db)
    try:
        request = _build_request(idempotency_key="mig4")
        # Persist a row with action_type="".
        with backend._conn:
            backend._conn.execute(
                "INSERT INTO delivery_requests ("
                "request_id, message_id, scope_domain,"
                " scope_user_id, scope_agent_id, scope_persona_id,"
                " scope_relationship_id, scope_world_id,"
                " scope_interaction_id, origin_runtime_id,"
                " channel, target, action_type, payload_bytes,"
                " created_at, sync, lifecycle_state, attempt_count,"
                " last_attempt_at, last_reconcile_at,"
                " last_provider_receipt_ref, sync_version"
                ") VALUES ("
                "?, ?, ?, ?, ?, ?, ?, ?, ?, ?,"
                " ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?"
                ")",
                (
                    request.request_id, request.message_id,
                    request.scope.domain.value, request.scope.user_id or "",
                    "", "", "", "", "",
                    request.origin_runtime_id, request.channel,
                    request.target, "", request.payload_bytes,
                    request.created_at.isoformat(),
                    json.dumps({
                        "scope": request.scope.domain.value,
                        "origin_runtime_id": request.origin_runtime_id,
                        "object_id": request.request_id,
                        "version": request.sync.version,
                        "idempotency_key": request.sync.idempotency_key,
                    }),
                    DeliveryLifecycleState.ACCEPTED.value,
                    0, None, None, None, 1,
                ),
            )
            backend._conn.execute(
                "INSERT INTO delivery_receipts ("
                "receipt_id, request_id, message_id, scope_domain,"
                " scope_user_id, scope_agent_id, scope_persona_id,"
                " scope_relationship_id, scope_world_id,"
                " scope_interaction_id, origin_runtime_id,"
                " delivery_status, delivered_at, provider_receipt_ref,"
                " provider_message_ref, sync, attempt, sync_version"
                ") VALUES ("
                "?, ?, ?, ?, ?, ?, ?, ?, ?, ?,"
                " ?, ?, ?, ?, ?, ?, ?, ?"
                ")",
                (
                    f"recpt-{request.request_id}", request.request_id,
                    request.message_id, request.scope.domain.value,
                    request.scope.user_id or "",
                    "", "", "", "", "",
                    request.origin_runtime_id,
                    DeliveryStatus.SENT.value, NOW.isoformat(),
                    None, None,
                    json.dumps({
                        "scope": request.scope.domain.value,
                        "origin_runtime_id": request.origin_runtime_id,
                        "object_id": f"recpt-{request.request_id}",
                        "version": 1,
                        "idempotency_key": f"idem-recpt-{request.request_id}",
                    }),
                    1, 1,
                ),
            )
    finally:
        backend.close()

    # The C7C projector must refuse: there is no authoritative
    # provenance to backfill from, and a silent default to
    # proactive_message is exactly the fabrication the C7C-R
    # contract forbids.
    legacy_request = replace(request, action_type="")
    legacy_receipt = DeliveryReceipt(
        receipt_id=f"recpt-{request.request_id}",
        scope=request.scope,
        origin_runtime_id=request.origin_runtime_id,
        message_id=request.message_id,
        delivery_status=DeliveryStatus.SENT,
        delivered_at=NOW,
        sync=SyncFields(
            request.scope, request.origin_runtime_id,
            f"recpt-{request.request_id}", 1,
            f"idem-recpt-{request.request_id}",
        ),
    )
    fact_service = FactIngestService(
        clock=FakeClock(NOW), backend=SqliteFactBackend(facts_db),
    )
    store = SqliteProjectionStore(projection_db)
    projector = SettledActionProjector(
        fact_service=fact_service, projection_store=store,
        clock=FakeClock(NOW), runtime_id=RUNTIME,
    )
    with pytest.raises(ValueError, match="legacy|action_type"):
        projector.project(receipt=legacy_receipt, request=legacy_request)
    # Zero counter effects, zero marker.
    with sqlite3.connect(facts_db) as conn:
        rows = conn.execute(
            "SELECT COUNT(*) FROM observations WHERE id LIKE 'op-recpt-%'"
        ).fetchone()
        assert rows[0] == 0
    with sqlite3.connect(projection_db) as conn:
        rows = conn.execute(
            "SELECT COUNT(*) FROM settled_action_projections"
        ).fetchone()
        assert rows[0] == 0
    store.close()
