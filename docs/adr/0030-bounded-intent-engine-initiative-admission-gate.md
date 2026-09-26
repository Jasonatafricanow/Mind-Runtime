# ADR-0030: Bounded Intent Engine Initiative Admission Gate After Domain Scoring

- Date: 2026-09-25
- Status: **ACCEPTED**
- Authority: MR_INITIATIVE_ADMISSION_GATE_ARCHITECTURE_DECISION_V1.md
- Gate ID: BOUNDED_INTENT_ENGINE_INITIATIVE_ADMISSION_GATE_AFTER_DOMAIN_SCORING
- Overlap Policy: ROOT_OVERLAP_POLICY=CONDITIONAL
- Base implementation authority: 9b46d663ae9d8595357c16b2e71b12ae6ec017d8
- Target branch: w/mr-initiative-admission-gate-v1-01

## Context

Under ADR-0028, `DeterministicIntentEngine` enforces strict root isolation (`validate_intent_rule_surface_overlap`) forbidding any additive overlap between direct dynamics roots $R$ and transitive surface roots $U$ ($R \cap U = \emptyset$), as well as pairwise surface root sharing. This guarantees that direct dynamics dimensions cannot be double-counted as additive score contributions.

However, for proactive motives such as spontaneous sharing (`spontaneous_share`) and proactive inquiry (`proactive_inquiry`), behavioral drive originates from dedicated affective roots (`sharing_urge` and `curiosity`, respectively), while general behavioral activation is modulated by `Surface.initiative` ($0.60 \times \text{sharing\_urge} + 0.50 \times \text{curiosity} - 0.25 \times \text{sadness}$).

Because `Surface.initiative` transitively contains both `sharing_urge` and `curiosity`, treating `initiative` as an additive scoring weight would violate the strict non-overlap invariant and distort domain motivation. Furthermore, the sadness consumer audit (`MR-SADNESS-INITIATIVE-SUPPRESSION-AUDIT-V1-01`, commit `9b46d663`) identified a runtime functional gap: sadness lowers `Surface.initiative`, but without downstream consumption of `initiative`, sadness does not suppress proactive motives.

## Decision

1. **Gate Architecture**:
   Implement an independent `Surface.initiative` admission gate in `DeterministicIntentEngine` evaluated strictly **after** domain scoring:
   $$\text{Dynamics root} \longrightarrow \text{Domain Intent strength} \longrightarrow \text{Surface.initiative admission gate} \longrightarrow \text{Admitted candidate} \longrightarrow \text{ActionPolicy}$$

2. **Conceptual Split**:
   - *"How strongly do I want to do this?"* = Pure domain Intent score (unchanged by initiative, sadness, or gate thresholds).
   - *"Is current behavioral initiative sufficient for this new spontaneous motive to become a candidate?"* = Independent `Surface.initiative` admission gate.
   - *"Is the admitted action permitted now?"* = Downstream `ActionPolicy`.

3. **ROOT_OVERLAP_POLICY=CONDITIONAL**:
   - Additive direct-root / Surface-root overlap remains strictly forbidden (`validate_intent_rule_surface_overlap` is untouched and unchanged).
   - Initiative admission gating is **NOT** additive scoring. It does not alter domain score, unclamped score, or ranking weight.
   - Overlap is legal **only** under the exact V1 gate shape for admitted kinds:
     - `spontaneous_share`: direct root must be strictly `agent.affect.sharing_urge` ($> 0$), `surface_control_weights == ()`, `event_kind is None`, `event_bonus == 0`, `due_at_attribute is None`.
     - `proactive_inquiry`: direct root must be strictly `agent.affect.curiosity` ($> 0$), `surface_control_weights == ()`, `event_kind is None`, `event_bonus == 0`, `due_at_attribute is None`.
   - Any other Intent kind (including `reach_out`, `scheduled_follow_up`, `respond`) configuring `minimum_initiative` is strictly rejected. No blanket overlap bypass exists.

4. **Preservation of Domain Strength**:
   - Domain scoring evaluates base strength, direct dimensions, and schedule validity.
   - Only if domain score satisfies `final_strength >= minimum_strength` and the rule is schedule-valid does the initiative gate evaluate.
   - If `initiative < minimum_initiative`, candidate emission is suppressed (`candidate = None`, `admitted = False`), while `trace.final_strength` and `trace.unclamped_score` retain their exact, unmultiplied domain values with reason code `("initiative_below_minimum",)`.
   - If `initiative >= minimum_initiative`, candidate is admitted (`admitted = True`) with reason code `("threshold_met",)`, and `candidate.strength` equals the unchanged domain strength.

5. **Cross-Control Motive Admission**:
   - Transitive components in `initiative` (e.g. curiosity raising initiative for share, or sharing_urge raising initiative for inquiry) may permit admission without altering the respective domain score. This cross-motive activation is an intended V1 behavioral property.

6. **Typed Provenance and Lineage**:
   - A new typed contract `InitiativeAdmissionTrace` records:
     - `control = "initiative"`
     - `comparator = "gte"`
     - `minimum: float`
     - `observed: float | None`
     - `outcome: {"passed", "below_minimum", "surface_unavailable", "surface_stale_or_mismatch", "surface_invalid"}`
     - `admission_validation_ref: str` (deterministic hash of rule, dedicated root, control, threshold, candidate recipe, and manifest).
   - Added to `IntentScoreTrace` as `surface_admission: InitiativeAdmissionTrace | None = None`.
   - Surface lineage validation fails closed: missing, stale, mismatched, or malformed surface rejects candidate emission while preserving domain score on trace.
   - Passing candidates attach the trace as `Intent.surface_use` with `surface_controls_ref`, `surface_dependency_digest`, and `surface_recipe_ref` preserved.

7. **Backward Compatibility**:
   - Legacy rulesets omitting `minimum_initiative` omit the key during `rules_wire` serialization, ensuring byte-identical `ruleset_ref`.
   - Legacy persisted rows in SQLite omit `"surface_admission"` when None, ensuring byte-identical serialized JSON.

8. **Boundaries and Isolation**:
   - ActionPolicy semantics are unchanged. Rejected candidates never reach ActionPolicy.
   - Ticker semantics are unchanged; Ticker delegates candidate generation to IntentEngine without a separate gate.
   - Surface recipe and expression map are unchanged.
   - Provider prose generation remains isolated: neither initiative, sadness, threshold, nor admission outcomes are visible to the LLM.
   - Production calibration remains `PROVISIONAL` and production activation remains `BLOCKED_BY_CONFIG`.
