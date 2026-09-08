"""Semantic provider factory selects the configured abstraction backend.

The factory is the J8-SP1 replaceability seam: env ``MR_SEMANTIC_PROVIDER``
picks the model vendor. It must fail closed (return None -> router abstains)
rather than guess when configuration is missing or unknown.
"""

from __future__ import annotations

from mind_runtime.emotional_transition.factory import (
    GLM_KEY_ENV,
    SELECTOR_ENV,
    create_semantic_provider,
)
from mind_runtime.emotional_transition.glm_provider import GLMSemanticProvider
from mind_runtime.emotional_transition.zen_provider import ZenHy3Provider

#: A fake but structurally valid GLM key (used only as an env value, never
#: committed as a real credential).
FAKE_KEY = "abc123.def456"


def _select(monkeypatch, selector: str, *, key: str | None = FAKE_KEY) -> None:
    """Point the factory at a specific backend via real env mutation."""
    if key is None:
        monkeypatch.delenv(GLM_KEY_ENV, raising=False)
    else:
        monkeypatch.setenv(GLM_KEY_ENV, key)
    monkeypatch.setenv(SELECTOR_ENV, selector)


def test_default_unset_is_none(monkeypatch):
    # J8-SP1: default-OFF. Unset env must NOT auto-enable any vendor,
    # even if a GLM_API_KEY happens to exist in the operator's shell.
    monkeypatch.delenv(SELECTOR_ENV, raising=False)
    monkeypatch.delenv(GLM_KEY_ENV, raising=False)
    assert create_semantic_provider() is None


def test_default_unset_with_key_present_is_none(monkeypatch):
    # Credential availability != runtime authorization. Even with a
    # GLM_API_KEY present, unset MR_SEMANTIC_PROVIDER must return None.
    monkeypatch.delenv(SELECTOR_ENV, raising=False)
    monkeypatch.setenv(GLM_KEY_ENV, FAKE_KEY)
    assert create_semantic_provider() is None


def test_default_empty_string_is_none(monkeypatch):
    monkeypatch.setenv(SELECTOR_ENV, "")
    monkeypatch.setenv(GLM_KEY_ENV, FAKE_KEY)
    assert create_semantic_provider() is None


def test_glm_without_key_fails_closed(monkeypatch):
    _select(monkeypatch, "glm", key=None)
    provider = create_semantic_provider()
    assert provider is None


def test_glm_with_key_returns_provider(monkeypatch):
    _select(monkeypatch, "glm", key=FAKE_KEY)
    provider = create_semantic_provider()
    assert isinstance(provider, GLMSemanticProvider)


def test_zen_selected(monkeypatch):
    import importlib.util

    if importlib.util.find_spec("curl_cffi") is None:
        import pytest

        pytest.skip("curl_cffi not installed")

    _select(monkeypatch, "zen")
    provider = create_semantic_provider()
    assert isinstance(provider, ZenHy3Provider)


def test_none_disables_provider(monkeypatch):
    for selector in ("none", "off", "disabled"):
        _select(monkeypatch, selector)
        assert create_semantic_provider() is None


def test_unknown_selector_fails_closed(monkeypatch):
    _select(monkeypatch, "mystery-model")
    provider = create_semantic_provider()
    assert provider is None


def test_selector_is_case_insensitive(monkeypatch):
    import importlib.util

    if importlib.util.find_spec("curl_cffi") is None:
        import pytest

        pytest.skip("curl_cffi not installed")

    for selector in ("GLM", "gLm", "Zen", "OFF", "none"):
        _select(monkeypatch, selector, key=FAKE_KEY if selector.lower() == "glm" else None)
        result = create_semantic_provider()
        if selector.lower() == "glm":
            assert isinstance(result, GLMSemanticProvider)
        elif selector.lower() == "zen":
            assert isinstance(result, ZenHy3Provider)
        else:
            assert result is None


def test_whitespace_selector_is_normalized(monkeypatch):
    monkeypatch.setenv(SELECTOR_ENV, "  glm  ")
    monkeypatch.setenv(GLM_KEY_ENV, FAKE_KEY)
    assert isinstance(create_semantic_provider(), GLMSemanticProvider)


# ----------------------------------------------------------------------
# Optional-dependency tests (curl_cffi absence)
# ----------------------------------------------------------------------
# These tests verify that the factory + package remain importable when the
# ``curl_cffi`` optional dependency is missing, and that the factory
# fail-closes (returns None) when the operator explicitly selects Zen
# without the dependency being available.
#
# They are guarded by ``importorskip`` so they are SKIPPED when curl_cffi
# IS present (the live environment for normal development).  They run
# only in CI / clean environments via ``tests/emotional_transition/``.


def test_factory_module_importable_without_curl_cffi():
    """Importing the factory must never require curl_cffi."""
    import importlib
    import importlib.util

    spec = importlib.util.find_spec("curl_cffi")
    if spec is not None:
        import pytest

        pytest.skip("curl_cffi is installed in this environment")

    # If curl_cffi is missing, the factory must still import.
    factory = importlib.import_module("mind_runtime.emotional_transition.factory")
    assert factory.create_semantic_provider is not None


def test_factory_returns_none_when_zen_selected_without_curl_cffi(monkeypatch):
    """Selecting Zen without curl_cffi must fail closed."""
    import importlib.util

    if importlib.util.find_spec("curl_cffi") is not None:
        import pytest

        pytest.skip("curl_cffi is installed in this environment")

    monkeypatch.setenv(SELECTOR_ENV, "zen")
    monkeypatch.delenv(GLM_KEY_ENV, raising=False)
    # The factory call must not raise an ImportError.  When Zen is selected
    # but curl_cffi is missing, the factory must return None.
    assert create_semantic_provider() is None


def test_factory_returns_glm_when_curl_cffi_missing(monkeypatch):
    """curl_cffi absence must not impact GLM (which uses urllib only)."""
    import importlib.util

    if importlib.util.find_spec("curl_cffi") is not None:
        import pytest

        pytest.skip("curl_cffi is installed in this environment")

    monkeypatch.setenv(SELECTOR_ENV, "glm")
    monkeypatch.setenv(GLM_KEY_ENV, FAKE_KEY)
    # GLM uses urllib (stdlib); it must succeed even without curl_cffi.
    assert isinstance(create_semantic_provider(), GLMSemanticProvider)


def test_factory_returns_none_when_unset_and_curl_cffi_missing(monkeypatch):
    """Default-OFF must work without curl_cffi installed."""
    import importlib.util

    if importlib.util.find_spec("curl_cffi") is not None:
        import pytest

        pytest.skip("curl_cffi is installed in this environment")

    monkeypatch.delenv(SELECTOR_ENV, raising=False)
    monkeypatch.delenv(GLM_KEY_ENV, raising=False)
    assert create_semantic_provider() is None
