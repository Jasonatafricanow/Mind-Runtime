"""Pure D11S invariants over immutable, captured authoritative records."""

from __future__ import annotations

import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from math import isclose, isfinite
from pathlib import Path
from time import perf_counter

from mind_runtime.contracts import (
    AssessmentTrace,
    AuthorityLevel,
    EmotionalTransitionResult,
    RuntimeState,
    StateDefinition,
    StateValueType,
)
from mind_runtime.pipeline.fake_agent import FakeAgent
from mind_runtime.validation.composition import (
    CertificationRuntimeConfig,
    DurablePaths,
    build_composition,
)
from mind_runtime.validation.contracts import (
    CertificationPlan,
    DailyDecisionDigest,
    InvariantResult,
    RuntimeConfigManifest,
    SimulationEvent,
    decode_horizon_template_bytes,
    decode_runtime_config_manifest_bytes,
    load_model_swap_fixture,
    verify_fixture_artifacts,
)
from mind_runtime.validation.digest import canonical_json_bytes, sha256_bytes
from mind_runtime.validation.horizon import HorizonDayCapture, HorizonRun

_ASSISTANT_EVIDENCE_TYPES = frozenset({"assistant", "assistant_expression", "model_output"})


@dataclass(frozen=True, slots=True)
class CapturedContribution:
    """Pure projection of one contribution used for invariant reconciliation."""

    dimension: str
    source_kind: str
    source_ref: str
    amount: float
    applied: bool = True

    def __post_init__(self) -> None:
        if not self.dimension.strip():
            raise ValueError("contribution dimension must not be empty")
        if not self.source_kind.strip() or not self.source_ref.strip():
            raise ValueError("contribution source must not be empty")
        if (
            isinstance(self.amount, bool)
            or not isinstance(self.amount, (int, float))
            or not isfinite(float(self.amount))
        ):
            raise ValueError("contribution amount must be finite and numeric")
        if not isinstance(self.applied, bool):
            raise ValueError("contribution applied must be a bool")


@dataclass(frozen=True, slots=True)
class HistoryStepCapture:
    """Small captured-record projection for the false-history invariant."""

    capture_ref: str
    direct_state_write_refs: tuple[str, ...]
    contribution_count: int
    authoritative_evidence_refs: tuple[str, ...]
    trace_refs: tuple[str, ...]
    supplied_history_refs: tuple[str, ...]
    state_before_values: tuple[tuple[str, float], ...]
    state_values: tuple[tuple[str, float], ...]
    contributions: tuple[CapturedContribution, ...]
    elapsed_days: int

    def __post_init__(self) -> None:
        if not self.capture_ref.strip():
            raise ValueError("capture_ref must not be empty")
        for field_name in (
            "direct_state_write_refs",
            "authoritative_evidence_refs",
            "trace_refs",
            "supplied_history_refs",
            "state_before_values",
            "state_values",
            "contributions",
        ):
            if not isinstance(getattr(self, field_name), tuple):
                raise ValueError(f"{field_name} must be an immutable tuple")
        for refs in (
            self.direct_state_write_refs,
            self.authoritative_evidence_refs,
            self.trace_refs,
            self.supplied_history_refs,
        ):
            if any(not ref.strip() for ref in refs):
                raise ValueError("captured refs must not be empty")
        if isinstance(self.contribution_count, bool) or self.contribution_count < 0:
            raise ValueError("contribution_count must be non-negative")
        if isinstance(self.elapsed_days, bool) or self.elapsed_days < 0:
            raise ValueError("elapsed_days must be non-negative")
        for values in (self.state_before_values, self.state_values):
            dimensions = tuple(dimension for dimension, _value in values)
            if any(not dimension.strip() for dimension in dimensions):
                raise ValueError("state dimensions must not be empty")
            if len(dimensions) != len(set(dimensions)):
                raise ValueError("state dimensions must be unique")
            if any(
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not isfinite(float(value))
                for _dimension, value in values
            ):
                raise ValueError("state values must be finite and numeric")
        if any(not isinstance(item, CapturedContribution) for item in self.contributions):
            raise ValueError("contributions must contain CapturedContribution records")


@dataclass(frozen=True, slots=True)
class FalseHistoryInvariantResult(InvariantResult):
    """Invariant result retaining the explicit control-bound verdict."""

    within_control_bound: bool

    def __post_init__(self) -> None:
        super(FalseHistoryInvariantResult, self).__post_init__()
        if not isinstance(self.within_control_bound, bool):
            raise ValueError("within_control_bound must be a bool")


@dataclass(frozen=True, slots=True)
class LongHorizonCertification:
    """Semantic 30/90-day result from independent empty durable roots.

    Four roots: ``first-run`` and ``replay-run`` execute every exact decoded
    event (a repeated Evidence goes through the canonical REPLAY admission,
    never validation-side suppression); ``history-control-run`` withholds only
    the named false-history bundle; ``no-duplicate-control-run`` derives from
    the exact verified template with the named duplicate event removed.
    """

    source_head: str
    input_sha256: str
    runtime_config_manifest_sha256: str
    virtual_horizon_days: int
    wall_clock_execution_seconds: float
    first_run_daily_digests: tuple[DailyDecisionDigest, ...]
    replay_daily_digests: tuple[DailyDecisionDigest, ...]
    first_run_record_hashes: tuple[str, ...]
    replay_record_hashes: tuple[str, ...]
    history_control_run_record_hashes: tuple[str, ...]
    no_duplicate_control_run_record_hashes: tuple[str, ...]
    invariants: tuple[InvariantResult, ...]
    semantic_sha256: str

    def __post_init__(self) -> None:
        if len(self.source_head) != 40 or any(
            char not in "0123456789abcdef" for char in self.source_head
        ):
            raise ValueError("source_head must be an exact Git SHA")
        for field_name in (
            "input_sha256",
            "runtime_config_manifest_sha256",
            "semantic_sha256",
        ):
            if not _is_sha256(getattr(self, field_name)):
                raise ValueError(f"{field_name} must be a SHA-256")
        if self.virtual_horizon_days not in (30, 90):
            raise ValueError("virtual_horizon_days must be exactly 30 or 90")
        if (
            isinstance(self.wall_clock_execution_seconds, bool)
            or not isfinite(self.wall_clock_execution_seconds)
            or self.wall_clock_execution_seconds < 0
        ):
            raise ValueError("wall_clock_execution_seconds must be non-negative and finite")
        for field_name in (
            "first_run_daily_digests",
            "replay_daily_digests",
            "first_run_record_hashes",
            "replay_record_hashes",
            "history_control_run_record_hashes",
            "no_duplicate_control_run_record_hashes",
            "invariants",
        ):
            if not isinstance(getattr(self, field_name), tuple):
                raise ValueError(f"{field_name} must be an immutable tuple")
        codes = tuple(item.code for item in self.invariants)
        if len(codes) != len(set(codes)):
            raise ValueError("invariant codes must be unique")
        if self.semantic_sha256 != long_horizon_semantic_hash(self):
            raise ValueError("semantic_sha256 must cover the closed semantic record")


def check_boundedness(
    captured: HorizonDayCapture | HorizonRun | Sequence[HorizonDayCapture | HorizonRun],
) -> InvariantResult:
    """Require every captured scalar State to have finite definition-owned bounds."""
    captures = _flatten_captures(captured)
    failures: list[str] = []
    evidence_refs: list[str] = []
    checked = 0
    for capture in captures:
        definitions = _definitions_by_key(capture.records.state_definitions)
        for state in capture.records.canonical_states:
            evidence_refs.append(state.state_id)
            definition = definitions.get(state.dimension)
            if definition is None:
                failures.append(f"{state.state_id}:missing_definition")
                continue
            if definition.value_type is not StateValueType.SCALAR:
                continue
            checked += 1
            bounds = _scalar_bounds(definition)
            value = state.value
            if bounds is None:
                failures.append(f"{state.state_id}:invalid_bounds")
            elif isinstance(value, bool) or not isinstance(value, (int, float)):
                failures.append(f"{state.state_id}:non_numeric")
            elif not isfinite(float(value)):
                failures.append(f"{state.state_id}:non_finite")
            elif not bounds[0] <= float(value) <= bounds[1]:
                failures.append(f"{state.state_id}:outside[{bounds[0]},{bounds[1]}]")
    refs = _unique(evidence_refs) or _capture_record_refs(captures)
    return InvariantResult(
        code="state.boundedness",
        passed=not failures,
        observed=(f"checked={checked}; failures={','.join(failures) if failures else 'none'}"),
        expected="every scalar State is finite and within decoded StateDefinition bounds",
        evidence_refs=refs,
    )


def check_replay(first: HorizonRun, replay: HorizonRun) -> InvariantResult:
    """Compare ordered daily digests and independently captured full records."""
    digest_equal = first.daily_digests == replay.daily_digests
    first_records = tuple(_record_hash(capture) for capture in first.daily_captures)
    replay_records = tuple(_record_hash(capture) for capture in replay.daily_captures)
    records_equal = first_records == replay_records
    mismatched_days = tuple(
        day
        for day, (left, right) in enumerate(zip(first_records, replay_records, strict=False))
        if left != right
    )
    if len(first_records) != len(replay_records):
        mismatched_days += (min(len(first_records), len(replay_records)),)
    digest_mismatches = tuple(
        day
        for day, (left, right) in enumerate(
            zip(first.daily_digests, replay.daily_digests, strict=False)
        )
        if left != right
    )
    evidence_days = _unique((*mismatched_days, *digest_mismatches)) or (0,)
    refs: list[str] = []
    for day in evidence_days:
        if day < len(first_records):
            refs.append(f"daily-record:first:{day}:{first_records[day]}")
        if day < len(replay_records):
            refs.append(f"daily-record:replay:{day}:{replay_records[day]}")
    return InvariantResult(
        code="replay.semantic_records",
        passed=digest_equal and records_equal,
        observed=(
            f"digests_equal={str(digest_equal).lower()}; "
            f"full_records_equal={str(records_equal).lower()}"
        ),
        expected="ordered daily digests and full semantic records are byte-identical",
        evidence_refs=tuple(refs),
    )


def check_registered_time_dynamics(
    before: HorizonDayCapture,
    after: HorizonDayCapture,
    accepted_event_refs: tuple[str, ...],
) -> InvariantResult:
    """Allow a no-event step to change State only through registered recovery traces."""
    before_states = _state_values(before.records.canonical_states)
    after_states = _state_values(after.records.canonical_states)
    changed = tuple(
        dimension
        for dimension in sorted(set(before_states) | set(after_states))
        if before_states.get(dimension) != after_states.get(dimension)
    )
    before_definitions = _definitions_by_key(before.records.state_definitions)
    after_definitions = _definitions_by_key(after.records.state_definitions)
    new_traces = tuple(
        result.assessment_trace
        for result in after.records.transition_results
        if result.assessment_trace.trace_id
        not in {item.assessment_trace.trace_id for item in before.records.transition_results}
    )
    authority_bound = (
        bool(before_definitions)
        and before_definitions == after_definitions
        and all(dimension in before_definitions for dimension in changed)
    )
    traced = not changed or (
        len(new_traces) == 1
        and not new_traces[0].evidence_refs
        and not new_traces[0].history_refs
        and all(
            not contribution.applied or contribution.source_kind == "recovery"
            for contribution in new_traces[0].contributions
        )
        and _trace_reconciles_state_delta(before, after, new_traces[0])
    )
    facts_unchanged = (
        before.records.evidence == after.records.evidence
        and before.records.observations == after.records.observations
    )
    passed = not accepted_event_refs and authority_bound and traced and facts_unchanged
    refs = _unique(
        (
            *accepted_event_refs,
            *(
                state.state_id
                for state in after.records.canonical_states
                if state.dimension in changed
            ),
            *(trace.trace_id for trace in new_traces),
            *_capture_record_refs((before, after)),
        )
    )
    return InvariantResult(
        code="time.registered_dynamics",
        passed=passed,
        observed=(
            f"events={len(accepted_event_refs)}; changed={','.join(changed) or 'none'}; "
            f"authority_bound={str(authority_bound).lower()}; "
            f"traced={str(traced).lower()}; "
            f"facts_unchanged={str(facts_unchanged).lower()}"
        ),
        expected=(
            "no event, or only recovery reconciled to stable captured StateDefinition authority"
        ),
        evidence_refs=refs,
    )


def check_no_self_excitation(
    run: HorizonRun,
    events: tuple[SimulationEvent, ...],
    no_duplicate_control: HorizonRun | None = None,
) -> InvariantResult:
    """Reject duplicate-input excitation, expression Evidence, and stale history causes.

    The duplicate-day checks compare the treatment capture with the
    independent no-duplicate control capture at the same virtual day. They
    assume the repeated event is the only event on its day (true for the
    verified 30/90-day templates); a future template that adds another event
    on the same day must extend the counterfactual reconciliation rather than
    the simple equality checks.
    """
    failures: list[str] = []
    evidence_refs: list[str] = []
    final_evidence = run.daily_captures[-1].records.evidence
    for evidence, _interaction_id in final_evidence:
        payload_kind = ""
        if isinstance(evidence.payload, Mapping):
            raw_kind = evidence.payload.get("kind")
            payload_kind = raw_kind if isinstance(raw_kind, str) else ""
        if (
            evidence.source_type in _ASSISTANT_EVIDENCE_TYPES
            or payload_kind in _ASSISTANT_EVIDENCE_TYPES
        ):
            failures.append(f"assistant_evidence:{evidence.id}")
            evidence_refs.append(evidence.id)

    first_by_key: dict[str, SimulationEvent] = {}
    for event in events:
        for evidence in event.evidence:
            key = evidence.sync.idempotency_key
            previous = first_by_key.get(key)
            if previous is None:
                first_by_key[key] = event
                continue
            repeat_day = _event_capture_day(event)
            before_capture = run.daily_captures[max(0, repeat_day - 1)]
            replay_capture = _capture_for_event(run, event)
            control_available = no_duplicate_control is not None and no_duplicate_control is not run
            if not control_available:
                failures.append(f"duplicate_control_missing:{key}")
                evidence_refs.extend((previous.event_id, event.event_id, evidence.id))
                continue
            assert no_duplicate_control is not None
            control_before = no_duplicate_control.daily_captures[max(0, repeat_day - 1)]
            control_capture = _capture_for_event(no_duplicate_control, event)
            event_ids = {item.id for item in event.evidence}
            # 1. The replay adds no durable Evidence or Observation rows.
            before_evidence_ids = {item.id for item, _ref in before_capture.records.evidence}
            replay_evidence_ids = {item.id for item, _ref in replay_capture.records.evidence}
            before_observation_ids = {item.id for item in before_capture.records.observations}
            replay_observation_ids = {item.id for item in replay_capture.records.observations}
            if (
                replay_evidence_ids != before_evidence_ids
                or replay_observation_ids != before_observation_ids
            ):
                failures.append(f"duplicate_rows:{key}")
            # 2. The replay turn must not reapply the event: no accepted
            #    event, no event contribution, no Evidence-linked trace.
            replay_results = _new_transition_results(before_capture, replay_capture)
            event_reapplied = any(
                result.accepted_events
                or any(
                    item.source_kind == "event" for item in result.assessment_trace.contributions
                )
                or bool(set(result.assessment_trace.evidence_refs) & event_ids)
                for result in replay_results
            )
            if event_reapplied:
                failures.append(f"duplicate_event_reapplied:{key}")
            # 3. The audit Interaction is retained: exactly the event's own
            #    new interaction and nothing else (ADR-0009 §3).
            before_interaction_ids = {
                item.interaction_id for item in before_capture.records.interactions
            }
            new_interactions = tuple(
                item
                for item in replay_capture.records.interactions
                if item.interaction_id not in before_interaction_ids
            )
            audit_retained = len(new_interactions) == 1 and new_interactions[
                0
            ].interaction_id.endswith(f"{event.event_id}:interaction")
            if not audit_retained:
                failures.append(f"duplicate_audit_interaction:{key}")
            # 4. The only allowed State change is registered recovery,
            #    authority-bound and reconciled to the actual delta. This
            #    rejects the +event/-recovery=0 cancellation pattern even
            #    when the final State nets to zero.
            registered_recovery = check_registered_time_dynamics(
                before_capture, replay_capture, ()
            ).passed
            if not registered_recovery:
                failures.append(f"duplicate_recovery_not_registered:{key}")
            # 5. The no-duplicate control is the independent counterfactual:
            #    with the event absent, no turn runs and no record changes;
            #    the control State equals the treatment's post-turn State
            #    minus the replay turn's registered recovery movement.
            control_results = _new_transition_results(control_before, control_capture)
            control_polluted = any(
                result.accepted_events
                or any(
                    item.source_kind == "event" for item in result.assessment_trace.contributions
                )
                or bool(set(result.assessment_trace.evidence_refs) & event_ids)
                for result in control_results
            )
            control_records_unchanged = (
                not control_results
                and {item.id for item, _ref in control_capture.records.evidence}
                == {item.id for item, _ref in control_before.records.evidence}
                and {item.id for item in control_capture.records.observations}
                == {item.id for item in control_before.records.observations}
                and {item.interaction_id for item in control_capture.records.interactions}
                == {item.interaction_id for item in control_before.records.interactions}
            )
            if control_polluted or not control_records_unchanged:
                failures.append(f"duplicate_control_polluted:{key}")
            recovery_delta = _applied_recovery_deltas(replay_results)
            control_matches_counterfactual = _numeric_state_values(
                control_capture.records.canonical_states
            ) == _subtract_recovery(
                _numeric_state_values(replay_capture.records.canonical_states), recovery_delta
            )
            if not control_matches_counterfactual:
                failures.append(f"duplicate_state_mismatch:{key}")
            evidence_refs.extend(
                (
                    previous.event_id,
                    event.event_id,
                    evidence.id,
                    *_capture_record_refs((replay_capture, control_capture)),
                )
            )

    prior_history_refs: set[str] = set()
    for event in events:
        supplied = _history_refs(event)
        capture = _capture_for_event(run, event)
        current_trace_refs = {
            ref
            for result in capture.records.transition_results
            for ref in result.assessment_trace.history_refs
        }
        leaked = (current_trace_refs & prior_history_refs) - supplied
        if leaked:
            failures.extend(f"stale_history:{ref}" for ref in sorted(leaked))
            evidence_refs.extend(sorted(leaked))
        prior_history_refs.update(supplied)
        evidence_refs.append(event.event_id)
    return InvariantResult(
        code="history.no_self_excitation",
        passed=not failures,
        observed=f"failures={','.join(failures) if failures else 'none'}",
        expected=(
            "idempotent inputs add no durable row, no event transition, no State change "
            "beyond registered recovery, and retain exactly the audit Interaction; the "
            "independent no-duplicate control stays clean and matches the treatment minus "
            "registered recovery; expression and unsupplied history add no cause"
        ),
        evidence_refs=_unique(evidence_refs),
    )


def check_false_history_reversible(
    false_history_step: HistoryStepCapture,
    authoritative_correction_step: HistoryStepCapture,
    no_false_history_control: HistoryStepCapture,
    recovery_horizon_days: int,
    tolerance: str,
) -> FalseHistoryInvariantResult:
    """Check captured false-history isolation and bounded correction convergence."""
    try:
        tolerance_value = float(tolerance)
    except ValueError:
        tolerance_value = float("nan")
    correction = dict(authoritative_correction_step.state_values)
    control = dict(no_false_history_control.state_values)
    same_dimensions = correction.keys() == control.keys()
    differences = tuple(
        abs(correction[dimension] - control[dimension])
        for dimension in correction.keys() & control.keys()
    )
    within_control_bound = (
        isfinite(tolerance_value)
        and tolerance_value >= 0
        and same_dimensions
        and all(isfinite(value) and value <= tolerance_value for value in differences)
    )
    old_history = set(false_history_step.supplied_history_refs)
    explicitly_resupplied = set(authoritative_correction_step.supplied_history_refs)
    leaked_history = (
        set(authoritative_correction_step.trace_refs) & old_history
    ) - explicitly_resupplied
    control_history = set(no_false_history_control.trace_refs) & old_history
    within_window = authoritative_correction_step.elapsed_days <= recovery_horizon_days
    # The false-history step must not move State except through traced
    # contributions that reconcile to the actual delta. Zero contributions are
    # legitimate when the affect is already at its registered baseline (the
    # replay turn's recovery completed before this step); what is forbidden is
    # any untraced or unreconciled magnitude.
    contribution_reconciled = _captured_contributions_reconcile(
        false_history_step.state_before_values,
        false_history_step.state_values,
        false_history_step.contributions,
        false_history_step.contribution_count,
    )
    correction_authority = set(authoritative_correction_step.authoritative_evidence_refs)
    control_authority = set(no_false_history_control.authoritative_evidence_refs)
    correction_linked = bool(correction_authority) and correction_authority.issubset(
        authoritative_correction_step.trace_refs
    )
    control_linked = correction_authority == control_authority and control_authority.issubset(
        no_false_history_control.trace_refs
    )
    independent_control = no_false_history_control.capture_ref not in {
        false_history_step.capture_ref,
        authoritative_correction_step.capture_ref,
    }
    passed = (
        not false_history_step.direct_state_write_refs
        and contribution_reconciled
        and correction_linked
        and control_linked
        and independent_control
        and not leaked_history
        and not control_history
        and within_window
        and within_control_bound
    )
    refs = _unique(
        (
            false_history_step.capture_ref,
            authoritative_correction_step.capture_ref,
            no_false_history_control.capture_ref,
            *false_history_step.direct_state_write_refs,
            *authoritative_correction_step.authoritative_evidence_refs,
            *sorted(leaked_history),
            *sorted(control_history),
            f"manifest:recovery_horizon_days:{recovery_horizon_days}",
            f"manifest:convergence_tolerance:{tolerance}",
        )
    )
    return FalseHistoryInvariantResult(
        code="history.false_history_reversible",
        passed=passed,
        observed=(
            f"direct_writes={len(false_history_step.direct_state_write_refs)}; "
            f"contributions={false_history_step.contribution_count}; "
            f"contribution_reconciled={str(contribution_reconciled).lower()}; "
            f"correction_linked={str(correction_linked).lower()}; "
            f"control_linked={str(control_linked).lower()}; "
            f"independent_control={str(independent_control).lower()}; "
            f"leaked_history={','.join(sorted(leaked_history)) or 'none'}; "
            f"control_history={','.join(sorted(control_history)) or 'none'}; "
            f"within_window={str(within_window).lower()}; "
            f"within_control_bound={str(within_control_bound).lower()}"
        ),
        expected=(
            "no direct history write, delta-reconciled contribution(s) "
            "(zero allowed at registered baseline), authority-linked correction, "
            "independent-control bounded convergence"
        ),
        evidence_refs=refs,
        within_control_bound=within_control_bound,
    )


def certify_horizon(
    plan: CertificationPlan,
    *,
    root: Path,
    repository_root: Path | None = None,
) -> LongHorizonCertification:
    """Execute replay and history-control runs from distinct empty durable roots."""
    repository = Path(__file__).resolve().parents[3]
    if repository_root is not None:
        repository = repository_root.resolve()
    current_head = _current_source_head(repository)
    if plan.source_head != current_head:
        raise ValueError("plan source HEAD must equal the checked-out source HEAD")
    if root.exists() and any(root.iterdir()):
        raise ValueError("certification root must be empty")
    root.mkdir(parents=True, exist_ok=True)

    manifest_path = repository / "certification/d11s/inputs/runtime-config.json"
    manifest_bytes = manifest_path.read_bytes()
    manifest_hash = sha256_bytes(manifest_bytes)
    if manifest_hash != plan.runtime_config_manifest_sha256:
        raise ValueError("plan runtime manifest hash does not match verified bytes")
    manifest = decode_runtime_config_manifest_bytes(manifest_bytes)
    verify_fixture_artifacts(manifest, repository)
    horizon_path = repository / f"certification/d11s/inputs/horizon-{plan.horizon_days}.json"
    horizon_bytes = horizon_path.read_bytes()
    template = decode_horizon_template_bytes(horizon_bytes)
    expected_plan = CertificationPlan(
        certification_id=template.certification_id,
        source_head=current_head,
        persona_version=template.persona_version,
        runtime_config_manifest_sha256=manifest_hash,
        horizon_days=template.horizon_days,
        started_at=template.started_at,
        events=template.events,
        checkpoint_interval=template.checkpoint_interval,
    )
    if plan != expected_plan:
        raise ValueError("plan must decode from the exact verified horizon bytes")

    provider_fixture = load_model_swap_fixture(
        repository / "certification/d11s/inputs/model-swap-left.json"
    )
    false_history_event = next(
        event for event in template.events if event.expected_path == "false_history"
    )
    duplicate_event = next(
        event for event in template.events if event.expected_path == "idempotent_replay"
    )
    # The no-duplicate control derives from the exact verified template with
    # the named duplicate event removed — it is an independent root and an
    # independent trajectory, never built from the treatment run.
    no_duplicate_plan = replace(
        plan,
        events=tuple(
            event for event in template.events if event.event_id != duplicate_event.event_id
        ),
    )
    wall_started = perf_counter()
    first = _run_in_empty_root(
        plan,
        root / "first-run",
        repository,
        manifest_path,
        provider_fixture.responses,
    )
    replay = _run_in_empty_root(
        plan,
        root / "replay-run",
        repository,
        manifest_path,
        provider_fixture.responses,
    )
    history_control = _run_in_empty_root(
        plan,
        root / "history-control-run",
        repository,
        manifest_path,
        provider_fixture.responses,
        history_control_event_id=false_history_event.event_id,
    )
    no_duplicate_control = _run_in_empty_root(
        no_duplicate_plan,
        root / "no-duplicate-control-run",
        repository,
        manifest_path,
        provider_fixture.responses,
        excluded_event_ids=frozenset({duplicate_event.event_id}),
    )

    invariants = (
        check_boundedness((first, replay, history_control, no_duplicate_control)),
        check_replay(first, replay),
        _check_horizon_time_dynamics(
            (first, replay, history_control, no_duplicate_control), plan.events
        ),
        _merge_invariants(
            "history.no_self_excitation",
            (
                check_no_self_excitation(first, plan.events, no_duplicate_control),
                check_no_self_excitation(replay, plan.events, no_duplicate_control),
            ),
        ),
        _merge_invariants(
            "history.false_history_reversible",
            (
                _check_horizon_false_history(first, history_control, plan.events, manifest),
                _check_horizon_false_history(replay, history_control, plan.events, manifest),
            ),
        ),
    )
    first_record_hashes = tuple(_record_hash(item) for item in first.daily_captures)
    replay_record_hashes = tuple(_record_hash(item) for item in replay.daily_captures)
    history_control_record_hashes = tuple(
        _record_hash(item) for item in history_control.daily_captures
    )
    no_duplicate_control_record_hashes = tuple(
        _record_hash(item) for item in no_duplicate_control.daily_captures
    )
    semantic_fields = (
        plan.source_head,
        sha256_bytes(horizon_bytes),
        manifest_hash,
        plan.horizon_days,
        first.daily_digests,
        replay.daily_digests,
        first_record_hashes,
        replay_record_hashes,
        history_control_record_hashes,
        no_duplicate_control_record_hashes,
        invariants,
    )
    return LongHorizonCertification(
        source_head=plan.source_head,
        input_sha256=sha256_bytes(horizon_bytes),
        runtime_config_manifest_sha256=manifest_hash,
        virtual_horizon_days=plan.horizon_days,
        wall_clock_execution_seconds=perf_counter() - wall_started,
        first_run_daily_digests=first.daily_digests,
        replay_daily_digests=replay.daily_digests,
        first_run_record_hashes=first_record_hashes,
        replay_record_hashes=replay_record_hashes,
        history_control_run_record_hashes=history_control_record_hashes,
        no_duplicate_control_run_record_hashes=no_duplicate_control_record_hashes,
        invariants=invariants,
        semantic_sha256=sha256_bytes(canonical_json_bytes(semantic_fields)),
    )


def long_horizon_semantic_hash(result: LongHorizonCertification) -> str:
    """Recalculate semantic identity without wall time or durable root paths."""
    return sha256_bytes(
        canonical_json_bytes(
            (
                result.source_head,
                result.input_sha256,
                result.runtime_config_manifest_sha256,
                result.virtual_horizon_days,
                result.first_run_daily_digests,
                result.replay_daily_digests,
                result.first_run_record_hashes,
                result.replay_record_hashes,
                result.history_control_run_record_hashes,
                result.no_duplicate_control_run_record_hashes,
                result.invariants,
            )
        )
    )


def _run_in_empty_root(
    plan: CertificationPlan,
    durable_root: Path,
    repository_root: Path,
    manifest_path: Path,
    responses: tuple[str, ...],
    history_control_event_id: str | None = None,
    excluded_event_ids: frozenset[str] | None = None,
) -> HorizonRun:
    durable_root.mkdir(parents=True, exist_ok=True)

    def factory(inner_plan: CertificationPlan, clock):  # type: ignore[no-untyped-def]
        return build_composition(
            CertificationRuntimeConfig(
                repository_root=repository_root,
                manifest_path=manifest_path,
                manifest_sha256=inner_plan.runtime_config_manifest_sha256,
                durable_paths=DurablePaths.under(durable_root),
                clock=clock,
                certification_id=inner_plan.certification_id,
                agent=FakeAgent(responses),
            )
        )

    from mind_runtime.validation.horizon import HorizonRunner

    runner = HorizonRunner(factory)
    if history_control_event_id is not None:
        return runner._run_with_history_control(
            plan,
            history_control_event_id=history_control_event_id,
        )
    if excluded_event_ids is not None:
        return runner._run_with_excluded_events(
            plan,
            excluded_event_ids=excluded_event_ids,
        )
    return runner.run(plan)


def _check_horizon_time_dynamics(
    runs: tuple[HorizonRun, ...], events: tuple[SimulationEvent, ...]
) -> InvariantResult:
    event_days = {_event_capture_day(event) for event in events}
    results = tuple(
        check_registered_time_dynamics(run.daily_captures[day - 1], run.daily_captures[day], ())
        for run in runs
        for day in range(1, run.virtual_horizon_days + 1)
        if day not in event_days
    )
    return _merge_invariants("time.registered_dynamics", results)


def _check_horizon_false_history(
    run: HorizonRun,
    control_run: HorizonRun,
    events: tuple[SimulationEvent, ...],
    manifest: RuntimeConfigManifest,
) -> FalseHistoryInvariantResult:
    false_event = next(event for event in events if event.expected_path == "false_history")
    correction_event = next(
        event for event in events if event.expected_path == "authoritative_correction"
    )
    false_capture = _capture_for_event(run, false_event)
    false_capture_before = run.daily_captures[max(0, false_capture.virtual_day - 1)]
    correction_capture = _capture_for_event(run, correction_event)
    convergence_day = min(
        run.virtual_horizon_days,
        correction_capture.virtual_day + manifest.recovery_horizon_days,
    )
    convergence_capture = run.daily_captures[convergence_day]
    control_convergence_capture = control_run.daily_captures[convergence_day]
    false_trace = false_capture.records.transition_results[0].assessment_trace
    correction_trace = correction_capture.records.transition_results[0].assessment_trace
    control_correction_capture = _capture_for_event(control_run, correction_event)
    control_correction_trace = control_correction_capture.records.transition_results[
        0
    ].assessment_trace
    false_refs = _history_refs(false_event)
    state_direct_refs = tuple(
        ref
        for state in false_capture.records.canonical_states
        for ref in (*state.evidence_refs, *state.transition_refs)
        if ref in false_refs
    )
    prior_evidence_ids = {item.id for item, _ref in false_capture_before.records.evidence}
    prior_observation_ids = {item.id for item in false_capture_before.records.observations}
    direct_refs = (
        *state_direct_refs,
        *(
            item.id
            for item, _ref in false_capture.records.evidence
            if item.id not in prior_evidence_ids
        ),
        *(
            item.id
            for item in false_capture.records.observations
            if item.id not in prior_observation_ids
        ),
    )
    correction_evidence_ids = {item.id for item in correction_event.evidence}
    authoritative_refs = tuple(
        evidence.id
        for evidence, _interaction_id in correction_capture.records.evidence
        if evidence.id in correction_evidence_ids
        and evidence.authority_level is not AuthorityLevel.NONE
    )
    control_authoritative_refs = tuple(
        evidence.id
        for evidence, _interaction_id in control_correction_capture.records.evidence
        if evidence.id in correction_evidence_ids
        and evidence.authority_level is not AuthorityLevel.NONE
    )
    false_step = HistoryStepCapture(
        capture_ref=false_trace.trace_id,
        direct_state_write_refs=_unique(direct_refs),
        contribution_count=len(false_trace.contributions),
        authoritative_evidence_refs=(),
        trace_refs=_unique(
            (
                false_trace.trace_id,
                *false_trace.evidence_refs,
                *false_trace.history_refs,
                *(item.source_ref for item in false_trace.contributions),
            )
        ),
        supplied_history_refs=tuple(sorted(false_refs)),
        state_before_values=false_trace.state_before,
        state_values=_numeric_state_values(false_capture.records.canonical_states),
        contributions=_captured_contributions(false_trace),
        elapsed_days=0,
    )
    correction_step = HistoryStepCapture(
        capture_ref=correction_trace.trace_id,
        direct_state_write_refs=(),
        contribution_count=len(correction_trace.contributions),
        authoritative_evidence_refs=authoritative_refs,
        trace_refs=_unique(
            (
                correction_trace.trace_id,
                *correction_trace.evidence_refs,
                *correction_trace.history_refs,
                *(item.source_ref for item in correction_trace.contributions),
            )
        ),
        supplied_history_refs=tuple(sorted(_history_refs(correction_event))),
        state_before_values=correction_trace.state_before,
        state_values=_numeric_state_values(convergence_capture.records.canonical_states),
        contributions=_captured_contributions(correction_trace),
        elapsed_days=convergence_day - correction_capture.virtual_day,
    )
    control = HistoryStepCapture(
        capture_ref=(
            f"daily-record:control:{convergence_day}:{_record_hash(control_convergence_capture)}"
        ),
        direct_state_write_refs=(),
        contribution_count=len(control_correction_trace.contributions),
        authoritative_evidence_refs=control_authoritative_refs,
        trace_refs=_unique(
            (
                control_correction_trace.trace_id,
                *control_correction_trace.evidence_refs,
                *control_correction_trace.history_refs,
                *(item.source_ref for item in control_correction_trace.contributions),
            )
        ),
        supplied_history_refs=(),
        state_before_values=control_correction_trace.state_before,
        state_values=_numeric_state_values(control_convergence_capture.records.canonical_states),
        contributions=_captured_contributions(control_correction_trace),
        elapsed_days=convergence_day - control_correction_capture.virtual_day,
    )
    return check_false_history_reversible(
        false_step,
        correction_step,
        control,
        manifest.recovery_horizon_days,
        manifest.convergence_tolerance,
    )


def _merge_invariants(code: str, results: tuple[InvariantResult, ...]) -> InvariantResult:
    if not results:
        raise ValueError("at least one captured invariant result is required")
    return InvariantResult(
        code=code,
        passed=all(item.passed for item in results),
        observed="; ".join(item.observed for item in results),
        expected=results[0].expected,
        evidence_refs=_unique(tuple(ref for item in results for ref in item.evidence_refs)),
    )


def _captured_contributions(trace: AssessmentTrace) -> tuple[CapturedContribution, ...]:
    return tuple(
        CapturedContribution(
            dimension=item.dimension,
            source_kind=item.source_kind,
            source_ref=item.source_ref,
            amount=item.amount,
            applied=item.applied,
        )
        for item in trace.contributions
    )


def _applied_recovery_deltas(
    results: tuple[EmotionalTransitionResult, ...],
) -> dict[str, float]:
    """Sum the applied recovery contribution amounts per dimension."""
    deltas: dict[str, float] = {}
    for result in results:
        for contribution in result.assessment_trace.contributions:
            if contribution.applied and contribution.source_kind == "recovery":
                deltas[contribution.dimension] = deltas.get(contribution.dimension, 0.0) + float(
                    contribution.amount
                )
    return deltas


def _subtract_recovery(
    states: tuple[tuple[str, float], ...],
    deltas: dict[str, float],
) -> tuple[tuple[str, float], ...]:
    """Counterfactual: the treatment State minus the replay turn's registered
    recovery movement equals the no-duplicate control State."""
    return tuple((dimension, value - deltas.get(dimension, 0.0)) for dimension, value in states)


def _new_transition_results(
    before: HorizonDayCapture,
    after: HorizonDayCapture,
) -> tuple[EmotionalTransitionResult, ...]:
    prior_trace_ids = {
        result.assessment_trace.trace_id for result in before.records.transition_results
    }
    return tuple(
        result
        for result in after.records.transition_results
        if result.assessment_trace.trace_id not in prior_trace_ids
    )


def _captured_contributions_reconcile(
    state_before_values: tuple[tuple[str, float], ...],
    state_after_values: tuple[tuple[str, float], ...],
    contributions: tuple[CapturedContribution, ...],
    contribution_count: int,
) -> bool:
    before = dict(state_before_values)
    after = dict(state_after_values)
    if before.keys() != after.keys() or contribution_count != len(contributions):
        return False
    totals = {dimension: 0.0 for dimension in before}
    for contribution in contributions:
        if contribution.dimension not in totals:
            return False
        if contribution.applied:
            totals[contribution.dimension] += float(contribution.amount)
    return all(
        isclose(
            float(after[dimension]) - float(before[dimension]),
            totals[dimension],
            rel_tol=0.0,
            abs_tol=1e-12,
        )
        for dimension in before
    )


def _trace_reconciles_state_delta(
    before_capture: HorizonDayCapture,
    after_capture: HorizonDayCapture,
    trace: AssessmentTrace,
) -> bool:
    before = _numeric_state_values(before_capture.records.canonical_states)
    after = _numeric_state_values(after_capture.records.canonical_states)
    if dict(trace.state_before) != dict(before) or dict(trace.state_after) != dict(after):
        return False
    return _captured_contributions_reconcile(
        trace.state_before,
        trace.state_after,
        _captured_contributions(trace),
        len(trace.contributions),
    )


def _numeric_state_values(states: tuple[RuntimeState, ...]) -> tuple[tuple[str, float], ...]:
    return tuple(
        (state.dimension, float(state.value))
        for state in states
        if isinstance(state.value, (int, float)) and not isinstance(state.value, bool)
    )


def _event_capture_day(event: SimulationEvent) -> int:
    return event.at_offset.days + bool(event.at_offset.seconds or event.at_offset.microseconds)


def _current_source_head(repository_root: Path) -> str:
    return subprocess.run(
        ["git", "rev-parse", "--verify", "HEAD"],
        cwd=repository_root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(char in "0123456789abcdef" for char in value)


def _flatten_captures(
    captured: HorizonDayCapture | HorizonRun | Sequence[HorizonDayCapture | HorizonRun],
) -> tuple[HorizonDayCapture, ...]:
    if isinstance(captured, HorizonDayCapture):
        return (captured,)
    if isinstance(captured, HorizonRun):
        return captured.daily_captures
    return tuple(
        capture
        for item in captured
        for capture in ((item,) if isinstance(item, HorizonDayCapture) else item.daily_captures)
    )


def _definitions_by_key(definitions: tuple[StateDefinition, ...]) -> dict[str, StateDefinition]:
    result: dict[str, StateDefinition] = {}
    for definition in definitions:
        if definition.key in result:
            return {}
        result[definition.key] = definition
    return result


def _scalar_bounds(definition: StateDefinition) -> tuple[float, float] | None:
    bounds = definition.bounds
    if (
        not isinstance(bounds, tuple)
        or len(bounds) != 2
        or any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in bounds)
    ):
        return None
    lower, upper = (float(bounds[0]), float(bounds[1]))
    if not isfinite(lower) or not isfinite(upper) or lower > upper:
        return None
    return lower, upper


def _state_values(states: tuple[RuntimeState, ...]) -> dict[str, object]:
    return {state.dimension: state.value for state in states}


def _record_hash(capture: HorizonDayCapture) -> str:
    return sha256_bytes(
        canonical_json_bytes((capture.virtual_day, capture.captured_at, capture.records))
    )


def _capture_record_refs(captures: Sequence[HorizonDayCapture]) -> tuple[str, ...]:
    return tuple(
        f"daily-record:{capture.virtual_day}:{_record_hash(capture)}" for capture in captures
    )


def _capture_for_event(run: HorizonRun, event: SimulationEvent) -> HorizonDayCapture:
    day = _event_capture_day(event)
    return run.daily_captures[day]


def _history_refs(event: SimulationEvent) -> set[str]:
    history = event.historical_context
    if history is None:
        return set()
    refs = set(history.source_refs)
    refs.update(
        item.item_id
        for item in (*history.episodes, *history.stable_facts, *history.relationship_events)
    )
    for summary in history.pattern_summaries:
        refs.add(summary.summary_id)
        refs.update(summary.matched_refs)
    return refs


def _unique[T](values: Sequence[T]) -> tuple[T, ...]:
    return tuple(dict.fromkeys(values))
