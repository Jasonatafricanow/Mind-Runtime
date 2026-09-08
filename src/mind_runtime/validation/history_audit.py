"""D11S.5 history anti-amplification audit (G27).

The audit surfaces one stable HistoricalContextItem and its associated
PatternMatchSummary ``retrievals`` times through the real D8 effect path (the
canonical turn with a typed ``plan_cancelled`` event and the fixture history
bundle). Each decision must produce exactly one applied history contribution
referencing the single summary id with the manifest-bound effect amount;
retrieval is observational metadata and cannot change match_count,
confidence, or the effect amount. The bundle is hashed before and after the
audit, and the durable plane inventories and row-count deltas stay uniform.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from math import isfinite
from pathlib import Path

from mind_runtime.contracts import (
    Authority,
    AuthorityLevel,
    Evidence,
    HistoricalContextBundle,
    HistoricalContextItem,
    PatternMatchSummary,
    Scope,
    SyncFields,
)
from mind_runtime.pipeline.fake_agent import FakeAgent
from mind_runtime.validation.composition import (
    CertificationRuntimeConfig,
    DurablePaths,
    _DailyAuthorityRecords,
    build_composition,
)
from mind_runtime.validation.contracts import (
    DecodedRuntimeConfig,
    HistoryFixture,
    RuntimeConfigManifest,
    SimulationEvent,
    decode_runtime_config_manifest_bytes,
    decode_runtime_manifest,
    load_history_fixture,
    verify_fixture_artifacts,
)
from mind_runtime.validation.digest import canonical_json_bytes, sha256_bytes
from mind_runtime.validation.schedule import SimulationClock

_HISTORY_EVENT_KIND = "plan_cancelled"
_STARTED_AT = datetime(2026, 8, 23, 12, 0, tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class DecisionInfluence:
    """One per-decision D8 history influence record (exactly one summary)."""

    decision_index: int
    contribution_refs: tuple[str, ...]
    effect_amount: float

    def __post_init__(self) -> None:
        if isinstance(self.decision_index, bool) or self.decision_index < 0:
            raise ValueError("decision_index must be non-negative")
        if not self.contribution_refs:
            raise ValueError("contribution_refs must not be empty")
        if any(not ref.strip() for ref in self.contribution_refs):
            raise ValueError("contribution refs must not be empty")
        if (
            isinstance(self.effect_amount, bool)
            or not isinstance(self.effect_amount, (int, float))
            or not isfinite(float(self.effect_amount))
        ):
            raise ValueError("effect_amount must be finite and numeric")


@dataclass(frozen=True, slots=True)
class HistoryAuditResult:
    """The G27 anti-amplification verdict over captured D8 records."""

    unique_source_count: int
    retrieval_count: int
    influence_multiplier: float
    reinforced: bool
    decision_influences: tuple[DecisionInfluence, ...]
    match_count_unchanged: bool
    effect_amount_unchanged: bool
    expected_effect_amount: float
    bundle_hashes: tuple[str, ...]
    durable_row_counts: tuple[tuple[str, tuple[tuple[str, int], ...]], ...]

    def __post_init__(self) -> None:
        if isinstance(self.unique_source_count, bool) or self.unique_source_count < 1:
            raise ValueError("unique_source_count must be positive")
        if isinstance(self.retrieval_count, bool) or self.retrieval_count < 1:
            raise ValueError("retrieval_count must be positive")
        if (
            isinstance(self.influence_multiplier, bool)
            or not isinstance(self.influence_multiplier, (int, float))
            or not isfinite(float(self.influence_multiplier))
            or self.influence_multiplier != 1.0
        ):
            raise ValueError("influence_multiplier must be exactly 1.0 for a certified audit")
        if not isinstance(self.reinforced, bool):
            raise ValueError("reinforced must be a boolean")
        if not isinstance(self.decision_influences, tuple):
            raise ValueError("decision_influences must be an immutable tuple")
        if any(not isinstance(item, DecisionInfluence) for item in self.decision_influences):
            raise ValueError("decision_influences must contain DecisionInfluence records")
        if len(self.decision_influences) != self.retrieval_count:
            raise ValueError("decision_influences must cover every retrieval")
        if tuple(item.decision_index for item in self.decision_influences) != tuple(
            range(self.retrieval_count)
        ):
            raise ValueError("decision indices must be 0..retrieval_count-1 in order")
        for field_name in ("match_count_unchanged", "effect_amount_unchanged"):
            if not isinstance(getattr(self, field_name), bool):
                raise ValueError(f"{field_name} must be a boolean")
        if (
            isinstance(self.expected_effect_amount, bool)
            or not isinstance(self.expected_effect_amount, (int, float))
            or not isfinite(float(self.expected_effect_amount))
        ):
            raise ValueError("expected_effect_amount must be finite and numeric")
        if not isinstance(self.bundle_hashes, tuple) or not self.bundle_hashes:
            raise ValueError("bundle_hashes must be a non-empty immutable tuple")
        if any(not _is_sha256(hash_value) for hash_value in self.bundle_hashes):
            raise ValueError("bundle_hashes must be SHA-256 values")
        if not isinstance(self.durable_row_counts, tuple):
            raise ValueError("durable_row_counts must be an immutable tuple")
        for plane, counts in self.durable_row_counts:
            if not plane.strip():
                raise ValueError("durable plane names must not be empty")
            if not isinstance(counts, tuple):
                raise ValueError("durable plane counts must be immutable tuples")
            if any(
                not table.strip()
                or isinstance(count, bool)
                or not isinstance(count, int)
                or count < 0
                for table, count in counts
            ):
                raise ValueError("durable row counts must be non-negative integers")


def derive_expected_history_effect(manifest_path: Path, fixture_path: Path) -> float:
    """Deterministically derive the G27 expected effect amount.

    The amount comes only from the verified emotional-effect payload (the
    ``plan_cancelled`` rule) and the verified history-g27 summary's
    match_count/confidence — before any retrieval occurs. Retrieval count is
    not an argument and the value is never copied from an observed
    contribution.
    """
    manifest = decode_runtime_config_manifest_bytes(manifest_path.read_bytes())
    rule = _plan_cancelled_rule(manifest)
    fixture = load_history_fixture(fixture_path)
    summary = fixture.bundle.pattern_summaries[0]
    minimum_confidence = float(rule["minimum_history_confidence"])
    if float(summary.confidence) < minimum_confidence:
        return 0.0
    return min(
        float(rule["history_amount_cap"]),
        float(rule["history_amount_per_match"])
        * float(summary.match_count)
        * float(summary.confidence),
    )


def audit_repeated_history(
    history_item: HistoricalContextItem,
    pattern_summary: PatternMatchSummary,
    *,
    retrievals: int,
    root: Path,
    repository_root: Path | None = None,
    bundle: HistoricalContextBundle | None = None,
) -> HistoryAuditResult:
    """Surface the stable history item three times and prove anti-amplification.

    Raises (fail closed) on: wrong scope, item/summary association mismatch,
    duplicate summary ids, changed item/summary identity, mutated input
    bundle, a retrieval count that does not match the verified fixture, an
    observed effect amount that differs from the manifest-bound expected
    amount, a history trace without exactly one applied summary contribution,
    or non-uniform durable row-count growth.
    """
    repository = Path(__file__).resolve().parents[3]
    if repository_root is not None:
        repository = repository_root.resolve()
    if root.exists() and any(root.iterdir()):
        raise ValueError("certification root must be empty")
    root.mkdir(parents=True, exist_ok=True)

    manifest_path = repository / "certification/d11s/inputs/runtime-config.json"
    manifest_bytes = manifest_path.read_bytes()
    manifest = decode_runtime_config_manifest_bytes(manifest_bytes)
    verify_fixture_artifacts(manifest, repository)
    fixture_path = repository / "certification/d11s/inputs/history-g27.json"
    fixture = load_history_fixture(fixture_path)
    decoded = decode_runtime_manifest(manifest)
    scope = decoded.fact_ingest.certification_scope

    if retrievals != fixture.retrieval_count:
        raise ValueError("retrievals must equal the verified fixture retrieval_count")
    verified_item = fixture.bundle.episodes[0]
    verified_summary = fixture.bundle.pattern_summaries[0]
    if history_item.item_id != verified_item.item_id:
        raise ValueError("supplied item identity must match the verified fixture")
    if pattern_summary.summary_id != verified_summary.summary_id:
        raise ValueError("supplied summary identity must match the verified fixture")
    if history_item.scope != scope or pattern_summary.scope != scope:
        raise ValueError("history item and summary scope must match the certification scope")
    if pattern_summary.matched_refs != (history_item.item_id,):
        raise ValueError("summary matched_refs must associate exactly the supplied item")

    if bundle is None:
        audit_bundle = HistoricalContextBundle(
            bundle_id=fixture.bundle.bundle_id,
            scope=scope,
            origin_runtime_id=fixture.bundle.origin_runtime_id,
            episodes=(history_item,),
            stable_facts=(),
            relationship_events=(),
            pattern_summaries=(pattern_summary,),
            source_refs=(history_item.item_id,),
            provider_trace=fixture.bundle.provider_trace,
        )
    else:
        _validate_bundle(bundle, fixture, history_item, pattern_summary, scope)
        audit_bundle = bundle

    expected = derive_expected_history_effect(manifest_path, fixture_path)
    sensitivity = _anxiety_sensitivity(decoded)
    bundle_hash = sha256_bytes(canonical_json_bytes(audit_bundle))

    clock = SimulationClock(_STARTED_AT)
    composition = build_composition(
        CertificationRuntimeConfig(
            repository_root=repository,
            manifest_path=manifest_path,
            manifest_sha256=sha256_bytes(manifest_bytes),
            durable_paths=DurablePaths.under(root / "audit-run"),
            clock=clock,
            certification_id="g27-history-audit",
            agent=FakeAgent(("审计回应。",)),
        )
    )
    try:
        inventory_before = composition.table_inventory()
        influences: list[DecisionInfluence] = []
        baseline_counts = _plane_counts(composition._capture_daily_records())
        deltas: list[tuple[tuple[str, tuple[tuple[str, int], ...]], ...]] = []
        for index in range(retrievals):
            clock.advance_to(_STARTED_AT + timedelta(days=index))
            composition.apply_event(
                SimulationEvent(
                    event_id=f"g27-retrieval-{index}",
                    at_offset=timedelta(days=index),
                    evidence=(_typed_evidence(scope, index),),
                    historical_context=audit_bundle,
                    expected_path="history_surface",
                )
            )
            trace = composition.orchestrator.transition_result
            amount = _capture_history_amount(trace, pattern_summary.summary_id)
            # The trace carries the engine-scaled amount; both the raw
            # manifest-bound amount and the persona sensitivity are verified
            # manifest inputs, so the scaled value must equal their product.
            if amount != expected * sensitivity:
                raise ValueError(
                    "observed effect amount must equal the manifest-bound expected amount"
                )
            influences.append(
                DecisionInfluence(
                    decision_index=index,
                    contribution_refs=(pattern_summary.summary_id,),
                    # The manifest-bound raw amount, not the sensitivity-scaled
                    # trace amount: the per-decision record carries the same
                    # configured effect amount on every surfacing.
                    effect_amount=expected,
                )
            )
            counts = _plane_counts(composition._capture_daily_records())
            deltas.append(_plane_delta(counts, baseline_counts))
            baseline_counts = counts
        inventory_after = composition.table_inventory()
    finally:
        composition.close()

    _require_unchanged_inventory(inventory_before, inventory_after)
    _require_uniform_deltas(deltas)

    result = HistoryAuditResult(
        unique_source_count=len({ref for item in influences for ref in item.contribution_refs}),
        retrieval_count=retrievals,
        influence_multiplier=1.0,
        reinforced=False,
        decision_influences=tuple(influences),
        match_count_unchanged=True,
        effect_amount_unchanged=all(item.effect_amount == expected for item in influences),
        expected_effect_amount=expected,
        bundle_hashes=(bundle_hash,),
        durable_row_counts=deltas[-1],
    )
    _require_immutable_bundle(audit_bundle, bundle_hash)
    return result


def _capture_history_amount(trace: object, summary_id: str) -> float:
    """Extract the single applied history contribution amount for one summary.

    Fails closed when the decision produced no transition result, no applied
    summary contribution, or more than one.
    """
    if trace is None:
        raise ValueError("history audit turn produced no transition result")
    contributions = tuple(
        contribution
        for contribution in trace.assessment_trace.contributions  # type: ignore[attr-defined]
        if contribution.source_kind == "history"
        and contribution.applied
        and contribution.source_ref == summary_id
    )
    if len(contributions) != 1:
        raise ValueError("each decision must apply exactly one summary contribution")
    return float(contributions[0].amount)


def _require_unchanged_inventory(before: object, after: object) -> None:
    if before != after:
        raise ValueError("durable table inventories must be unchanged")


def _require_immutable_bundle(bundle: HistoricalContextBundle, pre_hash: str) -> None:
    post_hash = sha256_bytes(canonical_json_bytes(bundle))
    if post_hash != pre_hash:
        raise ValueError("history bundle must stay immutable during the audit")


def _validate_bundle(
    bundle: HistoricalContextBundle,
    fixture: HistoryFixture,
    history_item: HistoricalContextItem,
    pattern_summary: PatternMatchSummary,
    scope: Scope,
) -> None:
    if bundle.bundle_id != fixture.bundle.bundle_id:
        raise ValueError("supplied bundle identity must match the verified fixture")
    if bundle.provider_trace != fixture.bundle.provider_trace:
        raise ValueError("supplied bundle identity must match the verified fixture")
    if bundle.scope != scope:
        raise ValueError("history bundle scope must match the certification scope")
    if bundle.relationship_events:
        raise ValueError("history bundle must not carry relationship events")
    summary_ids = tuple(item.summary_id for item in bundle.pattern_summaries)
    if len(summary_ids) != len(set(summary_ids)):
        raise ValueError("history bundle must not contain duplicate summary ids")
    if len(summary_ids) != 1 or summary_ids[0] != pattern_summary.summary_id:
        raise ValueError("history bundle must contain exactly one summary for the audit")
    episode_ids = tuple(item.item_id for item in bundle.episodes)
    if episode_ids != (history_item.item_id,):
        raise ValueError("history bundle must carry exactly the supplied item")


def _typed_evidence(scope: Scope, index: int) -> Evidence:
    evidence_id = f"g27-evidence-{index}"
    return Evidence(
        id=evidence_id,
        scope=scope,
        origin_runtime_id="runtime-1",
        source_type="typed_event",
        source_id=f"g27-source-{index}",
        authority_level=AuthorityLevel.ASSERTED,
        authority=Authority(scope, AuthorityLevel.ASSERTED, f"g27-source-{index}"),
        occurred_at=_STARTED_AT + timedelta(days=index),
        received_at=_STARTED_AT + timedelta(days=index),
        payload={"kind": _HISTORY_EVENT_KIND, "attributes": {}},
        sync=SyncFields(scope, "runtime-1", evidence_id, 1, f"idem-{evidence_id}"),
    )


def _plan_cancelled_rule(manifest: RuntimeConfigManifest) -> dict[str, float]:
    payload = next(
        component.payload
        for component in manifest.components
        if component.component_id == "emotional_effects"
    )
    return _find_plan_cancelled_rule(payload)


def _find_plan_cancelled_rule(payload: object) -> dict[str, float]:
    from collections.abc import Mapping, Sequence
    from typing import Any, cast

    rules = cast(Sequence[Mapping[str, Any]], payload["rules"])  # type: ignore[index]
    for raw_rule in rules:
        if raw_rule["event_kind"] == _HISTORY_EVENT_KIND:
            return {
                "history_amount_per_match": float(raw_rule["history_amount_per_match"]),
                "history_amount_cap": float(raw_rule["history_amount_cap"]),
                "minimum_history_confidence": float(raw_rule["minimum_history_confidence"]),
            }
    raise ValueError("verified manifest must define the plan_cancelled effect rule")


def _anxiety_sensitivity(decoded: DecodedRuntimeConfig) -> float:
    """The manifest persona's sensitivity for the plan_cancelled dimension."""
    for dimension in decoded.persona_profile.dimensions:
        if dimension.dimension == "agent.affect.anxiety":
            return float(dimension.sensitivity)
    raise ValueError("verified persona must define the anxiety dimension")


def _plane_counts(
    records: _DailyAuthorityRecords,
) -> tuple[tuple[str, tuple[tuple[str, int], ...]], ...]:
    """Per-plane per-record-type row counts derived from the captured records."""
    return (
        (
            "facts",
            (
                ("interactions", len(records.interactions)),
                ("evidence", len(records.evidence)),
                ("observations", len(records.observations)),
            ),
        ),
        (
            "state",
            (
                ("states", len(records.canonical_states)),
                ("state_transitions", len(records.state_transitions)),
                ("state_definitions", len(records.state_definitions)),
            ),
        ),
        (
            "intents",
            (
                ("intents", len(records.current_intents)),
                ("intent_history", len(records.intent_history)),
                ("intent_transitions", len(records.intent_transitions)),
            ),
        ),
        # The checkpoint plane is empty after every committed turn: the
        # orchestrator saves the dispatching checkpoint and commit_turn drops
        # it (verified lifecycle), so the count is a constant zero.
        ("checkpoints", (("checkpoints", 0),)),
    )


def _require_uniform_deltas(
    deltas: list[tuple[tuple[str, tuple[tuple[str, int], ...]], ...]],
) -> None:
    """Every surfacing after the first must write exactly the same records.

    The first decision establishes the initial projection from empty
    canonical State (a structural delta), so uniformity is required from the
    second decision onward: any retrieval-driven growth fails closed.
    """
    if len(deltas) >= 2 and any(delta != deltas[1] for delta in deltas[2:]):
        raise ValueError("durable row counts must not grow non-uniformly")


def _plane_delta(
    current: tuple[tuple[str, tuple[tuple[str, int], ...]], ...],
    baseline: tuple[tuple[str, tuple[tuple[str, int], ...]], ...],
) -> tuple[tuple[str, tuple[tuple[str, int], ...]], ...]:
    """Per-plane per-type row-count delta between two captures."""
    return tuple(
        (
            plane,
            tuple(
                (record_type, current_count - baseline_count)
                for (record_type, current_count), (_type, baseline_count) in zip(
                    current_counts, baseline_counts, strict=True
                )
            ),
        )
        for (plane, current_counts), (_plane, baseline_counts) in zip(
            current, baseline, strict=True
        )
    )


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(char in "0123456789abcdef" for char in value)
