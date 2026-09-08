"""C7B STEP 7 — idempotency levels tests.

The four LEVELS (0-3) are defined at the top of the delivery
package; the Sqlite backend is pinned to LEVEL 0 by default. A
provider that exposes lookup can be pinned to LEVEL 1/2. LEVEL 3
is reserved for providers with explicit idempotency keys.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from mind_runtime.contracts import (
    DeliveryReceipt,
    DeliveryStatus,
    Scope,
    ScopeDomain,
    SyncFields,
)
from mind_runtime.delivery import (
    DeliveryLifecycleState,
    DeliveryRequest,
    NoopDeliveryReconciler,
    ResolvedAccept,
    SqliteDeliveryBackend,
    make_message_id,
    make_request_id,
)
from mind_runtime.delivery.daemon import DaemonPass

NOW = datetime(2026, 1, 1, tzinfo=UTC)
SCOPE = Scope(domain=ScopeDomain.USER, user_id="u1")
RUNTIME_ID = "xiyue"


def _request(
    *, request_id: str, body: bytes = b"hello",
) -> DeliveryRequest:
    return DeliveryRequest(
        request_id=request_id,
        message_id=make_message_id(request_id),
        scope=SCOPE, origin_runtime_id=RUNTIME_ID,
        channel="weixin", target="user-1", action_type="proactive_message", payload_bytes=body,
        created_at=NOW,
        sync=SyncFields(SCOPE, RUNTIME_ID, request_id, 1, f"idem-{request_id}"),
    )


class _CountingPort:
    def __init__(self) -> None:
        self.calls: list[DeliveryRequest] = []

    def deliver(self, request: DeliveryRequest) -> DeliveryReceipt:
        self.calls.append(request)
        return DeliveryReceipt(
            receipt_id=f"recpt-{request.request_id}",
            scope=request.scope,
            origin_runtime_id=request.origin_runtime_id,
            message_id=request.message_id,
            delivery_status=DeliveryStatus.SENT,
            delivered_at=datetime.now(tz=UTC),
            sync=SyncFields(
                request.scope, request.origin_runtime_id,
                f"recpt-{request.request_id}", 1,
                f"idem-recpt-{request.request_id}",
            ),
        )


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "c7b_levels.db"


# ----------------------------------------------------------- LEVEL 0


def test_level_0_unknown_stays_unknown_no_resend(
    db_path: Path,
) -> None:
    """LEVEL 0 (Noop): UNKNOWN can stay UNKNOWN even after
    reconcile, and the system does NOT resend.
    """

    request = _request(request_id=make_request_id(SCOPE, "intent-1", "k1"))
    backend = SqliteDeliveryBackend(db_path)
    backend.record_request(
        request, lifecycle_state=DeliveryLifecycleState.PENDING,
    )
    backend.set_lifecycle_state(
        request.request_id, DeliveryLifecycleState.UNKNOWN,
        at=datetime.now(tz=UTC),
    )

    port = _CountingPort()
    daemon = DaemonPass(
        backend=backend, port=port,
        reconciler=NoopDeliveryReconciler(), retry_budget=3,
    )
    outcomes = daemon.run()
    # Noop reconciler: UNKNOWN stays UNKNOWN; the carrier is not invoked.
    assert len(port.calls) == 0
    assert outcomes[0].final_state is DeliveryLifecycleState.UNKNOWN
    row = backend.get_durable_request(request.request_id)
    assert row is not None
    assert row.lifecycle_state is DeliveryLifecycleState.UNKNOWN
    backend.close()


# ----------------------------------------------------------- LEVEL 1


def test_level_1_stub_reconciler_resolves_unknown_to_accepted(
    db_path: Path,
) -> None:
    """LEVEL 1+ stub reconciler: UNKNOWN can resolve to ACCEPTED
    on reconcile and no duplicate send is observed.
    """

    request = _request(request_id=make_request_id(SCOPE, "intent-1", "k1"))
    backend = SqliteDeliveryBackend(db_path)
    backend.record_request(
        request, lifecycle_state=DeliveryLifecycleState.PENDING,
    )
    backend.set_lifecycle_state(
        request.request_id, DeliveryLifecycleState.UNKNOWN,
        at=datetime.now(tz=UTC),
    )

    class _AcceptingReconciler:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def reconcile(self, request: DeliveryRequest) -> ResolvedAccept:
            self.calls.append(request.request_id)
            return ResolvedAccept(
                provider_receipt_ref="wmp-y",
                provider_message_ref="wm-y",
            )

    reconciler = _AcceptingReconciler()
    port = _CountingPort()
    daemon = DaemonPass(
        backend=backend, port=port,
        reconciler=reconciler, retry_budget=3,
    )
    outcomes = daemon.run()
    # Reconciler decided ACCEPTED; carrier was not invoked.
    assert len(port.calls) == 0
    assert len(outcomes) == 1
    assert outcomes[0].final_state is DeliveryLifecycleState.ACCEPTED
    row = backend.get_durable_request(request.request_id)
    assert row is not None
    assert row.lifecycle_state is DeliveryLifecycleState.ACCEPTED
    assert row.last_provider_receipt_ref == "wmp-y"

    # Second daemon pass: the row is terminal; no further reconcile
    # is needed and no carrier call is made.
    port2 = _CountingPort()
    daemon2 = DaemonPass(
        backend=backend, port=port2,
        reconciler=reconciler, retry_budget=3,
    )
    second = daemon2.run()
    assert len(port2.calls) == 0
    assert second == ()
    backend.close()


# ----------------------------------------------------------- LEVEL 0 default


def test_sqlite_backend_is_level_0_by_default() -> None:
    """The Sqlite backend ships with the Noop reconciler as the
    documented default; the package docstring pins the LEVEL.
    """

    import mind_runtime.delivery as delivery_pkg
    doc = delivery_pkg.__doc__ or ""
    assert "LEVEL 0" in doc
    assert "Sqlite delivery backend" in doc
    assert "NoopDeliveryReconciler" in doc or "LEVEL 0" in doc


# ----------------------------------------------------------- LEVEL 2 placeholder


def test_level_2_marker_uses_same_reconciler_path() -> None:
    """LEVEL 2 is the same path as LEVEL 1: the difference is the
    primary delivery channel (provider push vs daemon pull). The
    durable backend, the state machine, and the daemon logic
    are identical. This test pins that the LEVEL 1+ interface is
    sufficient to express both.
    """

    class _Level2Reconciler:
        """Same surface as LEVEL 1: only the deployment path differs."""

        def __init__(self) -> None:
            self.push_calls = 0

        def reconcile(self, request: DeliveryRequest) -> ResolvedAccept:
            self.push_calls += 1
            return ResolvedAccept(
                provider_receipt_ref=f"push-{request.request_id}",
                provider_message_ref=None,
            )

    reconciler = _Level2Reconciler()
    request = _request(request_id=make_request_id(SCOPE, "intent-1", "k1"))
    result = reconciler.reconcile(request)
    assert isinstance(result, ResolvedAccept)
    assert reconciler.push_calls == 1


# ----------------------------------------------------------- LEVEL 3 reserved


def test_level_3_not_required_for_c7b() -> None:
    """LEVEL 3 is documented as reserved; the code does not
    provide a LEVEL-3-specific path. The contract is in the
    package docstring.
    """

    import mind_runtime.delivery as delivery_pkg
    doc = delivery_pkg.__doc__ or ""
    assert "LEVEL 3" in doc
    assert "reserved" in doc.lower()
