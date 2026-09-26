# Why LCE Became a Separate Engine

## Context

The original longitudinal question was often phrased as Hot Start: can an
agent begin a new session with a compact understanding formed from its earlier
history? Answering that question requires more than importing a few memory
records. It raises questions about semantic neighbourhoods, regions,
trajectory, temporal controls, and durable structure.

## Initial Approach

The simplest design was to make these capabilities another MR pipeline. MR
would discover related memories, interpret them, compile a summary, and feed it
back into the runtime.

## Failure / Limitation

That approach would make MR responsible for two different authorities:
current runtime state and research about structures that might exist across
history. It would also make every experiment a production pipeline change.

The concern was not that longitudinal research was unimportant. It was that
putting discovery and compilation inside the runtime would make an experimental
hypothesis look like an accepted current state.

## Alternatives

- Put all longitudinal discovery inside MR.
- Keep longitudinal work as ad hoc scripts beside MR.
- Create a separate, contract-first engine whose inputs and outputs remain
  explicit and optional.

The first overextended MR authority. The second made experiments difficult to
reproduce and review. The third preserved both research freedom and runtime
conservatism.

## Decision

LCE became an independent project. Its question is:

> What structure may exist across this history?

MR asks a different question:

> What state is authorized to participate in cognition now?

The MR-side adapter is optional, one-way, and contract-bound. LCE Core does
not own MR raw memory, vector coordinates, or current response reasoning.

## Architectural Consequence

MR continues to work without LCE. LCE consumes canonical external Memory views
and can persist its own derived Baseline lineage without becoming another
factual store. Thread and LCE are therefore logically part of the same Memory
projection hierarchy even though LCE Core remains a separate package and may
use separate physical persistence.

That split keeps the research surface replaceable: standalone LCE can evolve
its own discovery/topology implementation, while embedded MR swaps factual
source ownership for the MR `MemorySubstratePort`. No Memory-content
synchronization is required.

This is why the two repositories have different public identities. MR is the
runtime and authority boundary. LCE is the longitudinal structure and
compilation research surface.

## Evidence

- [MR-side LCE binding contract](../integrations/lce-binding.md)
- [Optional LCE substrate ADR](../adr/0026-optional-lce-memory-substrate-binding.md)
- [LCE Core repository](https://github.com/Jasonatafricanow/LCE-Longitudinal-Cognition-Engine)

## Current Status

The MR-side binding exists in the public MR source and production composition
can now automatically promote mature Thread projections into accepted LCE
Baselines when LCE is explicitly enabled. The Thread is then retired from the
active working set, leaving one live logical product rather than parallel
Thread/LCE copies.

LCE Core remains external. Idle/sleep/dream latent discovery over unstructured
Memory is still deferred; that future scheduler does not change the factual
ownership boundary.
