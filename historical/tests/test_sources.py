import hashlib
import sqlite3
from dataclasses import replace

import pytest
from historical.source_curator import HistoricalSourceCurator, SourceDisposition
from mr_mem import Scope, ScopeDomain


def test_curation_provenance_short_commitments_and_context(native):
    _, _, reader = native
    records = tuple(reader.iterate())
    curator = HistoricalSourceCurator()
    assert [curator.classify(r).value for r in records] == [
        "CONTEXT_ONLY",
        "COMPILE",
        "IGNORE",
        "IGNORE",
        "COMPILE",
        "IGNORE",
        "CONTEXT_ONLY",
    ]
    assert curator.classify(records[-2], necessary_context=True) == SourceDisposition.CONTEXT_ONLY
    assert curator.classify(records[2], necessary_context=True) == SourceDisposition.IGNORE
    assert (
        curator.classify(replace(records[1], record_type="agent_execution"))
        == SourceDisposition.IGNORE
    )
    assert curator.classify(replace(records[0], role="agent")) == SourceDisposition.IGNORE


def test_exact_read_only_native_binding_and_order(native):
    path, scope, reader = native
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    records = tuple(reader.iterate())
    short = records[1]
    iid = reader.bind(short)
    assert reader.current_user_source(scope, iid) == short.source_ref
    assert reader.current_ref(scope, short.source_ref) == short.source_ref
    assert reader.current_ref(Scope(ScopeDomain.USER, "other"), short.source_ref) is None
    assert [r.source_ref.record_id for r in reader.iterate(after=records[3].ordering_key)] == [
        "5",
        "7",
        "8",
    ]
    assert reader.before(short) == (records[0],)
    with pytest.raises(ValueError, match="eligible USER"):
        reader.bind(records[0])
    with pytest.raises(sqlite3.OperationalError):
        reader._db.execute("DELETE FROM messages")
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before
    with sqlite3.connect(path) as db:
        db.execute("UPDATE messages SET content='changed' WHERE id=2")
    assert reader.current_user_source(scope, iid) != short.source_ref
