"""Pure configuration-owned Intent scoring with inspectable contributions."""

from collections.abc import Mapping
from dataclasses import asdict, dataclass
import hashlib
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from math import isfinite

from mind_runtime.contracts import (
    Intent,
    IntentEngineInput,
    IntentEngineResult,
    IntentScoreContribution,
    IntentScoreTrace,
    IntentStatus,
    ReconsiderationPolicy,
    SemanticEventCandidate,
    SyncFields,
)
from mind_runtime.contracts.common import require_aware_utc, require_non_empty


def _require_number(value: object, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value):
        raise ValueError(f"{field_name} must be a finite numeric value")
    return float(value)


def _decimal(value: float) -> Decimal:
    return Decimal(str(value))


@dataclass(frozen=True, slots=True)
class IntentRule:
    """One product/persona-owned deterministic mapping into an Intent kind."""

    rule_id: str
    kind: str
    base_strength: float
    dimension_weights: tuple[tuple[str, float], ...]
    event_kind: str | None
    event_bonus: float
    minimum_strength: float
    due_at_attribute: str | None
    expires_after: timedelta | None
    reconsideration_policy: ReconsiderationPolicy
    surface_control_weights: tuple[tuple[str, float], ...] = ()
    minimum_initiative: float | None = None

    def __post_init__(self) -> None:
        require_non_empty(self.rule_id, "rule_id")
        require_non_empty(self.kind, "kind")
        _require_number(self.base_strength, "base_strength")
        _require_number(self.event_bonus, "event_bonus")
        minimum = _require_number(self.minimum_strength, "minimum_strength")
        if not 0 <= minimum <= 1:
            raise ValueError("minimum_strength must be in [0, 1]")
        seen_dimensions: set[str] = set()
        for dimension, weight in self.dimension_weights:
            require_non_empty(dimension, "dimension_weights dimensions")
            _require_number(weight, "dimension weight")
            if dimension in seen_dimensions:
                raise ValueError("dimension_weights dimensions must be unique")
            seen_dimensions.add(dimension)
        if self.event_kind is not None:
            require_non_empty(self.event_kind, "event_kind")
        elif self.event_bonus != 0:
            raise ValueError("event_bonus requires event_kind")
        if self.due_at_attribute is not None:
            require_non_empty(self.due_at_attribute, "due_at_attribute")
            if self.event_kind is None:
                raise ValueError("due_at_attribute requires event_kind")
        if self.expires_after is not None and self.expires_after <= timedelta(0):
            raise ValueError("expires_after must be positive")
        if not isinstance(self.reconsideration_policy, ReconsiderationPolicy):
            raise ValueError("reconsideration_policy must be a ReconsiderationPolicy")
        seen_controls: set[str] = set()
        for control, weight in self.surface_control_weights:
            require_non_empty(control, "surface_control_weights controls")
            _require_number(weight, "surface control weight")
            if control in seen_controls:
                raise ValueError("surface_control_weights controls must be unique")
            seen_controls.add(control)
        if self.minimum_initiative is not None:
            from mind_runtime.intents.surface_validator import (
                validate_initiative_gate_rule,
            )

            validate_initiative_gate_rule(self)
        if self.surface_control_weights:
            from mind_runtime.intents.surface_validator import (
                validate_intent_rule_surface_overlap,
            )

            validate_intent_rule_surface_overlap(self)


class DeterministicIntentEngine:
    """Apply fixed numeric rules without LLM or permission authority."""

    def __init__(self, rules: tuple[IntentRule, ...], runtime_id: str) -> None:
        require_non_empty(runtime_id, "runtime_id")
        rule_ids: set[str] = set()
        kinds: set[str] = set()
        for rule in rules:
            if rule.rule_id in rule_ids:
                raise ValueError("Intent rule_id values must be unique")
            if rule.kind in kinds:
                raise ValueError("Intent rule kind values must be unique")
            rule_ids.add(rule.rule_id)
            kinds.add(rule.kind)
        self._rules = rules
        self._runtime_id = runtime_id

        def _rule_wire(rule: IntentRule) -> dict[str, object]:
            data = asdict(rule)
            if rule.minimum_initiative is None:
                data.pop("minimum_initiative", None)
            return data

        rules_wire = json.dumps(
            [_rule_wire(rule) for rule in rules], sort_keys=True, default=str,
            separators=(",", ":"), ensure_ascii=True,
        ).encode("utf-8")
        self._ruleset_ref = "ruleset:" + hashlib.sha256(rules_wire).hexdigest()

    def evaluate(self, engine_input: IntentEngineInput) -> IntentEngineResult:
        if engine_input.origin_runtime_id != self._runtime_id:
            raise ValueError("intent engine input origin must match runtime_id")
        projected_values = {
            state.dimension: state.value for state in engine_input.projected.projected_states
        }
        candidates: list[Intent] = []
        traces: list[IntentScoreTrace] = []
        for rule in self._rules:
            candidate, trace = self._evaluate_rule(rule, engine_input, projected_values)
            traces.append(trace)
            if candidate is not None:
                candidates.append(candidate)
        candidates.sort(key=lambda item: (-item.strength, item.kind, item.intent_id))
        return IntentEngineResult(candidates=tuple(candidates), traces=tuple(traces))

    def _evaluate_rule(
        self,
        rule: IntentRule,
        engine_input: IntentEngineInput,
        projected_values: dict[str, object],
    ) -> tuple[Intent | None, IntentScoreTrace]:
        intent_id = f"intent-{engine_input.interaction_id}-{rule.rule_id}"
        trace_id = f"intent-score-{engine_input.interaction_id}-{rule.rule_id}"

        surface_controls_ref: str | None = None
        surface_dependency_digest: str | None = None
        overlap_validation_ref: str | None = None
        surface_recipe_ref: str | None = None

        is_surface_aware = len(rule.surface_control_weights) > 0
        if is_surface_aware:
            surface = engine_input.surface
            if surface is None or surface.status != "AVAILABLE" or surface.controls is None:
                trace = IntentScoreTrace(
                    trace_id=trace_id,
                    scope=engine_input.scope,
                    rule_id=rule.rule_id,
                    intent_id=intent_id,
                    contributions=(
                        IntentScoreContribution("base", rule.rule_id, float(rule.base_strength)),
                    ),
                    unclamped_score=float(rule.base_strength),
                    final_strength=0.0,
                    admitted=False,
                    reason_codes=("surface_unavailable",),
                    created_at=engine_input.clock,
                )
                return None, trace

            from mind_runtime.surface.lineage import validate_projected_surface

            reference = (
                f"tick:{engine_input.interaction_id}"
                if engine_input.interaction_id.startswith("cognitive-tick-")
                else f"interaction:{engine_input.interaction_id}"
            )
            if not validate_projected_surface(
                surface,
                projected=engine_input.projected,
                runtime_id=self._runtime_id,
                interaction_or_tick_ref=reference,
                persona_id=engine_input.projected.scope.persona_id,
                persona_version=engine_input.persona_version,
                persona_content_digest=engine_input.persona_content_digest,
            ):
                trace = IntentScoreTrace(
                    trace_id=trace_id, scope=engine_input.scope, rule_id=rule.rule_id,
                    intent_id=intent_id,
                    contributions=(IntentScoreContribution("base", rule.rule_id, float(rule.base_strength)),),
                    unclamped_score=float(rule.base_strength), final_strength=0.0,
                    admitted=False, reason_codes=("surface_stale_or_mismatch",),
                    created_at=engine_input.clock,
                )
                return None, trace

            controls = surface.controls
            if controls.get("runtime_id") != self._runtime_id:
                trace = IntentScoreTrace(
                    trace_id=trace_id,
                    scope=engine_input.scope,
                    rule_id=rule.rule_id,
                    intent_id=intent_id,
                    contributions=(
                        IntentScoreContribution("base", rule.rule_id, float(rule.base_strength)),
                    ),
                    unclamped_score=float(rule.base_strength),
                    final_strength=0.0,
                    admitted=False,
                    reason_codes=("surface_stale_or_mismatch",),
                    created_at=engine_input.clock,
                )
                return None, trace

            if controls.get("source_projection_id") != engine_input.projected.projection_id:
                trace = IntentScoreTrace(
                    trace_id=trace_id,
                    scope=engine_input.scope,
                    rule_id=rule.rule_id,
                    intent_id=intent_id,
                    contributions=(
                        IntentScoreContribution("base", rule.rule_id, float(rule.base_strength)),
                    ),
                    unclamped_score=float(rule.base_strength),
                    final_strength=0.0,
                    admitted=False,
                    reason_codes=("surface_stale_or_mismatch",),
                    created_at=engine_input.clock,
                )
                return None, trace

            if controls.get("source_phase") != "projected":
                trace = IntentScoreTrace(
                    trace_id=trace_id,
                    scope=engine_input.scope,
                    rule_id=rule.rule_id,
                    intent_id=intent_id,
                    contributions=(
                        IntentScoreContribution("base", rule.rule_id, float(rule.base_strength)),
                    ),
                    unclamped_score=float(rule.base_strength),
                    final_strength=0.0,
                    admitted=False,
                    reason_codes=("surface_stale_or_mismatch",),
                    created_at=engine_input.clock,
                )
                return None, trace

            projected_states_by_dim = {
                s.dimension: s for s in engine_input.projected.projected_states
            }
            state_mismatch = False
            for s_info in controls.get("source_states", []):
                d = s_info.get("dimension")
                p_s = projected_states_by_dim.get(d)
                if p_s is None or p_s.version != s_info.get("version"):
                    state_mismatch = True
                    break
            if state_mismatch:
                trace = IntentScoreTrace(
                    trace_id=trace_id,
                    scope=engine_input.scope,
                    rule_id=rule.rule_id,
                    intent_id=intent_id,
                    contributions=(
                        IntentScoreContribution("base", rule.rule_id, float(rule.base_strength)),
                    ),
                    unclamped_score=float(rule.base_strength),
                    final_strength=0.0,
                    admitted=False,
                    reason_codes=("surface_stale_or_mismatch",),
                    created_at=engine_input.clock,
                )
                return None, trace

            surface_controls_ref = str(controls.get("controls_id", ""))
            surface_dependency_digest = str(controls.get("dependency_digest", ""))
            from mind_runtime.intents.surface_validator import overlap_validation_reference

            overlap_validation_ref = overlap_validation_reference(rule)

        contributions = [IntentScoreContribution("base", rule.rule_id, float(rule.base_strength))]
        score = _decimal(float(rule.base_strength))
        for dimension, weight in rule.dimension_weights:
            raw_value = projected_values.get(dimension)
            if isinstance(raw_value, bool) or not isinstance(raw_value, (int, float)):
                amount = 0.0
            elif not isfinite(raw_value):
                amount = 0.0
            else:
                amount = float(_decimal(float(raw_value)) * _decimal(float(weight)))
            contributions.append(IntentScoreContribution("dimension", dimension, amount))
            score += _decimal(amount)

        if is_surface_aware:
            controls_values = controls.get("values", {})
            for control_name, weight in rule.surface_control_weights:
                c_val = controls_values.get(control_name)
                if (
                    c_val is None
                    or isinstance(c_val, bool)
                    or not isinstance(c_val, (int, float))
                    or not isfinite(c_val)
                ):
                    trace = IntentScoreTrace(
                        trace_id=trace_id,
                        scope=engine_input.scope,
                        rule_id=rule.rule_id,
                        intent_id=intent_id,
                        contributions=tuple(contributions),
                        unclamped_score=float(score),
                        final_strength=0.0,
                        admitted=False,
                        reason_codes=("surface_invalid",),
                        created_at=engine_input.clock,
                        surface_controls_ref=surface_controls_ref,
                        surface_dependency_digest=surface_dependency_digest,
                        overlap_validation_ref=overlap_validation_ref,
                    )
                    return None, trace
                amount = float(_decimal(float(c_val)) * _decimal(float(weight)))
                contributions.append(IntentScoreContribution("surface", control_name, amount))
                score += _decimal(amount)

        matched_event = self._first_event(rule, engine_input.accepted_events)
        if matched_event is not None and rule.event_bonus != 0:
            contributions.append(
                IntentScoreContribution(
                    "event", matched_event.candidate_id, float(rule.event_bonus)
                )
            )
            score += _decimal(float(rule.event_bonus))

        unclamped = float(score)
        final_strength = min(1.0, max(0.0, unclamped))
        earliest_at = engine_input.clock
        due_at: datetime | None = None
        schedule_valid = True
        if rule.due_at_attribute is not None:
            due_at = self._due_at(matched_event, rule.due_at_attribute)
            if due_at is None:
                schedule_valid = False
            else:
                earliest_at = due_at
        expiry_base = due_at if due_at is not None else engine_input.clock
        expires_at = expiry_base + rule.expires_after if rule.expires_after is not None else None
        if expires_at is not None and expires_at <= engine_input.clock:
            schedule_valid = False

        admitted = schedule_valid and final_strength >= rule.minimum_strength
        if not schedule_valid:
            reason_codes = ("invalid_due_at",)
        elif not admitted:
            reason_codes = ("below_minimum_strength",)
        else:
            reason_codes = ("threshold_met",)

        # Domain failure: gate is not evaluated, domain reason codes preserved
        if not admitted:
            trace = IntentScoreTrace(
                trace_id=trace_id,
                scope=engine_input.scope,
                rule_id=rule.rule_id,
                intent_id=intent_id,
                contributions=tuple(contributions),
                unclamped_score=unclamped,
                final_strength=final_strength,
                admitted=False,
                reason_codes=reason_codes,
                created_at=engine_input.clock,
                surface_controls_ref=surface_controls_ref,
                surface_dependency_digest=surface_dependency_digest,
                overlap_validation_ref=overlap_validation_ref,
                surface_weights=rule.surface_control_weights if is_surface_aware else (),
                surface_recipe_ref=(
                    f"{controls.get('recipe_id')}:{controls.get('recipe_version')}:{controls.get('recipe_digest')}"
                    if is_surface_aware else None
                ),
                ruleset_ref=self._ruleset_ref,
            )
            return None, trace

        # Domain admitted: evaluate independent initiative admission gate if configured
        is_initiative_gated = rule.minimum_initiative is not None
        surface_admission: InitiativeAdmissionTrace | None = None

        if is_initiative_gated:
            from mind_runtime.contracts.intent import InitiativeAdmissionTrace
            from mind_runtime.dynamics.persona import surface_digest
            from mind_runtime.intents.surface_validator import admission_validation_reference
            from mind_runtime.surface.lineage import validate_projected_surface
            from mind_runtime.surface.recipe import (
                CANDIDATE_RECIPE_DIGEST,
                CANDIDATE_RECIPE_ID,
                CANDIDATE_RECIPE_VERSION,
                MANIFEST,
            )

            adm_ref = admission_validation_reference(rule)
            surface = engine_input.surface

            # 1. Unavailable Surface
            if (
                surface is None
                or getattr(surface, "status", None) != "AVAILABLE"
                or getattr(surface, "controls", None) is None
            ):
                surface_admission = InitiativeAdmissionTrace(
                    minimum=rule.minimum_initiative,
                    observed=None,
                    outcome="surface_unavailable",
                    admission_validation_ref=adm_ref,
                )
                trace = IntentScoreTrace(
                    trace_id=trace_id,
                    scope=engine_input.scope,
                    rule_id=rule.rule_id,
                    intent_id=intent_id,
                    contributions=tuple(contributions),
                    unclamped_score=unclamped,
                    final_strength=final_strength,
                    admitted=False,
                    reason_codes=("surface_unavailable",),
                    created_at=engine_input.clock,
                    surface_admission=surface_admission,
                    ruleset_ref=self._ruleset_ref,
                )
                return None, trace

            controls = surface.controls
            # 2. Malformed / Invalid Surface
            is_invalid = False
            if not isinstance(controls, Mapping):
                is_invalid = True
            elif (
                controls.get("recipe_id") != CANDIDATE_RECIPE_ID
                or controls.get("recipe_version") != CANDIDATE_RECIPE_VERSION
                or controls.get("recipe_digest") != CANDIDATE_RECIPE_DIGEST
                or controls.get("dependencies_by_control") != MANIFEST
                or controls.get("dependencies_by_control", {}).get("initiative")
                != MANIFEST.get("initiative")
                or controls.get("derived_only") is not True
                or controls.get("canonical") is not False
            ):
                is_invalid = True
            elif not isinstance(controls.get("values"), Mapping):
                is_invalid = True
            elif "initiative" not in controls.get("values", {}):
                is_invalid = True
            else:
                vals = controls.get("values", {})
                init_val = vals.get("initiative")
                if (
                    isinstance(init_val, bool)
                    or not isinstance(init_val, (int, float))
                    or not isfinite(init_val)
                    or not 0.0 <= init_val <= 1.0
                ):
                    is_invalid = True
                elif set(vals) != set(MANIFEST) or any(
                    isinstance(v, bool)
                    or not isinstance(v, (int, float))
                    or not isfinite(v)
                    or not 0.0 <= v <= 1.0
                    for v in vals.values()
                ):
                    is_invalid = True
                else:
                    try:
                        semantic = {
                            k: v
                            for k, v in controls.items()
                            if k not in ("controls_id", "evaluation_ref")
                        }
                        if controls.get("controls_id") != "surface:" + surface_digest(
                            "controls", semantic
                        ):
                            is_invalid = True
                    except Exception:
                        is_invalid = True

            if is_invalid:
                surface_admission = InitiativeAdmissionTrace(
                    minimum=rule.minimum_initiative,
                    observed=None,
                    outcome="surface_invalid",
                    admission_validation_ref=adm_ref,
                )
                trace = IntentScoreTrace(
                    trace_id=trace_id,
                    scope=engine_input.scope,
                    rule_id=rule.rule_id,
                    intent_id=intent_id,
                    contributions=tuple(contributions),
                    unclamped_score=unclamped,
                    final_strength=final_strength,
                    admitted=False,
                    reason_codes=("surface_invalid",),
                    created_at=engine_input.clock,
                    surface_admission=surface_admission,
                    ruleset_ref=self._ruleset_ref,
                )
                return None, trace

            # 3. Stale or Mismatched Surface Lineage
            reference = (
                f"tick:{engine_input.interaction_id}"
                if engine_input.interaction_id.startswith("cognitive-tick-")
                else f"interaction:{engine_input.interaction_id}"
            )
            if not validate_projected_surface(
                surface,
                projected=engine_input.projected,
                runtime_id=self._runtime_id,
                interaction_or_tick_ref=reference,
                persona_id=engine_input.projected.scope.persona_id,
                persona_version=engine_input.persona_version,
                persona_content_digest=engine_input.persona_content_digest,
            ):
                surface_admission = InitiativeAdmissionTrace(
                    minimum=rule.minimum_initiative,
                    observed=None,
                    outcome="surface_stale_or_mismatch",
                    admission_validation_ref=adm_ref,
                )
                trace = IntentScoreTrace(
                    trace_id=trace_id,
                    scope=engine_input.scope,
                    rule_id=rule.rule_id,
                    intent_id=intent_id,
                    contributions=tuple(contributions),
                    unclamped_score=unclamped,
                    final_strength=final_strength,
                    admitted=False,
                    reason_codes=("surface_stale_or_mismatch",),
                    created_at=engine_input.clock,
                    surface_admission=surface_admission,
                    ruleset_ref=self._ruleset_ref,
                )
                return None, trace

            # 4. Valid Surface: inspect Surface.initiative
            observed_init = float(controls["values"]["initiative"])
            surface_controls_ref = str(controls.get("controls_id", ""))
            surface_dependency_digest = str(controls.get("dependency_digest", ""))
            surface_recipe_ref = f"{controls.get('recipe_id')}:{controls.get('recipe_version')}:{controls.get('recipe_digest')}"

            if observed_init < rule.minimum_initiative:
                surface_admission = InitiativeAdmissionTrace(
                    minimum=rule.minimum_initiative,
                    observed=observed_init,
                    outcome="below_minimum",
                    admission_validation_ref=adm_ref,
                )
                trace = IntentScoreTrace(
                    trace_id=trace_id,
                    scope=engine_input.scope,
                    rule_id=rule.rule_id,
                    intent_id=intent_id,
                    contributions=tuple(contributions),
                    unclamped_score=unclamped,
                    final_strength=final_strength,
                    admitted=False,
                    reason_codes=("initiative_below_minimum",),
                    created_at=engine_input.clock,
                    surface_controls_ref=surface_controls_ref,
                    surface_dependency_digest=surface_dependency_digest,
                    surface_recipe_ref=surface_recipe_ref,
                    surface_admission=surface_admission,
                    ruleset_ref=self._ruleset_ref,
                )
                return None, trace

            # Gate passed
            surface_admission = InitiativeAdmissionTrace(
                minimum=rule.minimum_initiative,
                observed=observed_init,
                outcome="passed",
                admission_validation_ref=adm_ref,
            )

        trace = IntentScoreTrace(
            trace_id=trace_id,
            scope=engine_input.scope,
            rule_id=rule.rule_id,
            intent_id=intent_id,
            contributions=tuple(contributions),
            unclamped_score=unclamped,
            final_strength=final_strength,
            admitted=admitted,
            reason_codes=reason_codes,
            created_at=engine_input.clock,
            surface_controls_ref=surface_controls_ref,
            surface_dependency_digest=surface_dependency_digest,
            overlap_validation_ref=overlap_validation_ref,
            surface_weights=rule.surface_control_weights if is_surface_aware else (),
            surface_recipe_ref=(
                surface_recipe_ref
                if is_initiative_gated
                else (
                    f"{controls.get('recipe_id')}:{controls.get('recipe_version')}:{controls.get('recipe_digest')}"
                    if is_surface_aware else None
                )
            ),
            ruleset_ref=self._ruleset_ref,
            surface_admission=surface_admission,
        )

        cause_refs = [engine_input.context.situation_id]
        if matched_event is not None:
            cause_refs.append(matched_event.candidate_id)
        if surface_controls_ref is not None:
            cause_refs.append(surface_controls_ref)
        candidate = Intent(
            intent_id=intent_id,
            scope=engine_input.scope,
            origin_runtime_id=self._runtime_id,
            kind=rule.kind,
            strength=final_strength,
            earliest_at=earliest_at,
            due_at=due_at,
            expires_at=expires_at,
            reconsideration_policy=rule.reconsideration_policy,
            cause_refs=tuple(cause_refs),
            state_refs=(engine_input.projected.projection_id,),
            status=IntentStatus.CANDIDATE,
            sync=SyncFields(
                scope=engine_input.scope,
                origin_runtime_id=self._runtime_id,
                object_id=intent_id,
                version=1,
                idempotency_key=f"idem-{intent_id}-v1",
            ),
            surface_use=trace if (is_surface_aware or is_initiative_gated) else None,
        )
        return candidate, trace

    @staticmethod
    def _first_event(
        rule: IntentRule, accepted_events: tuple[SemanticEventCandidate, ...]
    ) -> SemanticEventCandidate | None:
        if rule.event_kind is None:
            return None
        return next((event for event in accepted_events if event.kind == rule.event_kind), None)

    @staticmethod
    def _due_at(event: SemanticEventCandidate | None, attribute: str) -> datetime | None:
        if event is None:
            return None
        values = tuple(value for key, value in event.attributes if key == attribute)
        if len(values) != 1:
            return None
        try:
            parsed = datetime.fromisoformat(values[0])
            require_aware_utc(parsed, attribute)
        except (TypeError, ValueError):
            return None
        return parsed.astimezone(UTC)
