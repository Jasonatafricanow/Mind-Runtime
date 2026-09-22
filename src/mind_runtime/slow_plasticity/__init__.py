"""Rolling-window longitudinal state writer.

The historical SlowPlasticityWriter name remains available for compatibility.
"""

from mind_runtime.slow_plasticity.writer import (
    LongitudinalStateWriter,
    SlowContributionRecord,
    SlowPlasticityWriter,
    SlowStateBackend,
    SlowWindowSnapshot,
)

__all__ = [
    "LongitudinalStateWriter",
    "SlowContributionRecord",
    "SlowPlasticityWriter",
    "SlowStateBackend",
    "SlowWindowSnapshot",
]
