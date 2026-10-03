# MR Semantic Executor Boundary V1 — Frozen

Status: ACCEPTED / FROZEN. This records the Semantic Contract Unification work
order and complements the [Hot-Start invariant](MR_HOT_START_SOURCE_CURATION_FROZEN_INVARIANT.md).

| Authority | Executor / contract |
| --- | --- |
| Online semantic authority | Current Conversation Provider / Body LLM |
| Historical semantic worker | One-shot offline External Coding Agent / AGY |
| Shared semantic protocol | Existing MR-Mem `SemanticDeltaV1` |
| Canonical cognition authority | MR-Mem canonical `SemanticBlock` |
| Longitudinal structure | LCE derived projection |

Unify the protocol, not the executors. Online Body produces response and current
delta from the same inference. Tool cycles may invoke Body more than once, but
USER semantic compilation and canonical admission happen once. Historical AGY
uses a separate prompt/transport and emits one incremental JSON proposal per
eligible historical source. It does not participate in online conversation.

MR-Mem alone owns `semantic_contracts.py`, `semantic_validator.py`,
`semantic_closure.py`, `semantic_admission.py`, canonical identity, relations,
supersede lifecycle and recovery. Historical tools do not duplicate dataclasses,
validate with a second parser, assign Memory IDs or directly write canonical
rows. System-owned native SourceRef scope/version/interaction binding is checked
exactly at admission; agent JSON owns no source authority.

Historical order is Native Raw → three-state source curation → minimal context
assembly → External AGY → existing MR-Mem validator/closure/admission → embedding
and downstream projection. Short USER commitments remain eligible; assistant
material is context only; operational and AGY execution logs do not become
cognition. No whole transcript, Full-History recompilation or affect replay.

The offline implementation lives under `historical/`, outside installed online
packages. It uses `historical_semantic_delta_prompt_v1` with the same
`semantic_delta_v1` output schema. Model configuration, lifecycle, tool execution,
retry policy, provider billing/session management and online prompt transport
are not shared. No unified Model Producer port or resident AGY provider exists.

Rebuild starts in a fresh independent MR-Mem DB. Checkpoints preserve source and
ordering cursor, disposition/defer counts, failure source, prompt/schema versions
and accepted proposal/receipt recovery. Resume validates immutable Raw and
workspace/DB ownership before opening a writer. Production DB cutover is outside
this implementation.

Integrated LCE reads a thin view of committed MR-Mem Blocks through
`MRMemSemanticBlockAdapter`: original Memory ID, unchanged content, occurred
range, known_at, native source refs, context IDs and canonical relations. It
cannot reinterpret, split, merge or recompile them. LCE does not consume
SemanticDelta, SemanticPoints, the Body parser or AGY. The old Raw →
SemanticDecisionProvider → SemanticCompiler chain is LEGACY / STANDALONE; the
integrated canonical path bypasses it and retains existing trajectory algorithms.

Existing `mind_runtime.integrations.lce_projection` is the legacy factual bridge.
It is not a native Semantic Delta bridge. Native canonical callers use the new
optional LCE canonical projection factory. Enabling historical tools does not
enable an online feature flag, the old inspiration bridge or any production
cutover.
