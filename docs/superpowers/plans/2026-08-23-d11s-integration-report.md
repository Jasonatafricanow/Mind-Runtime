# D11S Deterministic Certification — Integration Report

- **Date:** 2026-08-24
- **Authority:** ADR-0008 and
  `docs/superpowers/specs/2026-08-23-d11s-deterministic-certification-and-d11l-entry-design.md`
- **D11S program base before Task 1:**
  `7c609f5363404e1884f94c4c0cfd9b609eadcdd0`
- **D11S.8 branch base / certified_code_head:**
  `25020c9b5da0930a566a2d34e278a40f62b2eba1`
- **report_commit_head:** intentionally not self-embedded; the immutable commit
  containing this report is recorded in the independent review and final
  handoff after commit.
- **merged_verification_head:** unavailable until reviewed merge; it will be
  recorded only in the external post-merge manifest and final handoff.

## Non-recursive certification identity

This report certifies only `certified_code_head` `25020c9`. That commit is the
merged D11S.1-.7 runtime, tests, fixed inputs, reports, and reviews before any
D11S.8 governance/report change. No tracked runtime, authoritative input,
validation test, pipeline adapter, or Golden fixture was changed after capture.

The report commit cannot contain its own Git identity. Recording
`report_commit_head` after the commit in the independent review is deliberate,
not missing evidence. Post-merge verification similarly writes only to the
ignored external `.artifacts/d11s/<merged_verification_head>/` path and never
changes this report.

## Delivered W inventory and reviews

| W | Accepted implementation/review identity | Evidence | Review result |
|---|---|---|---|
| D11S.1 contracts/digests | code `720f085`; accepted review subject `aee2f30` | `2026-08-23-d11s-task1-report.md`; `2026-08-23-d11s-task1-review.md` | No open Critical/Important |
| D11S.2 composition/horizon | code `601cf8c`; accepted review subject `6521ac6` | `2026-08-23-d11s-task2-report.md`; `2026-08-23-d11s-task2-review.md` | No open Critical/Important |
| D11S.3 bounded replay/G26 v2 | reviewed code `c31a30d`; merged closure `23ae408` | `2026-08-23-d11s-task3-v2-report.md`; `2026-08-23-d11s-task3-v2-review.md` | Approved; rejected v1 excluded |
| D11S.4 model swap/G25 | reviewed code `c5eead0`; merged closure `e8eddc0` | `2026-08-23-d11s-task4-report.md`; `2026-08-23-d11s-task4-review.md` | No open Critical/Important |
| D11S.5 history/G27 | code `67c722d`; merged closure `2f89867` | `2026-08-23-d11s-task5-report.md`; `2026-08-23-d11s-task5-review.md` | Approved |
| D11S.6 restart/G12 | code `b8882c7`; reviewed report `6f9724f`; merged closure `0ccd5b2` | `2026-08-23-d11s-task6-report.md`; `2026-08-23-d11s-task6-review.md` | Approved |
| D11S.7 reports/D11L entry | code `f8bbf3c`; reviewed report `aca1a3d`; merged closure `25020c9` | `2026-08-23-d11s-task7-report.md`; `2026-08-23-d11s-task7-review.md` | 0 Critical / 0 Important / 0 Minor |

## Authoritative fixed inputs

All hashes below cover the actual checked-in UTF-8 bytes at
`certified_code_head`.

| Logical input | Bytes | SHA-256 |
|---|---:|---|
| `runtime-config.json` | 12,982 | `c2112a2565f7917ffb54e836655a73645817b9e04f68a90dfe6d0cbcca13b613` |
| `horizon-30.json` | 9,523 | `8cd5d7778aacdb05da5761ab613cfbbe5d082ab5c3be5ca6c43c53f782463864` |
| `horizon-90.json` | 9,523 | `5f715e34130acabd053a829770a3b8e031d3dd8e1dd8cf21701b196b4d190ef1` |
| `model-swap-left.json` | 82 | `5b1d6e3ddf9ab66abddeacb869d8e632444ee8c233d292b10335e1a3437789fd` |
| `model-swap-right.json` | 89 | `e9e5bd342b768fda76434aafef4870d1a6e03d712a0468b5c73b45251b7acc0b` |
| `history-g27.json` | 1,421 | `1b4147a40432b9afc4acc45157c67235dcbd25ee4adbc91602bbcf1f8943f110` |
| `restart-g12.json` | 14,965 | `72820167ee8be0f3e78ffda5a91aaeae33ea07acaa3e845a93083bb5b4305d07` |

The complete `RuntimeConfigManifest` byte hash is therefore
`c2112a2565f7917ffb54e836655a73645817b9e04f68a90dfe6d0cbcca13b613`.
Its closed fixture registry was decoded and verified before each canonical
composition was built.

## 30/90 fixed-clock capture

Both certifications were constructed from the checked-in templates plus the
exact `certified_code_head`, into fresh empty roots. Each horizon ran first,
replay, history-control, and no-duplicate-control compositions over independent
durable stores. The report daily series excludes the initial baseline capture,
retains all 30/90 elapsed virtual-day captures, and reindexes them from zero as
required by the frozen `CertificationReport` contract.

| Horizon | Virtual duration | Measured wall time | Daily replay | Report semantic SHA-256 |
|---:|---:|---:|---|---|
| 30 days | 30 fixed-clock days | `20.0673336000036s` | 30/30 byte-identical | `fae2f6d50bead9622cabb5c32bc3e2e22c49e289e9cb4e3cf0af44885b1709f5` |
| 90 days | 90 fixed-clock days | `54.0575125000032s` | 90/90 byte-identical | `ff6dd6c7bc4459482f4d080b1d64374576f876c80e708318642d1cfa10ded79a` |

Wall-clock seconds are evidence metadata only and are excluded from the report
semantic identity.

### Invariant evidence

All five required invariants passed exactly once in both horizons.

| Invariant | 30-day refs | 90-day refs | Evidence boundary |
|---|---:|---:|---|
| `state.boundedness` | 88 | 88 | First/last typed affect state references through `day-21-restart` |
| `replay.semantic_records` | 2 | 2 | First-run and replay daily-record SHA-256 references |
| `time.registered_dynamics` | 42 | 162 | Registered non-event daily records through day 30/day 90 |
| `history.no_self_excitation` | 16 | 16 | Duplicate event/evidence plus all named event controls |
| `history.false_history_reversible` | 6 | 6 | False-history/correction assessment, independent control, recovery window, tolerance |

Representative replay references are:

- 30-day first/replay:
  `daily-record:first:0:5a28f3b03e859eafd72fb4163f6a6d9751c3fced2ee698a78220fa81d38201c3`
  and
  `daily-record:replay:0:5a28f3b03e859eafd72fb4163f6a6d9751c3fced2ee698a78220fa81d38201c3`;
- 90-day first/replay:
  `daily-record:first:0:114dc1bc5ad465e055a49527e74a8235574eb782e2d55e14fabaaddf90ac3864`
  and
  `daily-record:replay:0:114dc1bc5ad465e055a49527e74a8235574eb782e2d55e14fabaaddf90ac3864`.

## Actual report artifacts

`ArtifactManifest.bytes_sha256` matched an independent SHA-256 over the final
published bytes in both cases.

| Logical path | External capture path | Bytes | Actual-byte SHA-256 |
|---|---|---:|---|
| `d11s-certification-30.json` | `<TEMP_ROOT>\d11s8-run\d11s-certification-30.json` | 48,883 | `d956c8863316f3ea88c7334794f4258b0e52c3be611f9382daa0f22a69803a46` |
| `d11s-certification-90.json` | `<TEMP_ROOT>\d11s8-run\d11s-certification-90.json` | 135,044 | `3fdc8e287935373d11276b8c0e7de48c2f303d985fd4e0030a8645ac93d9d662` |

These temporary paths are capture provenance, not portable logical identity and
not committed repository content.

## Golden and xfail closure

The real canonical adapters produced exactly the fixture outputs:

```text
G12: restart.consistent=true
G25: internal_transition=same; intent=same; policy=same; expression=may_differ
G26: horizon.days=90; affect.within_bounds=true;
     recovery.replayable=true; self_excitation.unbounded=false
G27: unique_source_count=1; retrieval_count=3;
     influence_multiplier=1.0; reinforced=false
```

G12 is the ADR-0008-corrected composite restart property: existing durable Fact,
State, Intent, and Checkpoint planes close and reopen through public APIs;
read-only history remains unchanged. It does not claim `ReceiptStore`, an
individual `ActionReceipt`, `receipts.sqlite`, Native Memory, or `memory.sqlite`
durability.

The sole remaining strict xfail is exactly G28 with owner/reason
`MR-D11P not implemented`. G12/G25/G26/G27 are green through their real D11S
adapters; no Golden expectation or G28 ownership changed in D11S.8.

## D11L boundary

The separately committed D11L entry package contains exactly eleven mandatory
fields. All remain unavailable because no real host, eligible traffic contract,
accepted owner, operational threshold, privacy approval, kill-switch exercise,
rollback exercise, wall-clock observation, or live provider inventory exists.

D11S readiness authorizes only entry into a separately reviewed D11L design and
external-environment gate. It does not authorize traffic, deployment, D11P,
MR-4, or MR-5.

## Quality gates

The first complete post-governance gate produced:

```text
pytest --collect-only : 1387 tests collected
pytest                 : 1386 passed, 1 xfailed in 266.66s
coverage pytest        : 1386 passed, 1 xfailed in 524.93s
coverage               : 7126 statements / 2284 branches
                         0 missed / 0 partial / 100%
ruff check .           : All checks passed
ruff format --check .  : 313 files already formatted
mypy src tests         : Success: no issues found in 231 source files
git diff --check       : clean
sole strict xfail      : G28 — MR-D11P not implemented
```

The required second full gate after this report edit is recorded in the
independent review and final handoff rather than recursively changing these
captured values.

## Exclusions

- No live Kayla host or traffic was connected.
- No real 30/90 wall-clock-day observation was performed.
- No live shadow validation, feature flag, sampling plan, owner, threshold,
  privacy approval, kill switch, rollback, or model-drift policy was invented.
- No D11P onboarding or productization behavior was implemented.
- No certified runtime, fixed input, validation component, pipeline adapter,
  Golden fixture, or Golden expectation changed after capture.
- The rejected D11S.3 v1 shortcut is not part of this certification.

## Closure wording

```text
D11S: COMPLETE
FIXED-CLOCK 30/90-DAY CERTIFICATION: PASS
LIVE SHADOW VALIDATION: NOT PERFORMED
D11: INCOMPLETE
READY FOR D11L: YES
READY FOR D11P: NO
```

