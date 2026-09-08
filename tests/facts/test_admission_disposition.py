"""ADR-0009 Phase 1 contract tests: factual admission dispositions.

The factual plane owns idempotency at the canonical turn boundary. These
tests freeze the NEW / REPAIRED / REPLAY / conflict semantics decided by the
durable backend (never inferred from IDs, payload text, or fixtures) and the
atomic arbitration between stale-cache service instances over one backend.
"""

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from mind_runtime.contracts import Evidence, Interaction, Observation, Scope
from mind_runtime.facts.persistence import SqliteFactBackend
from mind_runtime.facts.ports import FactAdmissionDisposition, FactAdmissionResult
from mind_runtime.facts.service import FactAdmissionConflictError, FactIngestService
from mind_runtime.facts.validators import AuthorityError, OwnershipError
from tests.golden.fixtures.common import make_evidence, make_scope
from tests.support.fake_clock import FakeClock

NOW = datetime(2026, 8, 23, 16, 0, tzinfo=UTC)


def make_service(path: str | Path | None = None) -> FactIngestService:
    backend = SqliteFactBackend(path) if path is not None else None
    return FactIngestService(clock=FakeClock(NOW), backend=backend)


def admit(
    service: FactIngestService, evidence: Evidence, *, interaction_id: str = "interaction-1"
) -> FactAdmissionResult:
    return service.admit(
        evidence,
        interaction_id=interaction_id,
        writing_runtime="runtime-1",
        writing_persona_id=None,
    )


def test_case1_first_admission_is_new_and_persists_one_pair(tmp_path: Path) -> None:
    path = tmp_path / "facts.db"
    service = make_service(path)
    evidence = make_evidence(text="我刚睡醒")
    result = admit(service, evidence)
    assert result.disposition is FactAdmissionDisposition.NEW
    assert result.observation.evidence_refs == (evidence.id,)
    assert service.evidence.count() == 1
    assert service.observations.count() == 1
    conn = sqlite3.connect(path)
    try:
        assert conn.execute("SELECT COUNT(*) FROM evidence").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM observations").fetchone()[0] == 1
    finally:
        conn.close()


def test_case2_identical_in_memory_replay_is_replay_and_keeps_identity() -> None:
    service = make_service()
    evidence = make_evidence(text="我刚睡醒")
    first = admit(service, evidence)
    assert first.disposition is FactAdmissionDisposition.NEW
    second = admit(service, evidence)
    assert second.disposition is FactAdmissionDisposition.REPLAY
    # The original immutable Observation identity is preserved; a freshly
    # constructed current-interaction Observation never masquerades as replay.
    assert second.observation == first.observation
    assert second.observation.interaction_id == "interaction-1"
    assert service.observations.count() == 1
    assert service.evidence.count() == 1


def test_case3_identical_replay_after_sqlite_restart_is_replay(tmp_path: Path) -> None:
    path = tmp_path / "facts.db"
    service = make_service(path)
    evidence = make_evidence(text="我刚睡醒")
    assert admit(service, evidence).disposition is FactAdmissionDisposition.NEW
    restarted = make_service(path)
    result = admit(restarted, evidence)
    assert result.disposition is FactAdmissionDisposition.REPLAY
    assert result.observation.interaction_id == "interaction-1"
    assert restarted.observations.count() == 1


def test_case4_missing_observation_repairs_once_then_replays(tmp_path: Path) -> None:
    path = tmp_path / "facts.db"
    service = make_service(path)
    evidence = make_evidence(text="我刚睡醒", received_at=NOW - timedelta(hours=1))
    assert admit(service, evidence).disposition is FactAdmissionDisposition.NEW
    # Crash window: evidence row survives, derived observation row is gone.
    conn = sqlite3.connect(path)
    conn.execute("DELETE FROM observations")
    conn.commit()
    conn.close()
    restarted = make_service(path)
    assert restarted.evidence.count() == 1
    assert restarted.observations.count() == 0
    # Repair binds the ORIGINAL admission identity, not the repair attempt:
    # the repair runs under a different interaction, but the repaired
    # Observation keeps the durable original provenance Interaction ID and
    # the immutable Evidence.received_at.
    repaired = admit(restarted, evidence, interaction_id="interaction-2")
    assert repaired.disposition is FactAdmissionDisposition.REPAIRED
    assert repaired.observation.interaction_id == "interaction-1"
    assert repaired.observation.observed_at == evidence.received_at
    assert restarted.observations.count() == 1
    assert restarted.evidence.count() == 1
    # The next admission of the same evidence is REPLAY.
    again = admit(restarted, evidence, interaction_id="interaction-3")
    assert again.disposition is FactAdmissionDisposition.REPLAY
    assert again.observation == repaired.observation
    assert restarted.observations.count() == 1


def test_case5_stale_cache_services_share_one_backend_idempotently(
    tmp_path: Path,
) -> None:
    path = tmp_path / "facts.db"
    evidence = make_evidence(text="我刚睡醒")
    # Both instances are constructed BEFORE any admission: their caches are
    # stale at the same starting point. The backend transaction must choose
    # exactly one winner.
    first = make_service(path)
    second = make_service(path)
    first_result = admit(first, evidence)
    second_result = admit(second, evidence)
    winners = [
        result.disposition
        for result in (first_result, second_result)
        if result.disposition is FactAdmissionDisposition.NEW
    ]
    losers = [
        result.disposition
        for result in (first_result, second_result)
        if result.disposition is FactAdmissionDisposition.REPLAY
    ]
    assert len(winners) == 1
    assert len(losers) == 1
    # The loser returns the backend-authoritative stored Observation, and the
    # stored pair is byte-identical for both instances.
    assert second_result.observation == first_result.observation
    assert first_result.observation.interaction_id == "interaction-1"
    conn = sqlite3.connect(path)
    try:
        assert conn.execute("SELECT COUNT(*) FROM evidence").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM observations").fetchone()[0] == 1
    finally:
        conn.close()
    # A result where both instances report NEW would be a failure even when
    # the final row count is one; the assertions above already forbid it.


def test_case5b_stale_cache_repair_arbitration_is_single_winner(
    tmp_path: Path,
) -> None:
    path = tmp_path / "facts.db"
    evidence = make_evidence(text="我刚睡醒")
    service = make_service(path)
    assert admit(service, evidence).disposition is FactAdmissionDisposition.NEW
    conn = sqlite3.connect(path)
    conn.execute("DELETE FROM observations")
    conn.commit()
    conn.close()
    # Both repairers start from the same stale state (evidence cached, no
    # observation): exactly one wins REPAIRED, the other must see REPLAY.
    first = make_service(path)
    second = make_service(path)
    first_result = admit(first, evidence)
    second_result = admit(second, evidence)
    repaired = [
        r
        for r in (first_result, second_result)
        if r.disposition is FactAdmissionDisposition.REPAIRED
    ]
    replayed = [
        r for r in (first_result, second_result) if r.disposition is FactAdmissionDisposition.REPLAY
    ]
    assert len(repaired) == 1
    assert len(replayed) == 1
    assert first_result.observation == second_result.observation
    conn = sqlite3.connect(path)
    try:
        assert conn.execute("SELECT COUNT(*) FROM evidence").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM observations").fetchone()[0] == 1
    finally:
        conn.close()


def test_case6_assistant_and_wrong_owner_still_fail_closed() -> None:
    service = make_service()
    assistant = make_evidence(
        text="感觉你有点累。", source_id="assistant-1", source_type="assistant_message"
    )
    with pytest.raises(AuthorityError, match="assistant"):
        admit(service, assistant)
    assert service.observations.count() == 0
    # Evidence is still retained for independent auditability.
    assert service.evidence.count() == 1
    kayla_scope = make_scope(user_id="user-kayla")
    from mind_runtime.contracts import Scope, ScopeDomain

    kayla_scope = Scope(domain=ScopeDomain.AGENT, agent_id="kayla", persona_id="persona-kayla")
    evidence = make_evidence(text="kayla affect write", scope=kayla_scope)
    with pytest.raises(OwnershipError, match="cannot write"):
        service.admit(
            evidence,
            interaction_id="interaction-1",
            writing_runtime="lara",
            writing_persona_id="persona-kayla",
        )
    assert service.observations.count() == 0


def test_case7_same_scope_id_different_bytes_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "facts.db"
    service = make_service(path)
    original = make_evidence(text="我刚睡醒", evidence_id="evidence-1")
    assert admit(service, original).disposition is FactAdmissionDisposition.NEW
    # Same (scope, id) but a different payload: immutable bytes differ.
    conflicting = make_evidence(text="我睡不着", evidence_id="evidence-1")
    with pytest.raises(FactAdmissionConflictError, match="immutable bytes"):
        admit(service, conflicting)
    # After restart the stored row is still authoritative and the conflict
    # still fails closed.
    restarted = make_service(path)
    with pytest.raises(FactAdmissionConflictError, match="immutable bytes"):
        admit(restarted, conflicting)
    assert restarted.evidence.count() == 1
    assert restarted.observations.count() == 1
    assert restarted.observations.all()[0].value == {"text": "我刚睡醒"}


def test_case8_orphan_observation_fails_closed_atomically(tmp_path: Path) -> None:
    path = tmp_path / "facts.db"
    service = make_service(path)
    evidence = make_evidence(text="hello")
    assert admit(service, evidence).disposition is FactAdmissionDisposition.NEW
    # Impossible partial pair: the observation row exists without its
    # evidence row. This is never reinterpreted as replay and never healed
    # by fabricating Evidence history.
    conn = sqlite3.connect(path)
    conn.execute("DELETE FROM evidence")
    conn.commit()
    conn.close()
    restarted = make_service(path)
    assert restarted.evidence.count() == 0
    assert restarted.observations.count() == 1
    with pytest.raises(FactAdmissionConflictError, match="observation"):
        admit(restarted, evidence)
    # Atomic fail-closed: no rows were written by the failed admission.
    conn = sqlite3.connect(path)
    try:
        assert conn.execute("SELECT COUNT(*) FROM evidence").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM observations").fetchone()[0] == 1
    finally:
        conn.close()


# --- arbitration edge cases: lost writes re-read the backend (ADR-0009 §5) ---


class ScriptedObservationBackend:
    """FactBackend wrapper scripting save_observation outcomes for races."""

    def __init__(
        self,
        backend: SqliteFactBackend,
        *,
        save_observation_outcomes: tuple[bool, ...] = (True,),
    ) -> None:
        self._backend = backend
        self._save_outcomes = list(save_observation_outcomes)

    def load_interactions(self) -> tuple[Interaction, ...]:
        return self._backend.load_interactions()

    def save_interaction(self, interaction: Interaction) -> None:
        self._backend.save_interaction(interaction)

    def load_evidence(self) -> tuple[tuple[Evidence, str], ...]:
        return self._backend.load_evidence()

    def save_evidence(self, evidence: Evidence, *, interaction_id: str) -> bool:
        return self._backend.save_evidence(evidence, interaction_id=interaction_id)

    def load_observations(self) -> tuple[Observation, ...]:
        return self._backend.load_observations()

    def save_observation(self, observation: Observation) -> bool:
        if self._save_outcomes:
            return self._save_outcomes.pop(0)
        return True

    def find_evidence(self, scope: Scope, evidence_id: str) -> tuple[Evidence, str] | None:
        return self._backend.find_evidence(scope, evidence_id)

    def find_observation(self, scope: Scope, observation_id: str) -> Observation | None:
        return self._backend.find_observation(scope, observation_id)

    def save_admission(
        self, evidence: Evidence, *, interaction_id: str, observation: Observation
    ) -> bool:
        return self._backend.save_admission(
            evidence, interaction_id=interaction_id, observation=observation
        )


def test_arbitration_orphan_pair_after_lost_write_fails_closed(tmp_path: Path) -> None:
    """A lost save_admission whose backend now holds an observation without
    its evidence re-derives as an impossible pair and fails closed."""
    path = tmp_path / "facts.db"
    backend = SqliteFactBackend(path)
    stale = FactIngestService(clock=FakeClock(NOW), backend=backend)
    other = FactIngestService(clock=FakeClock(NOW), backend=backend)
    evidence = make_evidence(text="hello")
    assert admit(other, evidence).disposition is FactAdmissionDisposition.NEW
    # Corrupt the durable pair while `stale` still holds an empty cache.
    conn = sqlite3.connect(path)
    conn.execute("DELETE FROM evidence")
    conn.commit()
    conn.close()
    with pytest.raises(FactAdmissionConflictError, match="without its evidence row"):
        admit(stale, evidence)


def test_arbitration_byte_conflict_after_lost_write_fails_closed(tmp_path: Path) -> None:
    """A lost save_admission whose backend holds different immutable bytes
    under the same (scope, id) fails closed instead of replaying."""
    path = tmp_path / "facts.db"
    backend = SqliteFactBackend(path)
    stale = FactIngestService(clock=FakeClock(NOW), backend=backend)
    evidence = make_evidence(text="我刚睡醒")
    conflicting = make_evidence(text="我睡不着", evidence_id=evidence.id)
    # Another writer persisted a conflicting Evidence while `stale` was out.
    backend.save_evidence(conflicting, interaction_id="interaction-x")
    with pytest.raises(FactAdmissionConflictError, match="immutable bytes"):
        admit(stale, evidence)


def test_arbitration_repair_retry_wins_after_transient_loss(tmp_path: Path) -> None:
    """A transient save_observation loss is retried inside arbitration; the
    deterministic repair wins and returns REPAIRED exactly once."""
    path = tmp_path / "facts.db"
    real = SqliteFactBackend(path)
    service = FactIngestService(clock=FakeClock(NOW), backend=real)
    evidence = make_evidence(text="hello")
    assert admit(service, evidence).disposition is FactAdmissionDisposition.NEW
    conn = sqlite3.connect(path)
    conn.execute("DELETE FROM observations")
    conn.commit()
    conn.close()
    scripted = ScriptedObservationBackend(real, save_observation_outcomes=(False,))
    repairing = FactIngestService(clock=FakeClock(NOW), backend=scripted)
    result = admit(repairing, evidence)
    assert result.disposition is FactAdmissionDisposition.REPAIRED
    assert repairing.observations.count() == 1


def test_arbitration_observation_still_missing_fails_closed(tmp_path: Path) -> None:
    """If arbitration cannot observe any repaired Observation, the admission
    fails closed instead of guessing."""
    path = tmp_path / "facts.db"
    real = SqliteFactBackend(path)
    service = FactIngestService(clock=FakeClock(NOW), backend=real)
    evidence = make_evidence(text="hello")
    assert admit(service, evidence).disposition is FactAdmissionDisposition.NEW
    conn = sqlite3.connect(path)
    conn.execute("DELETE FROM observations")
    conn.commit()
    conn.close()
    scripted = ScriptedObservationBackend(real, save_observation_outcomes=(False, False))
    repairing = FactIngestService(clock=FakeClock(NOW), backend=scripted)
    with pytest.raises(FactAdmissionConflictError, match="still missing"):
        admit(repairing, evidence)


def test_arbitration_repair_binds_original_identity_when_cache_stale(
    tmp_path: Path,
) -> None:
    """Regression (W-B review IMPORTANT-1): a stale-cache service that wins
    the repair write through arbitration must bind the durable original
    provenance interaction and Evidence.received_at, never the current
    admission's identity."""
    path = tmp_path / "facts.db"
    backend = SqliteFactBackend(path)
    stale = FactIngestService(clock=FakeClock(NOW), backend=backend)
    # The backend state changes AFTER `stale` was constructed: another writer
    # persists the Evidence, then crashes before the Observation.
    evidence = make_evidence(text="hello", received_at=NOW - timedelta(hours=2))
    backend.save_evidence(evidence, interaction_id="interaction-original")
    result = admit(stale, evidence, interaction_id="interaction-2")
    assert result.disposition is FactAdmissionDisposition.REPAIRED
    assert result.observation.interaction_id == "interaction-original"
    assert result.observation.observed_at == evidence.received_at
    conn = sqlite3.connect(path)
    try:
        row = conn.execute("SELECT interaction_id, observed_at FROM observations").fetchone()
    finally:
        conn.close()
    assert row is not None
    assert row[0] == "interaction-original"
    assert row[1] == evidence.received_at.isoformat()


def test_poisoned_cache_does_not_block_later_replay(tmp_path: Path) -> None:
    """Regression (W-B review IMPORTANT-2): after a stale-cache service
    observes a byte conflict through arbitration, its cache may hold the
    conflicting bytes, but a later admission of the backend-authoritative
    original Evidence must still return REPLAY — the backend, not the cache,
    is the arbiter."""
    path = tmp_path / "facts.db"
    backend = SqliteFactBackend(path)
    stale = FactIngestService(clock=FakeClock(NOW), backend=backend)
    original = make_evidence(text="我刚睡醒")
    conflicting = make_evidence(text="我睡不着", evidence_id=original.id)
    # Another writer persists the authoritative pair while `stale` is out;
    # `stale` first tries the conflicting bytes (lost write -> conflict).
    other = FactIngestService(clock=FakeClock(NOW), backend=backend)
    assert admit(other, original).disposition is FactAdmissionDisposition.NEW
    with pytest.raises(FactAdmissionConflictError, match="immutable bytes"):
        admit(stale, conflicting)
    # The same stale instance must now return REPLAY for the authoritative
    # original, with the backend-stored Observation.
    replayed = admit(stale, original)
    assert replayed.disposition is FactAdmissionDisposition.REPLAY
    assert replayed.observation.interaction_id == "interaction-1"
    assert replayed.observation.value == {"text": "我刚睡醒"}


def test_repair_with_missing_durable_evidence_fails_closed(tmp_path: Path) -> None:
    """A repair whose durable Evidence row is missing cannot proceed: writing
    the Observation would fabricate an orphan pair, so admission fails
    closed instead (ADR-0009 §1)."""
    path = tmp_path / "facts.db"
    service = make_service(path)
    evidence = make_evidence(text="hello")
    assert admit(service, evidence).disposition is FactAdmissionDisposition.NEW
    conn = sqlite3.connect(path)
    conn.execute("DELETE FROM observations")
    conn.commit()
    conn.close()
    restarted = make_service(path)
    assert restarted.evidence.count() == 1
    assert restarted.observations.count() == 0
    # Tamper: the durable Evidence row disappears while the cache still
    # holds it.
    conn = sqlite3.connect(path)
    conn.execute("DELETE FROM evidence")
    conn.commit()
    conn.close()
    with pytest.raises(FactAdmissionConflictError, match="durable store"):
        admit(restarted, evidence)
    assert restarted.observations.count() == 0


def test_repair_without_original_provenance_fails_closed() -> None:
    """A repair attempt whose Evidence has no original provenance interaction
    cannot bind causal identity and fails closed (ADR-0009 §2).

    The branch is defensive: `admit` always records provenance on the same
    call, so it is reached only in-memory when the Evidence entered the cache
    without a provenance entry.
    """
    service = FactIngestService(clock=FakeClock(NOW))
    evidence = make_evidence(text="hello")
    service.evidence.append(evidence)
    with pytest.raises(FactAdmissionConflictError, match="no original provenance"):
        admit(service, evidence)


def test_arbitration_replay_after_repair_race(tmp_path: Path) -> None:
    """When the retried repair write loses and the re-read finds the
    authoritative Observation, the admission returns REPLAY with it."""

    class _RepairRaceBackend(ScriptedObservationBackend):
        def save_observation(self, observation: Observation) -> bool:
            # Second call: the other writer commits the row, but this write
            # still reports False; the re-read then finds the authoritative
            # Observation.
            if len(self._save_outcomes) == 1:
                self._backend.save_observation(observation)
            return super().save_observation(observation)

    path = tmp_path / "facts.db"
    real = SqliteFactBackend(path)
    service = FactIngestService(clock=FakeClock(NOW), backend=real)
    evidence = make_evidence(text="hello")
    assert admit(service, evidence).disposition is FactAdmissionDisposition.NEW
    conn = sqlite3.connect(path)
    conn.execute("DELETE FROM observations")
    conn.commit()
    conn.close()
    scripted = _RepairRaceBackend(real, save_observation_outcomes=(False, False))
    repairing = FactIngestService(clock=FakeClock(NOW), backend=scripted)
    result = admit(repairing, evidence)
    assert result.disposition is FactAdmissionDisposition.REPLAY
    assert repairing.observations.count() == 1
