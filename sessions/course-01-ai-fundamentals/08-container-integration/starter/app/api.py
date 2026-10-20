"""Prepared FastAPI application used by the Session 8 container exercises."""

from __future__ import annotations

import sys
import uuid
from functools import lru_cache
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field


SESSIONS_DIR = Path(__file__).resolve().parents[3]
SESSION_07_DIR = SESSIONS_DIR / "07-agent-api"
sys.path.insert(0, str(SESSION_07_DIR))

from observed_service import ObservedAgentService  # noqa: E402


RUNTIME_ID = uuid.uuid4().hex[:8]


class ChatRequest(BaseModel):
    session_id: str = Field(min_length=1)
    question: str = Field(min_length=1)
    max_steps: int = Field(default=4, ge=1, le=8)


class ChatResponse(BaseModel):
    answer: str
    tools_used: list[str]
    trace: list[dict[str, Any]]
    runtime_id: str
    service_id: str
    history_messages_before: int


class SearchRequest(BaseModel):
    question: str = Field(min_length=1)
    top_k: int = Field(default=2, ge=1, le=5)


class ResetRequest(BaseModel):
    session_id: str = Field(min_length=1)


@lru_cache(maxsize=1)
def get_service() -> ObservedAgentService:
    return ObservedAgentService()


app = FastAPI(title="Apollo Mission Copilot API", version="1.0.0")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "runtime_id": RUNTIME_ID}


@app.get("/session-state/{session_id}")
def session_state(
    session_id: str,
    service: ObservedAgentService = Depends(get_service),
) -> dict[str, Any]:
    # Local teaching endpoint: counts only, never the conversation contents.
    return {
        "runtime_id": RUNTIME_ID,
        "service_id": service.service_id,
        "session_exists": session_id in service.sessions,
        "history_messages": len(service.sessions.get(session_id, [])),
    }


@app.post("/chat", response_model=ChatResponse)
def chat(
    request: ChatRequest,
    service: ObservedAgentService = Depends(get_service),
) -> ChatResponse:
    try:
        history_messages_before = len(service.sessions.get(request.session_id, []))
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
        runtime_id=RUNTIME_ID,
        service_id=service.service_id,
        history_messages_before=history_messages_before,
    )


@app.post("/search")
def search(
    request: SearchRequest,
    service: ObservedAgentService = Depends(get_service),
) -> dict[str, list[dict[str, Any]]]:
    try:
        results = service.search(request.question, top_k=request.top_k)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"results": results}


@app.post("/sessions/reset")
def reset_session(
    request: ResetRequest,
    service: ObservedAgentService = Depends(get_service),
) -> dict[str, bool]:
    return {"cleared": service.reset(request.session_id)}
