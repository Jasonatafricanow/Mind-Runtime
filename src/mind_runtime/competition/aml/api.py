"""FastAPI surface for the AML Textual/Coding contract."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from mind_runtime.competition.aml.contracts import (
    AmlAddRequest,
    AmlMessage,
    AmlSearchRequest,
)
from mind_runtime.competition.aml.journal import AmlRequestConflict
from mind_runtime.competition.aml.runtime import AmlCompetitionRuntime


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


def create_app(
    runtime: AmlCompetitionRuntime,
    *,
    auth_token: str | None,
) -> FastAPI:
    app = FastAPI(title="Mind Runtime AML Competition Adapter")

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
        if (
            authorization in {
                f"Bearer {auth_token}",
                f"Token {auth_token}",
            }
            or x_api_key == auth_token
        ):
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

    @app.post("/aml/search", dependencies=[Depends(require_auth)])
    def search(body: _SearchModel) -> dict[str, object]:
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
                    "id": item.item_id,
                    "content": item.content,
                    "score": item.score,
                    "created_at": item.created_at,
                }
                for item in results
            ]
        }

    return app
