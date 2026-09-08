"""D11S.6 fresh-composition restart certification tests (G12)."""

from __future__ import annotations

import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest

import mind_runtime.validation.restart as restart_subject
from mind_runtime.contracts import DeliveryStatus, HistoricalContextBundle, ScopeDomain
from mind_runtime.pipeline.checkpoints import (
    SqliteCheckpointStore,
)
from mind_runtime.pipeline.checkpoints import (
    recovery_decision as actual_recovery_decision,
)
from mind_runtime.validation import RestartFixture, load_restart_fixture
from mind_runtime.validation.composition import DurablePaths
from mind_runtime.validation.digest import (
    canonical_json_bytes as actual_canonical_json_bytes,
)
from mind_runtime.validation.digest import (
    sha256_bytes as actual_sha256_bytes,
)
from mind_runtime.validation.restart import (
    RestartCertificationResult,
    _capture_canonical_runtime,
    _highest_states,
    certify_restart,
)

ROOT = Path(__file__).resolve().parents[2]
RESTART_FIXTURE = ROOT / "certification/d11s/inputs/restart-g12.json"


def make_restart_plan() -> RestartFixture:
    return load_restart_fixture(RESTART_FIXTURE)


def test_fresh_composition_restores_all_existing_durable_planes(tmp_path: Path) -> None:
    """Removing any close/reopen load or digest comparison must fail this test."""
    result = certify_restart(
        make_restart_plan(),
        DurablePaths.under(tmp_path),
        repository_root=ROOT,
    )

    assert result.fact_digest_before == result.fact_digest_after
    assert result.state_digest_before == result.state_digest_after
    assert result.canonical_state_digest_before == result.canonical_state_digest_after
    assert result.intent_digest_before == result.intent_digest_after
    assert result.checkpoint_digest_before == result.checkpoint_digest_after
    assert result.recovery_decision_before == result.recovery_decision_after
    assert result.history_hash_before == result.history_hash_after
    assert result.recovery_decision_after.action == "delivery_unknown"
    assert result.canonical_states_after == result.restored_states


def test_restart_restores_relationship_scope_and_highest_state_versions(
    tmp_path: Path,
) -> None:
    """Dropping relationship state or selecting an older version must fail."""
    result = certify_restart(make_restart_plan(), DurablePaths.under(tmp_path))

    relationship = tuple(
        state for state in result.restored_states if state.scope.domain is ScopeDomain.RELATIONSHIP
    )
    assert len(relationship) == 1
    assert relationship[0].scope.relationship_id == "relationship-user-1-kayla"
    assert relationship[0].dimension == "relationship.trust"
    assert relationship[0].version == 2
    assert tuple((state.dimension, state.version) for state in result.restored_states) == (
        ("agent.affect.anxiety", 2),
        ("relationship.trust", 2),
        ("user.sleep.phase", 1),
    )


def test_restart_restores_due_deferred_intent_history_and_lineage(tmp_path: Path) -> None:
    """Loading only the current Intent without append-only history must fail."""
    result = certify_restart(make_restart_plan(), DurablePaths.under(tmp_path))

    assert tuple(
        (intent.status.value, intent.sync.version) for intent in result.intent_history
    ) == (
        ("candidate", 1),
        ("deferred", 2),
    )
    assert result.current_intent.status.value == "deferred"
    assert result.current_intent.due_at is not None
    assert result.current_intent.due_at.isoformat() == "2026-01-15T08:00:00+00:00"
    assert result.intent_transitions[0].from_status.value == "candidate"
    assert result.intent_transitions[0].to_status.value == "deferred"


@pytest.mark.parametrize(
    ("delivery_status", "expected_action"),
    [
        (DeliveryStatus.SENT, "reconcile_complete"),
        (DeliveryStatus.UNSENT, "safe_abort"),
        (DeliveryStatus.UNKNOWN, "delivery_unknown"),
    ],
)
def test_restart_preserves_checkpoint_delivery_tristate(
    delivery_status: DeliveryStatus,
    expected_action: str,
    tmp_path: Path,
) -> None:
    """Normalizing UNKNOWN to UNSENT or losing SENT must fail this matrix."""
    fixture = make_restart_plan()
    fixture = replace(
        fixture, checkpoint=replace(fixture.checkpoint, delivery_status=delivery_status)
    )

    result = certify_restart(fixture, DurablePaths.under(tmp_path))

    assert result.recovery_decision_before.delivery_status is delivery_status
    assert result.recovery_decision_after.delivery_status is delivery_status
    assert result.recovery_decision_after.action == expected_action
    assert result.restored_checkpoint.action_id == "action-restart-g12-1"


def test_certification_closes_every_sqlite_store_and_adds_no_memory_planes(
    tmp_path: Path,
) -> None:
    """Leaking a connection or creating unauthorized durability must fail."""
    paths = DurablePaths.under(tmp_path)
    result = certify_restart(make_restart_plan(), paths)

    assert result.receipt_count_before == result.receipt_count_after == 0
    assert not (tmp_path / "receipts.sqlite").exists()
    assert not (tmp_path / "memory.sqlite").exists()
    for path in (paths.facts_db, paths.state_db, paths.intents_db, paths.checkpoints_db):
        renamed = path.with_suffix(".closed")
        path.rename(renamed)
        renamed.rename(path)


def test_history_is_read_only_and_not_materialized_into_a_database(tmp_path: Path) -> None:
    """A history write, touch, or reconstructed bundle must change this evidence."""
    fixture = make_restart_plan()
    result = certify_restart(fixture, DurablePaths.under(tmp_path))

    assert result.history_hash_before == result.history_hash_after
    assert result.restored_history == fixture.historical_context
    assert tuple(tmp_path.glob("*history*.sqlite")) == ()


def test_conflicting_equal_version_state_fails_closed(tmp_path: Path) -> None:
    """A corrupt durable state set must not choose a winner by insertion order."""
    fixture = make_restart_plan()
    original = fixture.states[-1]
    duplicate = replace(
        original,
        state_id=f"{original.state_id}-conflict",
        transition_refs=(),
        sync=replace(
            original.sync,
            object_id=f"{original.state_id}-conflict",
            idempotency_key=f"{original.sync.idempotency_key}-conflict",
        ),
    )
    fixture = replace(fixture, states=fixture.states + (duplicate,))

    with pytest.raises(ValueError, match="ambiguous current State"):
        certify_restart(fixture, DurablePaths.under(tmp_path))


def test_missing_durable_database_fails_closed(tmp_path: Path) -> None:
    """A missing plane must not be silently recreated during restart loading."""
    from mind_runtime.validation.restart import _capture_reopened_records

    paths = DurablePaths.under(tmp_path)
    with pytest.raises(ValueError, match="missing durable database"):
        _capture_reopened_records(make_restart_plan(), paths)


@pytest.mark.parametrize("prior_first", [True, False])
def test_highest_legal_state_version_wins_independent_of_row_order(
    prior_first: bool,
    tmp_path: Path,
) -> None:
    """Selecting the first row instead of the highest version must fail."""
    fixture = make_restart_plan()
    current = fixture.states[1]
    prior = replace(
        fixture.state_transitions[0].from_state,
        state_id="restart-g12-agent-state-v1",
        sync=replace(
            fixture.state_transitions[0].from_state.sync,
            object_id="restart-g12-agent-state-v1",
            idempotency_key="idem-restart-g12-agent-state-row-v1",
        ),
    )
    states = (prior,) + fixture.states if prior_first else fixture.states + (prior,)
    fixture = replace(fixture, states=states)

    result = certify_restart(fixture, DurablePaths.under(tmp_path))

    restored = next(
        state for state in result.restored_states if state.dimension == current.dimension
    )
    assert restored == current


def test_result_contract_rejects_non_certified_values(tmp_path: Path) -> None:
    """A caller cannot construct a successful-looking result from mismatched evidence."""
    result = certify_restart(make_restart_plan(), DurablePaths.under(tmp_path))
    assert isinstance(result, RestartCertificationResult)

    with pytest.raises(ValueError, match="SHA-256"):
        replace(result, fact_digest_before="bad")
    with pytest.raises(ValueError, match="SHA-256"):
        replace(result, fact_digest_before=1)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="must equal"):
        replace(result, fact_digest_after="0" * 64)
    with pytest.raises(ValueError, match="recovery decision"):
        replace(
            result,
            recovery_decision_after=replace(
                result.recovery_decision_after,
                action="wrong",
            ),
        )
    with pytest.raises(ValueError, match="ActionReceipt"):
        replace(result, receipt_count_after=1)


def test_certification_rejects_wrong_types_and_non_fresh_paths(tmp_path: Path) -> None:
    paths = DurablePaths.under(tmp_path)
    with pytest.raises(ValueError, match="RestartFixture"):
        certify_restart(object(), paths)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="DurablePaths"):
        certify_restart(make_restart_plan(), object())  # type: ignore[arg-type]

    paths.facts_db.parent.mkdir(parents=True, exist_ok=True)
    paths.facts_db.touch()
    with pytest.raises(ValueError, match="fresh durable paths"):
        certify_restart(make_restart_plan(), paths)


def test_fixture_state_definition_cannot_conflict_with_verified_manifest(
    tmp_path: Path,
) -> None:
    fixture = make_restart_plan()
    conflicting = replace(
        fixture.state_definitions[1],
        dynamics_policy="conflicting_policy",
    )
    fixture = replace(
        fixture,
        state_definitions=(
            fixture.state_definitions[0],
            conflicting,
            *fixture.state_definitions[2:],
        ),
    )

    with pytest.raises(ValueError, match="conflicts with the verified runtime manifest"):
        certify_restart(fixture, DurablePaths.under(tmp_path))


@pytest.mark.parametrize("forbidden_name", ["receipts.sqlite", "memory.sqlite"])
def test_certification_rejects_unauthorized_durable_planes(
    forbidden_name: str,
    tmp_path: Path,
) -> None:
    (tmp_path / forbidden_name).touch()

    with pytest.raises(ValueError, match="unauthorized durable plane"):
        certify_restart(make_restart_plan(), DurablePaths.under(tmp_path))


def test_duplicate_fact_admission_fails_closed(tmp_path: Path) -> None:
    fixture = make_restart_plan()
    evidence = fixture.evidence[0]
    second = replace(
        evidence,
        id="restart-g12-evidence-2",
        source_id="restart-g12-user-source-2",
        authority=replace(evidence.authority, source_id="restart-g12-user-source-2"),
        sync=replace(
            evidence.sync,
            object_id="restart-g12-evidence-2",
            idempotency_key="idem-restart-g12-evidence-2",
        ),
    )
    fixture = replace(fixture, evidence=fixture.evidence + (second,))

    with pytest.raises(ValueError, match="fact admission"):
        certify_restart(fixture, DurablePaths.under(tmp_path))


def test_duplicate_state_storage_identity_fails_closed(tmp_path: Path) -> None:
    fixture = make_restart_plan()
    state = fixture.states[0]
    duplicate = replace(state, dimension="user.sleep.other")
    fixture = replace(fixture, states=fixture.states + (duplicate,))

    with pytest.raises(ValueError, match="uniquely durable"):
        certify_restart(fixture, DurablePaths.under(tmp_path))


def test_missing_intent_transition_fails_closed(tmp_path: Path) -> None:
    fixture = replace(make_restart_plan(), intent_transitions=())

    with pytest.raises(ValueError, match="exact transition"):
        certify_restart(fixture, DurablePaths.under(tmp_path))


def test_multiple_intent_identities_fail_closed(tmp_path: Path) -> None:
    fixture = make_restart_plan()
    first = fixture.intent_history[0]
    second = replace(
        first,
        intent_id="restart-g12-intent-2",
        sync=replace(
            first.sync,
            object_id="restart-g12-intent-2",
            idempotency_key="idem-restart-g12-intent-2-v1",
        ),
    )
    fixture = replace(fixture, intent_history=fixture.intent_history + (second,))

    with pytest.raises(ValueError, match="exactly one Intent"):
        certify_restart(fixture, DurablePaths.under(tmp_path))


def test_missing_checkpoint_row_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(SqliteCheckpointStore, "save", lambda *_args: None)

    with pytest.raises(ValueError, match="checkpoint must remain durable"):
        certify_restart(make_restart_plan(), DurablePaths.under(tmp_path))


def test_changed_plane_digest_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def original(value: object) -> str:
        return actual_sha256_bytes(actual_canonical_json_bytes(value))

    calls = 0

    def changed_second_digest(value: object) -> str:
        nonlocal calls
        calls += 1
        return "0" * 64 if calls == 2 else original(value)

    monkeypatch.setattr(restart_subject, "_digest", changed_second_digest)
    with pytest.raises(ValueError, match="fact durable plane"):
        certify_restart(make_restart_plan(), DurablePaths.under(tmp_path))


def test_one_time_data_loss_during_first_restart_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The pre-close seed snapshot must not be replaced by a reopened snapshot."""
    paths = DurablePaths.under(tmp_path)
    original = _capture_canonical_runtime
    calls = 0

    def delete_evidence_after_first_reopen(plan, durable_paths, repository):  # type: ignore[no-untyped-def]
        nonlocal calls
        captured = original(plan, durable_paths, repository)
        calls += 1
        if calls == 1:
            with sqlite3.connect(paths.facts_db) as connection:
                connection.execute("DELETE FROM evidence")
        return captured

    monkeypatch.setattr(
        restart_subject,
        "_capture_canonical_runtime",
        delete_evidence_after_first_reopen,
    )

    with pytest.raises(ValueError, match="fact durable plane changed across restart"):
        certify_restart(make_restart_plan(), paths)


def test_changed_recovery_decision_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = actual_recovery_decision
    calls = 0

    def changed_second_recovery(checkpoint):  # type: ignore[no-untyped-def]
        nonlocal calls
        calls += 1
        result = original(checkpoint)
        return replace(result, action="wrong") if calls == 2 else result

    monkeypatch.setattr(restart_subject, "recovery_decision", changed_second_recovery)
    with pytest.raises(ValueError, match="recovery decision changed"):
        certify_restart(make_restart_plan(), DurablePaths.under(tmp_path))


def test_changed_history_hash_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = actual_canonical_json_bytes
    calls = 0

    def changed_second_history(value: object) -> bytes:
        nonlocal calls
        encoded = original(value)
        if isinstance(value, HistoricalContextBundle):
            calls += 1
            if calls == 2:
                return encoded + b"changed"
        return encoded

    monkeypatch.setattr(restart_subject, "canonical_json_bytes", changed_second_history)
    with pytest.raises(ValueError, match="read-only history changed"):
        certify_restart(make_restart_plan(), DurablePaths.under(tmp_path))


def test_highest_state_selection_ignores_a_later_lower_version() -> None:
    fixture = make_restart_plan()
    current = fixture.states[1]
    prior = replace(
        fixture.state_transitions[0].from_state,
        state_id="restart-g12-agent-state-later-v1",
        sync=replace(
            fixture.state_transitions[0].from_state.sync,
            object_id="restart-g12-agent-state-later-v1",
            idempotency_key="idem-restart-g12-agent-state-later-v1",
        ),
    )

    selected = _highest_states((current, prior))

    assert selected == (current,)


def test_canonical_runtime_rejects_state_selection_mismatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = _highest_states
    calls = 0

    def changed_expected(states):  # type: ignore[no-untyped-def]
        nonlocal calls
        calls += 1
        return () if calls == 3 else original(states)

    monkeypatch.setattr(restart_subject, "_highest_states", changed_expected)
    with pytest.raises(ValueError, match="exact highest-version State"):
        certify_restart(make_restart_plan(), DurablePaths.under(tmp_path))


def test_canonical_recovery_change_between_compositions_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = _capture_canonical_runtime
    calls = 0

    def changed_second(plan, paths, repository):  # type: ignore[no-untyped-def]
        nonlocal calls
        calls += 1
        captured = original(plan, paths, repository)
        if calls == 2:
            return replace(captured, recovery=replace(captured.recovery, action="wrong"))
        return captured

    monkeypatch.setattr(restart_subject, "_capture_canonical_runtime", changed_second)
    with pytest.raises(ValueError, match="canonical recovery decision changed"):
        certify_restart(make_restart_plan(), DurablePaths.under(tmp_path))


def test_canonical_recovery_must_equal_durable_checkpoint_decision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = _capture_canonical_runtime

    def changed_recovery(plan, paths, repository):  # type: ignore[no-untyped-def]
        captured = original(plan, paths, repository)
        return replace(captured, recovery=replace(captured.recovery, action="wrong"))

    monkeypatch.setattr(restart_subject, "_capture_canonical_runtime", changed_recovery)
    with pytest.raises(ValueError, match="canonical recovery must equal"):
        certify_restart(make_restart_plan(), DurablePaths.under(tmp_path))
