"""Default MR remains usable without the optional LCE/vector dependency set."""

import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize("enabled", ["false", "true", 0, 1, None, [], {}])
def test_invalid_activation_flags_fail_before_resolution(tmp_path, monkeypatch, enabled):
    from mind_runtime.contracts import Scope, ScopeDomain
    from mind_runtime.integrations import lce
    from mind_runtime.runtime_binding import production_binding

    def forbidden(*args, **kwargs):
        raise AssertionError("invalid activation must not resolve or initialize storage")

    monkeypatch.setattr(lce, "resolve_storage_paths", forbidden)
    with pytest.raises(TypeError, match="enabled"):
        lce.open_lce_binding(
            production_binding("fixture"),
            Scope(domain=ScopeDomain.USER, user_id="u"),
            enabled=enabled,
            consolidator=object(),
            production_root=tmp_path / "prod",
        )
    assert list(tmp_path.iterdir()) == []


def test_generic_core_cannot_claim_thread_namespace_without_lce() -> None:
    from mind_runtime.integrations.lce import _GenericLceCore

    class FakeCore:
        marker = "delegated"

        def consolidate(self, region_id, memory_ids):
            return region_id, memory_ids

    guarded = _GenericLceCore(FakeCore())
    with pytest.raises(ValueError, match="reserved"):
        guarded.consolidate("mr-thread:forged", ("memory-1",))
    assert guarded.consolidate("ordinary", ("memory-1",)) == (
        "ordinary",
        ("memory-1",),
    )
    assert guarded.marker == "delegated"


def test_thread_handoff_revalidates_durable_product_before_lce_import(tmp_path) -> None:
    from dataclasses import replace
    from datetime import UTC, datetime
    from types import SimpleNamespace

    from mind_runtime.integrations.lce import LceThreadHandoffSession
    from tests.memory.test_contracts import memory
    from tests.memory.test_product import second_memory, setup_store

    path, canonical, product = setup_store(
        tmp_path,
        rows=(memory(), second_memory()),
    )
    at = datetime(2026, 9, 25, tzinfo=UTC)
    opened = product.open_thread(
        thread_id="durable",
        scope=memory().scope,
        open_question="Is this caller-owned?",
        supporting_memory_ids=("memory-1",),
        at=at,
        working_summary="Initial.",
    )
    authoritative = product.update_thread(
        opened.thread_id,
        supporting_memory_ids=("memory-1", "memory-2"),
        at=at,
        working_summary="Durable authoritative summary.",
        mature=True,
    )
    product.close()
    canonical.close()

    adapter = SimpleNamespace(
        scope=memory().scope,
        _paths=SimpleNamespace(memory_db=path),
    )
    session = LceThreadHandoffSession(adapter, object())
    forged = replace(authoritative, working_summary="Caller-forged summary.")
    with pytest.raises(ValueError, match="durable MR product state"):
        session.handoff_thread(forged)


def test_no_site_packages_default_composition(tmp_path):
    source = Path(__file__).resolve().parents[2] / "src"
    metadata = tmp_path / "mind_runtime-0.0.0.dist-info"
    metadata.mkdir()
    (metadata / "METADATA").write_text("Name: mind-runtime\nVersion: 0.0.0\n")
    code = """
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
sys.path.insert(0, sys.argv[3])
from mind_runtime.integrations.lce import (
    open_lce_binding, open_lce_read_binding, open_lce_thread_handoff,
)
from mind_runtime.runtime_binding import production_binding
from mind_runtime.contracts import Scope, ScopeDomain
root = Path(sys.argv[2])
binding = production_binding('fixture')
scope = Scope(domain=ScopeDomain.USER, user_id='u')
assert open_lce_binding(
    binding, scope, production_root=root/'prod', lab_root=root/'lab'
) is None
assert open_lce_thread_handoff(
    binding, scope, production_root=root/'prod', lab_root=root/'lab'
) is None
assert open_lce_read_binding(
    binding, scope, production_root=root/'prod', lab_root=root/'lab'
) is None
assert not root.exists()
assert not any(k == 'lce' or k.startswith('lce.') for k in sys.modules)
assert 'qdrant_client' not in sys.modules
assert 'fastembed' not in sys.modules
"""
    result = subprocess.run(
        [sys.executable, "-S", "-c", code, str(source), str(tmp_path / "untouched"), str(tmp_path)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
