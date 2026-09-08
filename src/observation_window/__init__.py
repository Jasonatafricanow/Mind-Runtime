"""MR Observation Window — Phase 1 (canonical state + provenance) + Phase 3 (production causal chain).

OW-3 extends OW-P1 with read-only inspection of the J8-E3 Gate 8
production causal chain. The data is the live
``AppraisalAffectTransitionResult`` returned by
``EngineEmotionalTransitionPort.transition()`` — no new authoritative
types are introduced and no write methods are called.

OW-3 additionally does **not**:

- persist any J8-E3 trace data (OW-3 has no durable store),
- infer causal links from timing — every link is joined by canonical
  ``source_ref`` tokens,
- import ``TurnOrchestrator`` or any MR runtime orchestrator class,
- modify the orchestrator or any pipeline stage.

The boundary is enforced by construction: the only MR objects OW-3
references are the value-type contracts (``EmotionalTransitionResult``,
``AppraisalAffectTransitionResult``, ``AssessmentTrace``) and the
read-only backend interfaces used by OW-P1.
"""