import json
from copy import deepcopy
from datetime import UTC, datetime

import pytest
from mr_mem import MemoryCore, Scope, ScopeDomain, SemanticAdmissionService, SourceRef

from mind_runtime.integrations.historical_compiler import (
    SCHEMA_VERSION,
    HistoricalSemanticPipeline,
    validate_proposal,
)
from mind_runtime.integrations.native_history import NativeRecord, source_fragments

SCOPE = Scope(ScopeDomain.USER, user_id="u1")
NOW = datetime(2026, 10, 1, tzinfo=UTC)


class Host:
    def __init__(self, records):
        self.refs = {r.ref.source_key: r.ref for r in records}

    def current_ref(self, scope, ref):
        return self.refs.get(ref.source_key) if scope == SCOPE else None


class Clock:
    def now(self):
        return NOW


def record(mid=1, role="user", text=r"Tests completed; always preserve C:\new\test logs."):
    return NativeRecord(
        SourceRef("hermes", "s1", str(mid), NOW, "1"), role, text, (1.0, mid)
    )


def proposal(fragments, decisions=("DROP", "KEEP")):
    return {
        "schema_version": SCHEMA_VERSION,
        "fragments": [{
            "fragment_id": fragment.fragment_id,
            "disposition": disposition,
            "reason": "transient progress" if disposition == "DROP" else "durable constraint",
            "content": (
                r"User requires preserving C:\new\test logs." if disposition == "KEEP" else ""
            ),
            "attributes": {
                "subject": "user", "holder": "user", "polarity": "positive",
                "modality": "asserted", "temporal_scope": "ongoing", "kind": "constraint",
            } if disposition == "KEEP" else {},
        } for fragment, disposition in zip(fragments, decisions, strict=True)],
    }


class Cleaner:
    def __init__(self):
        self.calls = 0

    def compile(self, fragments, *, context):
        self.calls += 1
        return proposal(fragments)


class Consumer:
    def __init__(self, fail=False):
        self.calls = []
        self.fail = fail

    def consume(self, memories):
        self.calls.append(tuple(m.memory_id for m in memories))
        if self.fail:
            raise RuntimeError("projection failed")


def pipeline(tmp_path, core, cleaner, consumers=None):
    host = Host(tuple(record(mid) for mid in (1, 2, 3)))
    return HistoricalSemanticPipeline(
        path=tmp_path / "receipts.sqlite", core=core,
        admission=SemanticAdmissionService(
            store=core.canonical, sources=host, clock=Clock(),
            origin_runtime_id="host",
        ),
        scope=SCOPE, cleaner=cleaner, compiler_version="host-v1", consumers=consumers,
        sources=host,
    )


def test_mixed_turn_is_reduced_once_and_restart_retries_only_failed_projection(tmp_path):
    cleaner = Cleaner()
    thread, lce = Consumer(), Consumer(fail=True)
    with MemoryCore(tmp_path / "semantic.sqlite") as core:
        flow = pipeline(tmp_path, core, cleaner, {"thread": thread, "lce": lce})
        with pytest.raises(RuntimeError, match="projection failed"):
            flow.process(record())
        assert cleaner.calls == 1
        assert len(core.load_all()) == 1
        assert flow.funnel()["KEEP"] == 1
        flow.close()
    lce.fail = False
    with MemoryCore(tmp_path / "semantic.sqlite") as core:
        flow = pipeline(tmp_path, core, cleaner, {"thread": thread, "lce": lce})
        memories = flow.process(record())
        assert cleaner.calls == 1
        assert len(thread.calls) == 1
        assert len(lce.calls) == 2
        assert len(core.load_all()) == 1
        assert memories[0].content == r"User requires preserving C:\new\test logs."
        assert flow.funnel() == {
            "raw_records": 1,
            "structural_drop": 0,
            "DROP": 1,
            "KEEP": 1,
            "DEFER": 0,
            "semantic_memories": 1,
            "proposal_attempts": 1,
        }
        flow.close()
    assert b"Tests completed" not in (tmp_path / "semantic.sqlite").read_bytes()
    assert b"Tests completed" not in (tmp_path / "receipts.sqlite").read_bytes()


def test_tools_are_hard_dropped_without_semantic_or_downstream_calls(tmp_path):
    cleaner, consumer = Cleaner(), Consumer()
    with MemoryCore(tmp_path / "semantic.sqlite") as core:
        flow = pipeline(tmp_path, core, cleaner, {"lce": consumer})
        assert flow.process(record(2, "tool", "pytest stdout")) == ()
        assert cleaner.calls == 0
        assert consumer.calls == []
        assert core.load_all() == ()
        assert flow.funnel()["structural_drop"] == 1
        flow.close()


@pytest.mark.parametrize(
    "mutation",
    [
        "id",
        "foreign_source_fields",
        "duplicate",
        "coverage",
        "holder",
        "schema",
        "assistant",
        "drop_semantics",
    ],
)
def test_invalid_or_ambiguous_references_are_rejected_without_repair(mutation):
    fragments = source_fragments(record())
    raw = proposal(fragments)
    if mutation == "id":
        raw["fragments"][0]["fragment_id"] = "invented"
    elif mutation == "foreign_source_fields":
        raw["fragments"][0]["start"] = 999
        raw["fragments"][0]["quote"] = r"C:\new\test"
    elif mutation == "duplicate":
        raw["fragments"][1]["fragment_id"] = fragments[0].fragment_id
    elif mutation == "coverage":
        raw["fragments"].pop()
    elif mutation == "holder":
        raw["fragments"][1]["attributes"]["holder"] = "assistant"
    elif mutation == "schema":
        raw["schema_version"] = "wrong-provider-contract"
    elif mutation == "assistant":
        fragments = source_fragments(record(role="assistant"))
        raw = proposal(fragments)
    else:
        raw["fragments"][0]["content"] = "DROP cannot carry admitted semantics."
    with pytest.raises(ValueError):
        validate_proposal(raw, fragments)


def test_conflicting_proposals_append_and_cannot_overwrite_frozen_result(tmp_path):
    cleaner = Cleaner()
    with MemoryCore(tmp_path / "semantic.sqlite") as core:
        flow = pipeline(tmp_path, core, cleaner)
        accepted = flow.process(record())
        job_id = flow._db.execute("SELECT job_id FROM source_receipts").fetchone()[0]
        changed = deepcopy(proposal(source_fragments(record())))
        changed["fragments"][1]["content"] = "A different interpretation."
        with pytest.raises(ValueError, match="conflicting frozen"):
            flow.accept_proposal(job_id, changed, source_fragments(record()))
        assert flow.process(record()) == accepted
        assert cleaner.calls == 1
        statuses = flow._db.execute(
            "SELECT validation_error FROM proposal_history ORDER BY proposal_id"
        ).fetchall()
        assert len(statuses) == 2 and statuses[0][0] is None and statuses[1][0]
        with pytest.raises(Exception, match="append-only"):
            flow._db.execute("UPDATE proposal_history SET payload='{}'")
        flow.close()


def test_deferred_retry_reuses_kept_semantics_and_compiles_only_missing_fragments(tmp_path):
    class DeferredCleaner:
        def __init__(self):
            self.inputs = []

        def compile(self, fragments, *, context):
            self.inputs.append(tuple(f.fragment_id for f in fragments))
            return proposal(fragments, ("DEFER", "KEEP") if not context else ("DROP",))

    cleaner = DeferredCleaner()
    consumer = Consumer()
    with MemoryCore(tmp_path / "semantic.sqlite") as core:
        flow = pipeline(tmp_path, core, cleaner, {"thread:v1": consumer})
        first = flow.process(record())
        assert flow.funnel()["DEFER"] == 1
        context = source_fragments(record(2, text="bounded clarification"))
        second = flow.process(record(), context=context)
        assert first == second
        assert len(cleaner.inputs[0]) == 2
        assert cleaner.inputs[1] == (source_fragments(record())[0].fragment_id,)
        assert flow.funnel()["raw_records"] == 1
        assert flow.funnel()["DEFER"] == 0
        assert len(core.load_all()) == 1
        assert len(consumer.calls) == 1
        third = flow.process(record(), context=source_fragments(record(3, text="later context")))
        assert third == first and len(cleaner.inputs) == 2 and len(consumer.calls) == 1
        flow.close()


def test_semantic_drop_and_defer_do_not_enter_consumers(tmp_path):
    class DropCleaner:
        def compile(self, fragments, *, context):
            return proposal(fragments, ("DROP", "DEFER"))

    consumer = Consumer()
    with MemoryCore(tmp_path / "semantic.sqlite") as core:
        flow = pipeline(tmp_path, core, DropCleaner(), {"lce:v1": consumer})
        assert flow.process(record()) == ()
        assert consumer.calls == []
        assert core.load_all() == ()
        assert flow.funnel()["DEFER"] == 1
        flow.close()


def test_provider_exception_and_invalid_output_preserve_retry_and_inference_accounting(tmp_path):
    class UnavailableCleaner(Cleaner):
        def compile(self, fragments, *, context):
            self.calls += 1
            if self.calls == 1:
                raise ConnectionError("private provider response must not be logged")
            if self.calls == 2:
                return {"schema_version": SCHEMA_VERSION, "fragments": []}
            return proposal(fragments)

    cleaner, downstream = UnavailableCleaner(), Consumer()
    with MemoryCore(tmp_path / "semantic.sqlite") as core:
        flow = pipeline(tmp_path, core, cleaner, {"thread": downstream})
        with pytest.raises(ConnectionError):
            flow.process(record())
        assert core.load_all() == () and downstream.calls == []
        flow.close()
        flow = pipeline(tmp_path, core, cleaner, {"thread": downstream})
        with pytest.raises(ValueError, match="coverage"):
            flow.process(record())
        assert core.load_all() == () and downstream.calls == []
        accepted = flow.process(record())
        assert flow.process(record()) == accepted
        assert cleaner.calls == 3 and len(downstream.calls) == 1
        attempts = flow._db.execute(
            "SELECT payload,validation_error FROM proposal_history ORDER BY proposal_id"
        ).fetchall()
        assert attempts[0] == ("null", "producer failed: ConnectionError")
        assert attempts[1][1] and attempts[2][1] is None
        assert "private provider response" not in repr(attempts)
        flow.close()


@pytest.mark.parametrize(
    "fault", ["source_revision", "missing_context", "context_items", "context_chars"]
)
def test_invalid_native_source_or_context_cannot_invoke_provider(tmp_path, fault):
    cleaner = Cleaner()
    with MemoryCore(tmp_path / "semantic.sqlite") as core:
        flow = pipeline(tmp_path, core, cleaner)
        context = ()
        if fault == "source_revision":
            flow._sources.refs[record().ref.source_key] = SourceRef("hermes", "s1", "1", NOW, "2")
        elif fault == "missing_context":
            context = source_fragments(record(99, text="unavailable context"))
        elif fault == "context_items":
            context = source_fragments(record(2, text="clarification")) * 9
        else:
            context = source_fragments(record(2, text="x" * 4097))
        with pytest.raises(ValueError):
            flow.process(record(), context=context)
        assert cleaner.calls == 0 and core.load_all() == ()
        assert flow.funnel()["proposal_attempts"] == 0
        flow.close()


def test_receipt_recovery_fetches_exact_pointer_and_only_missing_consumer(tmp_path):
    cleaner, first, failing = Cleaner(), Consumer(), Consumer(fail=True)
    with MemoryCore(tmp_path / "semantic.sqlite") as core:
        flow = pipeline(tmp_path, core, cleaner, {"thread": first, "lce": failing})
        with pytest.raises(RuntimeError):
            flow.process(record())
        flow.close()
        failing.fail = False
        flow = pipeline(tmp_path, core, cleaner, {"thread": first, "lce": failing})
        fetched = []

        def fetch(ref):
            fetched.append(ref)
            return record(int(ref.record_id))

        assert flow.recover(fetch) == 1
        assert fetched == [record().ref]
        assert cleaner.calls == 1
        assert len(first.calls) == 1
        assert len(failing.calls) == 2
        assert flow.recover(fetch) == 0
        assert flow.source_cursor("native") is None
        flow.advance_source_cursor("native", (1.0, 1))
        assert flow.source_cursor("native") == (1.0, 1)
        with pytest.raises(ValueError, match="regress"):
            flow.advance_source_cursor("native", (0.0, 0))
        flow.close()


def test_corrupt_receipt_pointer_cannot_borrow_another_current_native_record(tmp_path):
    cleaner, failing = Cleaner(), Consumer(fail=True)
    with MemoryCore(tmp_path / "semantic.sqlite") as core:
        flow = pipeline(tmp_path, core, cleaner, {"lce": failing})
        with pytest.raises(RuntimeError):
            flow.process(record())
        pointer = json.loads(
            flow._db.execute("SELECT source_pointer FROM source_receipts").fetchone()[0]
        )
        pointer["record_id"] = "2"
        with flow._db:
            flow._db.execute("UPDATE source_receipts SET source_pointer=?", (json.dumps(pointer),))
        with pytest.raises(ValueError, match="receipt identity"):
            flow.recover(lambda ref: record(2))
        assert cleaner.calls == 1
        assert len(core.load_all()) == 1
        flow.close()
