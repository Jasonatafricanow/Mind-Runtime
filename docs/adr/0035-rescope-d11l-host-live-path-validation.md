# ADR-0035: Re-scope D11L as Host Live-Path Validation

- **Date:** 2026-09-29
- **Status:** Accepted
- **Supersedes:** the D11L entry/closure portions of ADR-0008 and
  `docs/superpowers/plans/2026-08-23-d11l-entry-requirements.md`
- **Does not supersede:** D11S deterministic-certification requirements or the
  rule that repository simulation cannot be presented as live operational evidence.

## Context

ADR-0008 was written when Mind Runtime had no real host integration. D11L was
therefore designed as a broad pre-production gate around a hypothetical Kayla
host, with eleven mandatory fields covering traffic sampling, wall-clock
observation, privacy, kill switches, rollback, release thresholds, and model
drift.

That gate solved a real problem at the time: fixed-clock 30/90-day simulations
must not be misrepresented as production operation.

The host situation has since changed. MR is now wired to the xiyue/Hermes
gateway. PR #42 established gateway-owned runtime readiness and explicit MR
enable/disable behavior, and PR #43 added readiness reconciliation so the
Observation Window can recover to READY before the first chat.

The old D11L contract now conflates three different claims:

1. whether the MR core is internally ready;
2. whether a concrete host is correctly wired to MR;
3. whether a broader production rollout has accumulated enough operational
   evidence for release-management claims.

Those claims must remain separate.

## Decision

### 1. D11S remains unchanged

D11S continues to own repository-controlled deterministic certification:
replay, restart consistency, bounded dynamics, model-isolation checks, and
fixed-clock horizon tests.

A fixed-clock simulation is still not live evidence. Nothing in this ADR
permits a repository test to be reported as real user traffic, wall-clock
operation, or production proof.

### 2. D11L is now a host live-path validation profile

D11L no longer acts as a universal product-release gate for MR itself.

D11L answers a narrower question:

> Does a named real host carry a real interaction through the MR integration
> path and recover correctly across the host/runtime failure boundaries that
> the integration actually exposes?

D11L is host-agnostic. The current host profile is xiyue/Hermes; the term
"Kayla host" is historical and is no longer a mandatory D11L concept.

### 3. Minimum D11L evidence

For a named host integration, D11L is complete when all of the following are
verified in the real environment:

1. **Host binding identity**
   - identify the host/gateway and MR revision being exercised;
   - identify whether MR is enabled for the run.

2. **Real end-to-end interaction**
   - a message from a real account enters the host;
   - the enabled MR seam participates in the turn;
   - the Body/model path produces a response;
   - the host delivers that response back to the originating account.
   Repository fixtures or synthetic turns cannot satisfy this item.

3. **Readiness and dependency recovery**
   - the host reports READY when MR core and required read-only dependencies
     are healthy;
   - loss of the Observation Window degrades readiness;
   - restoration of the Observation Window returns readiness to READY without
     granting the Observation Window write authority.

4. **Restart/autostart recovery**
   - after a clean host/runtime restart, required MR-side services are brought
     up by the supported startup path;
   - readiness returns to READY without requiring a first user chat to finish
     initialization.

5. **Fail-closed bypass behavior**
   - when MR is disabled or unavailable under the documented bypass mode,
     ordinary host chat does not accidentally construct or partially activate
     an MR adapter;
   - enabled-path initialization failures fail according to the host contract
     rather than silently claiming READY.

Evidence should record timestamps, revisions, readiness transitions, and
non-sensitive identifiers or hashes sufficient to reproduce the validation.
Message bodies need not be retained merely to prove D11L.

### 4. Product status is multi-axis

The following claims are independent and must be reported independently:

```text
MR core readiness
host integration readiness
real E2E live-path verification
restart/autostart verification
long-run production evidence
```

Failure to complete D11L live-path evidence does not revert an otherwise
certified MR core to "not ready". Conversely, a READY core or READY health
endpoint does not imply that a real account round trip has been verified.

"Product-level closure" must name which axis is being claimed. It is no longer
valid to use an unfinished legacy D11L checklist as a blanket blocker for MR
core closure.

### 5. Broader rollout controls are conditional deployment requirements

The following controls remain legitimate for broader or externally exposed
rollouts, but they are no longer universal D11L prerequisites:

- population sampling and minimum sample calculations;
- prolonged wall-clock observation windows;
- field-level privacy classification and trace-retention programs;
- formal 24/7 kill-switch ownership and latency SLOs;
- release rollback exercises and organization-level incident thresholds;
- provider-drift governance for multi-version managed rollouts.

A deployment or release plan that needs these controls must define and verify
them explicitly. Their absence must not be converted into a claim that the MR
core or a single-owner host integration is architecturally incomplete.

### 6. D11P is historical productization terminology

D11P remains useful when a release plan explicitly adopts that phase model.
It is not an implicit authority over current MR core readiness or xiyue host
closure merely because older D11 documents mention it.

## Current xiyue status at adoption

At commit `89ed89b`:

```text
MR core readiness:              READY
xiyue/Hermes host integration:  READY
OW degrade -> recover behavior: VERIFIED
real account E2E round trip:    NOT YET VERIFIED
restart/autostart E2E:          NOT YET VERIFIED
long-run production proof:      NOT CLAIMED
```

PR #42 and PR #43 establish the first three lines of this status. They do not
substitute for the two remaining live checks.

## Consequences

- The obsolete eleven-row D11L entry checklist is retired as an active gate.
- D11L documentation must refer to a named current host rather than requiring a
  Kayla-specific environment.
- Real-environment validation remains mandatory for live-path claims.
- Synthetic tests remain valuable preconditions but cannot self-authorize a
  live E2E claim.
- Status reports should expose the individual readiness axes instead of
  collapsing them into a single `D11L BLOCKED` verdict.

## Compatibility

No runtime API, state schema, memory authority, or expression authority changes
are introduced by this ADR. This is a governance and evidence-scope correction
to match the current architecture.
