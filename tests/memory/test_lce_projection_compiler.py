from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from mind_runtime.integrations import lce as lce_integration
from mind_runtime.integrations.lce import LceThreadProjectionCompiler
from mind_runtime.memory.product import MemoryThread, ThreadStatus
from mind_runtime.runtime_binding import production_binding
from tests.facts.test_admission import make_scope


def thread_fixture():
    return MemoryThread(
        thread_id="projection-line",
        scope=make_scope(),
        open_question="Will this line compile?",
        status=ThreadStatus.OPEN,
        importance=5,
        created_at=datetime(2026, 9, 20, tzinfo=UTC),
        updated_at=datetime(2026, 9, 25, tzinfo=UTC),
        touch_count=1,
        suppressed=False,
        origin_memory_ids=("memory-1",),
        current_support_ids=("memory-1",),
        working_summary="The relation is mature enough to compile.",
        mature=True,
    )


def test_lce_thread_projection_compiler_validates_thread_type():
    compiler = LceThreadProjectionCompiler(production_binding("p"))
    with pytest.raises(TypeError, match="thread must be MemoryThread"):
        compiler.compile(object())


def test_lce_thread_projection_compiler_disabled_returns_none(monkeypatch):
    calls = []

    def fake_open(*args, **kwargs):
        calls.append((args, kwargs))
        return None

    monkeypatch.setattr(lce_integration, "open_lce_thread_handoff", fake_open)
    compiler = LceThreadProjectionCompiler(production_binding("p"), enabled=False)
    assert compiler.compile(thread_fixture()) is None
    assert calls[0][1]["enabled"] is False


def test_lce_thread_projection_compiler_returns_accepted_baseline_id(monkeypatch):
    class Session:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

        def handoff_thread(self, thread):
            assert thread.thread_id == "projection-line"
            return SimpleNamespace(
                baseline=SimpleNamespace(baseline_id="baseline-projection-line")
            )

    monkeypatch.setattr(
        lce_integration,
        "open_lce_thread_handoff",
        lambda *args, **kwargs: Session(),
    )
    compiler = LceThreadProjectionCompiler(
        production_binding("p"),
        enabled=True,
        production_root="/tmp/prod",
        lab_root="/tmp/lab",
    )
    assert compiler.compile(thread_fixture()) == "baseline-projection-line"
