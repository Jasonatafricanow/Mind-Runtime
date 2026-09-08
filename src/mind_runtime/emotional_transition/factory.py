"""Semantic candidate provider factory (J8: replaceable abstraction providers).

Picks a ``SemanticCandidateProvider`` from environment configuration so the
abstraction layer is not hard-wired to any single model vendor.

Selection contract (``MR_SEMANTIC_PROVIDER``):
  * ``glm``             -> :class:`GLMSemanticProvider` (requires GLM_API_KEY)
  * ``zen``             -> :class:`ZenHy3Provider` (lazy-imported; requires curl_cffi)
  * ``none`` / ``off``  -> no provider (router abstains on language)
  * anything unknown      -> no provider (fail-closed; never guess)
  * unset / empty       -> no provider (default-OFF per J8-SP1 decision)

A provider requiring an API key is only returned when that key is actually
present. Keyless providers (zen) may still be returned. When no provider can
be constructed the factory returns ``None`` — the caller (SemanticRouter)
then abstains rather than fabricating candidates.

The factory does NOT write state, load memory, perform routing, or invoke
Appraisal. Its sole responsibility is configuration -> implementation
selection -> provider construction.

Optional-dependency contract:
  * GLM provider uses only the Python standard library (urllib). It is
    always importable when this module is imported.
  * Zen provider uses ``curl_cffi`` lazily — only imported when
    ``MR_SEMANTIC_PROVIDER=zen`` is explicitly set. The factory's top-
    level imports do NOT touch ``curl_cffi``, so callers that never
    opt in to Zen can run with the dependency missing.
  * ``GLMSemanticProvider`` is also imported lazily here so the factory
    can be imported in environments that have neither GLM nor Zen, as
    long as the operator never selects a provider.

See J8_SP1_DEFAULT_DECISION.md for the default-OFF authorization.
"""
from __future__ import annotations

import os
from typing import Optional

from mind_runtime.emotional_transition.semantic import SemanticCandidateProvider

#: Env var selecting the provider backend.
SELECTOR_ENV = "MR_SEMANTIC_PROVIDER"
#: Env var carrying the GLM API key.
GLM_KEY_ENV = "GLM_API_KEY"


def create_semantic_provider() -> Optional[SemanticCandidateProvider]:
    """Construct the configured abstraction provider, or ``None`` to abstain.

    The returned instance is read from the environment on each call so a
    process can hot-swap providers by changing env and rebuilding the
    orchestrator.

    Lazy-import semantics: provider classes are imported only when their
    selector is requested. This keeps the factory (and the orchestrator
    that imports it) importable in environments that lack one or both
    of the optional provider dependencies.
    """
    # Default OFF: env unset or empty means no provider (J8-SP1 decision).
    # The factory never auto-enables a vendor based on credential presence.
    selector_raw = os.environ.get(SELECTOR_ENV)
    if selector_raw is None or selector_raw.strip() == "":
        return None
    selector = selector_raw.strip().lower()

    if selector in ("none", "off", "disabled"):
        return None

    if selector == "zen":
        # Probe the optional curl_cffi dependency up front so the factory
        # can fail-closed (return None) when the dependency is missing.
        # zen_provider itself loads without curl_cffi (the import lives
        # inside _classify), but constructing the provider and expecting
        # it to ever work without curl_cffi would be misleading.
        try:
            import curl_cffi  # noqa: F401  -- dependency probe only
        except ImportError:
            return None
        # Lazy import of the class — only resolved when zen is selected
        # and the dependency is present.
        from mind_runtime.emotional_transition.zen_provider import ZenHy3Provider

        return ZenHy3Provider()

    if selector == "glm":
        if not os.environ.get(GLM_KEY_ENV):
            # fail-closed: no key -> no provider -> router abstains
            return None
        # Lazy import — only resolved when GLM is actually selected.
        from mind_runtime.emotional_transition.glm_provider import GLMSemanticProvider

        return GLMSemanticProvider()

    # Unknown selector: fail-closed, never guess.
    return None
