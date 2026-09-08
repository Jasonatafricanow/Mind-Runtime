"""MR-ALPHA-AS1: Harness-only synthetic adapters.

Both adapters here are marked EVIDENCE_MODE=HARNESS_VALIDATION_ONLY.
Results produced via these adapters do NOT count as MR Alpha evidence.
"""

from tests.mr_alpha.adapters.synthetic_intent_adapter import (
    INTENT_ADAPTER_VERSION,
    SlowStateReader,
    SyntheticIntentEngineAdapter,
)
from tests.mr_alpha.adapters.synthetic_slow_adapter import (
    SLOW_ADAPTER_VERSION,
    SyntheticSlowStateAdapter,
    make_slow_runtime_state,
)

__all__ = [
    "INTENT_ADAPTER_VERSION",
    "SLOW_ADAPTER_VERSION",
    "SlowStateReader",
    "SyntheticIntentEngineAdapter",
    "SyntheticSlowStateAdapter",
    "make_slow_runtime_state",
]