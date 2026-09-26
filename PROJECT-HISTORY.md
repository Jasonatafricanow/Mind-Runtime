# Project History and Public Baseline

Mind Runtime's public Git history is intentionally a **clean publication baseline**, not a reconstruction of the complete local development history.

This document exists so reviewers do not have to infer project age or design evolution from the small number of public commits.

## What the public Git history means

The repository was published after a longer local design and implementation line had already produced:

- runtime state and persistence;
- evidence / observation / state separation;
- affect and intent pipelines;
- restart and recovery validation;
- authority and admission rules;
- Observation Window;
- longitudinal-state experiments;
- the decision to split longitudinal cognition into LCE.

The public baseline preserves the resulting source, tests, ADRs, certification artifacts, and research records while keeping the Git graph small and auditable.

It therefore should **not** be read as:

```text
first public commit date == project start date
number of public commits == number of development iterations
```

## Architectural development record

The evolution is preserved primarily in the repository's documents and tests rather than in a replayed commit history.

### 1. Memory and durable state

The early problem was continuity across conversations and restarts. Memory retrieval was useful, but it left authority implicit: retrieved history could be reinterpreted on every turn without a clear distinction between evidence and current state.

Relevant evidence:

- `src/mind_runtime/memory/`
- `src/mind_runtime/state/`
- `src/mind_runtime/facts/`
- `docs/case-studies/01-memory-to-cognition-runtime.md`

### 2. Explicit authority boundaries

As state became durable, identity, scope, admission, and self-reinforcement became first-class problems.

The runtime introduced explicit authority boundaries rather than treating model output or retrieved candidates as automatically canonical.

Relevant evidence:

- `docs/adr/0009-idempotent-turn-fact-admission.md`
- `docs/adr/0010-no-self-authorizing-feedback.md`
- `docs/case-studies/06-retrieval-is-not-authority.md`

### 3. Runtime identity and multi-binding isolation

Persistence made "which runtime owns this state?" a correctness question. The architecture added explicit runtime bindings, storage isolation, and a persistent binding registry.

Relevant evidence:

- `docs/adr/0020-runtime-identity-binding-storage-isolation.md`
- `docs/adr/0021-multi-binding-registry-authority.md`
- `src/mind_runtime/runtime_binding.py`
- `src/mind_runtime/binding_registry.py`

### 4. Deterministic product slice and recovery

The runtime was compressed into a bounded product slice with explicit delivery gates, restart certification, recovery decisions, and fixed-clock deterministic validation.

Relevant evidence:

- `certification/d11s/`
- `src/mind_runtime/validation/`
- `tests/validation/`
- `docs/adr/0008-split-d11-certification-and-live-shadow.md`

### 5. Longitudinal state exposed a research boundary

Slow-state / plasticity work raised questions that no longer belonged inside runtime authority: semantic trajectories, higher-order structure, and longitudinal understanding.

Instead of turning experimental structure into runtime truth, that work was split into the independent LCE project.

Relevant evidence:

- `src/mind_runtime/slow_plasticity/`
- `docs/adr/0015-c10-b1-r3-contribution-timescale-authority.md`
- `docs/adr/0017-c10-b-w-slow-plasticity-accumulation-authority.md`
- `docs/case-studies/03-why-lce-is-separate.md`

### 6. Observation became a read-only governance surface

Persistent cognition required causal visibility, but the inspection layer was deliberately prevented from becoming another mutation path.

Relevant evidence:

- `src/observation_window/`
- `docs/case-studies/02-faculty-boundaries.md`

### 7. Optional bounded decision compute became a shared parallel capability

As retrieval, Thread, and longitudinal cognition matured, a new class of problem
became visible: some semantic judgments were too fuzzy for deterministic rules but
too small to justify another full reasoning pass.

The runtime therefore introduced a single provider-neutral decision-model seam rather
than adding model clients separately inside each feature.

The design is explicitly parallel and optional:

```text
feature baseline pipeline -------------------------------> result
                         \
                          -> bounded projection
                          -> DecisionModelPort
                          -> optional judgment
                          -> feature-owned policy
```

The first concrete use is canonical-Memory retrieval reranking. BM25/vector/RRF
discovery still produces candidates, MR revalidates canonical scope/lifecycle first,
and the optional decision model only judges semantic relevance over canonical Memory
content. Provider/index text never becomes authority through the reranker.

TypeSafe Jev is implemented as one replaceable backend behind the generic port. The
backend is lazy-loaded, has no SDK requirement in the default runtime import graph,
and defaults to a short fail-fast timeout. Absence, timeout, malformed output, or
backend failure must preserve the original baseline pipeline.

The same port is intentionally reusable by future Thread fuzzy identity resolution,
LCE reasoning-cost gating, Affect, or other bounded decisions without creating new
provider-specific API paths. No canonical mutation authority is delegated to the
decision model.

Relevant evidence:

- `src/mind_runtime/decision/`
- `src/mind_runtime/memory/decision_projection.py`
- `src/mind_runtime/memory/retrieval.py`
- `docs/adr/0034-body-owned-online-semantics-and-decision-model-option.md`
- `tests/decision/`
- `tests/memory_retrieval/test_decision_rerank.py`
- `tests/memory_retrieval/test_decision_composition.py`

This work was deliberately kept separate from the ACTIVE semantic migration so
bounded decision compute could not become a second semantic authority.

### 8. Online semantic understanding moved to the Body/Host boundary

The ACTIVE runtime originally retained an optional internal semantic-provider path
and a model-backed appraisal composition path. That duplicated work already performed
by the host model and made GLM/Zen/appraisal credentials part of runtime readiness.

The online boundary was changed so the Body/Host supplies bounded typed semantic and
appraisal proposals. MR binds Scope, runtime identity, and admitted Evidence
references itself, validates the proposals, materializes accepted appraisal effects,
and retains all Dynamics, Intent, Policy, journal, and commit authority.

MR no longer auto-constructs a semantic provider for an ACTIVE turn and production
composition no longer requires GLM/Zen or appraisal-model credentials. Legacy model
implementations remain explicit LAB/shadow/background compatibility code rather than
online authority.

Relevant evidence:

- `src/mind_runtime/contracts/appraisal.py`
- `src/mind_runtime/contracts/host.py`
- `src/mind_runtime/host/runtime_adapter.py`
- `src/mind_runtime/pipeline/orchestrator.py`
- `src/mind_runtime/dynamics/ports.py`
- `docs/adr/0034-body-owned-online-semantics-and-decision-model-option.md`
- `tests/host/test_body_semantic_input.py`
- `tests/host/test_semantic_activation.py`


## Why the history was not rewritten

A synthetic Git history would create cleaner-looking activity but weaker evidence.

The repository therefore keeps the publication baseline honest:

- no fabricated backdated commits;
- no reconstructed commit chronology presented as original;
- no claim that public timestamps represent the full project lifecycle.

The design evolution is instead backed by source boundaries, ADRs, tests, certification artifacts, and explicit case studies.

## Current status

The public baseline demonstrates a large deterministic and restart-safe runtime surface, but it is still **research engineering / pre-production**.

In particular, live shadow validation remains separate from deterministic certification, and incomplete external evidence is reported as incomplete rather than folded into a production claim.

The optional decision-model plane is currently being developed on an isolated branch and is not part of the public `main` baseline until its integration checks and the separate local semantic-migration work are reconciled.