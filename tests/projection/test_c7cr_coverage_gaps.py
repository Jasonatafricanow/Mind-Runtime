"""C7C-R coverage-fill tests for fail-closed branches.

The C7C-R contract is "no silent default" — every defensive
guard in OperationalFactAdmission, the projector, and the
DeliveryRequest.__post_init__ raises rather than fabricating
state. These tests drive each raise path so the contract is
locked at 100% line + branch coverage.
"""

from __future__ import annotations

from dataclasses import replace as _dc_replace
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
    make_message_id,
    make_request_id,
)
from mind_runtime.facts.service import (
    FactIngestService,
    OperationalFactAdmission,
)
from mind_runtime.projection import (
    SettledActionProjector,
    SqliteProjectionStore,
)

NOW = datetime(2026, 8, 28, 12, 0, tzinfo=UTC)
SCOPE = Scope(domain=ScopeDomain.USER, user_id="u-c7cr-cov")
RUNTIME = "runtime-c7cr-cov"


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
        target="user-c7cr-cov",
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


# ---- DeliveryRequest.__post_init__: action_type must be a string ----------


def test_delivery_request_rejects_non_string_action_type() -> None:
    """action_type is documented as a string. A non-string (e.g.
    None) is fail-closed (the __post_init__ guard rejects it)."""
    with pytest.raises(ValueError, match="action_type must be a string"):
        DeliveryRequest(
            request_id="req-1",
            message_id="msg-1",
            scope=SCOPE,
            origin_runtime_id=RUNTIME,
            channel="weixin",
            target="u-1",
            action_type=None,  # type: ignore[arg-type]
            payload_bytes=b"x",
            created_at=NOW,
            sync=SyncFields(SCOPE, RUNTIME, "req-1", 1, "idem-1"),
        )


# ---- OperationalFactAdmission: scope-mismatch on request+receipt ----------


def test_opf_scope_mismatch_request_vs_receipt_refused(tmp_path: Path) -> None:
    """validate_scope refuses a request and receipt that disagree."""
    request = _build_request()
    receipt = _accepted_receipt(request)
    other_scope = Scope(domain=ScopeDomain.USER, user_id="u-other")
    with pytest.raises(ValueError, match="scope must match"):
        OperationalFactAdmission.validate_scope(
            evidence_scope=other_scope, request=request, receipt=receipt,
        )


def test_opf_scope_missing_request_refused(tmp_path: Path) -> None:
    """A request duck-typed without scope is refused (defense in
    depth: the authority contract must reject any caller that does
    not provide the full request/receipt identity)."""
    receipt = _accepted_receipt(_build_request())

    class _NoScope:
        action_type = "proactive_message"

    with pytest.raises(ValueError, match="must both carry a scope"):
        OperationalFactAdmission.validate_scope(
            evidence_scope=SCOPE, request=_NoScope(), receipt=receipt,
        )


# ---- OperationalFactAdmission: source_id must equal receipt_id ------------


def test_opf_source_id_mismatch_refused(tmp_path: Path) -> None:
    """validate_authority refuses when evidence.source_id does not
    equal receipt.receipt_id (the receipt is the only authority)."""
    request = _build_request(idempotency_key="opf-sid")
    receipt = _accepted_receipt(request)
    # The receipt is the only authority. A mismatched source_id is
    # a forgery — fail closed.
    evidence = Evidence(
        id="op-evidence-wrong",
        scope=SCOPE,
        origin_runtime_id=RUNTIME,
        source_type=OperationalFactAdmission.ALLOWED_SOURCE_TYPE,
        source_id="DIFFERENT_FROM_RECEIPT",  # mismatch
        authority_level=AuthorityLevel.SYSTEM,
        authority=Authority(
            scope=SCOPE, level=AuthorityLevel.SYSTEM,
            source_id="DIFFERENT_FROM_RECEIPT",
        ),
        occurred_at=NOW,
        received_at=NOW,
        payload={"key": "counter.last_proactive_at", "value": "1"},
        sync=SyncFields(
            SCOPE, RUNTIME, "op-evidence-wrong", 1, "idem-w",
        ),
    )
    with pytest.raises(ValueError, match="source_id must equal"):
        OperationalFactAdmission.validate_authority(evidence, request, receipt)


# ---- admit_operational_fact: defensive observed_at fallback fail-closed -


def test_admit_operational_fact_rejects_receipt_without_delivered_at(
    tmp_path: Path,
) -> None:
    """admit_operational_fact refuses a receipt with no delivered_at
    (no silent fabrication of observed_at). The settled-delivery
    authority contract is fail-closed."""
    fact_service = FactIngestService(clock=FakeClock(NOW))
    request = _build_request(idempotency_key="k-no-dt")
    receipt = _dc_replace(
        _accepted_receipt(request), delivered_at=None,
    )
    assert receipt.delivered_at is None
    with pytest.raises(ValueError, match="receipt.delivered_at"):
        fact_service.admit_operational_fact(
            key="counter.last_proactive_at", value="1",
            request=request, receipt=receipt,
        )


# ---- projector: no-facts-for-action returns skip_reason="no_facts" --------


def test_projector_legacy_empty_action_type_explicit_error_message(
    tmp_path: Path,
) -> None:
    """A request with action_type="" (the legacy unknown sentinel)
    is rejected with a clear error message naming the
    backfill-required next step."""
    fact_service = FactIngestService(clock=FakeClock(NOW))
    store = SqliteProjectionStore(tmp_path / "p.sqlite")
    projector = SettledActionProjector(
        fact_service=fact_service, projection_store=store,
        clock=FakeClock(NOW), runtime_id=RUNTIME,
    )
    request = _build_request(idempotency_key="k-empty", action_type="")
    receipt = _accepted_receipt(request)
    with pytest.raises(ValueError, match="legacy unknown"):
        projector.project(receipt=receipt, request=request)
    store.close()


# ---- DB schema: action_type column is the migration touchpoint ----------


def test_is_known_action_type_accepts_typed_only() -> None:
    """The known-action_type set is the two typed kinds; everything
    else (None, empty, free-form) returns False."""
    assert OperationalFactAdmission.is_known_action_type("proactive_message") is True
    assert OperationalFactAdmission.is_known_action_type("send_photo") is True
    assert OperationalFactAdmission.is_known_action_type("") is False
    assert OperationalFactAdmission.is_known_action_type(None) is False
    assert OperationalFactAdmission.is_known_action_type("random") is False
    assert OperationalFactAdmission.is_known_action_type(42) is False  # type: ignore[arg-type]


# ---- OPF: validate_action_type static guard --------------------------------


def test_opf_allowed_keys_surface_is_frozen() -> None:
    """The allow-list is a frozen surface; adding a new key requires
    updating both the class attr and the C7C-R test surface."""
    assert OperationalFactAdmission.ALLOWED_KEYS == frozenset(
        {
            "counter.last_proactive_at",
            "counter.proactive_prompts_since_photo",
        }
    )
    assert OperationalFactAdmission.ALLOWED_SOURCE_TYPE == "settled_action_projection"
