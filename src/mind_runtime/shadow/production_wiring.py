"""C8C-B — Continuous production shadow wiring.

Default-OFF audit-only tap that, when enabled, runs the existing
SafeShadowRunner against a copy of the production Interaction after the
production commit. Persists a durable ShadowRunRecord. Has zero
cognitive authority, zero body side effect, and zero production coupling.

Architecture Lock reference:
  docs/architecture/MR_ARCHITECTURE_LOCK_v1_2_COMPLETE.md
  docs/research/c8c/C8C_AUDIT_v1.md
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from mind_runtime.contracts import Interaction
from mind_runtime.pipeline.trace import TraceRecorder
from mind_runtime.providers.clock import Clock
from mind_runtime.shadow import (
    HostOutcome,
    SafeShadowRunner,
    ShadowRecordStore,
    ShadowRunRecord,
    ShadowRunResult,
)

PRODUCTION_SHADOW_ENV = "MIND_RUNTIME_PRODUCTION_SHADOW"


def production_shadow_enabled() -> bool:
    """Default-OFF gate. Returns True only when env is set to a truthy value.

    Mirrors the convention used by ``MIND_RUNTIME_PRODUCTION_INGEST`` and
    ``MIND_RUNTIME_PROACTIVE_TICK`` in the same package.
    """
    raw = os.environ.get(PRODUCTION_SHADOW_ENV)
    if raw is None:
        return False
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class ShadowTapReport:
    """Per-pass counters for the production shadow tap.

    Counters track INVOCATIONS only, never cognitive outcomes. All
    fields are opt-in: a tap that is never wired leaves them at zero.
    """

    shadow_invoked: int = 0
    shadow_completed: int = 0
    shadow_failed: int = 0


class ProductionShadowTap:
    """Default-OFF audit-only tap over an existing SafeShadowRunner.

    Lifecycle: constructed once, used many times. The tap owns no
    external resource requiring a shutdown() method. State is held in
    the SafeShadowRunner and ShadowRecordStore it composes.

    Failure isolation: any exception inside ``tap()`` is caught and
    recorded in the per-pass report. Production callers never see
    a shadow exception propagated.
    """

    def __init__(
        self,
        *,
        runner: SafeShadowRunner,
        record_store: ShadowRecordStore,
        clock: Clock,
        trace: TraceRecorder,
        enabled: bool = False,
    ) -> None:
        self._runner = runner
        self._record_store = record_store
        self._clock = clock
        self._trace = trace
        self._enabled = enabled

    @property
    def enabled(self) -> bool:
        return self._enabled

    @classmethod
    def from_env(
        cls,
        *,
        clock: Clock,
        trace: TraceRecorder,
        record_store: ShadowRecordStore,
        runtime_id: str = "production-shadow",
    ) -> ProductionShadowTap:
        """Build a tap whose ``enabled`` follows ``MIND_RUNTIME_PRODUCTION_SHADOW``."""
        return cls(
            runner=SafeShadowRunner(
                clock=clock,
                trace=trace,
                record_store=record_store,
                runtime_id=runtime_id,
                shadow_enabled=production_shadow_enabled(),
            ),
            record_store=record_store,
            clock=clock,
            trace=trace,
            enabled=production_shadow_enabled(),
        )

    def tap(
        self,
        interaction: Interaction,
        *,
        host_outcome: HostOutcome | None = None,
        report: ShadowTapReport | None = None,
    ) -> ShadowRunResult | None:
        """Run one shadow observation for the given production interaction.

        Returns the ShadowRunResult on success, or None when the tap is
        disabled. Never raises. Records a FAILED ShadowRunRecord when the
        runner itself cannot complete, and writes it to the durable store
        before returning None.
        """
        if report is not None:
            report.shadow_invoked += 1

        if not self._enabled:
            return None

        try:
            result = self._runner.execute(interaction, host_outcome=host_outcome)
        except Exception as exc:  # noqa: BLE001
            # Production must never see a shadow exception. Record FAILED
            # for audit, then swallow.
            self._record_failure(interaction, exc)
            if report is not None:
                report.shadow_failed += 1
            return None

        # SafeShadowRunner.execute() already persisted the record via
        # record_store.save(); no second write here.
        if report is not None:
            if result.succeeded:
                report.shadow_completed += 1
            else:
                report.shadow_failed += 1
        return result

    def _record_failure(self, interaction: Interaction, exc: Exception) -> None:
        """Persist a FAILED ShadowRunRecord for a runner-level exception.

        Used only when ``SafeShadowRunner.execute`` itself raises (e.g.
        the runner was not properly constructed, or an unexpected error
        escaped its internal try/except). C8B-R already records
        FAILED records for lifecycle failures inside execute(); this
        path covers the narrower "runner construction/execution raised"
        case.
        """
        from mind_runtime.shadow.contracts import ShadowStatus

        runtime_digest = self._runner.runtime_id
        started_at = self._clock.now()
        completed_at = self._clock.now()
        record = ShadowRunRecord(
            shadow_run_id=f"shadow-fail-{interaction.interaction_id}",
            scope=f"{interaction.scope.domain.value}@{interaction.scope.user_id}",
            source_interaction_id=interaction.interaction_id,
            source_event_ref=None,
            runtime_config_digest=runtime_digest,
            started_at=started_at,
            completed_at=completed_at,
            status=ShadowStatus.FAILED,
            failure_stage="production_tap",
            failure_reason=f"{type(exc).__name__}: {exc}",
        )
        try:
            self._record_store.save(record)
        except Exception:  # noqa: BLE001
            # Persistence failure here is also non-authoritative. Swallow.
            pass
