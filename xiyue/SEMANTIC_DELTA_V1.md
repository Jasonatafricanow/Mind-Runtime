# Semantic Delta V1 Host composition

ADR-0002 is accepted in MR-Mem. Native SourceRef admission belongs to
SemanticAdmissionService, which calls CanonicalMemoryStore. No literal factual
Evidence/Observation pair or public MindRuntimeHostPort extension is used.

This integration targets the Hermes 0.19.0 gateway with the existing MR seam.
`apply_semantic_delta_patch.py --check --gateway-run-py <explicit path>` checks
the Body call anchor without writing. `--apply` applies only that call-site
patch. Install the existing MR seam first; run its check before the delta patch.
The feature defaults off. Enabling requires `SEMANTIC_DELTA_V1_ENABLED=true`
and an absolute `MR_MEM_CANONICAL_DB` path for the independent MR-Mem database.
Use the MR-Mem commit pinned in the Host CI workflow. Legacy MR readers cannot
decode native-backed MR-Mem memories; do not reuse their legacy database path.

The same terminal Body inference emits normal prose and a current delta.
The Host buffers final text, strips the sidecar before native assistant
persistence, and routes prose through the existing MR expression guard.
User semantics are independent of guard rejection. Current USER provenance
uses the native append receipt, exact platform message/session identity,
native session owner, current fingerprint, and system MR interaction mapping.
Compression that rotates the native session fails semantic admission closed.

Hermes normal tool/retry loops can make several model calls per conversation.
This integration adds no model invocation and no retry/compiler model; its
sibling outputs come from one terminal inference. It does not change Hermes
tool execution, retry policy, or provider selection.

The standalone composition test suite is `python -m pytest -q xiyue/tests`.
It has its own required CI job with an exact MR-Mem test dependency, so MR Core
installation and its public dependency/Host contracts remain unchanged.
Local fake-provider tests and external patch checks do not prove a live
provider will comply with the versioned semantic prompt.
