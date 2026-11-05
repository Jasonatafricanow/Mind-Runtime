# Current MR-Mem core integration

This composition consumes the current MR-Mem service through its existing HTTP
contract. Verified core revision: `bb0d296dfa60718740e7cbb3f99002f360c66b00`.
It replaces neither MR state authority nor the core's algorithms.

## Read and explicit core operations

Set `MR_MEM_CORE_ENABLED=true`, `MR_MEM_URL` to the service origin, and
`MR_USER_ID` to the logical user already present in that instance. When needed,
set `MR_MEM_TOKEN_ENV` to the name of the environment variable holding its token.
`MR_MEM_TIMEOUT` defaults to 120 seconds. Keep `MR_MEMORY_ENABLED`,
`MR_LCE_ENABLED`, `MR_LCE_INSPIRATION_ENABLED` and `SEMANTIC_DELTA_V1_ENABLED` off.
The new reader and the legacy writers are mutually exclusive.
If a DecisionContext configuration is supplied, its `allowed_history_kinds` must
explicitly include `memory.mr_mem_projection`; composition rejects a missing
allowlist entry rather than silently dropping the new history. Its existing
history/render budgets still apply. The production SURFACE_V1 renderer carries
admitted history to Body; legacy HI-2 summary rendering is not full memory text.

Programmatic composition uses the same interface:

```python
from mind_runtime.host.xiyue_adapter import default_adapter
from mind_runtime.integrations.mr_mem_core import MrMemClient

core = MrMemClient("http://127.0.0.1:8765", user_id="user")
adapter = default_adapter(user_id="user", mr_mem=core)
# After the host durably records actual messages, preserving source timestamps:
core.add(request_id="stable-batch-id", session_id="native-session-id", messages=[
    {"role": "user", "content": "Original source text", "timestamp": 1793836800000},
])
core.search("Original source text")
core.health()
assert adapter.memory is core
```

`HistoricalContextPort` calls the same full Search endpoint before appraisal.
The service selects and renders SBs, Lines, stretches, standing instructions,
raw snippets and configured decision notes. MR preserves returned order and
whole item text within its existing item/character budget. It does not run a
second BM25 pass, reranker or model. A broken enabled core fails the turn's
existing history read; it is never silently reported as successful empty memory.
The host's established failure/readiness handling remains in force.

The current Search wire schema provides result IDs and rendered content, not
per-item raw SourceRefs or a caller-specified knowledge cutoff. Context references
are explicitly scoped **result locators**, not verified raw Evidence. This path
reads the service's current projection and is not a time-travel reconstruction.
Source edits/invalidation, attention policy and private-display decisions are not
implemented by parsing or rewriting core output. Retrieval cannot write MR facts,
state or intents. Algorithm quality and real model behavior are separate checks.

HTTP `/admin/flush` is instance-wide. `core.flush()` refuses by default; only
`MrMemClient(..., exclusive_instance=True)` or `MR_MEM_EXCLUSIVE_INSTANCE=true`
permits it for an explicitly dedicated instance. No ordinary read or native
commit invokes admin Flush. Background compilation and compile-before-search
retain the core's own configured policy, including any model calls it enables.

## Optional Hermes durable-history delivery

Apply the existing MR gateway patch first, then inspect/apply:

```text
python xiyue/apply_core_memory_patch.py --check --gateway-run-py <gateway/run.py>
python xiyue/apply_core_memory_patch.py --apply --gateway-run-py <gateway/run.py>
```

This tool rejects drift and the competing old native patch. It preserves newline
style and is idempotent. Applying it to a real gateway is a deployment action;
no real gateway or production data was changed for implementation verification.

Enable `MR_MEM_NATIVE_HTTP_ENABLED=true` and provide:

- `MR_MEM_NATIVE_JOURNAL`: absolute path of a dedicated metadata SQLite journal;
- `MR_MEM_NATIVE_BASELINE`: explicit nonnegative native message-ID cutoff that
  excludes already processed history (`0` deliberately permits a full backfill).

The baseline is an operational exclusion, not proof those rows were compiled.
Use the verified native cutoff for the existing dataset; do not infer it from
file modification time or the maximum date in an unrelated archive.

Before MR reads, the hook verifies the current and previously enrolled sessions
against fingerprints of registered sources. Only after a successful MR commit
does it send unseen rows above the baseline to Add. The native DB is opened
read-only; timestamps, roles and text are preserved. The journal stores source
IDs, fingerprints, batch status and binding metadata, no message bodies. The core's
existing AML ingestion store retains its input copy under its established policy;
the original host DB remains the native source authority.

Pending batches are frozen before HTTP and replayed with exactly the same IDs and
payload after lost responses/restarts. A failed memory upload records `pending`
on `agent._mr_native_memory_status`, without rerunning Body or undoing a successful
MR commit. Add acceptance does not certify compilation completion. Retry occurs
on a later successful commit. Never-enrolled sessions are not automatically read.
The gateway's single-writer lifecycle and an in-process lock serialize delivery;
the journal is not a multi-process queue or an atomic cross-database snapshot.

The current core API is append-only and lacks native edit/delete invalidation.
An edited, deleted or hidden enrolled message **blocks the next history read**
with `NativeSourceChanged`; no changed version is silently appended or represented
as reconciled. Such a dataset needs explicit core reconciliation before reuse.
This is a deliberate limit, not the invalidation implementation from the older
`3aa8f74` integration branch. Historical baseline rows excluded from enrollment
are outside this adapter's freshness guarantee.

## Verification

`tests/host/test_mr_mem_core*.py` covers HTTP receipt validation, bound user,
transport failure, current Search -> MR context, budgets, restart and replay.
`tests/host/test_mr_mem_delivery.py` covers incremental-only delivery, lost receipts,
source-change blocking and the actual rendered gateway hook lifecycle.
`xiyue/tests/test_current_mr_mem_core.py` runs the real paired core and HTTP server
with a deterministic fixture compiler: Add -> compile -> Line/raw Search,
isolation, conflicting replay, Flush and restart without recompiling old windows.
These tests make no external model calls and use no private source data.
