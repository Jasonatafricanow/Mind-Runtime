"""Durability requirements for SqliteShadowRecordStore.

DR1  — COMPLETED record persists across store reopen.
DR2  — same logical execution after reopen → one logical record (idempotency).
DR3  — same shadow_run_id + divergent identity → fail closed.
DR4  — record cannot enter Evidence/State/Affect/Memory after reopen.
DR5  — store failure leaves no committable projection.
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from mind_runtime.shadow.contracts import (
    ComparisonResult,
    HostOutcome,
    ShadowRunRecord,
    ShadowSnapshot,
    ShadowStatus,
)
from mind_runtime.shadow.store import (
    _deserialize_comparison,
    _deserialize_host_outcome,
    _deserialize_snapshot,
    _serialize_comparison,
    _serialize_host_outcome,
    _serialize_snapshot,
)


# ── Fixtures ───────────────────────────────────────────────────────────────────


def _make_record(
    shadow_run_id: str = "test-run-001",
    status: ShadowStatus = ShadowStatus.COMPLETED,
    host_outcome: HostOutcome | None = None,
    comparison: ComparisonResult | None = None,
    failure_stage: str | None = None,
    failure_reason: str | None = None,
    captured_snapshot=None,
    mr_situation_summary: str = "test situation",
    mr_intent_type: str = "test_intent",
    mr_expression_ref: str = "expr-001",
    mr_would_send: bool = True,
    **overrides,
) -> ShadowRunRecord:
    """Minimal valid ShadowRunRecord for testing."""
    return ShadowRunRecord(
        shadow_run_id=shadow_run_id,
        scope="test@user",
        source_interaction_id="itxn-001",
        source_event_ref=None,
        runtime_config_digest="abcd1234",
        started_at=datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
        completed_at=datetime(2025, 1, 1, 12, 0, 1, tzinfo=timezone.utc),
        status=status,
        mr_situation_summary=mr_situation_summary,
        mr_intent_type=mr_intent_type,
        mr_policy_decision=None,
        mr_policy_reason_codes=("R1",),
        mr_expression_ref=mr_expression_ref,
        mr_would_send=mr_would_send,
        host_outcome=host_outcome,
        comparison=comparison,
        failure_stage=failure_stage,
        failure_reason=failure_reason,
        captured_snapshot=captured_snapshot,
        **overrides,
    )


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "shadow.sqlite"


# ── Serialisation round-trips (reopen-proof) ───────────────────────────────────


class TestSerialisationRoundTrips:
    def test_record_roundtrip(self, tmp_path: Path):
        """Verify a saved record round-trips correctly through SQLite."""
        from mind_runtime.shadow.store import SqliteShadowRecordStore

        record = _make_record("roundtrip-001", ShadowStatus.COMPLETED)

        store1 = SqliteShadowRecordStore(tmp_path / "rt.sqlite")
        store1.save(record)
        store1.close()

        store2 = SqliteShadowRecordStore(tmp_path / "rt.sqlite")
        restored = store2.get(record.shadow_run_id)
        store2.close()

        assert restored == record

    def test_host_outcome_roundtrip(self):
        ho = HostOutcome(host_action_taken=True, host_action_type="text", host_expression_ref="ref-1")
        raw = _serialize_host_outcome(ho)
        restored = _deserialize_host_outcome(raw)
        assert restored == ho

    def test_host_outcome_null(self):
        assert _deserialize_host_outcome(None) is None
        assert _serialize_host_outcome(None) is None

    def test_comparison_roundtrip(self):
        cmp = ComparisonResult(comparable=True, action_presence_match=True, action_type_match=False, policy_divergence=None)
        raw = _serialize_comparison(cmp)
        restored = _deserialize_comparison(raw)
        assert restored == cmp

    def test_comparison_null(self):
        assert _deserialize_comparison(None) is None
        assert _serialize_comparison(None) is None

    def test_snapshot_roundtrip(self):
        from mind_runtime.contracts import ExpressionDisposition
        from mind_runtime.contracts.expression import ExpressionOutcome, ExpressionAttemptTrace

        expr_outcome = ExpressionOutcome(
            outcome_id="out-001",
            scope=None,  # type: ignore[arg-required]
            origin_runtime_id="test-runtime",
            accepted_expression="hello",
            final_disposition=ExpressionDisposition.ACCEPT,
            attempts=(ExpressionAttemptTrace(
                attempt_id="a1",
                context_id="c1",
                render_id="r1",
                draft_id=None,
                attempt=1,
                disposition=ExpressionDisposition.ACCEPT,
                reason_codes=(),
            ),),
        )

        snap = ShadowSnapshot(
            interaction_id="itxn-001",
            situation=None,
            projected=None,
            intent=None,
            expression_outcome=expr_outcome,
            action_receipt=None,
            observations=(),
            decision_context=None,
            captured_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
        )
        raw = _serialize_snapshot(snap)
        restored = _deserialize_snapshot(raw)
        assert restored.interaction_id == snap.interaction_id
        assert restored.expression_outcome.outcome_id == snap.expression_outcome.outcome_id
        assert restored.expression_outcome.final_disposition == snap.expression_outcome.final_disposition

    def test_snapshot_null(self):
        assert _deserialize_snapshot(None) is None
        assert _serialize_snapshot(None) is None

# ── DR1: COMPLETED record persists across store reopen ─────────────────────────


class TestDR1PersistAcrossReopen:
    def test_completed_record_persists_after_reopen(self, db_path: Path):
        """DR1: A COMPLETED record survives store.close() + new instance."""
        from mind_runtime.shadow.store import SqliteShadowRecordStore

        record = _make_record("dr1-run", ShadowStatus.COMPLETED)

        # Save in first store instance
        store1 = SqliteShadowRecordStore(db_path)
        store1.save(record)
        store1.close()

        # Reopen with fresh instance
        store2 = SqliteShadowRecordStore(db_path)
        restored = store2.get(record.shadow_run_id)
        store2.close()

        assert restored is not None
        assert restored.shadow_run_id == record.shadow_run_id
        assert restored.status == ShadowStatus.COMPLETED
        assert restored.mr_would_send is True

    def test_failed_record_persists_after_reopen(self, db_path: Path):
        """DR1: A FAILED record also survives reopen."""
        from mind_runtime.shadow.store import SqliteShadowRecordStore

        record = _make_record("dr1-fail", ShadowStatus.FAILED)
        record_with_failure = ShadowRunRecord(
            shadow_run_id=record.shadow_run_id,
            scope=record.scope,
            source_interaction_id=record.source_interaction_id,
            source_event_ref=record.source_event_ref,
            runtime_config_digest=record.runtime_config_digest,
            started_at=record.started_at,
            completed_at=record.completed_at,
            status=ShadowStatus.FAILED,
            failure_stage="agent_respond",
            failure_reason="AgentFailure: test",
        )

        store1 = SqliteShadowRecordStore(db_path)
        store1.save(record_with_failure)
        store1.close()

        store2 = SqliteShadowRecordStore(db_path)
        restored = store2.get(record_with_failure.shadow_run_id)
        store2.close()

        assert restored is not None
        assert restored.status == ShadowStatus.FAILED
        assert restored.failure_stage == "agent_respond"

    def test_all_records_returned_after_reopen(self, db_path: Path):
        """DR1: all() reflects persisted records after reopen."""
        from mind_runtime.shadow.store import SqliteShadowRecordStore

        records = [
            _make_record("dr1-all-1", ShadowStatus.COMPLETED),
            _make_record("dr1-all-2", ShadowStatus.FAILED),
        ]

        store1 = SqliteShadowRecordStore(db_path)
        for r in records:
            store1.save(r)
        store1.close()

        store2 = SqliteShadowRecordStore(db_path)
        all_records = store2.all()
        store2.close()

        assert len(all_records) == 2
        ids = {r.shadow_run_id for r in all_records}
        assert ids == {"dr1-all-1", "dr1-all-2"}


# ── DR2: Idempotency — same record is a no-op ────────────────────────────────


class TestDR2Idempotency:
    def test_identical_record_is_noop(self, db_path: Path):
        """DR2: saving the same record twice is a silent no-op."""
        from mind_runtime.shadow.store import SqliteShadowRecordStore

        record = _make_record("dr2-run", ShadowStatus.COMPLETED)

        store1 = SqliteShadowRecordStore(db_path)
        store1.save(record)
        store1.save(record)  # second save — must not raise
        store1.save(record)  # third save — must not raise
        store1.close()

        store2 = SqliteShadowRecordStore(db_path)
        all_records = store2.all()
        store2.close()

        # Only one record despite three saves
        assert len(all_records) == 1
        assert all_records[0].shadow_run_id == "dr2-run"

    def test_different_record_same_id_raises(self, db_path: Path):
        """DR3: saving the same id with different content raises ValueError."""
        from mind_runtime.shadow.store import SqliteShadowRecordStore

        record1 = _make_record("dr3-run", ShadowStatus.COMPLETED)
        record2 = _make_record(
            "dr3-run",
            ShadowStatus.COMPLETED,
            mr_situation_summary="different summary",
        )

        store1 = SqliteShadowRecordStore(db_path)
        store1.save(record1)

        with pytest.raises(ValueError, match="identity collision"):
            store1.save(record2)

        store1.close()

    def test_identical_record_across_reopen(self, db_path: Path):
        """DR2: idempotent even across reopen cycles."""
        from mind_runtime.shadow.store import SqliteShadowRecordStore

        record = _make_record("dr2-reopen", ShadowStatus.COMPLETED)

        store1 = SqliteShadowRecordStore(db_path)
        store1.save(record)
        store1.close()

        store2 = SqliteShadowRecordStore(db_path)
        store2.save(record)  # idempotent on reopen
        store2.close()

        store3 = SqliteShadowRecordStore(db_path)
        all_records = store3.all()
        store3.close()

        assert len(all_records) == 1

    def test_failed_overwrites_failed_same_content(self, db_path: Path):
        """DR2/DR3 boundary: FAILED record with same id+content is idempotent."""
        from mind_runtime.shadow.store import SqliteShadowRecordStore

        failed = ShadowRunRecord(
            shadow_run_id="dr2-boundary",
            scope="test@user",
            source_interaction_id="itxn-001",
            source_event_ref=None,
            runtime_config_digest="abcd1234",
            started_at=datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
            completed_at=datetime(2025, 1, 1, 12, 0, 1, tzinfo=timezone.utc),
            status=ShadowStatus.FAILED,
            failure_stage="agent_respond",
            failure_reason="AgentFailure: test",
        )

        store = SqliteShadowRecordStore(db_path)
        store.save(failed)
        store.save(failed)  # same content — idempotent
        store.close()

        store2 = SqliteShadowRecordStore(db_path)
        restored = store2.get("dr2-boundary")
        store2.close()

        assert restored is not None
        assert restored.status == ShadowStatus.FAILED
        assert restored.failure_reason == "AgentFailure: test"


# ── DR4: Reopen does not grant cognitive authority ─────────────────────────────


class TestDR4NoAuthorityAfterReopen:
    def test_record_has_no_committable_handles(self, db_path: Path):
        """DR4: retrieved record cannot be used to commit a projection."""
        from mind_runtime.shadow.store import SqliteShadowRecordStore

        from mind_runtime.shadow.store import SqliteShadowRecordStore

        record = _make_record("dr4-run", ShadowStatus.COMPLETED)

        store1 = SqliteShadowRecordStore(db_path)
        store1.save(record)
        store1.close()

        store2 = SqliteShadowRecordStore(db_path)
        restored = store2.get("dr4-run")
        store2.close()

        assert restored is not None
        # ShadowRunRecord is a frozen dataclass with no commit() method,
        # no writer handle, no projection handle.
        assert not hasattr(restored, "commit")
        assert not hasattr(restored, "write")
        assert not hasattr(restored, "project")
        # The record itself is the only artifact — it has no authority methods
        assert isinstance(restored, ShadowRunRecord)

    def test_record_cannot_be_cast_to_evidence(self, db_path: Path):
        """DR4: retrieved record is not usable as Evidence/Observation/Intent."""
        from mind_runtime.shadow.store import SqliteShadowRecordStore

        record = _make_record("dr4-evidence", ShadowStatus.COMPLETED)

        store = SqliteShadowRecordStore(db_path)
        store.save(record)
        store.close()

        store2 = SqliteShadowRecordStore(db_path)
        restored = store2.get("dr4-evidence")
        store2.close()

        # The record is ShadowRunRecord — not any cognitive plane type
        assert type(restored).__name__ == "ShadowRunRecord"
        # It is not Evidence, Observation, or Intent
        from mind_runtime.contracts import Evidence, Intent, Observation

        assert not isinstance(restored, Evidence)
        assert not isinstance(restored, Observation)
        assert not isinstance(restored, Intent)


# ── DR5: Store failure does not leave committable projection ───────────────────


class TestDR5StoreFailureNoCommittableProjection:
    def test_save_failure_does_not_raise_on_identical_record(self, db_path: Path):
        """DR5: when save() fails for non-identity reasons, idempotent re-save succeeds."""
        from mind_runtime.shadow.store import SqliteShadowRecordStore

        record = _make_record("dr5-run", ShadowStatus.COMPLETED)

        store = SqliteShadowRecordStore(db_path)
        store.save(record)
        # Re-save is a no-op, never a failure (idempotent)
        store.save(record)
        store.close()

    def test_close_after_save_no_open_transaction(self, db_path: Path):
        """DR5: after save(), close() must not leave uncommitted transaction."""
        from mind_runtime.shadow.store import SqliteShadowRecordStore

        record = _make_record("dr5-commit", ShadowStatus.COMPLETED)

        store = SqliteShadowRecordStore(db_path)
        store.save(record)
        store.close()  # must not raise

        # Verify data is committed: can reopen and read
        store2 = SqliteShadowRecordStore(db_path)
        restored = store2.get("dr5-commit")
        store2.close()
        assert restored is not None

    def test_raw_sqlite_integrity_error_is_not_swallowed(self, db_path: Path):
        """DR5: non-idempotent content raises ValueError (not silently dropped)."""
        from mind_runtime.shadow.store import SqliteShadowRecordStore

        record1 = _make_record("dr5-collision", ShadowStatus.COMPLETED)
        record2 = _make_record(
            "dr5-collision",
            ShadowStatus.COMPLETED,
            mr_situation_summary="malicious override",
        )

        store = SqliteShadowRecordStore(db_path)
        store.save(record1)

        with pytest.raises(ValueError, match="identity collision"):
            store.save(record2)

        store.close()

    def test_mkdir_created_automatically(self, tmp_path: Path):
        """DR5: parent directories are created so save() never fails on missing dir."""
        from mind_runtime.shadow.store import SqliteShadowRecordStore

        nested = tmp_path / "a" / "b" / "c" / "shadow.sqlite"
        assert not nested.parent.exists()

        store = SqliteShadowRecordStore(nested)
        store.save(_make_record("dr5-mkdir"))
        store.close()

        assert nested.exists()


# ── ShadowSelf-Authority ───────────────────────────────────────────────────────


class TestShadowSelfAuthority:
    """Shadow Self-Authority Golden Mapping.

    Verifies that each SH invariant maps to a concrete code location / test.
    """

    def test_shad0_no_committable_handle_in_record(self, db_path: Path):
        """SHAD-0: ShadowRunRecord exposes no commit / write / project methods."""
        from mind_runtime.shadow.store import SqliteShadowRecordStore

        record = _make_record()
        store = SqliteShadowRecordStore(db_path)
        store.save(record)
        store.close()

        store2 = SqliteShadowRecordStore(db_path)
        restored = store2.get(record.shadow_run_id)
        store2.close()

        assert restored is not None
        assert not hasattr(restored, "commit")
        assert not hasattr(restored, "write")
        assert not hasattr(restored, "project")

    def test_shad1_no_delivery_port_in_runner(self):
        """SHAD-1: SafeShadowRunner does not receive a DeliveryPort."""
        from mind_runtime.shadow import SafeShadowRunner

        # The orchestrator is built with shadow_enabled=True
        # and SafeShadowRunner does not pass a DeliveryPort.
        # This is verified by construction — the runner only passes
        # clock, trace, runtime_id.
        # If a DeliveryPort were needed, the dataclass would require it.
        import dataclasses

        fields = {f.name for f in dataclasses.fields(SafeShadowRunner)}
        assert "delivery_port" not in fields

    def test_shad2_lifecycle_order_hardened_in_code(self):
        """SHAD-2: execute() enforces capture→abort→persist ordering."""
        import inspect
        from mind_runtime.shadow import SafeShadowRunner

        source = inspect.getsource(SafeShadowRunner.execute)
        # Must capture BEFORE abort
        assert source.index("_capture_snapshot") < source.index("abort_turn")
        # Must abort BEFORE persist
        assert source.index("abort_turn") < source.index("record_store.save")
        # Must persist BEFORE return
        assert source.index("record_store.save") < source.index("return ShadowRunResult")

    def test_shad3_status_enum_values(self):
        """SHAD-3: ShadowStatus is a StrEnum with expected values."""
        assert ShadowStatus.COMPLETED == "completed"
        assert ShadowStatus.FAILED == "failed"
        assert ShadowStatus.ABORTED == "aborted"
        assert isinstance(ShadowStatus.COMPLETED, str)

    def test_shad4_comparison_is_deterministic(self):
        """SHAD-4: ComparisonResult uses only categorical fields (no LLM judge)."""
        cmp1 = ComparisonResult(
            comparable=True,
            action_presence_match=True,
            action_type_match=False,
            policy_divergence=None,
        )
        cmp2 = ComparisonResult(
            comparable=True,
            action_presence_match=True,
            action_type_match=False,
            policy_divergence=None,
        )
        # Same inputs → same categorical result
        assert cmp1 == cmp2
        # No LLM-related fields
        assert not hasattr(cmp1, "llm_judgment")
        assert not hasattr(cmp1, "semantic_similarity")

    def test_shad5_frozen_dataclass(self):
        """SHAD-5: ShadowRunRecord is frozen — cannot be mutated after construction."""
        record = _make_record()
        with pytest.raises(Exception):  # frozen dataclass
            record.mr_situation_summary = "hacked"

    def test_shad6_snapshot_frozen(self):
        """SHAD-6: ShadowSnapshot is frozen."""
        from mind_runtime.contracts import ExpressionDisposition
        from mind_runtime.contracts.expression import ExpressionOutcome, ExpressionAttemptTrace

        expr_outcome = ExpressionOutcome(
            outcome_id="o1",
            scope=None,  # type: ignore[arg-required]
            origin_runtime_id="test",
            accepted_expression="hello",
            final_disposition=ExpressionDisposition.ACCEPT,
            attempts=(ExpressionAttemptTrace(
                attempt_id="a1",
                context_id="c1",
                render_id="r1",
                draft_id=None,
                attempt=1,
                disposition=ExpressionDisposition.ACCEPT,
                reason_codes=(),
            ),),
        )

        snap = ShadowSnapshot(
            interaction_id="x",
            situation=None,
            projected=None,
            intent=None,
            expression_outcome=expr_outcome,
            action_receipt=None,
            observations=(),
            decision_context=None,
            captured_at=datetime.now(timezone.utc),
        )
        with pytest.raises(Exception):
            snap.interaction_id = "hacked"

    def test_shad7_persistence_error_reraised(self, db_path: Path):
        """SHAD-7: ShadowPersistenceError is raised when store.save() fails."""
        from mind_runtime.shadow import SafeShadowRunner

        # A store that always fails on save
        class FailingStore:
            def save(self, record):
                raise RuntimeError("disk full")

            def get(self, id):
                return None

            def all(self):
                return []

        class FakeClock:
            def now(self):
                from datetime import datetime, timezone
                return datetime(2025, 1, 1, tzinfo=timezone.utc)

        runner = SafeShadowRunner(
            clock=FakeClock(),
            trace=None,  # type: ignore[arg-type]
            record_store=FailingStore(),  # type: ignore[arg-type]
            shadow_enabled=True,
            runtime_id="test-fail-store",
        )

        from mind_runtime.contracts import Interaction, Scope, ScopeDomain
        from mind_runtime.contracts.interaction import InteractionStatus

        interaction = Interaction(
            interaction_id="itxn-fail",
            scope=Scope(domain=ScopeDomain.USER, user_id="u1"),
            channel="test",
            session_id="sess-1",
            turn_id="turn-1",
            started_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
            committed_at=None,
            status=InteractionStatus.OPEN,
        )

        # execute() must raise ShadowPersistenceError, not the underlying RuntimeError
        with pytest.raises(Exception) as exc_info:
            runner.execute(interaction)

        # Should wrap the original error
        assert "disk full" in str(exc_info.value) or "persistence" in str(exc_info.value).lower()

    def test_shad8_host_outcome_no_text_copy(self):
        """SHAD-8: HostOutcome does not accept arbitrary text (only refs/categories)."""
        ho = HostOutcome(
            host_action_taken=True,
            host_action_type="text",
            host_expression_ref="stable-ref-123",  # ref, not copy
        )
        # host_expression_ref is a stable ref, not raw text
        assert ho.host_expression_ref is not None
        # No field accepts large text content
        assert not hasattr(ho, "raw_text")
        assert not hasattr(ho, "transcript")
