# MR Fast Function V1 Architecture Contract

## Principle

> "A fast state exists only when it provides a distinct runtime function."

Fast states exist solely to drive concrete behavioral and cognitive functions within the runtime pipeline. They are not an open taxonomy of human emotions, nor an ontological representation of personality.

## V1 Functional Fast State Lock

| State | Semantic Label | Primary Function | Intended consumer | Outbound-capable? | Registry status |
|---|---|---|---|:---:|---|
| `agent.affect.longing` | longing | `PROACTIVE_CONTACT` | Intent / proactive message path | Yes | ACTIVE |
| `agent.affect.sharing_urge` | sharing urge | `PROACTIVE_SHARE` | Intent / share path | Yes | ACTIVE |
| `agent.affect.curiosity` | curiosity | `INQUIRY_EXPLORATION` | Intent / retrieval-or-question path | Yes | ACTIVE |
| `agent.affect.anger` | anger / boundary pressure | `BOUNDARY_CONFRONTATION` | existing Surface / Intent / expression path | Yes | ACTIVE |
| `agent.affect.sadness` | sadness / low mood | `INITIATIVE_SUPPRESSION` | existing initiative / expression path | No | ACTIVE |
| `agent.affect.restlessness` | activation / excitation | `ACTIVITY_WAKE` | CognitiveTicker / wake-reconsider path | No | ACTIVE |
| `agent.affect.diligence_pressure` | responsibility pressure | `FOLLOW_UP_PERSISTENCE` | unresolved-task/follow-up Intent reconsideration + ActionPolicy anti-repeat controls | Yes | ACTIVE |
| `agent.affect.fatigue` | fatigue / cognitive load | `COGNITIVE_REST_PRESSURE` | future homeostasis / cognitive-mode scheduler | No | REGISTERED_ONLY |

`ACTIVE` here means that the functional state contract is registered for V1.
It does not certify that the named consumer is closed or that a production
runtime configuration enables it. Consumer closure and activation are tracked
separately in the behavior gates. `Outbound-capable` identifies a possible
function, while ActionPolicy remains the only action permission authority.
`REGISTERED_ONLY` fatigue has no live dynamics parameters or outbound consumer.

## Key Invariants

1. **Restlessness Semantic Compatibility**: The persisted state key `agent.affect.restlessness` remains canonical for compatibility. Its V1 product interpretation is broadened to activation/excitation (tendency to wake, seek activity, or break prolonged inactivity).
2. **Diligence Anti-Spam (`FOLLOW_UP_PERSISTENCE != FOLLOW_UP_FREQUENCY`)**: `diligence_pressure` means an unresolved obligation remains behaviorally relevant for reconsideration. It does **not** mean sending reminders more frequently. Outbound reminder frequency remains strictly governed by cooldown, user response, duplicate protection, and ActionPolicy.
3. **Fatigue Ownership & Registered-Only Status**: `agent.affect.fatigue` is the only genuinely new V1 state concept. Its function contract is frozen, targeting cognitive-mode scheduling (daydream, sleep, offline consolidation, dream). Because adding it to canonical dynamics would require uncalibrated parameters (awake accumulation rate, sleep threshold, circadian model), its status is `REGISTERED_ONLY` until calibrated. Fatigue has no outbound-action consumer and does not send outbound messages.
4. **Existing States Outside V1 Lock**: Compatible runtime states (`agent.affect.closeness_craving`, `agent.affect.social_pull`, `agent.affect.introspective_pull`, `agent.affect.anxiety`) are preserved in persona configurations but are not members of `FAST_FUNCTION_V1`. In particular, `introspective_pull` is not the authority for fatigue / sleep / dream processing.

## Open Semantic Appraisal Boundary

Open semantic Appraisal may contain unlimited meanings. FAST_FUNCTION_V1 does not attempt to enumerate human emotion. Unsupported meanings remain unmapped rather than creating new state dimensions.
