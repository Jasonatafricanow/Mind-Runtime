# Mind Runtime

**A stateful cognition runtime for long-lived AI agents.**

Mind Runtime (MR) is a runtime for carrying authorized state across turns,
restarts, and model changes. It separates evidence, memory, runtime identity,
canonical state, policy, expression, persistence, and observation so that a
model can continue from what a system has already established instead of
reconstructing everything from historical fragments on every turn.

MR is a runtime boundary, not a claim that current systems are conscious or
fully autonomous. Models remain responsible for bounded inference and
expression. MR is responsible for the state and authority boundaries from
which inference may safely continue.

## Why Mind Runtime Exists

Large language models are good at reasoning in the moment, but they do not
naturally maintain a stable understanding of a person, themselves, or an
ongoing relationship across time.

Many memory systems address this by retrieving historical information and
placing it back into the prompt. Mind Runtime takes a different approach. It
treats persistent cognition as runtime state with explicit authority,
provenance, identity, lifecycle, and failure semantics.

The question is not only whether a system can remember that something
happened. The question is whether it can continue from the understanding
that event produced, while distinguishing evidence, interpretation, current
state, projection, and superseded state.

## What MR Is Not

Mind Runtime is not:

- a vector database;
- a chat-history wrapper;
- a prompt persona;
- a RAG framework;
- an autonomous-agent framework;
- a virtual companion application.

Models still perform inference. MR provides the durable runtime state and
governance boundaries that inference consumes.

## Problem Definition

A long-lived agent needs to answer questions such as:

- Who is the user and who is the agent?
- What changed, and when?
- What was already understood?
- Which conclusions remain valid?
- Which state was temporary, expired, or superseded?
- What is allowed to affect the next decision?

A simple historical loop is:

```text
history -> retrieve -> prompt -> model reinterpretation
```

That loop can be useful, but by itself it leaves authority implicit. It also
permits model variance, repeated reasoning, retrieval being mistaken for
belief, self-reinforcement, and ambiguity between current and superseded
state. MR makes those boundaries explicit in code and contracts.

## Design Principles

### Evidence is not cognition

Interaction, observation, retrieved memory, model interpretation, projection,
and canonical state are different objects. They have different provenance and
different authority.

### Retrieval is not authority

Similarity, recency, frequency, and clustering can find candidates. They do
not by themselves authorize canonical runtime state. Authority is explicit.

### Cognition should survive model replacement

Durable state should become less dependent on model-specific reconstruction.
MR does not claim complete model independence; it provides the boundaries that
make that direction testable.

### Longitudinal state is different from memory

Remembering that something happened is different from representing how
something changed over time.

### Ambiguity should fail closed

When identity, scope, binding, or authority is ambiguous, the safe behavior is
to reject or abstain. Convenience is not allowed to create authority.

### Persistent cognition must be inspectable

Provenance, telemetry, causal tracing, human inspection, and restart/recovery
checks are runtime governance, not optional decoration. The read-only
Observation Window source under `src/observation_window/` is part of that
boundary.

## Architecture

```text
                     Model / Agent Host
                            |
                            v
                  +-------------------+
                  |    Mind Runtime   |
                  |                   |
Interaction ----->| Runtime Binding   |
                  | Admission         |
                  | State Authority   |
                  | Memory Authority  |
                  | Persistence       |
                  | Telemetry         |
                  +---------+---------+
                            |
              +-------------+-------------+
              v             v             v
        Canonical State   Memory       Observation
           SQLite        Storage         Window
                            |
                            | optional
                            v
                    External Cognition
                        Substrates
                            |
                            v
                           LCE
```

MR owns runtime authority. External systems may discover, retrieve, or
interpret structures; they do not automatically become canonical MR state.

## Verified Product Slice and Delivery Gates

The currently verified compressed product slice is:

```text
Interaction
-> Evidence
-> Observation
-> Effective State
-> Factual Context
-> Deterministic Emotional Transition
-> Projected Internal State
-> Intent / Scheduler
-> ActionPolicy
-> Minimal Decision Context
-> Agent / LLM Expression
-> ExpressionGuard
-> Commit
```

The accepted delivery order keeps deterministic certification separate from
live shadow validation:

```text
D0 -> D1 -> D2 -> D2S -> D3 -> D4 -> D5 -> D6 -> D7 -> D7R -> D8 -> D9 -> D10 -> D11S -> D11L -> D11 completion -> D11P
```

The current gate snapshot is deliberately explicit:

| Gate | Current status | Scope |
| --- | --- | --- |
| D7R | Complete | Compressed runtime topology and authority boundaries are frozen. |
| D8 | Complete | Deterministic emotional-transition step and fail-closed semantic candidates are covered. |
| D9 | Complete | Intent lifecycle, scheduling, policy, and persistence are covered. |
| D10 | Complete | Bounded expression runtime, context compilation, guards, and rewrite limits are covered. |
| D11S | Complete | Fixed-clock deterministic certification is closed. |
| D11L | Blocked | Live shadow validation is blocked by unavailable external environment evidence. |
| D11 | Incomplete | Fixed-clock certification is complete; live validation is not performed. |
| D11P | Blocked | Productization waits for its named gates. |

This table records verified scope, not a claim of live deployment or complete
longitudinal cognition.

## Current Implementation

The following claims are verified against this clean source tree and its
tests:

| Capability | Current boundary | Evidence |
| --- | --- | --- |
| Canonical runtime state | SQLite-backed facts, state, intent, delivery, and checkpoint persistence | `src/mind_runtime/facts/`, `state/`, `intents/`, `delivery/`, `pipeline/checkpoints.py` |
| Runtime identity and namespaces | Explicit binding identity, production compatibility binding, storage namespace validation, and physical path isolation | `src/mind_runtime/runtime_binding.py` |
| Multi-binding isolation | Persistent `BindingRegistry` with explicit reader/writer ports and fail-closed resolution | `src/mind_runtime/binding_registry.py`, `binding_registry_composition.py` |
| Legacy production compatibility | `production/xiyue` remains an explicit compatibility namespace; explicit bindings take precedence | `runtime_binding.py`, `src/observation_window/web/` |
| Memory authority | Canonical memory store and admission/projection seams separate storage authority from retrieval | `src/mind_runtime/memory/`, ADRs 0023–0025 |
| Retrieval and context | Historical context is assembled through a bounded read seam; optional providers supply candidates, not authority | `memory/retrieval.py`, `memory/retrieval_composition.py`, `pipeline/ports.py` |
| Optional vector retrieval | FastEmbed/Qdrant adapters are optional and isolated behind provider ports | `memory/providers/`, `pyproject.toml` |
| MR-side LCE boundary | An optional one-way adapter binds MR memory to an external LCE package; LCE Core is not vendored here | `src/mind_runtime/integrations/lce.py`, `docs/integrations/lce-binding.md` |
| Turn admission | Process-local atomic turn admission and commit/abort boundaries protect a single runtime process | `src/mind_runtime/runtime_admission.py`, `pipeline/orchestrator.py` |
| Slow longitudinal state | Slow-state contracts and persistence exist as runtime objects; they are not the same as a compiled cognition engine | `contracts/slow_state.py`, `state/longitudinal.py`, `slow_plasticity/` |
| Telemetry and causal tracing | Typed telemetry contracts, trace recording, and Observation Window causal inspection | `contracts/telemetry.py`, `pipeline/trace.py`, `src/observation_window/` |
| Read-only observation | Observation Window health and query surfaces advertise and enforce read-only inspection | `src/observation_window/web/api.py`, `query_service.py` |
| Restart recovery | Durable state/checkpoint loading and deterministic binding reconstruction are covered by restart validation | `state/persistence.py`, `pipeline/checkpoints.py`, `validation/restart.py` |

These are implementation boundaries, not a promise that every optional
provider, live integration, or external project is installed in every clone.

## Current Limitations

The following are intentionally not presented as implemented runtime
features:

- Compiled Cognition is not implemented in MR Core.
- `EffectiveCognitionView` remains design/draft work, not a current authority.
- Committed cognition lineage and effective-head selection are not implemented.
- Cross-process writer authority is unsupported; the turn-admission guarantee
  is process-local.
- Legacy `MAX(version)`-style resolution remains in historical or bounded
  paths and is not claimed as a new authority model.
- Full longitudinal cognition compilation is not owned by MR Core.
- Live shadow validation and external-provider behavior require separate
  environments and gates.

## MR and LCE

MR and LCE are independent projects with a deliberately narrow integration
boundary.

**MR owns:** runtime authority, identity, state, memory consumption,
admission, persistence, telemetry, and observation.

**LCE owns:** longitudinal cognition-engine research and structures compiled
across evidence over time.

> LCE asks: **What structure may exist across this history?**
>
> MR asks: **What state is authorized to participate in cognition now?**

The MR-side adapter is optional and one-way. LCE Core implementation and its
internal schema remain outside this repository. The external project is
[LCE — Longitudinal Cognition Engine](https://github.com/Jasonatafricanow/LCE-Longitudinal-Cognition-Engine).

## Observation Window

Observation Window is a read-only inspection surface for runtime visibility,
binding visibility, durable state queries, causal trace, and telemetry. It is
not a cognition editor and it does not own cognition writes.

## Research Direction

The longer-term research direction is:

```text
history
  -> evidence
  -> longitudinal structure
  -> accepted understanding
  -> reusable runtime cognition
```

This differs from:

```text
history
  -> retrieval
  -> prompt
  -> full reinterpretation
```

Compiled Cognition, Cognitive Trajectory, Cognitive Frontier, Effective
Cognition, Committed Lineage, and Supersession are ongoing research/design
directions. They are not current MR runtime features unless the implementation
and authority contract are explicitly accepted in a later milestone.

## Architecture Journey

The architecture was shaped by rejected shortcuts as much as by accepted
implementations. The [architecture case studies](docs/case-studies/README.md)
trace the decisions from retrieval-oriented memory toward explicit runtime
authority, a separate longitudinal cognition engine, and a deliberately
conservative production boundary.

## Repository Structure

This public seed contains the following source surfaces:

```text
src/mind_runtime/          canonical runtime, contracts, persistence, memory
src/observation_window/    read-only inspection and web/query surfaces
xiyue/                     MR-side host seam and integration entrypoints
tests/                     unit, contract, integration, and certification tests
docs/                      accepted ADRs, architecture, research, and integration docs
certification/             deterministic certification inputs and reports
scripts/                   portable operator and verification helpers
configs/                   safe, non-secret runtime/persona/config templates
```

Durable runtime databases, logs, provider outputs, embeddings, and real
interaction data are excluded by policy and `.gitignore`.

## Testing

From a Python 3.12+ environment:

```powershell
python -m venv .venv
& '.\.venv\Scripts\python.exe' -m pip install -e '.[dev]'
& '.\.venv\Scripts\python.exe' -m pytest -q
```

The core and production-relevant suites can run without production data. Some
tests require optional local dependencies such as `fastembed`, an external
semantic model fixture, or a live provider environment. Live tests are marked
and are not a substitute for the deterministic local suite.

The clean seed's non-live verification currently records 2,883 passing tests,
3 test failures, 2 errors, and 7 skips. The known non-pass cases are missing
optional `fastembed`, missing external semantic-model fixtures, and a
pre-existing C9 helper import gap; none is a seed-omission claim. This is
reported explicitly rather than represented as an all-green badge.

## Governance and Design References

- [Repository governance](AGENTS.md)
- [Architecture lock](docs/architecture/MR_ARCHITECTURE_LOCK_v1_1.md)
- [Runtime identity and storage isolation](docs/adr/0020-runtime-identity-binding-storage-isolation.md)
- [Multi-binding registry authority](docs/adr/0021-multi-binding-registry-authority.md)
- [Canonical Memory authority](docs/adr/0023-canonical-memory-authority.md)
- [Shared Memory retrieval seam](docs/adr/0024-shared-memory-retrieval-read-seam.md)
- [Optional semantic vector provider](docs/adr/0025-optional-semantic-vector-provider.md)
- [Optional LCE substrate binding](docs/adr/0026-optional-lce-memory-substrate-binding.md)
- [Atomic affect projection](docs/adr/0005-atomic-affect-vector-projection.md)
- [Bounded expression authority](docs/adr/0007-bound-expression-authority.md)
- [MR-side LCE binding](docs/integrations/lce-binding.md)
- [Design philosophy](docs/design-philosophy.md)

## Status

This repository is a clean-history public baseline extracted from the verified
Mind Runtime source line. It is the future development repository for MR.
The historical source repository and production cutover worktree remain
separate audit and rollback references; they are not this repository's Git
history.
