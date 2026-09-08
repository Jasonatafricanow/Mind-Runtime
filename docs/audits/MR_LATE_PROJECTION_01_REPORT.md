# MR-LATE-PROJECTION-01 — authority preflight report

Date: 2026-09-09. Verdict: BLOCKED pending acceptance of proposed ADR-0027.
This is an audit/design deliverable, not an implementation completion report.

Branch: w/mr-late-projection-01.
Worktree: C:/projects/Mind Runtime/.worktrees/mr-late-projection-01.
Base and current code HEAD: a7c347dcfe2bcc0867d9851275bbe5ea1e2c96f8.
Local main was clean when inspected. No remote freshness claim is made.
The original C:/projects/Mind Runtime checkout is a dirty older branch at
f0f575bc1ee58dcaff15b242ae3f33044af6e955; none of its overlays were imported.

1. **Current choke point.** GLM prompt/parser restrict events to four recipe
   kinds; EffectMapper selects candidate[0].kind, exits unknown before appraisal
   access; accepted_events additionally requires mapped impulses. Transition
   result/compiler lack an accepted-appraisal consumer payload. OW has partial
   appraisal telemetry but no materialized projection status/consumer seam.

2. **ADR/authority decision.** ADR-0027 is PROPOSED, not accepted. User section 5
   explicitly requires ADR authorization for a missing cognition seam. AGENTS.md
   protects Dynamics, appraisal/trace, DecisionContext and commit contracts.
   Proposed approach: one projector replacing mapper authority, durable derived
   appraisal/projection records, COGNITIVE_MEANING view, existing commit owner.

3. **Changed contracts.** None implemented. Proposed contract details are in
   ../adr/0027-late-bound-appraisal-projection.md, including input dependency key,
   statuses, acceptance ownership, scoped cognition, deduplication and atomicity.

4. **RED tests.** Nine required executable acceptance cases are specified in the
   ADR; they have NOT been written/run because the prerequisite ADR is unaccepted.
   A read-only synthetic current-code probe confirmed: meanings recognition,
   relief, increased_confidence_in_user survive in routing; mapper impulses=0,
   reasons=[unknown_event_kind], status field absent, appraisal payload absent,
   accepted_events condition=false. This is reproduction evidence, not RED TDD.

5. **Implementation.** Documentation only. No production source, config, DB,
   LCE, ontology or running provider changed. Sequential W1/W2/W3 scope and tests
   are proposed in ADR-0027; no later delivery gate is authorized by this report.

6. **GREEN tests.** Existing baseline only: 54 passed in 1.18s using
   C:/projects/Mind Runtime/.venv/Scripts/python.exe -m pytest
   tests/emotional_transition/test_effects.py
   tests/emotional_transition/test_appraisal_producer.py
   tests/expression/test_context.py -q
   from this isolated worktree. Initial --no-cov attempt failed at argument
   parsing (plugin unavailable), then was rerun without that option. Full suite,
   new-contract GREEN and static gates have not been run; no code was changed.

7. **Novel semantic live trace.** Not performed. Synthetic probe is not a live
   provider trace. Required final evidence starts with natural language through a
   real provider under isolated LAB binding, after authorized implementation.

8. **Existing-rule regression.** Current mapper baseline passed; exact four-rule
   old/new production equivalence is not yet tested because no new mapper exists.
   Include history caps, gate denial, longitudinal values and final state vector.

9. **Projection coverage sample.** Not available in current schema. Do not
   fabricate MAPPED/UNMAPPED counts from existing abstention reasons. ADR defines
   distinct appraisal/projection denominators, version buckets, replay dedup and
   unmapped meaning/event-kind grouping for implementation.

10. **PASS / BLOCKED.** BLOCKED for implementation at ADR authorization, not PASS.
    Independent document review found compatibility/group-formation ambiguity,
    unspecified acceptance owner and journal/application identity gaps. The draft
    was revised to preserve legacy pre-group gate decisions, define acceptance
    owner and route handling, and prevent cross-interaction/version reapplication.
    Final independent re-review found all three addressed at ADR level, with no
    new blocking finding; suitable for user authorization, not implementation
    approval evidence. No merge/push/deploy.

Approval requested: accept ADR-0027 and its minimal additive cognition contract,
then proceed with sequential RED -> implementation -> GREEN -> independent review
for the full assignment. Review is of a concrete draft, not permission to invent
an implementation contract later. The four affect dimensions remain unchanged.
