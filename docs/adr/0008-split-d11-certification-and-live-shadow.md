# ADR-0008: Split D11 Deterministic Certification from Live Shadow Validation

- **Date:** 2026-08-23
- **Status:** Accepted after independent architecture-entry review

## Problem

The approved compressed Product Slice describes D11 as both long-horizon
fixed-input validation and Kayla shadow integration. Those claims require
different evidence:

- fixed-clock 30-day and 90-day simulations can be executed reproducibly in
  the repository;
- feature-flagged shadow, context-assist, controlled takeover, kill-switch,
  rollback, sampling, redaction, and retention claims require a real Kayla
  host and wall-clock operational evidence that this repository does not
  provide by itself.

Treating a fast fixed-clock simulation as 90 days of real operation would be a
false delivery claim. Blocking all deterministic certification until a host is
available would also discard useful evidence that the repository can produce
now.

G12 has a second authority conflict. ADR-0003 moved the composite restart
scenario to D11 and described it as state, Memory, relationship, and pending
writeback consistency. Native Memory is still MR-4, outside the continuous
Product Slice backlog. D11 cannot create a fake Memory domain or a
MemoryCandidate write path merely to make G12 green.

## Decision

Split D11 into two ordered gates:

```text
D10 -> D11S deterministic certification -> D11L live shadow validation
    -> D11 complete -> D11P
```

### D11S — deterministic certification

D11S runs repository-owned, fixed-input certification against the one
canonical runtime path. It may add a validation package, manifests, test
fixtures, and reports. It must use the existing orchestrator and production
components rather than implement a second business pipeline.

D11S owns:

1. 30-day and 90-day fixed-clock simulations;
2. bounded-state, recovery, saturation, clamp, replay, and self-excitation
   invariants;
3. expression-model swap comparison in which prose may differ but the
   deterministic Transition, Intent, and ActionPolicy digest must not;
4. repeated read-only history surfacing without reinforcement or multiplicative
   influence;
5. a fresh-process-equivalent restart over every durable plane already in the
   Product Slice;
6. reproducible certification manifests tied to an exact Git HEAD, frozen
   event bytes, complete effective runtime configuration, and actual scripted
   provider-fixture bytes. No implicit unhashed default is permitted.

D11S completion may emit `READY FOR D11L: YES`. It may not emit `D11:
COMPLETE`, `READY FOR D11P`, a deployment claim, or a real 30/90-day-operation
claim.

### D11L — live shadow validation

D11L owns real host integration and operational evidence. Its entry gate
requires a separately approved design containing the exact Kayla host,
eligible traffic definition, wall-clock observation period, minimum sample,
privacy/redaction policy, trace-retention policy, feature-flag ownership,
kill-switch owner, rollback procedure, and success/abort thresholds.

Until that design and environment exist, D11L remains blocked. Repository-only
tests, scripted providers, or synthetic traffic cannot satisfy D11L.

### G12 scope resolution

G12 is corrected to certify the durable planes that exist in the Product
Slice:

- Evidence and Observation;
- Canonical user, agent, and relationship State plus StateTransition;
- pending Intent lifecycle;
- TurnCheckpoint, including its durable `action_id` and `delivery_status`
  inputs to restart recovery/reconcile decisions;
- the hash of any supplied read-only HistoricalContextBundle.

The test constructs a fresh runtime composition over the same SQLite files and
compares the authoritative post-restart snapshot, checkpoint recovery
decision, and pending-work digest. `ReceiptRegistry` is currently in-memory;
this ADR does not claim that individual ActionReceipt records are durable. A
read-only historical bundle must remain byte/content equivalent and must not
gain a reinforcement, touch, promotion, or write record.

G12 does **not** require or authorize Native Memory, MemoryCandidate, Memory
consolidation, relationship inference, or Memory writeback. References in the
fixture and test prose to Memory writeback are replaced under this ADR. MR-4
remains blocked.

## Evidence Labels

Every D11S report must record both values:

```text
virtual_horizon_days: 30 or 90
wall_clock_execution_seconds: measured runtime
```

The report uses the term `fixed-clock simulation`, never `operated for 90
days`, `production proven`, or `shadow validated`.

Certification and publication use three non-recursive identities:

- `certified_code_head` is the merged D11S.1-.7 runtime/test/input commit
  actually exercised before D11S.8 report/governance-only changes;
- `report_commit_head` contains the report that points back to that certified
  code head;
- `merged_verification_head` is main after the reviewed report commit merges.

Post-merge verification evidence is stored as an ignored external artifact
keyed by `merged_verification_head`; it is never committed back into the
certified repository and therefore cannot recursively change the claimed HEAD.

## Rejected Alternatives

### Treat fixed-clock simulation as complete D11

Rejected because it would fabricate operational evidence and bypass the
approved shadow, rollback, privacy, and kill-switch requirements.

### Keep all D11 work blocked until a host exists

Rejected because deterministic replay, model isolation, restart, and
anti-amplification are valid repository-owned acceptance evidence and catch
defects before live integration.

### Implement a temporary Memory store for G12

Rejected because it would create MR-4 behavior without its provider benchmark,
domain design, or architecture gate. Test-only fake Memory would also violate
ADR-0003's requirement that restart correctness live on the canonical path.

### Make D11S a second scenario-only business pipeline

Rejected because it could pass while the canonical orchestrator remains
incorrect. The certification layer may schedule inputs, build runtime
compositions, capture snapshots, and compare evidence; business decisions stay
inside the existing runtime.

## Affected Authority and Contracts

- D7R section 9 is interpreted as two ordered D11 gates rather than one
  repository-only completion claim.
- ADR-0003's G12 owner remains MR-D11, but its unavailable Native Memory clause
  is resolved as an explicit non-requirement for D11S.
- G12 and G25-G27 remain strict xfails until their D11S implementation W closes.
- G28 remains owned by D11P and is not changed by D11S or D11L.
- No protected runtime contract changes are authorized by this ADR. Any later
  need to change a protected contract requires its own ADR before code.

## Rollback

Before D11S merges, rollback is deletion of the D11S architecture branch.
After merge, revert the ADR, design, D11S validation package, fixtures, and
reports as one reviewed batch. Rollback must restore G12 and G25-G27 to their
previous strict-xfail owner bindings; it must not leave a green Golden backed
by an unowned validation path.

## Acceptance

ADR-0008 is accepted only when an independent reviewer confirms:

- the D11S/D11L evidence boundary is explicit and fail closed;
- G12 no longer implies unauthorized Native Memory;
- D11S always uses the canonical runtime;
- virtual and wall-clock duration are reported separately;
- D11P, MR-4, MR-5, deployment, and release remain blocked;
- no current production code or Golden owner is changed by this architecture
  entry commit.
