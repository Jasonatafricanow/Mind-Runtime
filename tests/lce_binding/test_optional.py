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
from mind_runtime.integrations.lce import open_lce_binding
from mind_runtime.runtime_binding import production_binding
from mind_runtime.contracts import Scope, ScopeDomain
root = Path(sys.argv[2])
assert open_lce_binding(production_binding('fixture'),
    Scope(domain=ScopeDomain.USER, user_id='u'),
    production_root=root/'prod', lab_root=root/'lab') is None
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
