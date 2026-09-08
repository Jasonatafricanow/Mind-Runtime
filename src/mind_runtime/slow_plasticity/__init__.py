"""MR-C10-B-W: Slow Plasticity Writer package.

The SlowPlasticityWriter is the authoritative longitudinal writer for
the C10-B-W slow-state plane. It consumes HomeostasisDecision records
with SLOW_ACCEPT disposition from the per-turn emotional-transition
pipeline and writes persistent, accumulated slow-state records to the
shared StateBackend.

Design contract (ADR-0017, ACCEPTED):

  W_t(d) = last N qualifying SLOW_ACCEPT contributions
  A_t(d) = Σ(salience_i * proposed_value_i) / Σ salience_i
  S_t(d) = A_t(d)         (overwrite; no prior-state blend)
  Empty W_t(d) → NO WRITE

The writer does NOT introduce any multiplicative constant
(learning_rate / alpha / LR), does NOT blend with prior state, does
NOT clamp writer-side, and does NOT write on an empty window. N is
configuration-owned and must be >= 1.
"""

from mind_runtime.slow_plasticity.writer import (
    SlowContributionRecord,
    SlowPlasticityWriter,
    SlowStateBackend,
    SlowWindowSnapshot,
)

__all__ = [
    "SlowPlasticityWriter",
    "SlowContributionRecord",
    "SlowWindowSnapshot",
    "SlowStateBackend",
]
