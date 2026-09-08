"""Settled-action projector (C7C).

The single writer that converts an ACCEPTED delivery receipt into
an operational fact on the existing FactIngestService plane. The
CognitiveTicker and the C6B cadence rule stay read-only over the
counter facts; this is the only code that ever mutates them.

Hard contract:
  * Only ACCEPTED receipts drive a projection.
  * Idempotency is bound to receipt_id (NOT wall-clock); the durable
    SqliteProjectionStore is the only idempotency record.
  * Cadence semantics follow docs/legacy/kayla-rule-map.md:
      - settled proactive text -> counter.proactive_prompts_since_photo ++
      - settled SEND_PHOTO      -> counter.proactive_prompts_since_photo := 0
  * Cooldown:
      - settled proactive text -> counter.last_proactive_at := settled_at
  * Crash windows: the durable idempotency record is the single
    source of truth; a fresh projector on a fresh disk must reach
    the same conclusion (already_applied) when the same receipt is
    projected twice.

The projector NEVER writes to any counter table directly. It only
admit()s through FactIngestService and only records()s to
SqliteProjectionStore. The factory is fail-closed: invalid args
raise before any side effect.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from mind_runtime.contracts import (
    DeliveryReceipt,
    DeliveryStatus,
    Scope,
)
from mind_runtime.contracts.common import (
    require_aware_utc,
)
from mind_runtime.delivery import DeliveryRequest
from mind_runtime.facts.service import FactIngestService, OperationalFactAdmission
from mind_runtime.projection.store import (
    FrozenPlan,
    ProjectionRecord,
    SqliteProjectionStore,
)

# The projector is a runtime-owned authority writer. The values it
# writes are operationally attested by the delivery receipt itself
# (provider-accepted timestamp, immutable bytes), so ASSERTED is
# the correct level: the receipt IS the proof. The Authority scope
# is rebuilt per admission so it matches the request scope exactly.
_FACT_AUTHORITY_SOURCE = "settled_action_projection"


# ---- doorways --------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ProjectionOutcome:
    """The single return shape for SettledActionProjector.project()."""

    applied: bool
    """True if a new fact was admitted and an idempotency record was written."""

    already_applied: bool
    """True if a prior projection of the same receipt was found
    in the durable store; the side effects were skipped (no fact, no
    idempotency record)."""

    derived_counter_key: str
    """The counter fact key the projector would have written
    (e.g. 'counter.proactive_prompts_since_photo'). Set on
    applied=True and on already_applied=True so callers can see
    the stable counter identifier; empty on skip paths."""

    derived_settled_at: datetime | None
    """The provider-accepted timestamp the projector used; None on
    skip paths (the receipt was not ACCEPTED)."""

    skip_reason: str | None
    """A short code explaining the no-op path, or None if applied.
    One of: not_accepted (UNKNOWN/REJECTED/FAILED_RETRYABLE/etc.)."""

    derived_counter_value: str = field(default="")
    """The value of the counter fact admitted (the new count or
    timestamp). Empty on skip paths."""


# ---- internal helpers ------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _DerivedFact:
    fact_key: str
    fact_value: str


# ---- ports -----------------------------------------------------------------


class _ClockPort(Protocol):
    def now(self) -> datetime: ...


class _FaultHook(Protocol):
    """Test-only hook: receives (receipt, request) and either
    returns (no-op) or raises to simulate a crash at the precise
    post-plan, pre-first-admission boundary. This is NOT a
    process-kill test; it is an in-process injection at the
    fault window R3 promises to close. Real OS-level kill /
    SQLite reopen / restart evidence is a separate W (C11 soak)."""

    def __call__(
        self, *, receipt: DeliveryReceipt, request: DeliveryRequest,
    ) -> None: ...


# ---- projector --------------------------------------------------------------


class SettledActionProjector:
    """The single writer for the C5B/C6B counter plane.

    Construction is fail-closed: invalid args raise before any
    side effect. The projector is the only place in the codebase
    that may admit a counter fact.
    """

    _CADENCE_COUNTER_KEY = "counter.proactive_prompts_since_photo"
    _COOLDOWN_FACT_KEY = "counter.last_proactive_at"

    def __init__(
        self,
        *,
        fact_service: FactIngestService,
        projection_store: SqliteProjectionStore,
        clock: _ClockPort,
        runtime_id: str = "runtime-c7c",
    ) -> None:
        if not isinstance(fact_service, FactIngestService):
            raise ValueError("fact_service must be a FactIngestService")
        if not isinstance(projection_store, SqliteProjectionStore):
            raise ValueError("projection_store must be a SqliteProjectionStore")
        if not isinstance(runtime_id, str) or not runtime_id.strip():
            raise ValueError("runtime_id must be a non-empty string")
        require_aware_utc(clock.now(), "clock.now()")
        self._fact_service = fact_service
        self._store = projection_store
        self._clock = clock
        self._runtime_id = runtime_id
        # C7C-R3 fault-injection hook. Production: None. Tests: a
        # callable that receives (receipt, request) and is invoked
        # AFTER record_frozen_plan and BEFORE the first fact admit,
        # simulating a crash at the precise boundary. See R3-9.
        # Note: this is an in-process injection, not an OS-level
        # process kill; the SQLite reopen path is exercised
        # separately by the recovery step in R3-9.
        self._fault_after_plan: _FaultHook | None = None

    def set_fault_after_plan(self, hook: _FaultHook | None) -> None:
        """Install or clear the post-plan fault-injection hook.

        This is a test-only surface. Production callers MUST leave
        it set to None. The hook is invoked exactly once per
        project() call, immediately after the plan commit and
        before the first fact admission. If it raises, the
        exception propagates and the projector leaves the store
        in the crash-window state (plan present, marker absent,
        no facts admitted).
        """
        self._fault_after_plan = hook

    @property
    def _clock_now(self) -> datetime:
        now = self._clock.now()
        require_aware_utc(now, "clock.now()")
        return now

    def project(
        self,
        *,
        receipt: DeliveryReceipt,
        request: DeliveryRequest,
    ) -> ProjectionOutcome:
        if not isinstance(receipt, DeliveryReceipt):
            raise ValueError("receipt must be a DeliveryReceipt")
        if not isinstance(request, DeliveryRequest):
            raise ValueError("request must be a DeliveryRequest")

        if receipt.delivery_status is not DeliveryStatus.SENT:
            return ProjectionOutcome(
                applied=False,
                already_applied=False,
                derived_counter_key="",
                derived_settled_at=None,
                skip_reason="not_accepted",
                derived_counter_value="",
            )

        # Idempotency fast-path: a completed projection (the marker
        # row exists) is a no-op. The has() check uses the marker
        # table; the frozen_plan table is only consulted in the
        # crash-window path below.
        if self._store.has(receipt.receipt_id):
            return _already_applied_outcome(receipt=receipt, store=self._store)

        # C7C-R3 state consistency:
        #
        # The projection durable plane is the (marker, plan) pair.
        # Three legal states and one illegal one:
        #
        #   marker present, plan present (any completed flag)
        #     → already-applied; return the marker.
        #
        #   marker absent, plan present with completed=False
        #     → crash window: replay from the frozen plan verbatim.
        #
        #   marker present, plan absent
        #     → pre-R3 marker (legacy or written before R3 was
        #       in effect). The marker alone is authoritative; the
        #       missing plan is benign.
        #
        #   marker absent, plan present with completed=True
        #     → INCONSISTENT. The plan was marked completed (its
        #       mark_plan_completed happened) but the marker write
        #       did not survive (or was rolled back). This state
        #       is forbidden: re-deriving from ambient state would
        #       silently overwrite the immutable plan. Fail closed
        #       with a clear error; an operator must decide
        #       whether to repair the marker or escalate.
        plan = self._store.get_frozen_plan(receipt.receipt_id)
        if plan is not None:
            # Crash window. Replay the plan verbatim (no
            # re-derivation against current state). The settled_at
            # in the plan is the original timestamp.
            settled_at = plan.settled_at
            for fact_key, fact_value in plan.facts:
                self._admit_counter_fact(
                    key=fact_key,
                    value=fact_value,
                    receipt=receipt,
                    request=request,
                    settled_at=settled_at,
                )
            # Write the idempotency record (mirrors the normal
            # path below). The marker is the COMPLETED signal.
            primary_key, primary_value = plan.facts[0]
            record = ProjectionRecord(
                receipt_id=receipt.receipt_id,
                request_id=request.request_id,
                message_id=request.message_id,
                scope=request.scope,
                origin_runtime_id=request.origin_runtime_id,
                derived_counter_key=primary_key,
                derived_counter_value=primary_value,
                derived_settled_at=settled_at,
                projected_at=self._clock_now,
                sync_version=1,
            )
            self._store.record(record)
            # Mark the plan as completed so future replays are no-ops.
            self._store.mark_plan_completed(receipt.receipt_id)
            return ProjectionOutcome(
                applied=False,
                already_applied=True,
                derived_counter_key=primary_key,
                derived_settled_at=settled_at,
                skip_reason=None,
                derived_counter_value=primary_value,
            )

        # C7C-R3 state consistency: (marker absent, plan completed=True)
        #
        # The plan was marked completed (mark_plan_completed was called)
        # but the marker write did not survive (crash after that update,
        # or rolled back). The plan's facts are immutable; re-deriving
        # would silently produce different ambient-derived values and
        # overwrite the invariant. Fail closed. An operator must inspect
        # the store and decide whether to insert the missing marker or
        # escalate the inconsistency.
        any_plan = self._store.get_frozen_plan_any(receipt.receipt_id)
        if any_plan is not None and any_plan.completed:
            raise ValueError(
                f"projection inconsistent for receipt_id"
                f" {receipt.receipt_id!r}: the frozen plan is"
                f" completed=True but the idempotency marker is"
                f" absent. This state cannot be self-healed; the"
                f" immutable plan must not be overwritten by"
                f" re-derivation. Operator must inspect the store"
                f" and decide whether to insert the missing marker."
            )

        # Authoritative timestamp: provider accepted_at first.
        _settled_at: datetime | None = receipt.delivered_at
        if _settled_at is None:
            # Defensive: a SENT receipt with delivered_at=None is an
            # upstream contract bug; we fall back to request.created_at
            # so the counter still moves (the C7B contract guarantees
            # delivered_at is set on SENT, but fail-soft is safer than
            # dropping a real-world settled action).
            _settled_at = request.created_at
        assert _settled_at is not None
        settled_at = _settled_at
        require_aware_utc(settled_at, "settled_at")

        # C7C-R: legacy unknown action_type (the row load returns ""
        # for pre-C7C on-disk rows that lack the column) is FAIL
        # CLOSED for the settled-action projection. There is no
        # silent default to proactive_message. An operator-facing
        # deterministic backfill is the only path to recover a
        # legacy row, and it MUST go through the explicit
        # ``OperationalFactAdmission.is_known_action_type`` check
        # below. See docs/legacy/kayla-rule-map.md for the original
        # counter rules; the modern equivalent is per-receipt
        # action_type = "proactive_message" or "send_photo".
        action_type = getattr(request, "action_type", "") or ""
        if not action_type:
            raise ValueError(
                "settled-action projection refused: "
                "request.action_type is empty (legacy unknown). "
                "The C7C projector does NOT backfill silently. "
                "Restore action_type from authoritative intent "
                "provenance or escalate to an operator migration."
            )
        if not OperationalFactAdmission.is_known_action_type(action_type):
            raise ValueError(
                f"settled-action projection refused: "
                f"action_type={action_type!r} is not a known typed "
                f"action (expected 'proactive_message' or 'send_photo'). "
                f"No silent default is applied."
            )

        # C7C-R: write order is "plan first, facts second, marker LAST".
        # The frozen plan is the durable pre-side-effect record of
        # the exact (fact_key, fact_value) pairs the projector intends
        # to write. A crash between the plan write and the marker
        # write leaves the plan in place; on recovery the projector
        # replays the plan verbatim without re-deriving against
        # later mutable state. The plan's fact admissions are
        # individually idempotent by their deterministic observation
        # id, so the replay is safe.
        derived_facts = self._derive_new_counter_facts(
            request=request, settled_at=settled_at,
        )

        if not derived_facts:
            # Known action_type produced no facts (defensive — at
            # present only the "unknown" branch returns empty, but
            # future kinds may also). No counter mutation, no
            # projection marker (the receipt itself is durable
            # in the C7B delivery plane; the projection outcome
            # reflects the no-op without claiming completion).
            return ProjectionOutcome(
                applied=False,
                already_applied=False,
                derived_counter_key="",
                derived_settled_at=settled_at,
                skip_reason="no_facts_for_action",
                derived_counter_value="",
            )

        # C7C-R3: freeze the exact derivation BEFORE the first fact
        # side effect. The plan is the durable binding between this
        # receipt and the values that will be written. A replay that
        # finds this plan must use the plan's facts verbatim.
        plan_facts: tuple[tuple[str, str], ...] = tuple(
            (d.fact_key, d.fact_value) for d in derived_facts
        )
        self._store.record_frozen_plan(
            FrozenPlan(
                receipt_id=receipt.receipt_id,
                request_id=request.request_id,
                action_type=action_type,
                settled_at=settled_at,
                facts=plan_facts,
                completed=False,
            )
        )

        # C7C-R3 fault-injection hook: the precise boundary the
        # crash-window tests depend on. Production sets this to
        # None; tests inject a callable that raises to simulate a
        # crash between the plan commit and the first fact
        # admission. The store is left with plan=incomplete,
        # marker=missing, facts=absent; the recovery must use the
        # plan verbatim. This is NOT a process-kill test; R3-9
        # pairs this injection with a fresh store reopen
        # (SqliteProjectionStore over the same file) to exercise
        # the recovery path.
        fault = self._fault_after_plan
        if fault is not None:
            fault(receipt=receipt, request=request)

        for derived in derived_facts:
            self._admit_counter_fact(
                key=derived.fact_key,
                value=derived.fact_value,
                receipt=receipt,
                request=request,
                settled_at=settled_at,
            )

        # Persist the idempotency record AFTER the fact admission so a
        # crash-window between fact admission and idempotency record
        # results in a fresh project() call that re-admits the same
        # fact (idempotency on receipt_id keeps it safe: the fact
        # authority is idempotent on Evidence bytes; a re-admit with
        # the same evidence_id is a no-op). The primary derived fact
        # is the cadence counter (or its reset for send_photo);
        # cooldown facts are also recorded but don't change the
        # outcome's primary derived_counter_key.
        primary = derived_facts[0]
        record = ProjectionRecord(
            receipt_id=receipt.receipt_id,
            request_id=request.request_id,
            message_id=request.message_id,
            scope=request.scope,
            origin_runtime_id=request.origin_runtime_id,
            derived_counter_key=primary.fact_key,
            derived_counter_value=primary.fact_value,
            derived_settled_at=settled_at,
            projected_at=self._clock_now,
            sync_version=1,
        )
        self._store.record(record)
        # C7C-R3: mark the frozen plan completed so a future replay
        # that somehow finds it (should not happen; the marker already
        # covers this) is a clean no-op via the has() fast-path.
        self._store.mark_plan_completed(receipt.receipt_id)

        return ProjectionOutcome(
            applied=True,
            already_applied=False,
            derived_counter_key=primary.fact_key,
            derived_settled_at=settled_at,
            skip_reason=None,
            derived_counter_value=primary.fact_value,
        )

    # ---- counter derivation (read-modify-write over the fact plane) ------

    def _derive_new_counter_facts(
        self,
        *,
        request: DeliveryRequest,
        settled_at: datetime,
    ) -> tuple[_DerivedFact, ...]:
        """Derive the (fact_key, fact_value) pairs to admit for this projection.

        The cadence counter is the only key we ever write under
        ``counter.proactive_prompts_since_photo``; settled proactive
        text increments, settled SEND_PHOTO resets to zero. The
        cooldown fact under ``counter.last_proactive_at`` is also
        written for proactive text (the producer declared a known
        proactive action). Unknown action_type is treated as a
        counter-plane no-op (the producer declared no known kind).
        """
        if request.action_type == "send_photo":
            current = self._latest_observation_value(
                key=self._CADENCE_COUNTER_KEY, scope=request.scope,
            )
            new_count = 0  # reset
            return (_DerivedFact(self._CADENCE_COUNTER_KEY, str(new_count)),)
        if request.action_type == "proactive_message":
            current = self._latest_observation_value(
                key=self._CADENCE_COUNTER_KEY, scope=request.scope,
            )
            current_count = _parse_int_or_zero(current)
            new_count = current_count + 1
            return (
                _DerivedFact(self._CADENCE_COUNTER_KEY, str(new_count)),
                _DerivedFact(self._COOLDOWN_FACT_KEY, settled_at.isoformat()),
            )
        # Unknown action_type: a generated hint of a kind we don't
        # recognise MUST NOT pollute the counter plane. The producer
        # must declare a known action_type (proactive_message or
        # send_photo) to drive a counter write. The projector
        # fail-closes on unknown action_type before this method
        # runs, so the empty return is unreachable in practice.
        return ()  # pragma: no cover

    def _latest_observation_value(
        self, *, key: str, scope: Scope,
    ) -> str | None:
        """Return the latest observed value for a (scope, key) pair.

        The ObservationStore is append-only. The "latest" is the last
        observation matching the (scope, key) pair, where observed_at
        is the authoritative timestamp; ties are broken by insertion
        order (the last appended wins).
        """
        latest_value: str | None = None
        latest_at = None
        for observation in self._fact_service.observations.all():
            if observation.scope != scope or observation.key != key:
                continue
            if not isinstance(observation.value, str):
                continue
            if latest_at is None or observation.observed_at >= latest_at:
                latest_value = observation.value
                latest_at = observation.observed_at
        return latest_value

    def _admit_counter_fact(
        self,
        *,
        key: str,
        value: str,
        receipt: DeliveryReceipt,
        request: DeliveryRequest,
        settled_at: datetime,
    ) -> None:
        """Admit one operational fact through the fact service.

        C7C-R: the request and receipt are passed end-to-end so the
        ``OperationalFactAdmission`` authority contract (key
        allow-list, source_type, action_type, scope, status, sync)
        is enforced at admit time. The deterministic observation id
        is derived from ``(receipt_id, key)`` for idempotency.
        """
        if not key or not value:
            return
        self._fact_service.admit_operational_fact(
            key=key,
            value=value,
            request=request,
            receipt=receipt,
            observed_at=settled_at,
        )


def _fact_evidence_id(*, receipt_id: str, fact_key: str) -> str:
    return f"settled-fact-{receipt_id}-{fact_key}"


def _parse_int_or_zero(value: str | None) -> int:
    if value is None:
        return 0
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return 0
    return max(parsed, 0)


def _already_applied_outcome(
    *, receipt: DeliveryReceipt, store: SqliteProjectionStore,
) -> ProjectionOutcome:
    record = store.get(receipt.receipt_id)
    if record is None:
        # Store said has()=True but get()=None is a contradiction;
        # fall back to a minimal outcome so the caller can react.
        return ProjectionOutcome(
            applied=False,
            already_applied=True,
            derived_counter_key="",
            derived_settled_at=None,
            skip_reason=None,
            derived_counter_value="",
        )
    return ProjectionOutcome(
        applied=False,
        already_applied=True,
        derived_counter_key=record.derived_counter_key,
        derived_settled_at=record.derived_settled_at,
        skip_reason=None,
        derived_counter_value=record.derived_counter_value,
    )
