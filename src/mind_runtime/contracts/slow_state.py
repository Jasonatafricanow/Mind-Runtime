"""C10-C1 slow-state contracts: typed carry for authoritative SQLite records.

C10-C1 is the read/projection seam only.  It carries authoritative
RuntimeState records whose dimension is a registered longitudinal
target (e.g., ``agent.slow.*``) from ``SqliteStateBackend`` into the
``DecisionContextCompilerInput``.

The raw float value written by ``SlowPlasticityWriter.flush()`` is
preserved verbatim.  No band mapping, no threshold, no coefficient,
no aliasing, no priority offset is introduced here — those
concerns belong to a separate C2 authority decision.
"""

from __future__ import annotations

# SlowStateProjection is a frozen tuple of RuntimeState records whose
# dimension is a registered longitudinal target.  Read from the
# authoritative SQLite backend at orchestrator turn-runtime (no cache,
# no shadow copy).  An empty tuple is a valid projection when no
# registered slow dimensions are present.
SlowStateProjection = tuple["RuntimeState", ...]
