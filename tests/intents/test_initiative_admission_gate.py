"""RED contract and behavioral tests for MR-INITIATIVE-ADMISSION-GATE-V1-01.

Validates the bounded Surface.initiative admission gate in DeterministicIntentEngine:
Dynamics root -> Domain Intent strength -> Independent Surface.initiative admission gate -> Admitted candidate -> ActionPolicy

Invariants verified:
- minimum_initiative None preserves legacy behavior and exact ruleset_ref
- Gate restricted to spontaneous_share and proactive_inquiry with dedicated single direct root
- Domain score preserved identically across gate pass, below-threshold, and lineage failures
- No initiative amount in score contributions
- Failure suppresses candidate emission, lifecycle admission, policy execution, and WakeSignals
- Persistence round-trip retains typed InitiativeAdmissionTrace while legacy bytes remain byte-identical
"""

from __future__ import annotations

from collections.abc import Mapping
import copy
import hashlib
import json
import math
import sqlite3
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from mind_runtime.contracts import (
    ActionDecision,
    ActionPermission,
    ActionPolicyInput,
    ActionPolicyResult,
    Intent,
    IntentEngineInput,
    IntentScoreContribution,
    IntentScoreTrace,
    IntentStatus,
    PolicyResources,
    ProjectedMindState,
    ReconsiderationPolicy,
    RuntimeState,
    Scope,
    ScopeDomain,
    Situation,
    SurfaceProjectionResult,
    SyncFields,
    WakeSignal,
)
from mind_runtime.contracts.intent import InitiativeAdmissionTrace
from mind_runtime.dynamics.fast_functions import (
    SHARING_URGE_CONTROLS_SHARE_PRESSURE_NOT_FREQUENCY_INVARIANT,
)
from mind_runtime.dynamics.persona import PersonaProfile, surface_digest
from mind_runtime.intents.engine import DeterministicIntentEngine, IntentRule
from mind_runtime.intents.persistence import (
    SqliteIntentBackend,
    _surface_use_from_json,
    _surface_use_to_json,
)
from mind_runtime.intents.policy import ActionPolicyConfig, DeterministicActionPolicy, IntentPolicyRule
from mind_runtime.intents.surface_validator import (
    admission_validation_reference,
    validate_initiative_gate_rule,
    validate_intent_rule_surface_overlap,
)
from mind_runtime.surface import SurfaceProductionAdapter
from mind_runtime.surface.recipe import (
    CANDIDATE_RECIPE_DIGEST,
    CANDIDATE_RECIPE_ID,
    CANDIDATE_RECIPE_VERSION,
    MANIFEST,
)
from mind_runtime.validation.contracts import _intent_rule
from tests.surface.spec_support import sample_candidate, state, trait

FIXTURE_RUNTIME_ID = "fixture-runtime"
FIXTURE_INTERACTION_ID = "fixture-1"
FIXTURE_AGENT_ID = "fixture-persona"
FIXTURE_PERSONA_ID = "persona-fixture-a"


def _make_scope(agent_id: str = FIXTURE_AGENT_ID, persona_id: str = FIXTURE_PERSONA_ID) -> Scope:
    return Scope(
        domain=ScopeDomain.AGENT,
        agent_id=agent_id,
        persona_id=persona_id,
    )


def _make_situation(clock: datetime, scope: Scope) -> Situation:
    return Situation(
        situation_id="sit-test-01",
        scope=scope,
        origin_runtime_id=FIXTURE_RUNTIME_ID,
        derived_facts=(("interaction.state", "idle"),),
        effective_state_ref="effective-01",
        observed_at=clock,
        historical_context=None,
        persona_id=scope.persona_id,
        relationship_ids=(),
        evidence_refs=("evidence-01",),
    )


def _build_projected_and_surface(
    *,
    sharing_urge: float = 0.5,
    curiosity: float = 0.5,
    sadness: float = 0.1,
    longing: float = 0.5,
    runtime_id: str = FIXTURE_RUNTIME_ID,
    interaction_id: str = FIXTURE_INTERACTION_ID,
    persona_id: str = FIXTURE_PERSONA_ID,
    agent_id: str = FIXTURE_AGENT_ID,
) -> tuple[ProjectedMindState, SurfaceProjectionResult]:
    c = sample_candidate(persona_id)
    c["runtime_id"] = runtime_id
    c["owner"]["owner_runtime_id"] = runtime_id
    c["owner"]["owner_persona_id"] = persona_id
    c["interaction_or_tick_ref"] = f"interaction:{interaction_id}"
    c["expected_source_projection_id"] = f"projection:{interaction_id}"
    c["projected_dynamics"]["runtime_id"] = runtime_id
    c["projected_dynamics"]["owner"]["owner_runtime_id"] = runtime_id
    c["projected_dynamics"]["owner"]["owner_persona_id"] = persona_id
    c["projected_dynamics"]["interaction_or_tick_ref"] = f"interaction:{interaction_id}"
    c["projected_dynamics"]["source_projection_id"] = f"projection:{interaction_id}"

    scope = Scope(domain=ScopeDomain.AGENT, agent_id=agent_id, persona_id=persona_id)
    scope_wire = {
        "domain": "agent",
        "agent_id": agent_id,
        "persona_id": persona_id,
        "user_id": None,
        "relationship_id": None,
        "world_id": None,
        "interaction_id": None,
    }
    c["scope"] = scope_wire
    c["projected_dynamics"]["scope"] = scope_wire

    state(c, "sharing_urge")["value"] = sharing_urge
    state(c, "curiosity")["value"] = curiosity
    state(c, "sadness")["value"] = sadness
    state(c, "longing")["value"] = longing

    for s_item in c["projected_dynamics"]["states"]:
        s_item["runtime_id"] = runtime_id
        s_item["owner"]["owner_runtime_id"] = runtime_id
        s_item["owner"]["owner_persona_id"] = persona_id
        s_item["scope"] = scope_wire

    adapter = SurfaceProductionAdapter()
    surface = adapter.project(c)

    now = datetime(2026, 9, 25, 12, 0, tzinfo=UTC)
    projected_states = tuple(
        RuntimeState(
            state_id=s_item["state_id"],
            scope=scope,
            dimension=s_item["dimension"],
            value=s_item["value"],
            status="active",
            valid_from=now,
            valid_until=None,
            relevant_until=None,
            last_observed_at=now,
            evidence_refs=(),
            transition_refs=(),
            updated_at=now,
            origin_runtime_id=runtime_id,
            version=s_item["version"],
            sync=SyncFields(
                scope, runtime_id, s_item["state_id"], s_item["version"], f"idem-{s_item['state_id']}"
            ),
        )
        for s_item in c["projected_dynamics"]["states"]
    )
    proj_id = c["projected_dynamics"]["source_projection_id"]
    projected = ProjectedMindState(
        projection_id=proj_id,
        scope=scope,
        origin_runtime_id=runtime_id,
        projected_states=projected_states,
        sync=SyncFields(scope, runtime_id, proj_id, 1, "idem-proj-01"),
    )
    return projected, surface


def _make_engine_input(
    *,
    interaction_id: str = FIXTURE_INTERACTION_ID,
    scope: Scope,
    origin_runtime_id: str = FIXTURE_RUNTIME_ID,
    situation: Situation,
    projected: ProjectedMindState,
    surface: SurfaceProjectionResult | None = None,
    accepted_events: tuple = (),
    clock: datetime,
    persona_version: int | None = None,
    persona_content_digest: str | None = None,
) -> IntentEngineInput:
    if surface is not None and isinstance(surface.controls, Mapping):
        if persona_version is None:
            persona_version = surface.controls.get("persona_version", 1)
        if persona_content_digest is None:
            persona_content_digest = surface.controls.get("persona_content_digest", "fixture-digest")
    if persona_version is None:
        persona_version = 1
    if persona_content_digest is None:
        persona_content_digest = "fixture-digest"
    return IntentEngineInput(
        interaction_id=interaction_id,
        scope=scope,
        origin_runtime_id=origin_runtime_id,
        context=situation,
        projected=projected,
        accepted_events=accepted_events,
        clock=clock,
        surface=surface,
        persona_version=persona_version,
        persona_content_digest=persona_content_digest,
    )


# ==============================================================================
# SECTION 23: REQUIRED TESTS - CONTRACT
# ==============================================================================

class TestSection23IntentRuleContract:
    def test_23_a_minimum_initiative_none_preserves_legacy_rule(self):
        rule = IntentRule(
            rule_id="rule-share-legacy",
            kind="spontaneous_share",
            base_strength=0.0,
            dimension_weights=(("agent.affect.sharing_urge", 1.0),),
            event_kind=None,
            event_bonus=0.0,
            minimum_strength=0.3,
            due_at_attribute=None,
            expires_after=timedelta(minutes=30),
            reconsideration_policy=ReconsiderationPolicy.NEVER,
            minimum_initiative=None,
        )
        assert rule.minimum_initiative is None

    def test_23_b_valid_finite_thresholds_accepted(self):
        for val in (0.01, 0.4, 0.99, 1.0, 1):
            rule = IntentRule(
                rule_id=f"rule-share-{val}",
                kind="spontaneous_share",
                base_strength=0.0,
                dimension_weights=(("agent.affect.sharing_urge", 1.0),),
                event_kind=None,
                event_bonus=0.0,
                minimum_strength=0.3,
                due_at_attribute=None,
                expires_after=timedelta(minutes=30),
                reconsideration_policy=ReconsiderationPolicy.NEVER,
                minimum_initiative=val,
            )
            assert rule.minimum_initiative == float(val)

    def test_23_c_reject_invalid_thresholds(self):
        for invalid in (0, 0.0, -0.1, -1.0, 1.01, 2.0, True, False, math.nan, math.inf, -math.inf, "0.4", "high"):
            with pytest.raises(ValueError):
                IntentRule(
                    rule_id="rule-invalid-thresh",
                    kind="spontaneous_share",
                    base_strength=0.0,
                    dimension_weights=(("agent.affect.sharing_urge", 1.0),),
                    event_kind=None,
                    event_bonus=0.0,
                    minimum_strength=0.3,
                    due_at_attribute=None,
                    expires_after=timedelta(minutes=30),
                    reconsideration_policy=ReconsiderationPolicy.NEVER,
                    minimum_initiative=invalid,  # type: ignore
                )

    def test_23_d_gate_on_unsupported_intent_kind_rejected(self):
        for unsupported in ("reach_out", "scheduled_follow_up", "respond", "assert_boundary", "custom_motive"):
            with pytest.raises(ValueError, match="only supported for"):
                IntentRule(
                    rule_id=f"rule-{unsupported}",
                    kind=unsupported,
                    base_strength=0.0,
                    dimension_weights=(("agent.affect.longing", 1.0),),
                    event_kind=None,
                    event_bonus=0.0,
                    minimum_strength=0.3,
                    due_at_attribute=None,
                    expires_after=timedelta(minutes=30),
                    reconsideration_policy=ReconsiderationPolicy.NEVER,
                    minimum_initiative=0.4,
                )

    def test_23_e_gated_rule_with_surface_weights_rejected(self):
        with pytest.raises(ValueError, match="surface_control_weights must be empty"):
            IntentRule(
                rule_id="rule-gated-with-weights",
                kind="spontaneous_share",
                base_strength=0.0,
                dimension_weights=(("agent.affect.sharing_urge", 1.0),),
                event_kind=None,
                event_bonus=0.0,
                minimum_strength=0.3,
                due_at_attribute=None,
                expires_after=timedelta(minutes=30),
                reconsideration_policy=ReconsiderationPolicy.NEVER,
                surface_control_weights=(("initiative", 0.5),),
                minimum_initiative=0.4,
            )

    def test_23_f_gated_share_requires_single_sharing_urge_root(self):
        # Empty dimension_weights
        with pytest.raises(ValueError, match="direct root"):
            IntentRule(
                rule_id="rule-share-no-root",
                kind="spontaneous_share",
                base_strength=0.0,
                dimension_weights=(),
                event_kind=None,
                event_bonus=0.0,
                minimum_strength=0.3,
                due_at_attribute=None,
                expires_after=timedelta(minutes=30),
                reconsideration_policy=ReconsiderationPolicy.NEVER,
                minimum_initiative=0.4,
            )
        # Multiple roots
        with pytest.raises(ValueError, match="direct root"):
            IntentRule(
                rule_id="rule-share-multi-root",
                kind="spontaneous_share",
                base_strength=0.0,
                dimension_weights=(
                    ("agent.affect.sharing_urge", 0.8),
                    ("agent.affect.curiosity", 0.2),
                ),
                event_kind=None,
                event_bonus=0.0,
                minimum_strength=0.3,
                due_at_attribute=None,
                expires_after=timedelta(minutes=30),
                reconsideration_policy=ReconsiderationPolicy.NEVER,
                minimum_initiative=0.4,
            )
        # Wrong root
        with pytest.raises(ValueError, match="direct root"):
            IntentRule(
                rule_id="rule-share-wrong-root",
                kind="spontaneous_share",
                base_strength=0.0,
                dimension_weights=(("agent.affect.curiosity", 1.0),),
                event_kind=None,
                event_bonus=0.0,
                minimum_strength=0.3,
                due_at_attribute=None,
                expires_after=timedelta(minutes=30),
                reconsideration_policy=ReconsiderationPolicy.NEVER,
                minimum_initiative=0.4,
            )
        # Weight <= 0
        with pytest.raises(ValueError, match="direct root weight must be positive"):
            IntentRule(
                rule_id="rule-share-neg-weight",
                kind="spontaneous_share",
                base_strength=0.0,
                dimension_weights=(("agent.affect.sharing_urge", 0.0),),
                event_kind=None,
                event_bonus=0.0,
                minimum_strength=0.3,
                due_at_attribute=None,
                expires_after=timedelta(minutes=30),
                reconsideration_policy=ReconsiderationPolicy.NEVER,
                minimum_initiative=0.4,
            )

    def test_23_g_gated_inquiry_requires_single_curiosity_root(self):
        # Wrong root
        with pytest.raises(ValueError, match="direct root"):
            IntentRule(
                rule_id="rule-inquiry-wrong-root",
                kind="proactive_inquiry",
                base_strength=0.0,
                dimension_weights=(("agent.affect.sharing_urge", 1.0),),
                event_kind=None,
                event_bonus=0.0,
                minimum_strength=0.3,
                due_at_attribute=None,
                expires_after=timedelta(minutes=30),
                reconsideration_policy=ReconsiderationPolicy.NEVER,
                minimum_initiative=0.4,
            )
        # Multiple roots
        with pytest.raises(ValueError, match="direct root"):
            IntentRule(
                rule_id="rule-inquiry-multi",
                kind="proactive_inquiry",
                base_strength=0.0,
                dimension_weights=(
                    ("agent.affect.curiosity", 0.7),
                    ("agent.affect.sadness", -0.2),
                ),
                event_kind=None,
                event_bonus=0.0,
                minimum_strength=0.3,
                due_at_attribute=None,
                expires_after=timedelta(minutes=30),
                reconsideration_policy=ReconsiderationPolicy.NEVER,
                minimum_initiative=0.4,
            )


# ==============================================================================
# SECTION 24: REQUIRED TESTS - DOMAIN SCORE PRESERVATION
# ==============================================================================

class TestSection24DomainScorePreservation:
    def test_24_share_domain_score_identical_under_different_sadness_curiosity(self):
        clock = datetime(2026, 9, 25, 12, 0, tzinfo=UTC)
        scope = _make_scope()
        situation = _make_situation(clock, scope)
        rule = IntentRule(
            rule_id="rule-share",
            kind="spontaneous_share",
            base_strength=0.0,
            dimension_weights=(("agent.affect.sharing_urge", 1.0),),
            event_kind=None,
            event_bonus=0.0,
            minimum_strength=0.3,
            due_at_attribute=None,
            expires_after=timedelta(minutes=30),
            reconsideration_policy=ReconsiderationPolicy.NEVER,
            minimum_initiative=0.4,
        )
        engine = DeterministicIntentEngine((rule,), runtime_id=FIXTURE_RUNTIME_ID)

        # Case 1: Low sadness, high curiosity -> high initiative (Pass)
        proj_pass, surf_pass = _build_projected_and_surface(
            sharing_urge=0.6, curiosity=0.8, sadness=0.05
        )
        res_pass = engine.evaluate(
            _make_engine_input(
                scope=scope,
                situation=situation,
                projected=proj_pass,
                surface=surf_pass,
                clock=clock,
            )
        )

        # Case 2: High sadness, low curiosity -> low initiative (Reject)
        proj_rej, surf_rej = _build_projected_and_surface(
            sharing_urge=0.6, curiosity=0.1, sadness=0.9
        )
        res_rej = engine.evaluate(
            _make_engine_input(
                scope=scope,
                situation=situation,
                projected=proj_rej,
                surface=surf_rej,
                clock=clock,
            )
        )

        trace_pass = res_pass.traces[0]
        trace_rej = res_rej.traces[0]

        # Domain strength identical!
        assert trace_pass.final_strength == 0.6
        assert trace_rej.final_strength == 0.6
        assert trace_pass.unclamped_score == 0.6
        assert trace_rej.unclamped_score == 0.6

        # Admission flips!
        assert trace_pass.admitted is True
        assert trace_rej.admitted is False
        assert len(res_pass.candidates) == 1
        assert len(res_rej.candidates) == 0

        # Trace contributions must contain NO initiative or surface amount
        for trace in (trace_pass, trace_rej):
            for contrib in trace.contributions:
                assert contrib.source_kind != "surface"
                assert "initiative" not in contrib.source_ref

    def test_24_inquiry_domain_score_identical_under_different_sadness_sharing(self):
        clock = datetime(2026, 9, 25, 12, 0, tzinfo=UTC)
        scope = _make_scope()
        situation = _make_situation(clock, scope)
        rule = IntentRule(
            rule_id="rule-inquiry",
            kind="proactive_inquiry",
            base_strength=0.0,
            dimension_weights=(("agent.affect.curiosity", 1.0),),
            event_kind=None,
            event_bonus=0.0,
            minimum_strength=0.3,
            due_at_attribute=None,
            expires_after=timedelta(minutes=30),
            reconsideration_policy=ReconsiderationPolicy.NEVER,
            minimum_initiative=0.4,
        )
        engine = DeterministicIntentEngine((rule,), runtime_id=FIXTURE_RUNTIME_ID)

        # Pass case: curiosity=0.55, sharing_urge=0.8, sadness=0.05
        proj_pass, surf_pass = _build_projected_and_surface(
            curiosity=0.55, sharing_urge=0.8, sadness=0.05
        )
        res_pass = engine.evaluate(
            _make_engine_input(
                scope=scope,
                situation=situation,
                projected=proj_pass,
                surface=surf_pass,
                clock=clock,
            )
        )

        # Reject case: curiosity=0.55, sharing_urge=0.1, sadness=0.85
        proj_rej, surf_rej = _build_projected_and_surface(
            curiosity=0.55, sharing_urge=0.1, sadness=0.85
        )
        res_rej = engine.evaluate(
            _make_engine_input(
                scope=scope,
                situation=situation,
                projected=proj_rej,
                surface=surf_rej,
                clock=clock,
            )
        )

        trace_pass = res_pass.traces[0]
        trace_rej = res_rej.traces[0]

        assert trace_pass.final_strength == 0.55
        assert trace_rej.final_strength == 0.55
        assert trace_pass.admitted is True
        assert trace_rej.admitted is False


# ==============================================================================
# SECTION 25: REQUIRED TESTS - GATE
# ==============================================================================

class TestSection25GateMechanics:
    def test_25_gate_threshold_comparisons(self):
        clock = datetime(2026, 9, 25, 12, 0, tzinfo=UTC)
        scope = _make_scope()
        situation = _make_situation(clock, scope)

        # Formula: initiative = 0.60 * sharing_urge + 0.50 * curiosity - 0.25 * sadness
        # If sharing_urge=0.5, curiosity=0.5, sadness=0.4:
        # initiative = 0.60 * 0.5 + 0.50 * 0.5 - 0.25 * 0.4 = 0.30 + 0.25 - 0.10 = 0.45
        proj, surf = _build_projected_and_surface(
            sharing_urge=0.5, curiosity=0.5, sadness=0.4
        )
        observed_init = surf.controls["values"]["initiative"]
        assert round(observed_init, 2) == 0.45

        # 1. initiative > threshold: PASS
        rule_gt = IntentRule(
            rule_id="rule-gt",
            kind="spontaneous_share",
            base_strength=0.0,
            dimension_weights=(("agent.affect.sharing_urge", 1.0),),
            event_kind=None,
            event_bonus=0.0,
            minimum_strength=0.3,
            due_at_attribute=None,
            expires_after=timedelta(minutes=30),
            reconsideration_policy=ReconsiderationPolicy.NEVER,
            minimum_initiative=0.40,
        )
        engine_gt = DeterministicIntentEngine((rule_gt,), runtime_id=FIXTURE_RUNTIME_ID)
        res_gt = engine_gt.evaluate(
            _make_engine_input(
                scope=scope,
                situation=situation,
                projected=proj,
                surface=surf,
                clock=clock,
            )
        )
        assert len(res_gt.candidates) == 1
        t_gt = res_gt.traces[0]
        assert t_gt.admitted is True
        assert t_gt.reason_codes == ("threshold_met",)
        assert t_gt.surface_admission is not None
        assert t_gt.surface_admission.outcome == "passed"
        assert t_gt.surface_admission.observed == observed_init

        # 2. initiative == threshold: PASS
        rule_eq = IntentRule(
            rule_id="rule-eq",
            kind="spontaneous_share",
            base_strength=0.0,
            dimension_weights=(("agent.affect.sharing_urge", 1.0),),
            event_kind=None,
            event_bonus=0.0,
            minimum_strength=0.3,
            due_at_attribute=None,
            expires_after=timedelta(minutes=30),
            reconsideration_policy=ReconsiderationPolicy.NEVER,
            minimum_initiative=observed_init,
        )
        engine_eq = DeterministicIntentEngine((rule_eq,), runtime_id=FIXTURE_RUNTIME_ID)
        res_eq = engine_eq.evaluate(
            _make_engine_input(
                scope=scope,
                situation=situation,
                projected=proj,
                surface=surf,
                clock=clock,
            )
        )
        assert len(res_eq.candidates) == 1
        t_eq = res_eq.traces[0]
        assert t_eq.admitted is True
        assert t_eq.reason_codes == ("threshold_met",)
        assert t_eq.surface_admission.outcome == "passed"

        # 3. initiative just below threshold: REJECT
        rule_lt = IntentRule(
            rule_id="rule-lt",
            kind="spontaneous_share",
            base_strength=0.0,
            dimension_weights=(("agent.affect.sharing_urge", 1.0),),
            event_kind=None,
            event_bonus=0.0,
            minimum_strength=0.3,
            due_at_attribute=None,
            expires_after=timedelta(minutes=30),
            reconsideration_policy=ReconsiderationPolicy.NEVER,
            minimum_initiative=round(observed_init + 0.01, 2),
        )
        engine_lt = DeterministicIntentEngine((rule_lt,), runtime_id=FIXTURE_RUNTIME_ID)
        res_lt = engine_lt.evaluate(
            _make_engine_input(
                scope=scope,
                situation=situation,
                projected=proj,
                surface=surf,
                clock=clock,
            )
        )
        assert len(res_lt.candidates) == 0
        t_lt = res_lt.traces[0]
        assert t_lt.admitted is False
        assert t_lt.final_strength == 0.5  # Preserved domain strength!
        assert t_lt.unclamped_score == 0.5
        assert t_lt.reason_codes == ("initiative_below_minimum",)
        assert t_lt.surface_admission is not None
        assert t_lt.surface_admission.outcome == "below_minimum"
        assert t_lt.surface_admission.observed == observed_init


# ==============================================================================
# SECTION 26: REQUIRED TESTS - CROSS-CONTROL ADMISSION
# ==============================================================================

class TestSection26CrossControlAdmission:
    def test_26_curiosity_raises_initiative_to_admit_share_without_changing_share_strength(self):
        clock = datetime(2026, 9, 25, 12, 0, tzinfo=UTC)
        scope = _make_scope()
        situation = _make_situation(clock, scope)

        rule = IntentRule(
            rule_id="rule-share",
            kind="spontaneous_share",
            base_strength=0.0,
            dimension_weights=(("agent.affect.sharing_urge", 1.0),),
            event_kind=None,
            event_bonus=0.0,
            minimum_strength=0.3,
            due_at_attribute=None,
            expires_after=timedelta(minutes=30),
            reconsideration_policy=ReconsiderationPolicy.NEVER,
            minimum_initiative=0.45,
        )
        engine = DeterministicIntentEngine((rule,), runtime_id=FIXTURE_RUNTIME_ID)

        # Fixed sharing_urge=0.4, sadness=0.2
        # If curiosity=0.2: init = 0.6*0.4 + 0.5*0.2 - 0.25*0.2 = 0.24 + 0.10 - 0.05 = 0.29 (< 0.45 -> REJECT)
        proj_low, surf_low = _build_projected_and_surface(
            sharing_urge=0.4, curiosity=0.2, sadness=0.2
        )
        res_low = engine.evaluate(
            _make_engine_input(
                scope=scope,
                situation=situation,
                projected=proj_low,
                surface=surf_low,
                clock=clock,
            )
        )
        assert len(res_low.candidates) == 0
        assert res_low.traces[0].final_strength == 0.4
        assert res_low.traces[0].admitted is False

        # If curiosity=0.6: init = 0.6*0.4 + 0.5*0.6 - 0.25*0.2 = 0.24 + 0.30 - 0.05 = 0.49 (>= 0.45 -> ADMIT)
        proj_high, surf_high = _build_projected_and_surface(
            sharing_urge=0.4, curiosity=0.6, sadness=0.2
        )
        res_high = engine.evaluate(
            _make_engine_input(
                scope=scope,
                situation=situation,
                projected=proj_high,
                surface=surf_high,
                clock=clock,
            )
        )
        assert len(res_high.candidates) == 1
        assert res_high.candidates[0].strength == 0.4  # Exact same strength!
        assert res_high.traces[0].final_strength == 0.4
        assert res_high.traces[0].admitted is True

    def test_26_sharing_urge_raises_initiative_to_admit_inquiry_without_changing_inquiry_strength(self):
        clock = datetime(2026, 9, 25, 12, 0, tzinfo=UTC)
        scope = _make_scope()
        situation = _make_situation(clock, scope)

        rule = IntentRule(
            rule_id="rule-inquiry",
            kind="proactive_inquiry",
            base_strength=0.0,
            dimension_weights=(("agent.affect.curiosity", 1.0),),
            event_kind=None,
            event_bonus=0.0,
            minimum_strength=0.3,
            due_at_attribute=None,
            expires_after=timedelta(minutes=30),
            reconsideration_policy=ReconsiderationPolicy.NEVER,
            minimum_initiative=0.45,
        )
        engine = DeterministicIntentEngine((rule,), runtime_id=FIXTURE_RUNTIME_ID)

        # Fixed curiosity=0.4, sadness=0.2
        # sharing_urge=0.2 -> init = 0.29 < 0.45 -> REJECT
        proj_low, surf_low = _build_projected_and_surface(
            curiosity=0.4, sharing_urge=0.2, sadness=0.2
        )
        res_low = engine.evaluate(
            _make_engine_input(
                scope=scope,
                situation=situation,
                projected=proj_low,
                surface=surf_low,
                clock=clock,
            )
        )
        assert len(res_low.candidates) == 0
        assert res_low.traces[0].final_strength == 0.4

        # sharing_urge=0.6 -> init = 0.49 >= 0.45 -> ADMIT
        proj_high, surf_high = _build_projected_and_surface(
            curiosity=0.4, sharing_urge=0.6, sadness=0.2
        )
        res_high = engine.evaluate(
            _make_engine_input(
                scope=scope,
                situation=situation,
                projected=proj_high,
                surface=surf_high,
                clock=clock,
            )
        )
        assert len(res_high.candidates) == 1
        assert res_high.candidates[0].strength == 0.4
        assert res_high.traces[0].final_strength == 0.4
        assert res_high.traces[0].admitted is True


# ==============================================================================
# SECTION 27: REQUIRED TESTS - LINEAGE FAIL CLOSED
# ==============================================================================

class TestSection27LineageFailClosed:
    @pytest.fixture
    def base_env(self):
        clock = datetime(2026, 9, 25, 12, 0, tzinfo=UTC)
        scope = _make_scope()
        situation = _make_situation(clock, scope)
        rule = IntentRule(
            rule_id="rule-share",
            kind="spontaneous_share",
            base_strength=0.0,
            dimension_weights=(("agent.affect.sharing_urge", 1.0),),
            event_kind=None,
            event_bonus=0.0,
            minimum_strength=0.3,
            due_at_attribute=None,
            expires_after=timedelta(minutes=30),
            reconsideration_policy=ReconsiderationPolicy.NEVER,
            minimum_initiative=0.4,
        )
        engine = DeterministicIntentEngine((rule,), runtime_id=FIXTURE_RUNTIME_ID)
        proj, surf = _build_projected_and_surface(
            sharing_urge=0.7, curiosity=0.7, sadness=0.1
        )
        return clock, scope, situation, rule, engine, proj, surf

    def _eval(self, engine, clock, scope, situation, proj, surf, **kwargs):
        inp = _make_engine_input(
            interaction_id=kwargs.get("interaction_id", FIXTURE_INTERACTION_ID),
            scope=scope,
            origin_runtime_id=kwargs.get("origin_runtime_id", FIXTURE_RUNTIME_ID),
            situation=situation,
            projected=proj,
            surface=surf,
            clock=clock,
            persona_version=kwargs.get("persona_version"),
            persona_content_digest=kwargs.get("persona_content_digest"),
        )
        res = engine.evaluate(inp)
        assert len(res.candidates) == 0
        trace = res.traces[0]
        assert trace.admitted is False
        assert trace.final_strength == 0.7  # Domain strength inspectable!
        assert trace.unclamped_score == 0.7
        return trace

    def test_27_surface_none(self, base_env):
        clock, scope, situation, _, engine, proj, _ = base_env
        t = self._eval(engine, clock, scope, situation, proj, None)
        assert t.reason_codes == ("surface_unavailable",)
        assert t.surface_admission.outcome == "surface_unavailable"
        assert t.surface_admission.observed is None

    def test_27_surface_unvailable_status(self, base_env):
        clock, scope, situation, _, engine, proj, surf = base_env
        bad_surf = replace(surf, status="UNAVAILABLE")
        t = self._eval(engine, clock, scope, situation, proj, bad_surf)
        assert t.reason_codes == ("surface_unavailable",)
        assert t.surface_admission.outcome == "surface_unavailable"

    def test_27_wrong_runtime(self, base_env):
        clock, scope, situation, _, engine, proj, surf = base_env
        c_dict = dict(surf.controls)
        c_dict["runtime_id"] = "other-runtime"
        semantic = {k: v for k, v in c_dict.items() if k not in ("controls_id", "evaluation_ref")}
        c_dict["controls_id"] = "surface:" + surface_digest("controls", semantic)
        bad_surf = replace(surf, controls=c_dict)
        t = self._eval(engine, clock, scope, situation, proj, bad_surf)
        assert t.reason_codes == ("surface_stale_or_mismatch",)
        assert t.surface_admission.outcome == "surface_stale_or_mismatch"

    def test_27_wrong_interaction_ref(self, base_env):
        clock, scope, situation, _, engine, proj, surf = base_env
        # Evaluate with interaction_id mismatching surface interaction_or_tick_ref
        t = self._eval(engine, clock, scope, situation, proj, surf, interaction_id="other-turn")
        assert t.reason_codes == ("surface_stale_or_mismatch",)
        assert t.surface_admission.outcome == "surface_stale_or_mismatch"

    def test_27_wrong_persona_id_version_digest(self, base_env):
        clock, scope, situation, _, engine, proj, surf = base_env
        # wrong persona_id
        c_dict = dict(surf.controls)
        c_dict["persona_id"] = "other-persona"
        c_dict["owner"] = {"owner_runtime_id": FIXTURE_RUNTIME_ID, "owner_persona_id": "other-persona"}
        semantic = {k: v for k, v in c_dict.items() if k not in ("controls_id", "evaluation_ref")}
        c_dict["controls_id"] = "surface:" + surface_digest("controls", semantic)
        bad_surf = replace(surf, controls=c_dict)
        t1 = self._eval(engine, clock, scope, situation, proj, bad_surf)
        assert t1.reason_codes == ("surface_stale_or_mismatch",)

        # wrong version
        t2 = self._eval(engine, clock, scope, situation, proj, surf, persona_version=999)
        assert t2.reason_codes == ("surface_stale_or_mismatch",)

        # wrong digest
        t3 = self._eval(engine, clock, scope, situation, proj, surf, persona_content_digest="wrong-digest")
        assert t3.reason_codes == ("surface_stale_or_mismatch",)

    def test_27_wrong_projection(self, base_env):
        clock, scope, situation, _, engine, proj, surf = base_env
        c_dict = dict(surf.controls)
        c_dict["source_projection_id"] = "other-projection"
        semantic = {k: v for k, v in c_dict.items() if k not in ("controls_id", "evaluation_ref")}
        c_dict["controls_id"] = "surface:" + surface_digest("controls", semantic)
        bad_surf = replace(surf, controls=c_dict)
        t = self._eval(engine, clock, scope, situation, proj, bad_surf)
        assert t.reason_codes == ("surface_stale_or_mismatch",)

    def test_27_state_id_version_digest_mismatch(self, base_env):
        clock, scope, situation, _, engine, proj, surf = base_env
        states = list(proj.projected_states)
        s0 = states[0]
        states[0] = replace(s0, version=s0.version + 1, sync=replace(s0.sync, version=s0.version + 1))
        bad_proj = replace(proj, projected_states=tuple(states))
        t = self._eval(engine, clock, scope, situation, bad_proj, surf)
        assert t.reason_codes == ("surface_stale_or_mismatch",)

    def test_27_recipe_id_version_digest_mismatch(self, base_env):
        clock, scope, situation, _, engine, proj, surf = base_env
        # Recipe ID mismatch
        c_dict = dict(surf.controls)
        c_dict["recipe_id"] = "wrong-recipe"
        bad_surf = replace(surf, controls=c_dict)
        t = self._eval(engine, clock, scope, situation, proj, bad_surf)
        assert t.reason_codes == ("surface_invalid",)
        assert t.surface_admission.outcome == "surface_invalid"

        # Recipe version mismatch
        c_dict2 = dict(surf.controls)
        c_dict2["recipe_version"] = 99
        bad_surf2 = replace(surf, controls=c_dict2)
        t2 = self._eval(engine, clock, scope, situation, proj, bad_surf2)
        assert t2.reason_codes == ("surface_invalid",)

        # Recipe digest mismatch
        c_dict3 = dict(surf.controls)
        c_dict3["recipe_digest"] = "bad-digest"
        bad_surf3 = replace(surf, controls=c_dict3)
        t3 = self._eval(engine, clock, scope, situation, proj, bad_surf3)
        assert t3.reason_codes == ("surface_invalid",)

    def test_27_dependency_digest_and_initiative_manifest_mismatch(self, base_env):
        clock, scope, situation, _, engine, proj, surf = base_env
        c_dict = dict(surf.controls)
        deps = {k: dict(v) if isinstance(v, Mapping) else v for k, v in c_dict["dependencies_by_control"].items()}
        deps["initiative"] = dict(deps["initiative"])
        deps["initiative"]["dynamics"] = ["agent.affect.curiosity"]  # truncated!
        c_dict["dependencies_by_control"] = deps
        bad_surf = replace(surf, controls=c_dict)
        t = self._eval(engine, clock, scope, situation, proj, bad_surf)
        assert t.reason_codes == ("surface_invalid",)
        assert t.surface_admission.outcome == "surface_invalid"

    def test_27_malformed_initiative_values(self, base_env):
        clock, scope, situation, _, engine, proj, surf = base_env
        for bad_val in (True, False, "0.5", math.nan, math.inf, -0.1, 1.1):
            c_dict = dict(surf.controls)
            vals = dict(c_dict["values"])
            vals["initiative"] = bad_val
            c_dict["values"] = vals
            bad_surf = replace(surf, controls=c_dict)
            t = self._eval(engine, clock, scope, situation, proj, bad_surf)
            assert t.reason_codes == ("surface_invalid",)
            assert t.surface_admission.outcome == "surface_invalid"

    def test_27_missing_initiative_value(self, base_env):
        clock, scope, situation, _, engine, proj, surf = base_env
        c_dict = dict(surf.controls)
        vals = dict(c_dict["values"])
        del vals["initiative"]
        c_dict["values"] = vals
        bad_surf = replace(surf, controls=c_dict)
        t = self._eval(engine, clock, scope, situation, proj, bad_surf)
        assert t.reason_codes == ("surface_invalid",)

    def test_27_forged_controls_id(self, base_env):
        clock, scope, situation, _, engine, proj, surf = base_env
        c_dict = dict(surf.controls)
        c_dict["controls_id"] = "surface:forged-hash-123456"
        bad_surf = replace(surf, controls=c_dict)
        t = self._eval(engine, clock, scope, situation, proj, bad_surf)
        assert t.reason_codes == ("surface_invalid",)


# ==============================================================================
# SECTION 28: REQUIRED TESTS - EXCLUDED INTENTS
# ==============================================================================

class TestSection28ExcludedIntents:
    def test_28_reach_out_not_gated_by_low_initiative(self):
        clock = datetime(2026, 9, 25, 12, 0, tzinfo=UTC)
        scope = _make_scope()
        situation = _make_situation(clock, scope)

        # High longing (0.8), high sadness (0.9), low curiosity/sharing -> low initiative (< 0.2)
        proj, surf = _build_projected_and_surface(
            longing=0.8, sharing_urge=0.1, curiosity=0.1, sadness=0.9
        )
        assert surf.controls["values"]["initiative"] < 0.2

        # Ungated reach_out rule
        rule_reach = IntentRule(
            rule_id="rule-reach-out",
            kind="reach_out",
            base_strength=0.0,
            dimension_weights=(("agent.affect.longing", 1.0),),
            event_kind=None,
            event_bonus=0.0,
            minimum_strength=0.3,
            due_at_attribute=None,
            expires_after=timedelta(minutes=30),
            reconsideration_policy=ReconsiderationPolicy.NEVER,
            minimum_initiative=None,
        )
        engine = DeterministicIntentEngine((rule_reach,), runtime_id=FIXTURE_RUNTIME_ID)
        res = engine.evaluate(
            _make_engine_input(
                scope=scope,
                situation=situation,
                projected=proj,
                surface=surf,
                clock=clock,
            )
        )
        # reach_out candidate is NOT suppressed!
        assert len(res.candidates) == 1
        assert res.candidates[0].kind == "reach_out"
        assert res.candidates[0].strength == 0.8
        trace = res.traces[0]
        assert trace.admitted is True
        assert trace.surface_admission is None

    def test_28_scheduled_follow_up_and_respond_remain_ungated(self):
        clock = datetime(2026, 9, 25, 12, 0, tzinfo=UTC)
        scope = _make_scope()
        situation = _make_situation(clock, scope)
        proj, surf = _build_projected_and_surface(
            sharing_urge=0.05, curiosity=0.05, sadness=0.95
        )

        r_followup = IntentRule(
            rule_id="rule-followup",
            kind="scheduled_follow_up",
            base_strength=0.7,
            dimension_weights=(),
            event_kind="user.reminder",
            event_bonus=0.0,
            minimum_strength=0.5,
            due_at_attribute="due_time",
            expires_after=timedelta(minutes=30),
            reconsideration_policy=ReconsiderationPolicy.ON_DUE,
            minimum_initiative=None,
        )
        r_respond = IntentRule(
            rule_id="rule-respond",
            kind="respond",
            base_strength=0.9,
            dimension_weights=(),
            event_kind=None,
            event_bonus=0.0,
            minimum_strength=0.5,
            due_at_attribute=None,
            expires_after=timedelta(minutes=5),
            reconsideration_policy=ReconsiderationPolicy.NEVER,
            minimum_initiative=None,
        )
        engine = DeterministicIntentEngine((r_followup, r_respond), runtime_id=FIXTURE_RUNTIME_ID)
        res = engine.evaluate(
            _make_engine_input(
                scope=scope,
                situation=situation,
                projected=proj,
                surface=surf,
                clock=clock,
            )
        )
        # Respond candidate emitted normally despite very low initiative
        respond_cand = next(c for c in res.candidates if c.kind == "respond")
        assert respond_cand.strength == 0.9


# ==============================================================================
# SECTION 29: REQUIRED TESTS - TURN / TICK
# ==============================================================================

class TestSection29TurnAndTick:
    def test_29_turn_and_tick_gate_rejection_prevents_lifecycle_and_policy(self):
        clock = datetime(2026, 9, 25, 12, 0, tzinfo=UTC)
        scope = _make_scope()
        situation = _make_situation(clock, scope)

        rule = IntentRule(
            rule_id="rule-share",
            kind="spontaneous_share",
            base_strength=0.0,
            dimension_weights=(("agent.affect.sharing_urge", 1.0),),
            event_kind=None,
            event_bonus=0.0,
            minimum_strength=0.3,
            due_at_attribute=None,
            expires_after=timedelta(minutes=30),
            reconsideration_policy=ReconsiderationPolicy.NEVER,
            minimum_initiative=0.5,
        )
        policy_rule = IntentPolicyRule(
            intent_kind="spontaneous_share",
            action_type="proactive_share",
            proactive=True,
            interrupts_active_conversation=False,
            media_counter_fact=None,
            media_limit=None,
            required_resource=None,
        )
        policy = DeterministicActionPolicy(
            ActionPolicyConfig(
                rules=(policy_rule,),
                proactive_cooldown=timedelta(minutes=15),
            ),
            runtime_id=FIXTURE_RUNTIME_ID,
        )
        engine = DeterministicIntentEngine((rule,), runtime_id=FIXTURE_RUNTIME_ID)

        # Low initiative (0.3 < 0.5) -> REJECT
        proj_rej, surf_rej = _build_projected_and_surface(
            sharing_urge=0.6, curiosity=0.1, sadness=0.5
        )
        res_rej = engine.evaluate(
            _make_engine_input(
                scope=scope,
                situation=situation,
                projected=proj_rej,
                surface=surf_rej,
                clock=clock,
            )
        )
        assert len(res_rej.candidates) == 0
        # No candidate -> ActionPolicy is never invoked for rejected motive!

        # High initiative (0.6 > 0.5) -> PASS
        proj_pass, surf_pass = _build_projected_and_surface(
            sharing_urge=0.6, curiosity=0.8, sadness=0.1
        )
        res_pass = engine.evaluate(
            _make_engine_input(
                scope=scope,
                situation=situation,
                projected=proj_pass,
                surface=surf_pass,
                clock=clock,
            )
        )
        assert len(res_pass.candidates) == 1
        cand = res_pass.candidates[0]
        # Candidate evaluates normally under ActionPolicy
        p_res = policy.policy(
            ActionPolicyInput(
                intent=cand,
                context=situation,
                scope=scope,
                clock=clock,
                resources=PolicyResources(available_actions=("proactive_share",)),
            )
        )
        assert p_res.decision == ActionDecision.ALLOW
        assert p_res.permission is not None
        assert p_res.permission.action_type == "proactive_share"


# ==============================================================================
# SECTION 30: REQUIRED TESTS - PERSISTENCE & RULESET REF
# ==============================================================================

class TestSection30PersistenceAndRulesetRef:
    def test_30_passing_gated_intent_persistence_roundtrip(self, tmp_path):
        clock = datetime(2026, 9, 25, 12, 0, tzinfo=UTC)
        scope = _make_scope()
        situation = _make_situation(clock, scope)

        rule = IntentRule(
            rule_id="rule-share",
            kind="spontaneous_share",
            base_strength=0.0,
            dimension_weights=(("agent.affect.sharing_urge", 1.0),),
            event_kind=None,
            event_bonus=0.0,
            minimum_strength=0.3,
            due_at_attribute=None,
            expires_after=timedelta(minutes=30),
            reconsideration_policy=ReconsiderationPolicy.NEVER,
            minimum_initiative=0.4,
        )
        engine = DeterministicIntentEngine((rule,), runtime_id=FIXTURE_RUNTIME_ID)
        proj, surf = _build_projected_and_surface(
            sharing_urge=0.6, curiosity=0.7, sadness=0.1
        )
        res = engine.evaluate(
            _make_engine_input(
                scope=scope,
                situation=situation,
                projected=proj,
                surface=surf,
                clock=clock,
            )
        )
        cand = res.candidates[0]
        assert cand.surface_use is not None
        trace = cand.surface_use
        assert trace.surface_admission is not None

        # Test SQLite serialization round-trip
        backend = SqliteIntentBackend(tmp_path / "intents.db")
        backend.append_initial(cand)
        history = backend.history(cand.scope, cand.intent_id)
        assert len(history) == 1
        loaded = history[0]
        assert loaded is not None
        assert loaded.surface_use is not None
        l_trace = loaded.surface_use
        assert l_trace.surface_controls_ref == trace.surface_controls_ref
        assert l_trace.surface_dependency_digest == trace.surface_dependency_digest
        assert l_trace.surface_recipe_ref == trace.surface_recipe_ref
        assert l_trace.surface_admission is not None
        assert l_trace.surface_admission.control == "initiative"
        assert l_trace.surface_admission.comparator == "gte"
        assert l_trace.surface_admission.minimum == 0.4
        assert l_trace.surface_admission.outcome == "passed"
        assert l_trace.surface_admission.observed == trace.surface_admission.observed
        assert l_trace.surface_admission.admission_validation_ref == trace.surface_admission.admission_validation_ref

    def test_30_legacy_surface_use_json_bytes_identical_when_admission_none(self):
        clock = datetime(2026, 9, 25, 12, 0, tzinfo=UTC)
        scope = _make_scope()
        trace_legacy = IntentScoreTrace(
            trace_id="trace-01",
            scope=scope,
            rule_id="rule-reach",
            intent_id="intent-01",
            contributions=(IntentScoreContribution("base", "rule-reach", 0.5),),
            unclamped_score=0.5,
            final_strength=0.5,
            admitted=True,
            reason_codes=("threshold_met",),
            created_at=clock,
            surface_controls_ref="controls-ref",
            surface_dependency_digest="dep-digest",
            overlap_validation_ref="overlap-ref",
            surface_weights=(("contact_seeking", 0.2),),
            surface_recipe_ref="recipe:1:hash",
            ruleset_ref="ruleset:legacy",
            surface_admission=None,
        )
        serialized = _surface_use_to_json(trace_legacy)
        assert serialized is not None
        data = json.loads(serialized)
        # surface_admission must NOT be present as a key when None!
        assert "surface_admission" not in data

        # Round-trip deserializes as None
        deserialized = _surface_use_from_json(serialized, scope)
        assert deserialized is not None
        assert deserialized.surface_admission is None

    def test_30_ruleset_ref_backward_compatibility(self):
        rule_legacy = IntentRule(
            rule_id="rule-legacy",
            kind="reach_out",
            base_strength=0.5,
            dimension_weights=(("agent.affect.longing", 1.0),),
            event_kind=None,
            event_bonus=0.0,
            minimum_strength=0.3,
            due_at_attribute=None,
            expires_after=timedelta(minutes=30),
            reconsideration_policy=ReconsiderationPolicy.NEVER,
            minimum_initiative=None,
        )
        engine_1 = DeterministicIntentEngine((rule_legacy,), runtime_id=FIXTURE_RUNTIME_ID)

        # Manually compute what legacy wire payload produced
        legacy_rule_dict = {
            "rule_id": "rule-legacy",
            "kind": "reach_out",
            "base_strength": 0.5,
            "dimension_weights": [["agent.affect.longing", 1.0]],
            "event_kind": None,
            "event_bonus": 0.0,
            "minimum_strength": 0.3,
            "due_at_attribute": None,
            "expires_after": "0:30:00",
            "reconsideration_policy": "never",
            "surface_control_weights": [],
        }
        legacy_wire = json.dumps([legacy_rule_dict], sort_keys=True, default=str, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
        expected_ruleset_ref = "ruleset:" + hashlib.sha256(legacy_wire).hexdigest()

        assert engine_1._ruleset_ref == expected_ruleset_ref

        # Changing gate threshold changes ruleset_ref
        rule_gated_04 = IntentRule(
            rule_id="rule-gated",
            kind="spontaneous_share",
            base_strength=0.0,
            dimension_weights=(("agent.affect.sharing_urge", 1.0),),
            event_kind=None,
            event_bonus=0.0,
            minimum_strength=0.3,
            due_at_attribute=None,
            expires_after=timedelta(minutes=30),
            reconsideration_policy=ReconsiderationPolicy.NEVER,
            minimum_initiative=0.4,
        )
        rule_gated_05 = replace(rule_gated_04, minimum_initiative=0.5)

        eng_04 = DeterministicIntentEngine((rule_gated_04,), runtime_id=FIXTURE_RUNTIME_ID)
        eng_05 = DeterministicIntentEngine((rule_gated_05,), runtime_id=FIXTURE_RUNTIME_ID)

        assert eng_04._ruleset_ref != eng_05._ruleset_ref


# ==============================================================================
# SECTION 12: CONFIG DECODING
# ==============================================================================

class TestSection12ConfigDecoding:
    def test_12_config_decoding_optional_minimum_initiative(self):
        base_dict = {
            "rule_id": "rule-share",
            "kind": "spontaneous_share",
            "base_strength": 0.0,
            "dimension_weights": [["agent.affect.sharing_urge", 1.0]],
            "event_kind": None,
            "event_bonus": 0.0,
            "minimum_strength": 0.3,
            "due_at_attribute": None,
            "expires_after": 1800000000,
            "reconsideration_policy": "never",
        }
        # Missing -> None
        rule_missing = _intent_rule(base_dict, "test.rule")
        assert rule_missing.minimum_initiative is None

        # Explicit float -> 0.4
        with_thresh = dict(base_dict)
        with_thresh["minimum_initiative"] = 0.4
        rule_configured = _intent_rule(with_thresh, "test.rule")
        assert rule_configured.minimum_initiative == 0.4

        # Reject invalid types and values
        for bad in (True, False, "0.4", -0.1, 0.0, 1.5, math.nan, math.inf):
            bad_dict = dict(base_dict)
            bad_dict["minimum_initiative"] = bad
            with pytest.raises(ValueError):
                _intent_rule(bad_dict, "test.rule")

        # Reject unsupported kinds with minimum_initiative
        bad_kind_dict = dict(base_dict)
        bad_kind_dict["kind"] = "reach_out"
        bad_kind_dict["dimension_weights"] = [["agent.affect.longing", 1.0]]
        bad_kind_dict["minimum_initiative"] = 0.4
        with pytest.raises(ValueError):
            _intent_rule(bad_kind_dict, "test.rule")
