"""HI-1: MindRuntimeHostPort — the public Host contract.

This is the public, vendor-neutral integration surface for any Agent
Host (Hermes, OpenClaw, custom). The contract is the only thing a Host
is allowed to import from MR; all other types are MR internals.

The port is implemented by `mind_runtime.host.runtime_adapter.MindRuntimeHostAdapter`
which wraps the existing production `TurnOrchestrator`. The adapter is
the only consumer of the orchestrator from a Host perspective.

Do NOT widen this surface without re-running the HI-1 contract review.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from mind_runtime.contracts.host import (
    HostAbortReceipt,
    HostAbortRequest,
    HostCommitReceipt,
    HostCommitRequest,
    HostInspectRequest,
    HostInspectResult,
    HostProactiveTurnResult,
    HostProviderProseRequest,
    HostProviderProseResult,
    HostTurnRequest,
    HostTurnResult,
    HostWakeNotification,
)
from mind_runtime.contracts.intent import WakeSignal


@runtime_checkable
class MindRuntimeHostPort(Protocol):
    """PUBLIC. The thin Host → MR contract.

    Four operations:

      begin_turn(request)    : start a turn for a given interaction.
                              Returns a HostTurnResult with a debug_ref
                              and (when available) a decision_context_ref.
      commit_turn(request)   : promote the turn's projection to canonical.
                              Returns a HostCommitReceipt. Idempotent on
                              the same interaction_id.
      abort_turn(request)    : discard the cognitive projection. Durable
                              facts survive. Returns a HostAbortReceipt.
                              Idempotent on the same interaction_id.
      inspect(request)       : read-only correlation view. No side
                              effects. Returns a HostInspectResult.

    `tick()` is intentionally NOT in MVP. A proactive runtime is a
    separate ticket and would expand the surface; the HI-1 contract
    must not grow speculatively.

    The port is a Protocol so Hosts can be unit-tested with a fake
    implementation; the production implementation is
    `MindRuntimeHostAdapter`.
    """

    def begin_turn(self, request: HostTurnRequest) -> HostTurnResult:
        ...

    def commit_turn(self, request: HostCommitRequest) -> HostCommitReceipt:
        ...

    def guard_provider_prose(self, request: HostProviderProseRequest) -> HostProviderProseResult:
        """SURFACE_V1: evaluate provider prose before external message delivery."""
        ...

    def abort_turn(self, request: HostAbortRequest) -> HostAbortReceipt:
        ...

    def inspect(self, request: HostInspectRequest) -> HostInspectResult:
        ...

    def consume_wake(self, wake: WakeSignal) -> HostWakeNotification:
        """HI-1: Smallest typed consumer of proactive wake signals at the Host boundary."""
        ...

    def run_proactive_turn(self, wake: WakeSignal) -> HostProactiveTurnResult:
        """HI-1: Execute a proactive Body turn following wake admission."""
        ...
