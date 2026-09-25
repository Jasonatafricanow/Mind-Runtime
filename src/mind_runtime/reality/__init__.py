"""Trimmed StateBar-derived raw-text input for Mind Runtime.

This package owns proposal extraction only.  Canonical admission remains in
the existing MR factual plane and canonical state remains in the existing
state reconciler/backend.
"""

from mind_runtime.reality.eligibility import (
    StateEligibility,
    evaluate_state_eligibility,
)
from mind_runtime.reality.extraction import (
    FastRealityExtractor,
    OpenAICompatRealityExtractor,
    PersistentRealityExtractor,
    RealityCandidate,
    RealityInputService,
    build_reality_input,
    validate_reality_payload,
)
from mind_runtime.reality.temporal import (
    normalize_temporal,
    resolve_trusted_timezone,
)

__all__ = [
    "FastRealityExtractor",
    "OpenAICompatRealityExtractor",
    "PersistentRealityExtractor",
    "RealityCandidate",
    "RealityInputService",
    "StateEligibility",
    "build_reality_input",
    "evaluate_state_eligibility",
    "normalize_temporal",
    "resolve_trusted_timezone",
    "validate_reality_payload",
]
