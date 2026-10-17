"""Environment composition for reproducible AML experiment profiles."""

from __future__ import annotations

import os
from pathlib import Path

from mind_runtime.competition.aml.contracts import AmlRuntimeConfig
from mind_runtime.competition.aml.providers import (
    OpenAICompatibleAmlHostSemanticProvider,
    OpenAICompatibleCompletion,
    OpenAICompatibleEmbedding,
)
from mind_runtime.competition.aml.runtime import AmlCompetitionRuntime
from mind_runtime.decision.factory import (
    DecisionModelConfig,
    build_decision_capability,
)
from mind_runtime.memory.providers.hybrid import PromptHyDEExpander

_PROFILE_FLAGS = {
    "bm25": (False, False, False),
    "hybrid": (False, False, True),
    "thread": (True, False, True),
    "lce": (False, True, True),
    "full": (True, True, True),
}


def _triplet(prefix: str) -> tuple[str, str, str] | None:
    endpoint = os.environ.get(f"{prefix}_ENDPOINT")
    api_key = os.environ.get(f"{prefix}_API_KEY")
    model = os.environ.get(f"{prefix}_MODEL")
    present = tuple(
        isinstance(value, str) and bool(value.strip())
        for value in (endpoint, api_key, model)
    )
    if not any(present):
        return None
    if not all(present):
        raise ValueError(
            f"{prefix}_ENDPOINT/API_KEY/MODEL must be supplied together"
        )
    assert endpoint is not None
    assert api_key is not None
    assert model is not None
    return endpoint, api_key, model


def build_runtime_from_env() -> AmlCompetitionRuntime:
    profile = os.environ.get("AML_PROFILE", "full").strip().casefold()
    if profile not in _PROFILE_FLAGS:
        raise ValueError(
            "AML_PROFILE must be bm25, hybrid, thread, lce, or full"
        )
    thread_enabled, lce_enabled, require_embedding = _PROFILE_FLAGS[
        profile
    ]
    config = AmlRuntimeConfig(
        result_cap=int(os.environ.get("AML_RESULT_CAP", "30")),
        candidate_limit=int(
            os.environ.get("AML_CANDIDATE_LIMIT", "70")
        ),
        max_context_characters=int(
            os.environ.get(
                "AML_MAX_CONTEXT_CHARACTERS",
                "65536",
            )
        ),
        thread_enabled=thread_enabled,
        lce_enabled=lce_enabled,
        lce_bootstrap_on_add=(
            os.environ.get(
                "AML_LCE_BOOTSTRAP_ON_ADD",
                "true",
            ).strip().casefold()
            in {"1", "true", "yes", "on"}
        ),
        thread_cap=int(os.environ.get("AML_THREAD_CAP", "4")),
        lce_cap=int(os.environ.get("AML_LCE_CAP", "8")),
        hyde_min_results=int(
            os.environ.get("AML_HYDE_MIN_RESULTS", "20")
        ),
    )

    embedding = None
    embed_profile = _triplet("AML_EMBED")
    if embed_profile is not None:
        endpoint, api_key, model = embed_profile
        dimension_raw = os.environ.get("AML_EMBED_DIMENSION")
        if dimension_raw is None:
            raise ValueError(
                "AML_EMBED_DIMENSION is required with AML_EMBED_*"
            )
        embedding = OpenAICompatibleEmbedding(
            endpoint=endpoint,
            api_key=api_key,
            model=model,
            dimension=int(dimension_raw),
            revision=os.environ.get(
                "AML_EMBED_REVISION",
                f"aml:{model}",
            ),
            timeout_seconds=float(
                os.environ.get(
                    "AML_EMBED_TIMEOUT_SECONDS",
                    "12",
                )
            ),
        )
    elif require_embedding:
        raise ValueError(
            f"AML_PROFILE={profile} requires AML_EMBED_* configuration"
        )

    hyde = None
    hyde_profile = _triplet("AML_HYDE")
    if hyde_profile is not None:
        endpoint, api_key, model = hyde_profile
        hyde = PromptHyDEExpander(
            OpenAICompatibleCompletion(
                endpoint=endpoint,
                api_key=api_key,
                model=model,
                timeout_seconds=float(
                    os.environ.get(
                        "AML_HYDE_TIMEOUT_SECONDS",
                        "12",
                    )
                ),
            )
        )

    semantic = None
    if thread_enabled:
        body_profile = _triplet("AML_BODY")
        if body_profile is None:
            raise ValueError(
                "Thread profiles require AML_BODY_* Host semantics"
            )
        endpoint, api_key, model = body_profile
        semantic = OpenAICompatibleAmlHostSemanticProvider(
            endpoint=endpoint,
            api_key=api_key,
            model=model,
            timeout_seconds=float(
                os.environ.get(
                    "AML_BODY_TIMEOUT_SECONDS",
                    "20",
                )
            ),
        )

    lce_provider = None
    lce_interpreter = None

    decision = build_decision_capability(
        DecisionModelConfig(
            backend=os.environ.get(
                "AML_DECISION_BACKEND",
                "none",
            ),
            api_key=os.environ.get("AML_DECISION_API_KEY"),
            endpoint=os.environ.get("AML_DECISION_ENDPOINT"),
            model=os.environ.get("AML_DECISION_MODEL"),
            timeout_seconds=float(
                os.environ.get(
                    "AML_DECISION_TIMEOUT_SECONDS",
                    "2",
                )
            ),
        )
    )

    return AmlCompetitionRuntime(
        Path(os.environ.get("AML_DATA_ROOT", ".aml-data")),
        run_id=os.environ.get("AML_RUN_ID", "local-development"),
        config=config,
        semantic=semantic,
        embedding=embedding,
        hyde_expander=hyde,
        decision=decision,
        lce_provider=lce_provider,
        lce_interpreter=lce_interpreter,
    )
