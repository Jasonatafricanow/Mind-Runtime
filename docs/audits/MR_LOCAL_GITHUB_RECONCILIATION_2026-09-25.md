# MR Local-to-GitHub Reconciliation Audit — 2026-09-25

**Status:** ACTIVE RECOVERY / MIGRATION RECORD  
**Purpose:** prevent completed local development from being lost behind the clean publication baseline, and provide one explicit reconciliation map from preserved local worktrees/branches to current GitHub `main`.

## 1. Why this audit exists

The public repository was intentionally rebuilt as a clean publication baseline. That decision made the Git graph smaller, but it also created a second obligation: every locally completed feature line must be explicitly classified as one of:

1. migrated into canonical `main`;
2. preserved as an active/recoverable implementation line;
3. archived as superseded evidence;
4. intentionally left research-only.

The previous assumption that the clean baseline already contained all completed implementation work is false. At least two substantial implementation lines are absent from current `main`:

- MR Reality/Input / StateBar-derived integration;
- Late Projection -> W3 Surface -> Fast Function -> proactive behavior.

This document is the canonical reconciliation record for recovering those lines without redesigning them.

## 2. Current canonical GitHub target

Repository: `Jasonatafricanow/Mind-Runtime`

Current target at audit start:

```text
main = 80a62129f048b422ba0d586d1e83530320dba813
```

Current main contains the clean publication baseline, packaging/CI cleanup, cognitive modes, and the later Memory architecture/product work. It does **not** contain the mature Reality/Input or behavior feature trains described below.

## 3. Last confirmed local cleanup snapshot

The 2026-09-24 worktree hygiene pass intentionally reduced the local checkout from 28 worktrees to 8 while preserving all active lines.

Authoritative local root:

```text
C:\projects\mind-runtime-main-merge
```

The old `C:\projects\Mind Runtime` path is historical and must not be treated as authority.

The cleanup preserved the following active/recovery lines:

| Local line | Preserved head / state | Classification |
| --- | --- | --- |
| canonical main | `9552c0d...` at cleanup time | canonical |
| W3 Surface | `386d3e8...` | completed implementation line |
| Reality/Input | `14154a5...` | completed implementation line |
| Fast Function V1 | `5f96352...` | completed implementation line |
| Longing proactive | `e48ce1e...` dirty at cleanup; later hardened further | active implementation line |
| Affect longitudinal harness | `08cca45...` dirty | research/experimental, preserve |
| Gu Qinghe experiment | `3e68d75...` | research/benchmark evidence |
| recovery/pre-hygiene-untracked-20260924 | `d7bd226...` | recovery authority for untracked docs/evidence |

The cleanup also created six recovery commits before pruning dirty superseded worktrees:

```text
4da579e...  18 files
07d4053...   3 probes
6ab39cd...   3 contract/experiment files
e778749...  14 audit/probe files
b6ab23f...   3 review/probe files
8f57bb4...   6 golden/contract files
```

These recovery refs exist to prevent data loss. They are not automatically production migration candidates.

Archived tags preserved superseded predecessor lines:

```text
archive/mr-late-projection-w1
archive/mr-late-projection-f1-f2
archive/mr-statebar-reuse-01
archive/statebar-mr-binding-01
```

Do not delete recovery refs/tags until this audit is fully closed.

## 4. Local-only Reality/Input line

The final preserved local Reality/Input implementation is:

```text
w/mr-reality-eligibility-replay-stability-01
14154a52848906b67ad200ce39f0094b2d06e0e5
```

Its predecessor chain included:

```text
w/statebar-mr-binding-01
w/mr-statebar-reuse-01
w/mr-reality-input-hardening-01
w/mr-reality-eligibility-replay-stability-01
```

The final line had already implemented and reviewed:

- deterministic Reality/Input eligibility;
- modality / semantic-time / effective-window handling;
- planned/tentative/future observations do not become current state;
- replay does not re-run semantic/provider interpretation;
- replay preserves original semantic target and provenance;
- exact terminal/cancellation target binding;
- stable retry/replay behavior;
- no required StateBar runtime dependency.

Historical final evidence reported:

```text
Reality/Input: 69/69 PASS
affected:      51/51 PASS
full suite:    2957 passed / 7 failed / 2 errors
```

The 7 failures and 2 errors matched that historical baseline rather than new Reality regressions.

Current GitHub main has the architecture note but not this implementation.

Migration tracking: GitHub issue #8.

## 5. Behavior feature train that diverged after 17772842

Current remote feature branches preserve a continuous implementation train whose merge-base with current `main` is:

```text
17772842aaffd44c4ff1a643e9fa4621fa9e6652
```

The advanced branch line contains the following major stages.

### 5.1 Late Projection W1/W2

Recovered progression includes:

```text
2a2af130...  accept ADR-0027
f3196eba...  bounded open event vocabulary
6e027cdc...  deterministic appraisal/projection journal
...
ee6b25d...   W2 runtime consumption completion
```

The W2 implementation included:

- `AcceptedAppraisal`;
- one deterministic AppraisalProjector;
- durable projection journal;
- MAPPED / UNMAPPED / ABSTAINED / REJECTED outcomes;
- accepted meaning independent from effect mapping coverage;
- application receipts and exactly-once application semantics;
- retry/restart and cross-interaction protections;
- bounded `COGNITIVE_MEANING` provider context;
- explicit legacy no-appraisal compatibility path.

The W2 audit reported a fully green implementation run after targeted hardening, while later recertification documents recorded review-process/manifest gates. Migration must therefore recover the **final hardened source lineage**, not an earlier intermediate review state.

Current GitHub main still contains the old pre-acceptance ADR-0027 text marked PROPOSED and none of the production symbols above. This is stale relative to the completed feature line.

### 5.2 W3 Surface

Recovered progression includes:

```text
e4af8b09...  Persona behavioral disposition authority
702a22ac...  deterministic Surface projection
b35c584d...  Surface-aware Intent integration
f2f01b40...  Surface expression/provider exposure
386d3e8d...  authority and durability hardening
```

The implementation added production modules including:

```text
src/mind_runtime/contracts/surface.py
src/mind_runtime/surface/
src/mind_runtime/persona_publication.py
src/mind_runtime/delivery/surface_handoff.py
src/mind_runtime/intents/surface_validator.py
src/mind_runtime/expression/expression_map.py
```

Key properties already implemented:

- stable Persona behavioral-disposition authority;
- immutable Persona publication/revision resolution;
- one deterministic Surface projection;
- Surface -> Intent influence without granting action permission;
- Surface -> qualitative expression guidance;
- restart recomputation from canonical state + exact Persona revision;
- durable provider handoff lineage;
- no raw affect/persona numeric leakage into provider guidance;
- no independent Surface state store.

Current GitHub main contains none of these modules.

### 5.3 Fast Function V1

Recovered implementation:

```text
5f963528... feat(dynamics): freeze functional fast-state v1 registry
```

Production module:

```text
src/mind_runtime/dynamics/fast_functions.py
```

The frozen registry separated functional state contracts from consumer closure and did not claim that every registered state was production-activated.

Current GitHub main does not contain this module.

### 5.4 Proactive behavior consumers

The same feature train later implemented/hardened:

```text
longing -> proactive contact
sharing_urge -> proactive share
curiosity -> proactive inquiry
anger -> boundary/directness expression
sadness -> initiative-suppression audit
```

The proactive host path was corrected so causal order is:

```text
Dynamics / Surface
-> Intent
-> ActionPolicy
-> WakeSignal
-> Host wake admission
-> Body proactive turn
-> provider realization
-> ExpressionGuard
-> explicit delivery commit
```

Provider invocation was removed from the ticker. Action permission remained owned by ActionPolicy.

Important migration rule: code recovery must **not** silently change activation state. Historical audits explicitly left several consumers blocked by runtime config or deferred:

- longing runtime machinery closed; production config gap remained;
- sharing urge code ready; production activation blocked by config;
- curiosity question branch closed; retrieval branch deferred; activation blocked by config;
- anger expression branch closed; proactive boundary Intent deferred;
- sadness Surface math/expression verified but no effective initiative consumer was certified.

Migration restores code capability and audit truth. It does not convert deferred/config-blocked features into active production behavior.

## 6. Remote code evidence vs current main

Against current `main`, the advanced behavior branch contains a large non-main code surface.

Observed missing-on-main production additions include:

```text
src/mind_runtime/contracts/late_projection.py
src/mind_runtime/contracts/surface.py
src/mind_runtime/delivery/surface_handoff.py
src/mind_runtime/dynamics/fast_functions.py
src/mind_runtime/emotional_transition/projection_journal.py
src/mind_runtime/expression/expression_map.py
src/mind_runtime/intents/surface_validator.py
src/mind_runtime/persona_publication.py
src/mind_runtime/surface/__init__.py
src/mind_runtime/surface/adapter.py
src/mind_runtime/surface/cognition.py
src/mind_runtime/surface/evaluator.py
src/mind_runtime/surface/expression_map.py
src/mind_runtime/surface/lineage.py
src/mind_runtime/surface/projector.py
src/mind_runtime/surface/recipe.py
```

The feature branch also modifies dozens of existing production files and carries extensive focused tests. Therefore this line must be reconciled rather than recreated.

## 7. Recovery-only / research lines

The following preserved local work is **not** automatically a production migration target.

### Affect longitudinal harness

Preserved head:

```text
08cca45...
```

The line contains useful longitudinal/restart/provenance experiments, but later work remained dirty and unresolved around temporal/occurrence authority. Preserve as research evidence; do not import wholesale into runtime.

### Gu Qinghe experiment

Preserved head:

```text
3e68d75...
```

The experiment produced useful benchmark evidence but also exposed invalid samples where history was only placed in provider prompt rather than truly replayed into MR. Preserve experiment/results; do not treat as production feature code.

### Recovery/untracked docs

Recovery head:

```text
d7bd22690864f2d5b2e9581e5330539de7c0f47d
```

It preserved architecture/audit material including files that are absent from current main, such as the Reality Observation and Affect Runtime contract records. Recover documents selectively after byte/content review; do not infer production authority from a recovery branch alone.

## 8. Already represented / superseded lines

These do not need separate production resurrection:

- baseline reconciliation that is already in canonical history;
- predecessor StateBar binding/reuse branches once the final Reality/Input line is recovered;
- predecessor Late Projection W1/F1-F2 snapshots once the final hardened W2 source is recovered;
- temporary cleanup/portfolio branches whose content already exists in current main.

Archived refs remain evidence until final reconciliation closes.

## 9. ADR numbering collision

The behavior feature train used historical ADR numbers that now collide with later mainline Memory ADR numbering.

In particular:

```text
feature train ADR-0028 = single-surface behavior exposure
current main ADR-0028  = three-timescale memory and incremental cognition
```

Migration must not overwrite current Memory ADRs.

Required treatment:

1. preserve accepted behavior decision content;
2. assign new non-conflicting ADR numbers in current main;
3. update internal references;
4. record old -> new ADR number mapping;
5. do not reinterpret this as a new design decision.

## 10. Migration dependency order

The recovery order is constrained by the historical implementation dependency graph:

```text
A. Reality/Input
   -> current-main reconciliation
   -> focused + full CI

B1. Late Projection W1/W2 final hardened source
   -> reconcile stale ADR state
   -> focused + full CI

B2. W3 Surface + Persona publication + durable handoff
   -> renumber conflicting ADRs
   -> preserve current Memory/LCE work
   -> focused + full CI

B3. Fast Function V1 registry
   -> focused + full CI

B4. Proactive consumers
   -> longing
   -> sharing urge
   -> curiosity question path
   -> anger expression
   -> sadness audit truth
   -> keep config/deferred states unchanged
   -> focused + full CI

C. Recovery documents
   -> selective restoration after byte/content review
```

Do not merge the advanced feature branch wholesale. It diverged before later mainline packaging/CI/cognition/Memory work and modifies many of the same files. Migration is a forward-port/reconciliation job.

## 11. Required fresh local audit before deleting any preserved refs

Before migration is declared complete, the authoritative local root must be opened and verified directly.

Required commands/outputs must establish:

- `git rev-parse --show-toplevel`;
- `git status --short`;
- `git worktree list --porcelain`;
- `git branch -vv --all`;
- `git log --all --decorate --oneline` around all preserved heads;
- existence/content of local-only commits `14154a5...`, `08cca45...`, `3e68d75...`, `d7bd226...` and the six recovery commits;
- any work performed after the 2026-09-24 cleanup snapshot that is not represented by current GitHub branches;
- dirty/untracked bytes in every still-preserved worktree.

No preserved local worktree, recovery ref, or archive tag may be deleted until this direct audit and the corresponding migration/content-equivalence review are complete.

## 12. Closure condition

This reconciliation is complete only when every preserved local line has one explicit final disposition:

```text
MIGRATED_TO_MAIN
SUPERSEDED_BY_MIGRATED_DESCENDANT
PRESERVED_RESEARCH_ONLY
PRESERVED_RECOVERY_ONLY
INTENTIONALLY_DEFERRED
```

and all `MIGRATED_TO_MAIN` lines have:

- source head recorded;
- target main base recorded;
- reconciled file inventory;
- behavioral-difference report;
- focused tests;
- current full CI;
- post-migration main SHA;
- old worktree/ref cleanup decision.

Until then, the clean publication baseline must not be treated as proof that local implementation history has been fully migrated.
