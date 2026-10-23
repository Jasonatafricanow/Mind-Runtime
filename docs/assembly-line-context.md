# Standalone Line read contract

The existing HistoricalContextPort may now carry a bounded neighbourhood from
MR-Mem's persisted Line graph. It uses kind `memory.line`, source references and
explicit stored progression edges. These are derived historical context, not new
MR evidence or canonical state. No new authority or writer is introduced.

Set `MR_MEM_LINE_ROOT` to the same MR-Mem data directory's `lce_tree` folder,
alongside `MR_MEM_READ_ENABLED=true` and `MR_MEM_CANONICAL_DB`. Programmatic
composition uses `default_adapter(mr_mem_db=..., mr_mem_line_root=...)`.
This requires the paired MR-Mem development build implementing
`mr_mem.integrations.line_read`; the previous public dependency supports canonical
reading only. An explicitly enabled unsupported graph reader fails at import/read.

The caller's current clock is both the knowledge cutoff and tense evaluation time.
All expanded steps must pass MR's existing automatic surface policy, same-scope
check, source-reference requirement and knowledge cutoff. Hidden steps cannot be
traversed to reveal other steps. Character/item limits apply to the final bundle.
MR does not infer host-native message timestamps from admission timestamps.

Every read opens and closes read-only graph/tense connections. No graph files yet
means canonical-only results; a partial or corrupt graph is an explicit error.
This is current-turn historical context, not a full historical reconstruction of
canonical lifecycle and attention policy. Algorithm quality remains separately
unverified; accepted fixture edges establish only the assembly contract.
