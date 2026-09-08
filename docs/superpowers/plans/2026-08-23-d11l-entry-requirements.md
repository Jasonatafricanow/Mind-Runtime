# D11L Entry Requirements

- **Date:** 2026-08-24
- **Authority:**
  `docs/superpowers/specs/2026-08-23-d11s-deterministic-certification-and-d11l-entry-design.md`
  and `docs/adr/0008-split-d11-certification-and-live-shadow.md`
- **Produced by:** D11S.7
- **Current status:** `D11L: BLOCKED_BY_EXTERNAL_ENVIRONMENT`

## Purpose and boundary

This document records the evidence that a separately reviewed D11L design must
provide before live shadow validation can begin. It does not create a host
adapter, authorize traffic, name owners who have not accepted responsibility,
or treat repository simulations as operational evidence.

D11S fixed-clock certification may establish `READY FOR D11L: YES` only as
readiness to enter the D11L design and environment gate. It does not mean that
D11L execution is currently possible. D11 remains incomplete, live shadow
validation has not been performed, and D11P remains unauthorized.

## Mandatory entry fields

| # | Mandatory field | Current availability | Required owner or authority | Required admissible evidence | Fail-closed behavior |
|---:|---|---|---|---|---|
| 1 | Real Kayla host and deployment boundary | **Unavailable.** No real Kayla host or deployable boundary is identified in repository evidence. | A host/platform owner must accept the named runtime, environment, deployment unit, and isolation boundary. | Reviewed host inventory, deployment topology, environment identity, and access boundary from the real operating environment. | No host adapter, shadow connection, or traffic may be enabled. |
| 2 | Eligible traffic and exclusions | **Unavailable.** No real interaction population, eligibility rule, or exclusion list is approved. | Product, safety, and host owners must jointly approve eligibility and exclusions. | Executable traffic definition tied to real host fields, explicit exclusions, and validation samples from the named environment. | Treat all traffic as ineligible. |
| 3 | Feature flag owner and default-OFF behavior | **Unavailable.** No exact flag, owner, scope, or default is approved. | A named operational flag owner with authority over the real host must accept responsibility. | Flag definition, default-OFF proof, scope rules, authorization path, audit trail, and negative test from the real environment. | The feature remains OFF; absence or ambiguity is OFF, never implicit enablement. |
| 4 | Phase transitions | **Unavailable.** Shadow, context-assist, and controlled-takeover entry/exit transitions are not designed or approved. | A named D11L release authority plus safety owner must approve every phase transition. | Separately reviewed state machine with prerequisites, approvals, rollback edges, and evidence required for each transition. | Remain outside D11L; no later phase may be inferred from elapsed time or partial success. |
| 5 | Sampling method and minimum sample | **Unavailable.** No population method, stratification, exclusion handling, or minimum sample exists. | A named experiment/measurement owner and safety reviewer must approve the method. | Sampling specification tied to eligible traffic, bias analysis, minimum sample calculation, and reproducible selection audit. | No acceptance rate or safety conclusion may be calculated or claimed. |
| 6 | Wall-clock observation duration | **Unavailable.** Fixed-clock 30/90-day simulation is not real elapsed observation time. | A named D11L measurement owner must approve start/stop criteria and minimum duration. | Timestamped evidence from the real host covering the approved continuous or cumulative wall-clock window and interruptions. | Report `LIVE SHADOW VALIDATION: NOT PERFORMED`; never convert virtual days into operating days. |
| 7 | Privacy classification, redaction, and retention | **Unavailable.** No field-level live-traffic classification, redaction policy, or trace-retention schedule is approved. | Named privacy/security/data-governance owners must approve classification and handling. | Field inventory, classification, collection purpose, redaction tests, access controls, retention/deletion rules, and compliance approval. | Collect and retain no live D11L traces. |
| 8 | Kill switch owner, latency, and test | **Unavailable.** No owner, maximum activation latency, mechanism, or real-environment exercise is approved. | A named 24/7 operational owner with authority to disable the feature must accept responsibility. | Kill-switch implementation identity, alert/runbook, maximum latency SLO, authorization path, and timed real-environment exercise. | D11L cannot start; an untested or ownerless kill switch is equivalent to no kill switch. |
| 9 | Rollback owner, target, and recovery verification | **Unavailable.** No rollback owner, known-good target, restoration objective, or recovery test exists. | A named release/operations owner must own rollback execution and verification. | Immutable rollback target, dependency/data compatibility analysis, runbook, recovery objectives, and successful real-environment rollback/recovery exercise. | No deployment or traffic transition may occur. |
| 10 | Acceptance, pause, abort, and incident thresholds | **Unavailable.** No operational metric definitions or numeric thresholds are approved. | Named safety, product, and incident authorities must approve thresholds and escalation ownership. | Exact metrics, denominators, windows, minimum samples, acceptance/pause/abort values, incident classes, alert routes, and decision authority. | Any missing metric, denominator, or threshold blocks progression; safety uncertainty pauses/aborts rather than passes. |
| 11 | Model/provider versions and drift handling | **Unavailable.**（注：owner 嘉森已于 2026-08-26 认领并拍板允许切换不冻结——决策记录见 `2026-08-26-d11l-entry-claims-accepted.md`；本字段在证据完备前保持 Unavailable，反映"未满足"而非"未认领"。） | Named model/platform and D11L safety owners must own version changes and drift decisions. | Exact provider/model/version/config identity, monitoring signals, drift thresholds, freeze/re-certification rules, and tested fallback behavior. | Unidentified or changed model/provider state blocks or pauses D11L until separately reviewed and re-certified as required. |

## Evidence admission rules

- Synthetic traffic, scripted providers, local fixtures, Golden scenarios, and
  fixed-clock certification cannot fill any field above.
- A repository path, planned owner, or proposed threshold is not evidence of
  real-environment availability or operational acceptance.
- Every owner must be a named authority who has accepted the duty; ownership is
  not inferred from code authorship or component maintainership.
- Evidence must identify the real host/environment, collection time, source,
  version, approval, and integrity reference. Missing lineage is unavailable.
- Partial completion of a row leaves that row unavailable. Completion of ten
  rows cannot compensate for one missing mandatory row.

## Required next decision

All eleven mandatory fields are currently unavailable. D11L execution must not
begin, no live traffic may be admitted, and no shadow-validation claim may be
emitted.

```text
D11L: BLOCKED_BY_EXTERNAL_ENVIRONMENT
LIVE SHADOW VALIDATION: NOT PERFORMED
D11: INCOMPLETE
READY FOR D11P: NO
```

Later availability requires a separately reviewed D11L design revision that
replaces each unavailable entry with admissible external evidence and records
the named approving owner. This document is a current fail-closed entry
package, not a promise that those prerequisites will become available.
