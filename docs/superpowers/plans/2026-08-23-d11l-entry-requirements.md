# D11L Entry Requirements — Superseded

- **Original date:** 2026-08-24
- **Superseded:** 2026-09-29
- **Current authority:** `docs/adr/0035-rescope-d11l-host-live-path-validation.md`
- **Historical authority:** ADR-0008 and the original D11S/D11L design
- **Current status:** legacy eleven-field gate retired

## Why this document was superseded

This file originally defined D11L as an eleven-field production-entry gate
because MR had no real host integration. It required a Kayla host, formal
traffic sampling, wall-clock observation, privacy/retention governance,
kill-switch ownership, rollback exercises, release thresholds, and model-drift
handling before any live validation could begin.

That boundary is now stale.

MR is currently integrated with the xiyue/Hermes gateway. The old checklist
therefore mixes together:

- MR core readiness;
- host integration readiness;
- live end-to-end verification;
- broader production rollout governance.

ADR-0035 separates those claims. The eleven-row checklist below is no longer
an active blocker and must not be used to conclude that MR core closure is
incomplete.

## Current D11L contract

D11L now means **real host live-path validation** for a named integration.

For the current xiyue/Hermes profile, the minimum live evidence is:

| Check | Required evidence | Current state at `89ed89b` |
|---|---|---|
| Host binding | xiyue/Hermes gateway is bound to the intended MR revision and enable state | **READY** |
| Real E2E round trip | real account message enters xiyue, MR participates, Body/model responds, reply is delivered to the same account | **NOT YET VERIFIED** |
| Readiness recovery | healthy MR + OW => READY; OW loss => DEGRADED; OW recovery => READY | **VERIFIED** |
| Restart/autostart | supported restart brings MR-side services back and restores READY without waiting for a first chat | **NOT YET VERIFIED** |
| Fail-closed bypass | disabled MR does not construct/partially activate an adapter; enabled-path startup failure cannot claim READY | **VERIFIED BY INTEGRATION/TEST EVIDENCE** |

Repository fixtures, scripted providers, and deterministic simulations may
support these checks but cannot substitute for the real E2E or restart checks.

## Status vocabulary

Status reports should publish the axes separately:

```text
MR core readiness:              READY | DEGRADED | NOT READY
host integration readiness:     READY | DEGRADED | NOT READY
real E2E live-path verification: VERIFIED | NOT VERIFIED
restart/autostart verification: VERIFIED | NOT VERIFIED
long-run production proof:      CLAIMED | NOT CLAIMED
```

Do not collapse these into the legacy statement:

```text
D11L: BLOCKED_BY_EXTERNAL_ENVIRONMENT
D11: INCOMPLETE
READY FOR D11P: NO
```

unless a specific historical D11 release plan explicitly chooses to use that
old phase model.

## Evidence rules that still apply

The important anti-overclaim rule is retained:

- fixed-clock 30/90-day simulation is not wall-clock production operation;
- synthetic traffic is not a real user round trip;
- a READY health endpoint is not proof that a message completed the full path;
- tests must not self-authorize a live-validation claim;
- evidence should identify the host, revision, time, and relevant readiness
  transitions without retaining message content unnecessarily.

## Broader rollout governance

The following items from the original checklist remain useful when a deployment
actually needs them, but they are deployment-profile requirements rather than
universal D11L prerequisites:

- traffic eligibility, exclusions, sampling, and minimum sample;
- prolonged wall-clock observation;
- privacy classification, redaction, and trace retention;
- formal kill-switch ownership and activation SLO;
- rollback target and recovery exercise;
- acceptance/pause/abort thresholds and incident routing;
- provider/model drift policy.

A broader release plan may require all or some of them. Their absence does not,
by itself, make the MR core or a controlled single-owner host integration
architecturally incomplete.

## Historical note

The original eleven-field table is intentionally not preserved as an active
checklist in this file. Git history retains it at the pre-ADR-0035 revision.
Use that historical revision only when auditing the August 2026 Product Slice
decision process.
