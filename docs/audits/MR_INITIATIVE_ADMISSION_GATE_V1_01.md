# MR Initiative Admission Gate V1 — mainline record

The completed initiative-gate branch was forward-ported to the current mainline
rather than merged with its stale history.

The final mainline implementation intentionally keeps only the behavioral
requirement:

- domain score is computed first and remains inspectable;
- `spontaneous_share` and `proactive_inquiry` may require minimum initiative;
- the Surface projection is lineage-validated before the gate is used;
- low initiative suppresses candidate emission, not domain strength;
- ActionPolicy remains the permission authority;
- other intents, including `reach_out`, cannot use the gate;
- production calibration/activation remains config-blocked.

The older branch's dedicated admission-trace hierarchy and large certification
test matrix were not forward-ported because the existing `IntentScoreTrace`
already expresses the required audit boundary.
