# Memory Core Boundary

Status: implementation note under ADR-0023 and ADR-0033.

`mind_runtime.memory.core.MemoryCore` is the runtime-independent ownership
surface for canonical MR Memory and the temporary local projections stored
beside it.

The boundary is intentionally small:

```text
caller / product adapter
        |
        v
     MemoryCore
      /     \
canonical   product projections
 Memory       (Thread/attention)
```

It accepts a canonical `memory.sqlite` path directly and therefore does not
import `RuntimeBinding`, host composition, Body agents, retrieval providers,
AML, or LCE. Bound MR composition resolves the physical path and then uses this
same core.

This is a packaging/ownership split, not a new authority layer:

- Evidence/Observation admission remains the only factual write authority.
- Canonical Memory remains the sole durable factual Memory substrate.
- Thread/attention state remains derived and cannot authorize Memory.
- LCE remains an optional higher projection.
- A standalone adapter may reuse `MemoryCore`; it must not create a second
  canonical factual store merely to satisfy an external interface.

The exact-selection helper rejects the complete request when any requested
Memory is missing, duplicated, outside the authorized Scope, or ineligible.
This preserves the same fail-closed support boundary used by projection
adapters.
