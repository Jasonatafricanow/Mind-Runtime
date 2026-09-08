# ADR-0024: Shared Memory retrieval and bounded historical context

- Status: ACCEPTED for the bounded MR-MEM-2 assignment
- Date: 2026-09-07
- Base: 6b9725d9e5abfd0b2b2c8fc9ff7079d926fd8c67
- Authority: MR-MEM-2 ticket; ADR-0020/0022/0023 unchanged.

## Decision

RetrievalProvider.search receives a structured, host-authorized Scope, query
text and bounded limit. It returns ranked stable memory_id references with
transient provider/score metadata. It has no write/admission surface. Provider
text is optional diagnostic data, never canonical content or historical evidence.
MR validates identities by exact canonical lookup, never provider UUID fallback.
The upstream ID contract is not replaced with a provider-specific format rule.

Stage A is relevance discovery. Stage B reads CanonicalMemoryStore.get and admits
only existing, exact-Scope, ACTIVE records to the read result. ARCHIVED and
SUPERSEDED are excluded; no lifecycle changes or supersession policy are added.
Provider order is the rank order. Duplicate stable IDs keep the first eligible
occurrence. Discovery scans at most query.limit candidates, with an absolute cap
of 100; consumer item and character budgets provide additional bounds. Oversized
canonical propositions are omitted whole, not truncated. No database-wide scan
or SQLite semantic search is introduced.

The new HistoricalContext adapter implements the existing HistoricalContextPort,
not a new parallel port. Consumers use its existing read contract.
Port.read uses only bounded text from current admitted user-message Observations;
it does not infer a query from Situation, advice, Intent, model output or ticks.
Context and Observation scopes must match. Current Observation IDs/Evidence refs
are excluded from the historical contribution. The adapter produces episodes with
canonical content and Evidence refs, confidence/relevance_hint=None and no pattern
summaries. Bundle refs are recomputed solely from selected items. Thus retrieval
does not manufacture recurrence counts, new Evidence or direct C10 effects.

Query Scope is supplied by the existing host authority. Provider-side filters are
defense in depth only. The canonical store remains bound to the existing Runtime
namespace. A read_only open uses SQLite mode=ro without mkdir, DDL, schema repair,
manifest writes or Memory creation. Bound retrieval verifies the existing manifest
and opens only StoragePaths.memory_db. Missing/corrupt canonical storage fails;
it is not reinterpreted as an empty index.

None/Null is intentional disabled retrieval and returns no contribution, opening
no Memory file. An enabled provider exception remains RetrievalProviderUnavailable;
the retrieval/history adapter does not silently convert it into no matches. Existing
host fail-soft handling remains a separate consumer-level behavior. Default production
composition still uses NullHistoricalContext; no real provider is configured.

## Deferred and activation gate

The MR-MEM-1 fact-commit to Memory-job-registration crash gap is a **DEFERRED
PRE-PRODUCTION-ACTIVATION BLOCKER**. Retrieval neither fixes nor hides it.
Historical backfill, supersession emitter, provider/embedding selection, real
vector adapters (MR-MEM-3), reinforcement/use-axis, LCE binding, Diary/date queries
and current-turn reasoning remain outside this ticket. LCE is untouched; shared
stable IDs plus canonical get already support its future ordinary read sequence.

## Verification

Tests in tests/memory_retrieval cover T1–T18: canonical content supremacy, malformed
provider IDs, Scope/lifecycle checks, deterministic ranking/dedup/budgets, outage
distinction, actual HistoricalContextPort use, read-only/repeated reads, restart,
namespace isolation and a stdlib-only subprocess. Paired full regression uses the
exact base commit in a real Git worktree, never the dirty original checkout.
