"""MR-ALPHA-AS1: Synthetic IntentEngineAdapter — harness validation only.

NOT production code.  Results through this adapter do NOT count as MR Alpha
evidence.  This adapter stubs the IntentEnginePort so the harness can exercise
the consumption path (ABLATION_ARM → CONSUME_OFF) without a real model.

It accepts IntentEngineInput, optionally reads agent.slow.* from the slow
adapter (consumption arm), and emits a valid IntentEngineResult with at least
one CANDIDATE Intent — demonstrating that the consumer was invoked.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, UTC
from typing import Callable

from mind_runtime.contracts import Scope, ScopeDomain, SyncFields
from mind_runtime.contracts.behavior import IntentEngineInput
from mind_runtime.contracts.intent import (
    Intent,
    IntentEngineResult,
    IntentScoreContribution,
    IntentScoreTrace,
    IntentStatus,
    ReconsiderationPolicy,
)
from mind_runtime.pipeline.ports import IntentEnginePort

# The canonical prefix for longitudinal state dimensions in agent state.
SLOW_DIMENSION_PREFIX = "agent.slow."

__all__ = ["SyntheticIntentEngineAdapter", "INTENT_ADAPTER_VERSION"]

INTENT_ADAPTER_VERSION = "synth-v1"
_RUNTIME_ID = "alpha-synth"


@dataclass
class SlowStateReader:
    """Minimal callable interface for reading accumulated slow state."""

    get: Callable[[str], float]  # dimension → value, 0.0 if absent


class SyntheticIntentEngineAdapter(IntentEnginePort):
    """Synthetic stand-in for IntentEngine — harness validation only.

    By default the adapter reads agent.slow.* dimensions via the provided
    reader.  Set ``enabled=False`` to implement the CONSUME_OFF ablation arm
    (slow writes fire but nothing reads them).
    """

    def __init__(
        self,
        slow_reader: SlowStateReader | None = None,
        *,
        enabled: bool = True,
        runtime_id: str = "runtime-1",
    ) -> None:
        self._slow_reader = slow_reader
        self._enabled = enabled
        self._invocation_count = 0
        self._last_intent_strength = 0.0
        self._last_intent_id: str | None = None
        self._last_candidates: tuple[Intent, ...] = ()
        self._runtime_id = runtime_id

    def evaluate(self, engine_input: IntentEngineInput) -> IntentEngineResult:
        self._invocation_count += 1

        # Read accumulated slow state if enabled and reader is present
        slow_reads: dict[str, float] = {}
        if self._enabled and self._slow_reader is not None:
            for dim, value in [
                ("agent.slow.anxiety", self._slow_reader.get("agent.slow.anxiety")),
                ("agent.slow.affiliation", self._slow_reader.get("agent.slow.affiliation")),
                ("agent.slow.agency", self._slow_reader.get("agent.slow.agency")),
                ("agent.slow.confidence", self._slow_reader.get("agent.slow.confidence")),
            ]:
                if value != 0.0:
                    slow_reads[dim] = value

        # Emit a minimal CANDIDATE Intent; the harness observes invocation_count
        now = datetime.now(tz=UTC)
        intent_id = f"synthetic-intent-{self._invocation_count}"
        scope = engine_input.scope

        # Score is influenced by slow state if we read any
        base_strength = 0.4
        if slow_reads:
            # Modulate score with accumulated state
            slow_influence = sum(slow_reads.values()) / len(slow_reads)
            strength = min(1.0, base_strength + slow_influence * 0.3)
            contributions = tuple(
                IntentScoreContribution(
                    source_kind="slow_state",
                    source_ref=dim,
                    amount=val,
                )
                for dim, val in slow_reads.items()
            )
            reason_codes = ("SLOW_ACCUMULATED",)
        else:
            strength = base_strength
            contributions = ()
            reason_codes = ("SYNTHETIC",)

        intent = Intent(
            intent_id=intent_id,
            scope=scope,
            origin_runtime_id=self._runtime_id,
            kind="synthetic_curiosity",
            strength=strength,
            earliest_at=None,
            due_at=None,
            expires_at=None,
            reconsideration_policy=ReconsiderationPolicy.ON_CONTEXT_CHANGE,
            cause_refs=(),
            state_refs=tuple(slow_reads.keys()),
            status=IntentStatus.CANDIDATE,
            sync=SyncFields(
                scope=scope,
                origin_runtime_id=self._runtime_id,
                object_id=intent_id,
                version=1,
                idempotency_key=f"idem-{intent_id}",
            ),
        )

        trace = IntentScoreTrace(
            trace_id=f"trace-{intent_id}",
            scope=scope,
            rule_id="synthetic_rule",
            intent_id=intent_id,
            contributions=contributions,
            unclamped_score=strength,
            final_strength=strength,
            admitted=True,
            reason_codes=reason_codes,
            created_at=now,
        )

        # Record the last result so the runner can introspect it
        self._last_intent_strength = strength
        self._last_intent_id = intent_id
        self._last_candidates = (intent,)

        return IntentEngineResult(
            candidates=(intent,),
            traces=(trace,),
        )

    # ── Inspection ──────────────────────────────────────────────────────────

    @property
    def invocation_count(self) -> int:
        return self._invocation_count

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def last_intent_strength(self) -> float:
        return self._last_intent_strength

    @property
    def last_candidates(self) -> tuple[Intent, ...]:
        return self._last_candidates
