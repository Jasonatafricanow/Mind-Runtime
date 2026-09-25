# W3 ADR number migration (Issue #11, Gate B2)

The historical W3 branch at `386d3e8d8e49a1f2d8e9d6d4e18641ed2d0c504e`
accepted two Surface decisions under ADR-0028 and ADR-0029. Main subsequently
assigned those numbers to Memory. This gate changes document numbers and links
only; it does not reopen either W3 decision or alter the Memory decisions.

| Historical W3 decision | Main number | Historical acceptance |
| --- | --- | --- |
| `docs/adr/0028-single-surface-behavior-exposure.md` | [`ADR-0031`](../adr/0031-single-surface-behavior-exposure.md) | `6e3f9216c692a6f08b8e30dc2fd057a31d524500` |
| `docs/adr/0029-persona-publication-and-surface-handoff-provenance.md` | [`ADR-0032`](../adr/0032-persona-publication-and-surface-handoff-provenance.md) | `386d3e8d8e49a1f2d8e9d6d4e18641ed2d0c504e` |

Current main retains [`ADR-0028`](../adr/0028-three-timescale-memory-and-incremental-cognition.md)
for three-timescale Memory and [`ADR-0029`](../adr/0029-hybrid-memory-retrieval.md)
for hybrid Memory retrieval. The historical W3 acceptance IDs in the migrated
documents remain unchanged as provenance. W3 architecture, contracts, code,
and tests use the new decision numbers and paths. Older branch audit records
may still mention the historical numbers; their meanings are fixed by their
source SHA and this mapping.
