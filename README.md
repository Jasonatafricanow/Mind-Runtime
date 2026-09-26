# Mind Runtime

Mind Runtime is a Python runtime for keeping agent state across turns and process restarts.

The repository currently implements persistent facts/state/intents/checkpoints, runtime identity and storage isolation, bounded memory retrieval, turn commit/abort handling, restart validation, telemetry, and a read-only Observation Window.

## Runtime shape

```text
user / host input
      |
      v
interaction + evidence
      |
      v
runtime checks / state transition logic
      |
      +----> facts / state / intents / delivery / checkpoints (SQLite)
      |
      +----> bounded memory retrieval
      |
      +----> telemetry / trace
      |
      v
decision context -> model / agent host
```

The model can interpret input and propose changes, but persistent state is written by runtime code. Retrieved items are context candidates; retrieval alone does not modify stored state.

## Main components

### Persistent state

SQLite-backed storage is used for:

- facts;
- runtime state;
- intents and scheduling;
- delivery/retry records;
- checkpoints;
- longitudinal state records.

Relevant code lives under:

```text
src/mind_runtime/facts/
src/mind_runtime/state/
src/mind_runtime/intents/
src/mind_runtime/delivery/
src/mind_runtime/pipeline/checkpoints.py
```

### Runtime bindings

`runtime_binding.py` and `binding_registry.py` give each runtime an explicit identity and storage namespace.

Bindings are checked before use rather than inferred from arbitrary paths. Multi-binding setups use separate registry entries and storage paths.

### Memory and retrieval

The memory layer separates stored records from retrieval.

```text
stored memory
   |
   v
retrieval provider
   |
   v
bounded context candidates
   |
   v
turn context
```

The default implementation works without a vector database. Qdrant/FastEmbed adapters are optional and live behind provider interfaces under `src/mind_runtime/memory/providers/`.

The retrieval seam also supports a dependency-free BM25 arm, Reciprocal Rank Fusion across lexical/semantic providers, and optional HyDE query expansion. The preferred policy keeps HyDE off the normal path and invokes it only when primary hybrid recall is sparse. These mechanisms only rank stable Memory IDs; canonical Scope/lifecycle/content are still revalidated by MR before anything reaches context. See ADR-0029.

MR treats durable memory as one authority with layered projections:

```text
raw text / Evidence / Observation
        -> canonical Memory
        -> temporary Thread projection
        -> accepted LCE Baseline projection
```

StateBar remains a separate short-lived current-state authority. Inside the
Memory subsystem, canonical Memory is the factual substrate; Thread and LCE are
derived views over the same stable Memory identities. Retrieval/vector state is
also derived and never becomes authority.

The post-commit Thread updater reuses semantic work already performed for the
turn. A Thread is a temporary cache for an online line that may still develop,
not a second history. When LCE is enabled and a mature Thread is successfully
compiled into an accepted Baseline, MR deletes that temporary Thread
projection instead of maintaining the same logic twice. The Baseline lineage
and canonical Memory support retain the durable trace.
Failed or disabled compilation leaves the Thread intact and never rolls back
canonical Memory.

Unstructured history remains available for future idle/sleep/dream LCE
discovery. The same historical-context composition is the single outward read
boundary: it prefers accepted Baselines, may expose at most a bounded relevant
active Thread projection, then fills remaining budget with canonical Memory
detail. Raw Evidence/source text is retained primarily for provenance,
falsification, rebuild, and retrieval fallback. See
`docs/architecture/MEMORY_ARCHITECTURE_V1.md`, ADR-0028, and ADR-0033.

### Turn admission and commit

`runtime_admission.py` and the orchestrator implement process-local admission plus commit/abort behavior for a turn.

This prevents one process from treating partially completed work as committed state. Cross-process single-writer coordination is not implemented.

### Restart recovery

Restart validation covers loading persisted state/checkpoints and reconstructing runtime bindings deterministically.

Relevant code:

```text
src/mind_runtime/validation/restart.py
src/mind_runtime/state/persistence.py
src/mind_runtime/pipeline/checkpoints.py
```

### Observation Window

`src/observation_window/` exposes runtime state, binding information, traces, and health/query surfaces for inspection.

It is read-only with respect to MR state: the UI/query layer does not become another write path.

### LCE integration

MR has an optional LCE integration under `src/mind_runtime/integrations/lce.py`.
LCE remains a separate repository and is not vendored into MR Core.

The integration keeps canonical Memory authority in MR while supporting three
bounded operations: explicit-ID LCE Core consolidation, no-model compilation of
a mature Thread's already-reasoned working structure, and readback of accepted
Baseline cognition into HistoricalContext. When production LCE composition is
enabled, the normal post-commit Thread path performs that compilation
automatically and retires the lower-level Thread projection after Baseline
acceptance.

Accepted cognition is preferred over ordinary Memory retrieval inside the same
bounded history budget, so previously compiled longitudinal logic does not need
to be reconstructed every turn.

The full standalone LCE V1 discovery runtime is not copied into MR because its
standalone Reference Memory owns source evidence as well as derived cognition.
Any future latent-discovery binding must keep MR as the sole factual substrate
and LCE storage derived-only. See ADR-0026.

## Verified status

The current public repository separates deterministic/local verification from claims that still require live external evidence.

| Area | Public status | Evidence |
| --- | --- | --- |
| Persistent state, bindings, commit/abort, restart recovery | Implemented and regression-tested | `src/mind_runtime/`, `tests/`, restart validation |
| Deterministic certification | Implemented | `certification/`, validation tests, current CI |
| Observation Window | Implemented as a read-only inspection surface | `src/observation_window/` |
| Layered Memory projections / LCE integration | Canonical-Memory binding, automatic mature-Thread projection upgrade when enabled, accepted-cognition readback | `src/mind_runtime/memory/`, `src/mind_runtime/integrations/lce.py`, ADR-0033 |
| Live shadow validation | Incomplete / externally blocked | certification and architecture records |
| General-purpose longitudinal cognition inside MR | Not a product claim | longitudinal research remains separate or bounded |

Detailed historical gate names remain in the architecture/certification records; they are implementation history, not required vocabulary for understanding the current runtime.

For machine-verifiable compatibility with the repository's historical governance tests, the
compressed delivery slice is retained here without making it the primary reviewer vocabulary:

```text
D7 -> D7R -> D8 -> D9 -> D10 -> D11S -> D11L -> D11 completion -> D11P

Input / Evidence
-> Factual Context
-> Deterministic Emotional Transition
-> Intent / Scheduler
-> Decision Context / Expression
```

| Gate | Historical repository status |
| --- | --- |
| D7R | Complete |
| D8 | Complete |
| D9 | Complete |
| D10 | Complete |
| D11S | Complete |
| D11L | Blocked |
| D11 | Incomplete |
| D11P | Blocked |

The frozen D11 split is `D10 -> D11S -> D11L -> D11 completion -> D11P`.


## Current implementation boundaries

The repository contains code for:

- persistent facts and state;
- binding/namespace isolation;
- canonical memory storage, bounded retrieval, attention/surfacing governance, and temporary Thread projections;
- optional semantic vector retrieval;
- intent lifecycle and scheduling;
- expression/context guards;
- telemetry and causal tracing;
- restart/recovery validation;
- read-only Observation Window;
- an optional LCE adapter.

The following are not complete production claims:

- cross-process writer coordination;
- live external-provider validation in every environment;
- a finished general-purpose longitudinal cognition engine inside MR;
- automatic deployment hardening for arbitrary multi-host setups.

Research experiments that do not belong in the runtime are kept separate or moved to LCE.

## Verification

Install and run the local test suite:

```bash
python -m pip install -e ".[dev]"
python -m pytest -q
```

The repository also uses Ruff, mypy, coverage, deterministic fixtures, restart tests, and certification inputs.

Some static-analysis findings are historical debt rather than a claim that the entire tree is currently lint/type-clean. CI work tracks these separately from runtime tests.

## Repository layout

```text
src/mind_runtime/
  facts/                persisted facts
  state/                runtime state + persistence
  memory/               storage/retrieval/providers
  intents/              intent lifecycle + scheduling
  delivery/             retry/reconcile/delivery state
  pipeline/             turn orchestration/checkpoints/trace
  validation/           restart/horizon/model-swap checks
  integrations/         optional external adapters

src/observation_window/  read-only inspection/query surface

tests/                   unit, contract, recovery, integration, regression tests
certification/           deterministic certification inputs
docs/                    ADRs, reports, historical design records
```

## Stack

Python 3.12+ · SQLite · FastAPI · pytest · mypy · Ruff · optional Qdrant/FastEmbed

## Project history

The public Git history is a cleaned publication baseline rather than the complete local development history. See [PROJECT-HISTORY.md](PROJECT-HISTORY.md) for the project sequence and the code/ADR/test artifacts that record it.