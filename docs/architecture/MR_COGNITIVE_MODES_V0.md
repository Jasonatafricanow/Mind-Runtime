# MR Cognitive Modes V0 Architecture Contract

**Task:** MR-COGNITIVE-MODES-V0-CONTRACT-01  
**Status:** FROZEN CONCEPT LAYER (V0)  
**Module:** `src/mind_runtime/cognition/modes.py`  

> "Cognitive modes define when and what kind of cognition runs.
> They do not define emotion, personality, truth, or action authority."

---

## 1. Core Principle

Cognitive modes are **cognitive execution modes**. They govern runtime scheduling and processing dispatch for autonomous cognition.

They are **NOT**:
- Affect dimensions
- Persona traits
- Surface controls
- Prompt style labels

---

## 2. The Five Frozen Cognitive Execution Modes

The V0 runtime freezes exactly five cognitive execution modes:

| Mode | Purpose | Interactive | Background | Outbound Allowed | Interruptible | Parent Mode | Output Class |
|---|---|---|---|---|---|---|---|
| `ACTIVE` | Normal online cognition | `True` | `False` | `True` | `True` | `None` | Canonical turn pipeline |
| `INTROSPECTIVE` | Structured internal reflection | `False` | `True` | `False` | `True` | `None` | Candidate cognition only |
| `DAYDREAM` | Lightweight idle association | `False` | `True` | `False` | `True` | `None` | Candidate cognition only |
| `SLEEP` | Deep offline cognitive rest | `False` | `True` | `False` | `True` | `None` | Candidate consolidation only |
| `DREAM` | Sleep-associated loose linking | `False` | `True` | `False` | `True` | `CognitiveMode.SLEEP` | Candidate cognition only |

### 2.1 ACTIVE

Normal online cognition. The existing normal path remains authoritative:

```text
inbound / clock
    → cognition
    → Dynamics
    → Intent
    → ActionPolicy
    → Body
```

- Normal user interaction and proactive clock-tick processing.
- Outbound delivery remains exclusively governed by ActionPolicy.

### 2.2 INTROSPECTIVE

Structured internal reflection.

- **Purpose:** Self-review, unresolved thought processing, recent experience reflection, future LCE/compiled-cognition preparation.
- **Properties:**
  - Background and internal.
  - No direct outbound authority.
  - Interruptible by inbound interaction.
  - Any future result is candidate cognition, never canonical truth.

### 2.3 DAYDREAM

Lightweight idle cognition.

- **Purpose:** Loose association, spontaneous recollection, low-cost background thought, opportunistic semantic linking.
- **Properties:**
  - Intended for idle periods.
  - Cheaper and lighter than sleep consolidation.
  - Immediately interruptible.
  - No direct canonical memory mutation.
  - No direct outbound authority.

### 2.4 SLEEP

Deep offline cognitive-rest mode.

- **Purpose:** Suppress ordinary proactive activity; provide future processing windows for:
  - Affect consolidation
  - Slow-state maintenance
  - Memory consolidation
  - LCE consolidation
  - Trajectory cleanup
- **Properties:**
  - Not an affect state.
  - Not merely "no messages".
  - Inbound activity may wake the agent.
  - No direct provider generation required.
  - No direct canonical mutation merely because sleep occurs.

### 2.5 DREAM

A sleep-associated loose-association processing mode.

- **Purpose:** Broader association than ordinary introspection, cross-memory and cross-semantic candidate generation, future LCE/cognition discovery input.
- **Properties:**
  - Logically associated with `SLEEP` (`parent_mode = CognitiveMode.SLEEP`).
  - Dream output is **CANDIDATE** cognition only.
  - Dream output **MUST NOT** automatically become:
    - Evidence
    - Fact
    - Memory truth
    - Persona
    - Identity
    - Accepted Compiled Cognition
  - Any future accepted result must pass the normal authority/admission boundary.

---

## 3. Fatigue Boundary

Fatigue is **NOT** a `CognitiveMode`.

Fatigue is a runtime state / pressure signal which **MAY LATER** influence mode selection.

Conceptually:

```text
agent.affect.fatigue
    ↓
future CognitiveModeController (NOT IMPLEMENTED)
    ↓
ACTIVE / INTROSPECTIVE / DAYDREAM / SLEEP / DREAM
```

### Boundary Guarantees:
- **No thresholds in V0:** No fatigue accumulation rate, daydream threshold, sleep threshold, dream probability, circadian rhythm, sleep duration, or wake threshold are implemented.
- **Canonical Planned Key:** Reference only to `agent.affect.fatigue`. No conflicting second definition is created.

---

## 4. Legacy `introspective_pull` Compatibility

Existing persona configurations (e.g. `configs/personas/kayla.json`) carry:

```text
agent.affect.introspective_pull
```

This affect dimension remains completely untouched for backward compatibility.

**Frozen Boundary:**
```text
agent.affect.introspective_pull != CognitiveMode.INTROSPECTIVE
```
- The former is an existing affect/runtime dimension.
- The latter is a cognitive execution mode.
- Neither is silently mapped to the other.

---

## 5. Non-Negotiable Authority Rules

The following 10 invariants are frozen across code, tests, and documentation:

1. **Cognitive mode does not create external-action authority.**
2. **Any outbound action still requires:** `Intent -> ActionPolicy -> normal Body / Delivery path`.
3. **Background thought is not Evidence.**
4. **Dream output is not canonical memory.**
5. **Daydream output is not canonical memory.**
6. **Introspection output is not canonical identity.**
7. **Sleep does not automatically mutate Slow state.**
8. **LCE remains a future consumer/provider of derived cognition, not the authority for runtime mode switching.**
9. **CognitiveMode is runtime orchestration state, not a personality dimension.**
10. **No raw mode metadata must be exposed to provider unless a future bounded consumer explicitly requires it.**

---

## 6. Future Target Topology (Document Only — Non-Implemented)

```text
Wall Clock / Inbound
        ↓
Fast State / fatigue
        ↓
CognitiveModeController            [NOT IMPLEMENTED]
        ↓
┌────────────────────────────┐
│ ACTIVE                     │
│ INTROSPECTIVE              │
│ DAYDREAM                   │
│ SLEEP                      │
│   └─ DREAM                 │
└────────────────────────────┘
        ↓
mode-specific cognitive work
        ↓
candidate cognition
        ↓
existing admission / authority boundaries
```

### Non-Implemented Status Markers:
- `MODE_CONTROLLER_STATUS = NOT_IMPLEMENTED`
- `TRANSITION_POLICY_STATUS = NOT_IMPLEMENTED`
- `BACKGROUND_LCE_STATUS = NOT_IMPLEMENTED`

---

## 7. Explicit Non-Goals

The V0 concept layer deliberately excludes:
- Full sleep implementation
- Dream generation worker or LLM prompting
- Daydream generation worker
- Introspection LLM calls
- LCE integration or background daemons
- Fatigue calibration, accumulation, or decay math
- Mode transition equations (ACTIVE ↔ DAYDREAM ↔ SLEEP ↔ DREAM)
- Sleep cycle simulation (REM / NREM modeling)
- Persona profile modifications
- Gu Qinghe personality work
- Memory kernel redesign
- New Surface dimensions
