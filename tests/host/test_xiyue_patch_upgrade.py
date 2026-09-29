"""Regression for the deployed Hermes 0.19.0 double-bootstrap upgrade."""

from pathlib import Path

from xiyue.apply_mr_patch import _upgrade_legacy


def test_legacy_patch_upgrade_moves_epoch_to_locked_gateway(tmp_path: Path) -> None:
    legacy = '''# --- Xiyue MR seam bootstrap (HI-2) ---
import mr_seam as _mr_seam
# --- end Xiyue MR seam bootstrap ---

# --- Xiyue MR seam bootstrap (HI-2) ---
_mr_seam.on_gateway_process_startup()
_mr_adapter = _mr_seam.get_mr_adapter()
# --- end Xiyue MR seam bootstrap ---

    atexit.register(release_gateway_runtime_lock)
''' + (
        '                if _mr_profile == "xiyue" and _mr_verdict is not None '
        'and not _mr_verdict.admitted and _mr_verdict.status in ("NOT_READY", "FAILED"):\n'
        '                    result = {"final_response": _mr_verdict.error_message or '
        '"Mind Runtime is temporarily unavailable. (MR_NOT_READY)",}\n'
        '                    _active_adapter = _mr_seam.get_mr_adapter() '
        'if _mr_seam else _mr_adapter\n'
    )
    upgraded = _upgrade_legacy(legacy, tmp_path, tmp_path / "site-packages")

    assert upgraded.count("# --- Xiyue MR seam bootstrap (HI-2) ---") == 1
    assert upgraded.count("_mr_seam.on_gateway_process_startup()") == 1
    assert upgraded.index("atexit.register(release_gateway_runtime_lock)") < upgraded.index(
        "_mr_seam.on_gateway_process_startup()"
    )
    assert "_mr_adapter = _mr_seam.get_mr_adapter()" not in upgraded
    assert '_mr_os.environ.get("MR_ENABLED", "false")' in upgraded
    assert "(_mr_enabled and _mr_seam is None)" in upgraded
    assert _upgrade_legacy(upgraded, tmp_path, tmp_path / "site-packages") == upgraded
