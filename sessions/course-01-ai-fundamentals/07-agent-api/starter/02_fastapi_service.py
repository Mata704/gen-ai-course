"""Session 7 exercise 2: expose the RAG agent through typed HTTP endpoints."""

from __future__ import annotations

import sys
from functools import lru_cache
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field


SESSIONS_DIR = Path(__file__).resolve().parents[3] / "sessions"
SESSION_DIR = SESSIONS_DIR / "07-agent-api"
sys.path.insert(0, str(SESSION_DIR))

from agent_service import AgentService  # noqa: E402


class ChatRequest(BaseModel):
    session_id: str = Field(min_length=1)
    question: str = Field(min_length=1)
    max_steps: int = Field(default=4, ge=1, le=8)


class ChatResponse(BaseModel):
    answer: str
    tools_used: list[str]
    trace: list[dict[str, Any]]


class SearchRequest(BaseModel):
    question: str = Field(min_length=1)
    top_k: int = Field(default=2, ge=1, le=5)


class SearchResponse(BaseModel):
    results: list[dict[str, Any]]


class ResetRequest(BaseModel):
    session_id: str = Field(min_length=1)


class ResetResponse(BaseModel):
    cleared: bool


@lru_cache(maxsize=1)
def get_service() -> AgentService:
    return AgentService()


def create_app() -> FastAPI:
    app = FastAPI(title="Apollo Mission Copilot API", version="1.0.0")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/chat", response_model=ChatResponse)
    def chat(
        request: ChatRequest,
        service: AgentService = Depends(get_service),
    ) -> ChatResponse:
        try:
            reply = service.chat(
                request.session_id, request.question, max_steps=request.max_steps
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        return ChatResponse(
            answer=reply.answer,
            tools_used=reply.tools_used,
            trace=reply.trace,
        )

    @app.post("/search", response_model=SearchResponse)
    def search(
        request: SearchRequest,
        service: AgentService = Depends(get_service),
    ) -> SearchResponse:
        try:
            results = service.search(request.question, top_k=request.top_k)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return SearchResponse(results=results)

    @app.post("/sessions/reset", response_model=ResetResponse)
    def reset_session(
        request: ResetRequest,
        service: AgentService = Depends(get_service),
    ) -> ResetResponse:
        return ResetResponse(cleared=service.reset(request.session_id))

    return app


app = create_app()
