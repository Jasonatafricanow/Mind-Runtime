"""C9-W1B-R2: Wiring Reconciliation Regression

Proves that the retired external-memory authority wiring has been removed
from TurnOrchestrator and that C9-W1B Pending Working Overlay behavior
is preserved.

ADR-0013: External Context Authority — NO SEPARATE SEAM.

Authoritative base: w/c7a-delivery-contract at C9-W1B-R2 implementation HEAD.
"""

from __future__ import annotations

from datetime import UTC, datetime


class _FakeClock:
    def now(self) -> datetime:
        return datetime(2026, 1, 1, tzinfo=UTC)


class _FakeTrace:
    def add_event(self, *args, **kwargs) -> None:
        return None


# Test A — clean construction
def test_orchestrator_constructs_without_untracked_memory_files():
    """TurnOrchestrator() must construct on committed HEAD with no workspace memory/*."""
    from mind_runtime.pipeline.orchestrator import TurnOrchestrator

    orch = TurnOrchestrator(clock=_FakeClock(), trace=_FakeTrace())
    assert orch is not None


# Test B — no retired default construction
def test_constructor_does_not_require_default_external_memory_authority():
    """Source/runtime proof: DefaultExternalMemoryAuthority default path is gone."""
    import inspect

    from mind_runtime.pipeline import orchestrator

    src = inspect.getsource(orchestrator.TurnOrchestrator.__init__)
    # The retired default construction path is removed:
    #   self._em_authority = external_memory_authority or DefaultExternalMemoryAuthority()
    assert "DefaultExternalMemoryAuthority()" not in src, (
        "Constructor still references retired DefaultExternalMemoryAuthority default"
    )


# Test C — no retired gate call
def test_orchestrator_run_does_not_call_gate_external_memory():
    """Production orchestrator must not call gate_external_memory."""
    import inspect

    from mind_runtime.pipeline import orchestrator

    src = inspect.getsource(orchestrator.TurnOrchestrator.run)
    assert "gate_external_memory" not in src, (
        "TurnOrchestrator.run still calls retired gate_external_memory"
    )


# Test D — pending path survives (write/read path is DEFERRED per d0d5f4f)
def test_pending_overlay_lifecycle_intact():
    """C9-W1B pending overlay write/read lifecycle is preserved unchanged."""
    from mind_runtime.contracts import Scope, ScopeDomain
    from mind_runtime.memory.pending import (
        PendingStatus,
        PendingWorkingEvidence,
        PendingWorkingOverlay,
    )

    overlay = PendingWorkingOverlay()
    user_scope = Scope(
        domain=ScopeDomain.USER,
        user_id="u1",
    )
    overlay.add(
        PendingWorkingEvidence(
            pending_id="p1",
            evidence_ref="e1",
            source_turn_id="t1",
            scope=user_scope,
            semantic_payload=(("k", "v"),),
            confidence=0.5,
            status=PendingStatus.PENDING,
            origin_runtime_id="runtime-1",
            source_text="text",
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
    )

    # PENDING visible
    pending_items = overlay.get_pending(scope=user_scope)
    assert len(pending_items) == 1
    assert pending_items[0].pending_id == "p1"

    # ACCEPT clears
    overlay.accept("p1")
    pending_after_accept = overlay.get_pending(scope=user_scope)
    assert len(pending_after_accept) == 0

    # Reject path also intact
    overlay.add(
        PendingWorkingEvidence(
            pending_id="p2",
            evidence_ref="e2",
            source_turn_id="t1",
            scope=user_scope,
            semantic_payload=(("k", "v"),),
            confidence=0.5,
            status=PendingStatus.PENDING,
            origin_runtime_id="runtime-1",
            source_text="text",
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
    )
    overlay.reject("p2")
    pending_after_reject = overlay.get_pending(scope=user_scope)
    assert len(pending_after_reject) == 0


# Test E — rejected/absent pending remains absent
def test_no_pending_fabrication_when_overlay_absent():
    """No fabrication when pending_overlay is not configured."""
    from mind_runtime.pipeline.orchestrator import TurnOrchestrator

    orch = TurnOrchestrator(clock=_FakeClock(), trace=_FakeTrace())
    # Pending overlay is None by default
    assert orch._pending_overlay is None


# Test F — compatibility slots are inert
def test_external_memory_compatibility_slots_are_inert():
    """Injected external_memory_authority / external_memory_reference_store
    are stored verbatim and do not invoke any retired default construction.
    """
    from mind_runtime.pipeline.orchestrator import TurnOrchestrator

    sentinel_authority = object()
    sentinel_store = object()
    orch = TurnOrchestrator(
        clock=_FakeClock(),
        trace=_FakeTrace(),
        external_memory_authority=sentinel_authority,
        external_memory_reference_store=sentinel_store,
    )
    assert orch._em_authority is sentinel_authority
    assert orch._em_reference_store is sentinel_store


# Test G — run path does not pass authorized_external_items
def test_run_path_does_not_pass_authorized_external_items():
    """Orchestrator's run() path does not pass a stale authorized_external_items field."""
    import inspect

    from mind_runtime.pipeline import orchestrator

    src = inspect.getsource(orchestrator.TurnOrchestrator.run)
    assert "authorized_external_items" not in src, (
        "TurnOrchestrator.run still passes retired authorized_external_items"
    )


# Test H — constructor signature preserves compatibility params (no signature churn)
def test_constructor_signature_preserves_compatibility_params():
    """external_memory_authority and external_memory_reference_store
    parameters are preserved as inert compatibility slots.
    """
    import inspect

    from mind_runtime.pipeline.orchestrator import TurnOrchestrator

    sig = inspect.signature(TurnOrchestrator.__init__)
    assert "external_memory_authority" in sig.parameters
    assert "external_memory_reference_store" in sig.parameters
    # Defaults must be None (no automatic construction)
    assert sig.parameters["external_memory_authority"].default is None
    assert sig.parameters["external_memory_reference_store"].default is None