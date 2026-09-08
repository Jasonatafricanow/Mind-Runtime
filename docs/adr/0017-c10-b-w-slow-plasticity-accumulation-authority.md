# ADR-0017 — C10-B-W Slow Plasticity Accumulation Authority

**Status:** ACCEPTED
**Ticket:** C10-B-W (Accumulation)
**Author:** ZCode
**Date:** 2026-09-03 (revised: Step A/B split, salience double-weighting clarified,
         decay/recovery scope reduced, ADR-0016 reference reanchored)
**Base:** `a4f7bb3` (`w/hi-2-xiyue-host-integration`)
**Authority basis:**
- ADR-0016 — Salience Authority (ADR-0017 does **not** overlap with ADR-0016)
- ADR-0015 §6 — longitudinal accumulation deferred to future ADR
- `docs/C10_BW_ACCUMULATION_AUTH_AUDIT.md` — BLOCKED verdict
- `docs/C10_LONGITUDINAL_TARGET_ONTOLOGY_CONTRACT.md` — BW-ONTO resolved
- `.worktrees/c10-b2-impl/docs/MR_C10_B_W_ARCHITECTURE_SKELETON.md` — B2 skeleton (evidence, not authority)
- `src/mind_runtime/slow_plasticity/writer.py` — current writer implementation (evidence, not authority)
- `src/mind_runtime/contracts/appraisal.py` — SemanticAppraisal / CandidateStateDelta
- Frozen topology: immediate → DynamicsEngine, longitudinal → Homeostasis →
  SlowPlasticity (DynamicsEngine bypassed on the longitudinal path)

---

## Preamble

This ADR does **not** modify code. It answers four semantic questions that
no frozen contract currently resolves, and whose answers are the prerequisite
for any compliant B-W writer implementation.

Two existing candidates are present in the worktree:

- **B2 skeleton** (`MR_C10_B_W_ARCHITECTURE_SKELETON.md`): frequency-window model
- **Current writer** (`src/mind_runtime/slow_plasticity/writer.py`): scalar accumulation model

Neither is the authority. Both are evidence. The authority is this ADR.

---

## Decision 1: What does `proposed_value` represent?

### Evidence (NOT authority)

**B2 skeleton** (`_build_candidate()`):
```python
events: list[SlowEvent]
return events[-1].proposed_value  # last value wins
```
> **Note:** This proves only that the B2 skeleton reads the last event's
> `proposed_value` and passes it through. It does NOT prove that
> `proposed_value` is an absolute target rather than a delta. The B2 skeleton
> is **evidence**, not authority.

**Current writer** (`_accumulate()`):
```python
delta = proposed_value * salience * DEFAULT_LEARNING_RATE  # α = 0.01
next_ = prior + delta
```
> **Note:** This encodes `proposed_value` as a delta and uses it additively.
> This is **evidence** that one implementation chose delta semantics, not
> authority for that choice.

### Options

| Label | Interpretation | Update semantics |
|---|---|---|
| **A** | `proposed_value` is an **absolute target** | `next = target` (window aggregation of targets) |
| **B** | `proposed_value` is a **signed delta** | `next = prior + delta * f(salience)` |
| **C** | `proposed_value` is a **contribution magnitude** | `next = prior + sign * magnitude * f(salience)` |
| **D** | `proposed_value` is a **promotion proposal** | `next = discrete_update(target, proposal_kind)` |

### Decision 1 (frozen by this ADR)

> ⚠️ **This is a NEW semantic decision made by ADR-0017.**
> It is NOT derived from either candidate implementation. Both candidates
> are evidence only. The architecture authority is this ADR.

**`proposed_value ∈ [0.0, 1.0]` is an ABSOLUTE TARGET STATE VALUE.**

Rationale (architecture authority, not implementation-derived):
1. `CandidateStateDelta.amount` carries the magnitude of the per-turn affect
   contribution. The Gate operates on state values, not state increments —
   `SLOW_ACCEPT` means "this target should influence the slow state."
2. Additive accumulation (B/C) creates unbounded drift risk without explicit
   decay mechanics; the slow state spec has no decay mechanism yet (see
   Step C scope reduction below).
3. ADR-0015 §6: grief is "a slow build-up of target state (high negative
   valence)," not an ever-growing numerical increment.
4. The `PromotionCandidate` shape in B2 has a single scalar per dimension;
   this is consistent with absolute-target semantics.

**Implication for B2 skeleton:**
The skeleton's `events[-1].proposed_value` is structurally compatible
under Decision 1 = A: it passes the last event's absolute target forward.
But this is NOT evidence that the skeleton chose A; it just happens to
be a degenerate merge strategy compatible with A.

---

## Decision 2: Step A — Window aggregation

### Critical separation: aggregation ≠ state update

ADR-0017 explicitly splits the slow-state pipeline into three independent
steps, each with its own authority:

```text
Step A — Window aggregation
    A_t = Aggregate(events_in_window_t)            ← THIS DECISION
    (does NOT read S_{t-1}, does NOT write S_t)

Step B — State mutation
    S_t = Update(S_{t-1}, A_t)                      ← DECISION 1+2 caller
    (this is where inertia/retention lives, IF at all)

Step C — Autonomous dynamics
    decay / recovery / bounds                       ← NOT IN ADR-0017 v1
    (deferred to a separate slow-dynamics policy)
```

**Step A and Step B must be specified independently.** Conflating them
(e.g., "writer outputs `new = old + aggregate`") produces unbounded drift
and reintroduces an uncontracted inertia/retention parameter — which is
exactly the `learning_rate` problem this ADR removes.

This ADR freezes **Step A only**. Step B is specified in Decision 2.5
below. Step C is explicitly out of scope.

### Evidence

**B2 skeleton** — `events[-1].proposed_value` (last-value only).
**Current writer** — additive accumulation with `prior` mixed in (which
violates Step A/B separation by definition).

### Options for Step A only

| Label | Strategy | Step A vs B |
|---|---|---|
| **L** | Last-value: `events[-1].proposed_value` | pure A; B can use as input |
| **M** | Arithmetic mean | pure A; B can use as input |
| **W** | Salience-weighted mean | pure A; B can use as input |
| **W+recency** | Salience-weighted mean with recency bias | **REJECTED for v1** — recency_decay is an uncontracted parameter; same class as LR; if needed, belongs in Step C |
| **A-add** | Additive sum | **INVALID**: mixes Step A and Step B |
| **EMA** | Exponential moving average over window | ambiguous; depends on whether it spans windows |

### Salience double-weighting — explicit semantic separation

Salience participates in two architecturally distinct roles. They are
NOT the same semantic operation:

```text
Homeostasis salience        → eligibility test (gate input)
   "is this event significant enough to enter the slow layer?"
   binary / threshold test (per-event)
   produces SLOW_ACCEPT vs REJECT

Aggregation salience        → in-window weighting (writer input)
   "among events that already passed the gate, which better
    represents this window's accumulated intent?"
   weighted average (per-window)
   produces the window's aggregate target
```

These two uses of `salience` are **not double-weighting** because they
operate at different stages on different sets:

| Stage | Operates on | Output |
|---|---|---|
| Homeostasis | all events from a single turn | SLOW_ACCEPT events (subset) |
| Aggregation | SLOW_ACCEPT events in window | one scalar per dimension |

A REJECT event does NOT reach the aggregation step at all. A SLOW_ACCEPT
event at low salience contributes a low weight to the window aggregate —
this is correct: low-salience persistent events should bias the window
less than high-salience ones.

### Decision 2 — Step A (frozen)

#### Window semantics — frozen FIRST

> ⚠️ **Window type and content must be frozen before Step A is implementable.**
> v1 uses a **rolling window of the last N SLOW_ACCEPT longitudinal contributions**
> for each dimension.

```text
slow_window_size = N accepted contributions     ← configuration-owned
window_type = "rolling"                         ← only one supported in v1
                                                 (no tumbling, no time window, no hybrid)
```

The window contents are **accepted contributions per dimension**, ordered
by their admission timestamp. Each time a new `SLOW_ACCEPT` contribution
arrives for dimension `d`, it is appended to `d`'s window; if the window
size exceeds `N`, the oldest contribution is dropped.

The window slides one contribution at a time. Step A runs **after each
contribution append** (or at a configuration-controlled cadence — this
cadence knob is the only scheduling parameter allowed in v1).

**Why rolling, not tumbling:** A tumbling window would make `S_t = A_t`
equivalent to "last window's summary," which lacks longitudinal inertia.
A rolling window means historical inertia is carried **inside the
window itself**, not via an uncontracted α or retention parameter.
The slow character of the state comes from the multi-event window,
not from a writer-internal smoothing constant.

**v1 explicitly does not support:** tumbling windows, time-based windows
(N seconds), hybrid windows, adaptive window sizes, multiple window
strategies per dimension. These are out of scope; if needed later,
they belong in Step C / `SlowDynamicsPolicy`.

#### Step A formula (frozen)

```
A_t(d) =
    Σ [salience_i × proposed_value_i]    for i in W_t(d)
    ------------------------------------------------
                Σ salience_i              for i in W_t(d)

where W_t(d) = last N SLOW_ACCEPT longitudinal contributions
              for dimension d
              (rolling, ordered by admission timestamp)
```

Properties:
- `A_t(d) ∈ [0.0, 1.0]` (proved by input contract: `proposed_value ∈ [0,1]`,
  `salience > 0`; weighted mean of [0,1] values with positive weights is in [0,1])
- A window with zero qualifying contributions → `A_t(d)` is **undefined**;
  no write occurs (see Empty window below)
- A contribution with `salience == 0.0` contributes weight 0.0 → effectively dropped
- Step A reads NO prior slow state. `S_{t-1}` is not consulted here.
- Step A writes NO slow state. It only emits `A_t(d)`.
- Step A introduces NO recency bias, NO EMA, NO time-decay weighting.
  The only weight is `salience`.

### Decision 2.5 — Step B (frozen)

```
S_t(d) = A_t(d)
```

Step B is **overwrite**: the slow state for dimension `d` is replaced by
that window's aggregate. There is no blending with `S_{t-1}`, no EMA,
no retention parameter.

**Inertia is in the window, not in the update function.** The rolling window
maintains a buffer of the last N accepted contributions. Inertia over time
is achieved by window content, not by a smoothing constant applied during
write.

**Consequence:** The slow character of the state comes from:
1. The **multi-event window** (N contributions, not one)
2. The **salience-weighted average** (high-salience events dominate)
3. **Rolling behavior** (older contributions are displaced as new ones arrive)

It does NOT come from a `learning_rate`, `retention`, or any multiplicative
constant in the writer.

### Empty window — no aggregate, no write

```
If W_t(d) is empty (zero qualifying contributions):
    A_t(d) is undefined
    NO WRITE to slow state
    S_{t-1}(d) is retained unchanged
```

**This is the same semantic principle as `None ≠ 0.0` in salience:** the
absence of evidence is not evidence of zero. A zero salience contribution
has weight 0.0 in the mean (it appears in W but contributes nothing).
A missing window means there is no aggregate — this is categorically
different from "the aggregate is 0.0."

---

## Decision 3: Does `learning_rate` exist?

### Evidence

**Current writer**:
```python
delta = proposed_value * salience * DEFAULT_LEARNING_RATE  # α = 0.01
```

The `DEFAULT_LEARNING_RATE = 0.01` is a hard-coded constant with no
frozen authority. ADR-0015 §5 says "all numerical thresholds are
configuration-owned" but does not specify whether LR exists.

**B2 skeleton** — no LR parameter anywhere.

### Options

| Label | Interpretation |
|---|---|
| **Y-CFG** | LR exists, is configuration-owned, has an explicit config field |
| **Y-FROZEN** | LR exists as a frozen architectural constant |
| **N** | LR does not exist; the writer MUST NOT introduce a multiplicative constant |

### Decision 3 (frozen)

**Option N — LR does not exist in the slow accumulation formula.**

Rationale:
1. `proposed_value` is an absolute target (Decision 1 = A); scaling by a
   constant LR is semantically wrong.
2. ADR-0015 §5: "The writer MUST NOT recompute salience" — by the same
   principle, the writer MUST NOT introduce its own uncontracted scaling.
3. Cross-window inertia (a Step B candidate) is now excluded from v1
   (Decision 2.5 = B-overwrite). There is no LR-style knob left.
4. The B2 skeleton has no LR.

```
LEARNING_RATE does NOT exist in the SlowPlasticityWriter accumulation formula.
The writer MUST NOT introduce any multiplicative constant other than salience.
If slower accumulation is desired, the mechanism is window configuration
(count/frequency) or upstream gate threshold, not a writer-internal α.
```

---

## Decision 4: Who owns state bounds, decay, and recovery?

### Critical retraction

> ⚠️ **The earlier draft of this ADR assigned decay/recovery to
> DynamicsEngine. THIS IS RETRACTED.**
>
> The frozen topology is:
> ```text
> immediate affect     → DynamicsEngine
> longitudinal state   → Homeostasis → SlowPlasticity
>                       (DynamicsEngine bypassed on this path)
> ```
> Assigning slow-state decay/recovery to DynamicsEngine would re-couple
> the Fast and Slow paths that the topology explicitly separates.

### v1 scope reduction

> **ADR-0017 v1 freezes mutation only. Autonomous dynamics are out of scope.**

```text
Step C — Autonomous dynamics
    decay / recovery / bounds
    NOT owned by the writer (out of scope for v1)
    NOT owned by DynamicsEngine (would violate topology)
    NOT in ADR-0017 v1
    DEFERRED to a separate slow-dynamics policy ADR
    (future: StateDefinition.dynamics_policy → SlowDynamicsPolicy,
     independent of AffectiveDynamicsPolicy used by DynamicsEngine)
```

### Decision 4 (frozen — narrow scope)

```
STATE BOUNDS (floor/ceiling/clamp):
    A_t(d) ∈ [0, 1] is GUARANTEED by the input contract and the Step A
    formula: weighted mean of values in [0,1] with strictly positive
    weights stays in [0,1]. No writer-side clamp is needed.
    The input contract on `proposed_value ∈ [0,1]` is enforced upstream
    by input validation, NOT by the slow writer.
    Bounds is therefore a contract-validation concern, not a writer concern.

TIME-DRIVEN DECAY and RECOVERY:
    Out of scope for ADR-0017 v1.
    Deferred to Step C ADR (future SlowDynamicsPolicy).

HOMEOSTASIS GATE owns eligibility (SLOW_ACCEPT vs REJECT).

WRITER owns Step A (aggregation over rolling window) and Step B (S_t = A_t).
WRITER does NOT own time-driven evolution of the slow state.
```

### v1 acknowledged gaps (real, not contrived)

| Gap | Status | Mitigation |
|---|---|---|
| No time-driven decay | Deferred to Step C | If needed, this is the natural Step C owner |
| No recovery schedule | Deferred to Step C | Same |
| No autonomous `S_{t-1}` evolution between windows | By design | Slow character comes from rolling window, not from smoothing |
| No clamp on A_t | Not needed | A_t ∈ [0,1] by construction |

These are the only real v1 gaps. There is no `[0,1] bounds deferred` gap
because the bounds are mathematically guaranteed by the formula.

---

## Resulting Formula (canonical v1)

```text
For dimension d:

W_t(d) = last N SLOW_ACCEPT longitudinal contributions
         for dimension d
         (rolling, ordered by admission timestamp)

If W_t(d) is empty:
    A_t(d) is undefined
    NO WRITE
    S_{t-1}(d) is retained unchanged

Otherwise:

A_t(d) =  Σ [salience_i × proposed_value_i]    for i in W_t(d)
         -----------------------------------------------
                    Σ salience_i                  for i in W_t(d)

S_t(d) = A_t(d)
```

Where:
- `proposed_value ∈ [0, 1]` (input contract; enforced upstream)
- `salience > 0` (gate-eligible contributions; weight 0 effectively drops)
- `N = slow_window_size` (configuration-owned)

**Explicitly absent:** LR, EMA, recency_decay, prior-state blending,
empty→0 semantics, writer clamp, time-driven decay/recovery.

The slow character of the state comes from:
1. The multi-event rolling window (N ≥ 1 contributions)
2. The salience-weighted average (high-salience events dominate)
3. Rolling behavior (older contributions are displaced as new ones arrive)

Not from any multiplicative constant in the writer.

---

## Rejected Alternatives

| Alternative | Rejection reason |
|---|---|
| `proposed_value = signed delta` | Additive accumulation risks unbounded drift; conflates target semantics with delta semantics |
| `next = prior + proposed_value * salience * LR` | LR has no frozen authority; additive accumulation violates Step A/B separation |
| `events[-1].proposed_value` (last-value) | Discards salience information from intermediate events; not principled aggregation |
| Step B = blend with retention | Would re-introduce an uncontracted `retention` parameter — same class as LR, rejected |
| Salience-weighted mean with recency bias | `recency_decay` is an uncontracted parameter, same class as LR; if time-decay is needed, it belongs in Step C, not the writer |
| Writer owns bounds clamp | A_t ∈ [0,1] is guaranteed by input contract + positive-weighted mean; bounds is a contract-validation concern, not writer concern |
| Writer introduces its own decay | Writer has no clock; decay/recovery deferred to Step C |
| Salience defaults to 1.0 when None | None at gate boundary is contractually 0.0; using 1.0 bypasses the gate threshold |
| DynamicsEngine owns slow decay/recovery | Violates frozen topology: longitudinal path bypasses DynamicsEngine |
| `empty_window → A_t = 0.0 → S_t = 0.0` | Conflates absence of evidence with evidence of zero; same anti-pattern as `None → 0.0` in salience |
| Tumbling windows in v1 | Would make S_t = A_t equivalent to "last window's summary," losing inertia; rolling is the only v1 window type |
| Time-based windows (N seconds) in v1 | Out of scope for v1; only rolling-N-contributions is frozen |

---

## Affected Contracts

| Contract | Change |
|---|---|
| ADR-0015 §6 | Confirmed: multi-turn aggregation deferred to B-W, now resolved by ADR-0017 |
| C10-SALIENCE-IMPL-R | No change: salience participation in Homeostasis eligibility is unchanged; double-use in aggregation is semantically distinct (see § salience double-weighting) |
| C10-B-W-ONTO | No change: longitudinal target dimension authority unchanged |
| `src/mind_runtime/slow_plasticity/writer.py` | MUST BE REFACTORED: remove LR, replace additive accumulation with rolling-window salience-weighted mean, remove hard clamp; expose `slow_window_size = N` configuration |
| `src/mind_runtime/dynamics/engine.py` | NO CHANGE: DynamicsEngine does NOT own slow-state dynamics; longitudinal path bypasses it (topology) |
| (future) `SlowDynamicsPolicy` | Step C owner — deferred ADR required before production use |

---

## Migration

### Phase 1 (this ADR, no code change)

1. Freeze Decisions 1, 2, 2.5, 3, 4
2. Mark the current `writer.py` as NON-CONFORMANT pending refactor
3. Register Step C as an acknowledged gap (deferred ADR)

### Phase 2 (B-W refactor — mechanical once ADR accepted)

1. Refactor `SlowPlasticityWriter`:
   - Remove `DEFAULT_LEARNING_RATE`
   - Remove additive accumulation (`next = prior + ...`)
   - Implement rolling window of accepted contributions per dimension
     (window size = configuration-owned `slow_window_size`)
   - Implement Step A: salience-weighted mean over the window
   - Implement Step B: `S_t = A_t` (overwrite; no-op if window empty)
   - Remove hard clamp `max(0.0, min(1.0, ...))`
   - Enforce `proposed_value ∈ [0,1]` validation upstream (NOT in writer)
2. Update tests in `tests/mr_assembly_b/test_c10_bw_slow_writer.py`:
   - Remove tests asserting `prior + delta` additive semantics
   - Add tests for rolling-window salience-weighted mean
   - Add tests: empty window → no write
   - Add tests: writer does NOT apply clamp (bounds by formula)
   - Add tests: writer does NOT have LR or recency_decay

### Rollback

If this ADR is rejected: the current writer remains non-conformant but
functional. Step C remains deferred. No regression.

---

## Acceptance Tests

After Phase 2 refactor, the following must pass:

| ID | Description |
|---|---|
| T-BW-A1 | Step A: one contribution in window (salience=0.8, proposed_value=0.7) → A_t = 0.7 |
| T-BW-A2 | Step A: two contributions (0.8, 0.6) and (0.4, 0.8) → A_t ≈ 0.68 (salience-weighted) |
| T-BW-A3 | Step A: salience = 0.0 contributions contribute 0.0 weight |
| T-BW-A4 | Step A: REJECT contributions do NOT contribute (filtered out by disposition) |
| T-BW-A5 | Window is rolling: oldest contribution dropped when N exceeded |
| T-BW-B1 | Step B: S_t = A_t (overwrite, no prior-state influence) |
| T-BW-B2 | Empty window → A_t undefined → no write → S_{t-1} retained |
| T-BW-C1 | Writer does NOT apply additive accumulation |
| T-BW-C2 | Writer does NOT apply recency_bias or time-decay |
| T-BW-C3 | Writer has no `learning_rate` or `DEFAULT_LEARNING_RATE` constant |
| T-BW-C4 | Writer does NOT apply hard clamp `max(0, min(1, ...))` |
| T-BW-C5 | Writer does NOT read `S_{t-1}` (Step A/B separation) |
| T-BW-C6 | `proposed_value` validation to [0,1] is upstream (test the input validation, not the writer) |

---

## Verdict

**DRAFT — Pending architecture authority acceptance.**

ADR-0017 v1 freezes the slow accumulation pipeline as a rolling-window
salience-weighted mean over `SLOW_ACCEPT` longitudinal contributions,
with `S_t = A_t` overwrite and no write when the window is empty.

Architecture authority verdict (pending acceptance):

| Decision | Verdict |
|---|---|
| `proposed_value = absolute target` | ✅ ACCEPT |
| Step A = salience-weighted mean | ✅ ACCEPT |
| recency bias | ❌ DELETED from v1 (same class as LR) |
| Step B `S_t = A_t` | ✅ ACCEPT (precondition: rolling window) |
| Window semantics | ✅ ACCEPT: rolling N accepted contributions |
| `learning_rate` | ✅ does not exist |
| empty window | ✅ RETAIN / no-write only |
| writer clamp | ✅ deleted |
| decay/recovery | ✅ deferred to Step C |

Current writer is non-conformant in three ways:
1. Uses additive accumulation (conflates Step A and Step B)
2. Introduces uncontracted `learning_rate`
3. Applies writer-side hard clamp (bounds is input contract, not writer concern)

The refactor is mechanical once accepted: rolling-window salience-weighted
mean, `S_t = A_t` overwrite, no-write on empty window, remove LR and clamp.

---

---

## Appendix: Relationship to C10-SALIENCE-IMPL-R §9

The audit suggested placing accumulation formula in a C10-SALIENCE-IMPL-R §9.
This was considered and rejected:

- `salience` is already contracted: it is appraisal authority and participates
  in Homeostasis eligibility (C10-SALIENCE-IMPL-R §3).
- Adding the accumulation formula to the Salience contract would couple two
  separate concerns (salience assessment vs. slow-state update mechanics).
- Slow Plasticity accumulation is the authority of Slow Plasticity, not Salience.
- Separate ADR preserves module boundaries per the Non-negotiable Boundaries
  governance rule.
