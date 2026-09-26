"""FastAPI surface matching the AML Textual Add/Search contract."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from mind_runtime.aml.contracts import (
    AmlAddRequest,
    AmlMessage,
    AmlRuntimeConfig,
    AmlSearchRequest,
)
from mind_runtime.aml.providers import (
    OpenAICompatibleCompletion,
    OpenAICompatibleEmbedding,
    OpenAICompatibleThreadSemanticProvider,
)
from mind_runtime.aml.runtime import AmlMemoryRuntime, AmlRequestConflict
from mind_runtime.decision.factory import (
    DecisionModelConfig,
    build_decision_capability,
)
from mind_runtime.memory.providers.hybrid import PromptHyDEExpander


class _MessageModel(BaseModel):
    role: str = Field(min_length=1)
    content: str = Field(min_length=1)
    timestamp: int | float | None = None


class _AddModel(BaseModel):
    request_id: str = Field(min_length=1)
    messages: list[_MessageModel] = Field(min_length=1)
    user_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)


class _SearchModel(BaseModel):
    query: str = Field(min_length=1)
    options: list[str] | None = None
    user_id: str = Field(min_length=1)
    top_k: int = Field(ge=1, le=100)


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    normalized = raw.strip().casefold()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be a boolean-like value")


def _optional_triplet(prefix: str) -> tuple[str, str, str] | None:
    endpoint = os.environ.get(f"{prefix}_ENDPOINT")
    api_key = os.environ.get(f"{prefix}_API_KEY")
    model = os.environ.get(f"{prefix}_MODEL")
    values = (endpoint, api_key, model)
    if all(value and value.strip() for value in values):
        return str(endpoint), str(api_key), str(model)
    if any(value and value.strip() for value in values):
        raise ValueError(
            f"{prefix}_ENDPOINT/API_KEY/MODEL must be supplied together"
        )
    return None


def build_runtime_from_env() -> AmlMemoryRuntime:
    config = AmlRuntimeConfig(
        result_cap=int(os.environ.get("AML_RESULT_CAP", "20")),
        candidate_limit=int(
            os.environ.get("AML_CANDIDATE_LIMIT", "50")
        ),
        max_context_characters=int(
            os.environ.get("AML_MAX_CONTEXT_CHARACTERS", "32768")
        ),
        thread_enabled=_env_bool("AML_THREAD_ENABLED", True),
        lce_enabled=_env_bool("AML_LCE_ENABLED", True),
        thread_cap=int(os.environ.get("AML_THREAD_CAP", "2")),
        lce_cap=int(os.environ.get("AML_LCE_CAP", "4")),
        retrieval_cache_users=int(
            os.environ.get("AML_RETRIEVAL_CACHE_USERS", "12")
        ),
        hyde_min_results=int(
            os.environ.get("AML_HYDE_MIN_RESULTS", "20")
        ),
    )

    embedding = None
    embed_profile = _optional_triplet("AML_EMBED")
    if embed_profile is not None:
        endpoint, api_key, model = embed_profile
        dimension = int(os.environ["AML_EMBED_DIMENSION"])
        revision = os.environ.get(
            "AML_EMBED_REVISION",
            f"aml:{model}",
        )
        embedding = OpenAICompatibleEmbedding(
            endpoint=endpoint,
            api_key=api_key,
            model=model,
            dimension=dimension,
            revision=revision,
            timeout_seconds=float(
                os.environ.get("AML_EMBED_TIMEOUT_SECONDS", "12")
            ),
        )

    hyde = None
    hyde_profile = _optional_triplet("AML_HYDE")
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

    thread_semantics = None
    thread_profile = _optional_triplet("AML_THREAD")
    if thread_profile is not None:
        endpoint, api_key, model = thread_profile
        thread_semantics = OpenAICompatibleThreadSemanticProvider(
            endpoint=endpoint,
            api_key=api_key,
            model=model,
            timeout_seconds=float(
                os.environ.get(
                    "AML_THREAD_TIMEOUT_SECONDS",
                    "20",
                )
            ),
        )

    lce_semantic_provider = None
    lce_interpreter = None
    lce_profile = _optional_triplet("AML_LCE")
    if lce_profile is not None:
        endpoint, api_key, model = lce_profile
        from mind_runtime.aml.lce_provider import (
            OpenAICompatibleBoundedInterpreter,
            OpenAICompatibleLceSemanticProvider,
        )

        lce_timeout = float(
            os.environ.get("AML_LCE_TIMEOUT_SECONDS", "20")
        )
        lce_semantic_provider = OpenAICompatibleLceSemanticProvider(
            endpoint=endpoint,
            api_key=api_key,
            model=model,
            timeout_seconds=lce_timeout,
        )
        lce_interpreter = OpenAICompatibleBoundedInterpreter(
            endpoint=endpoint,
            api_key=api_key,
            model=model,
            timeout_seconds=lce_timeout,
        )

    decision_backend = os.environ.get(
        "AML_DECISION_BACKEND",
        "none",
    )
    decision = build_decision_capability(
        DecisionModelConfig(
            backend=decision_backend,
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

    return AmlMemoryRuntime(
        Path(os.environ.get("AML_DATA_ROOT", ".aml-data")),
        config=config,
        embedding=embedding,
        hyde_expander=hyde,
        decision=decision,
        thread_semantics=thread_semantics,
        lce_semantic_provider=lce_semantic_provider,
        lce_interpreter=lce_interpreter,
    )


def create_app(
    runtime: AmlMemoryRuntime,
    *,
    auth_token: str | None = None,
) -> FastAPI:
    app = FastAPI(title="Mind Runtime AML Adapter")

    def require_auth(
        authorization: Annotated[
            str | None,
            Header(alias="Authorization"),
        ] = None,
        x_api_key: Annotated[
            str | None,
            Header(alias="X-Api-Key"),
        ] = None,
    ) -> None:
        if auth_token is None:
            return
        accepted = {
            f"Bearer {auth_token}",
            f"Token {auth_token}",
        }
        if authorization in accepted or x_api_key == auth_token:
            return
        raise HTTPException(status_code=401, detail="unauthorized")

    @app.get("/health")
    def health() -> dict[str, bool]:
        return {"ok": True}

    @app.post("/aml/add", dependencies=[Depends(require_auth)])
    def add(body: _AddModel) -> dict[str, object]:
        request = AmlAddRequest(
            request_id=body.request_id,
            user_id=body.user_id,
            session_id=body.session_id,
            messages=tuple(
                AmlMessage(
                    role=item.role,
                    content=item.content,
                    timestamp=item.timestamp,
                )
                for item in body.messages
            ),
        )
        try:
            runtime.add(request)
        except AmlRequestConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except (ImportError, RuntimeError) as exc:
            raise HTTPException(
                status_code=503,
                detail=type(exc).__name__,
            ) from exc
        return {
            "success": True,
            "request_id": body.request_id,
            "user_id": body.user_id,
            "session_id": body.session_id,
        }

    @app.post("/aml/search")
    def search(
        body: _SearchModel,
        _: Annotated[None, require_auth],
    ) -> dict[str, object]:
        request = AmlSearchRequest(
            user_id=body.user_id,
            query=body.query,
            top_k=body.top_k,
            options=tuple(body.options or ()),
        )
        try:
            results = runtime.search(request)
        except (ImportError, RuntimeError) as exc:
            raise HTTPException(
                status_code=503,
                detail=type(exc).__name__,
            ) from exc
        return {
            "data": [
                {
                    "id": item.id,
                    "content": item.content,
                    "score": item.score,
                    "created_at": item.created_at,
                }
                for item in results
            ]
        }

    return app


def create_app_from_env() -> FastAPI:
    return create_app(
        build_runtime_from_env(),
        auth_token=os.environ.get("AML_AUTH_TOKEN"),
    )
