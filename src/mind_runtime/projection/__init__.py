"""Settled-action projection (C7C).

This is the doorway that converts an external ACCEPTED delivery
outcome (a carrier's SENT receipt) into an internal operational
fact (counter.last_proactive_at, counter.proactive_prompts_since_photo).
The single-writer contract is the whole point of this module:

  * CognitiveTicker stays read-only over the counter plane.
  * The C6B cadence rule stays read-only over the counter plane.
  * SettledActionProjector is the only writer; it goes through
    FactIngestService (the existing fact authority) and never
    mutates any counter table directly.

Idempotency is bound to receipt_id (NOT wall-clock): the same
receipt replayed never increments twice. The durable idempotency
record is SqliteProjectionStore; the durable fact admission goes
through the existing FactIngestService pipeline.

Cadence semantics follow the legacy rule map:
  - settled proactive text  -> counter.proactive_prompts_since_photo ++
  - settled SEND_PHOTO       -> counter.proactive_prompts_since_photo := 0
  - settled proactive text  -> counter.last_proactive_at := settled_at
Only ACCEPTED receipts drive a projection. UNKNOWN / FAILED_RETRYABLE
/ REJECTED are no-ops (no idempotency record, no fact).
"""

from mind_runtime.projection.projector import (
    ProjectionOutcome,
    SettledActionProjector,
)
from mind_runtime.projection.store import (
    FrozenPlan,
    ProjectionRecord,
    SqliteProjectionStore,
)

__all__ = [
    "FrozenPlan",
    "ProjectionOutcome",
    "ProjectionRecord",
    "SettledActionProjector",
    "SqliteProjectionStore",
]
