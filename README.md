# Mind Runtime

**A stateful runtime for long-lived AI agents.**

Mind Runtime (MR) is built around a problem that prompt expansion and memory retrieval do not fully solve:

> How can an agent continue from previously established state across turns, restarts, and model changes without allowing retrieval or model output to silently become authority?

MR separates evidence, memory, runtime identity, canonical state, policy, persistence, expression, telemetry, and observation. Models still perform inference; MR defines the state and authority boundary from which inference continues.

## Portfolio role

```text
                         LCE
             longitudinal structure research
                          |
                          | optional derived input
                          v
Agent host -------> Mind Runtime
 interaction       runtime authority
                          |
                          +------> Observation Window
                          |          read-only inspection
                          |
                          +------> MR Habitat
                                     spatial projection
```

[Statebar MCP](https://github.com/Jasonatafricanow/Statebar-mcp) solves a narrower current-state problem. MR generalizes the same concern into a long-lived agent runtime with explicit identity, persistence, admission, policy, and recovery semantics.

## The problem

A common memory loop is:

```text
history -> retrieve -> prompt -> model reinterpretation
```

This is useful for recall, but it leaves several questions implicit:

- Is retrieved material evidence, a candidate, or accepted state?
- Which conclusion is still current after later evidence?
- What survives restart?
- What happens when two runtime identities share one process?
- Can a model's own previous interpretation reinforce itself?
- Which state is allowed to affect planning or expression now?

MR treats those as runtime questions rather than prompt-engineering details.

## How the design evolved

### 1. Memory retrieval exposed an authority problem

Improving retrieval did not remove repeated reinterpretation. The model still had to reconstruct what mattered and could treat a retrieved item as if it were already accepted truth.

The design moved from "better memory injection" toward explicit state objects with provenance, lifecycle, identity, and admission rules.

### 2. Persistent state required runtime identity

Once state survives turns and restarts, "which agent/user/runtime does this belong to?" becomes a storage and authority question.

MR therefore uses explicit runtime bindings, namespaces, storage validation, and multi-binding isolation rather than relying on ambient process configuration.

### 3. More capability increased the need for boundaries

Affect, intent, scheduling, context compilation, and expression were added as bounded stages. The runtime does not become an open-ended agent core: deterministic and policy-owned transitions stay separate from model reasoning and language generation.

### 4. Longitudinal cognition outgrew the runtime

Experiments around semantic structure, trajectories, and understanding across long histories became a different class of problem. Keeping that work inside MR would let experimental discovery look like current runtime authority.

That led to [LCE](https://github.com/Jasonatafricanow/LCE-Longitudinal-Cognition-Engine) as a separate engine.

### 5. Inspection became a governance surface

Persistent systems need more than logs. Observation Window was kept read-only so state, bindings, causal traces, and telemetry can be inspected without giving the inspection layer write authority.

[MR Habitat](https://github.com/Jasonatafricanow/MR-Habitat) explores a later product question: whether that state can be perceived as spatial presence without moving cognition ownership into the visualization.

## Key design decisions

### Evidence is not cognition

Interaction, memory, retrieved candidates, model interpretation, projection, and canonical state are distinct objects with different provenance and authority.

### Retrieval is not authority

Similarity, recency, frequency, and clustering may surface candidates. They do not authorize runtime state.

### Model output cannot authorize itself

Probabilistic inference can propose meaning. Promotion into durable runtime state requires an explicit authority path.

### Ambiguity fails closed

Identity, scope, binding, or authority ambiguity is rejected or left unknown rather than silently resolved for convenience.

### Runtime state must survive restart

Persistence and checkpoint semantics are part of correctness, not a cache optimization.

### Observation is read-only

Inspection should explain the system without becoming another hidden write path.

### Current-turn reasoning stays outside MR

MR provides durable state, policy boundaries, and bounded context. The model/agent host still owns current-turn reasoning and expression within those constraints.

## Runtime architecture

```text
Interaction
    |
    v
Runtime Binding / Admission
    |
    v
Evidence -> Effective State -> Factual Context
                         |
                         v
               bounded deterministic state
               affect / intent / policy
                         |
                         v
                 Context Compilation
                         |
                         v
                    Model / Agent
                         |
                         v
                 Expression Guard
                         |
                         v
                       Commit
                         |
            +------------+------------+
            v                         v
       Persistence                Telemetry
                                     |
                                     v
                             Observation Window
```

Optional external cognition systems such as LCE may provide derived structures through narrow adapters. They do not automatically become canonical MR state.

## Current implemented scope

The public baseline includes:

- SQLite-backed canonical facts, state, intent, delivery, and checkpoints;
- explicit runtime binding and storage namespaces;
- persistent multi-binding registry and isolation;
- memory admission / retrieval seams;
- optional vector retrieval adapters;
- optional one-way LCE integration boundary;
- process-local atomic turn admission;
- bounded affect, intent, scheduler, action-policy, and expression stages;
- telemetry and causal tracing;
- read-only Observation Window;
- restart and recovery validation.

The repository intentionally distinguishes implemented runtime behavior from research vocabulary.

## Verification and delivery status

MR uses pytest, strict mypy, Ruff, branch coverage, deterministic certification inputs, restart validation, and explicit live-test markers.

```bash
python -m pip install -e ".[dev]"
python -m pytest -q
```

The deterministic local product slice has been certified further than the live integration surface. Live shadow validation still depends on external environment evidence and is not represented as complete production validation.

See:

- [architecture lock](docs/architecture/MR_ARCHITECTURE_LOCK_v1_1.md)
- [case studies](docs/case-studies/README.md)
- [design philosophy](docs/design-philosophy.md)
- [repository governance](AGENTS.md)

## Boundaries and non-claims

MR does **not** currently claim:

- solved persistent or general cognition;
- Compiled Cognition as a completed MR Core feature;
- model independence;
- cross-process writer authority;
- complete live production validation;
- ownership of LCE internals or current-turn open-ended reasoning.

Uncertainty and incomplete authority are valid runtime outcomes.

## Research direction

The longer-term question is:

```text
history
  -> evidence
  -> longitudinal structure
  -> accepted understanding
  -> reusable runtime cognition
```

instead of repeatedly doing:

```text
history
  -> retrieve
  -> prompt
  -> reinterpret everything
```

The research vocabulary around trajectory, frontier, committed cognition, effective cognition, and supersession is kept separate from implemented claims until an explicit authority contract and runtime implementation exist.

## Stack and repository layout

Python 3.12+ · SQLite · pytest · mypy · Ruff · optional Qdrant/FastEmbed

```text
src/mind_runtime/          runtime, authority, persistence, memory
src/observation_window/    read-only inspection
xiyue/                     host / integration seam
tests/                     unit, contract, integration, certification
docs/                      ADRs, architecture, research, case studies
certification/             deterministic certification artifacts
```

## Repository history

This repository is a clean-history public baseline extracted from the longer Mind Runtime development line. Its Git history is intentionally not a complete reconstruction of every private/local development step.

## Engineering philosophy

> Build for the original problem, not for the maximum available capability.

The durable asset is not the largest feature surface. It is the set of boundaries that remain necessary when models, providers, or surrounding frameworks change.
