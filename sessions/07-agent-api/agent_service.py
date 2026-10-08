"""Small reusable service for the Session 7 RAG agent and API exercises."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI


SESSION_DIR = Path(__file__).resolve().parent
SESSIONS_DIR = SESSION_DIR.parent
sys.path.insert(0, str(SESSIONS_DIR))

from rag_course_support import (  # noqa: E402
    GENERATION_MODEL,
    Chunk,
    create_embeddings,
    load_documents,
    rank_by_embedding,
    require_api_key,
    whole_document_chunks,
)


load_dotenv()

TIMELINES_FILE = (
    SESSIONS_DIR
    / "06-conversational-ai"
    / "test-data"
    / "mission-timelines.json"
)

TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "name": "search_documents",
        "description": "Search Apollo documents for narrative facts and explanations.",
        "parameters": {
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "A standalone factual question for retrieval.",
                }
            },
            "required": ["question"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "get_mission_timeline",
        "description": "Get exact launch, lunar landing, and splashdown dates.",
        "parameters": {
            "type": "object",
            "properties": {
                "mission": {
                    "type": "string",
                    "description": "Apollo mission name, for example Apollo 11.",
                }
            },
            "required": ["mission"],
            "additionalProperties": False,
        },
        "strict": True,
    },
]


@dataclass(frozen=True)
class AgentReply:
    answer: str
    tools_used: list[str]
    trace: list[dict[str, Any]]


class AgentService:
    """Own the corpus, tool execution and short in-memory conversation state."""

    def __init__(self) -> None:
        require_api_key()
        self.client = OpenAI()
        self.chunks = whole_document_chunks(load_documents())
        self.chunk_embeddings = create_embeddings(
            self.client, [chunk.text for chunk in self.chunks]
        )
        self.timelines = json.loads(TIMELINES_FILE.read_text(encoding="utf-8"))
        self.sessions: dict[str, list[dict[str, str]]] = {}

    def search(self, question: str, top_k: int = 2) -> list[dict[str, Any]]:
        if not question.strip():
            raise ValueError("question cannot be empty.")
        if top_k < 1 or top_k > 5:
            raise ValueError("top_k must be between 1 and 5.")
        query_embedding = create_embeddings(self.client, [question.strip()])[0]
        results = rank_by_embedding(
            self.chunks, self.chunk_embeddings, query_embedding, top_k=top_k
        )
        return [
            {
                "source": result.chunk.source,
                "chunk_id": result.chunk.chunk_id,
                "text": result.chunk.text,
                "score": round(result.score, 3),
            }
            for result in results
        ]

    def execute_tool_call(self, call: Any) -> dict[str, Any]:
        try:
            arguments = json.loads(call.arguments)
        except (TypeError, json.JSONDecodeError):
            return self._tool_error("invalid_arguments", "Arguments are not valid JSON.")
        if not isinstance(arguments, dict):
            return self._tool_error("invalid_arguments", "Arguments must be an object.")

        handlers = {
            "search_documents": self._search_documents,
            "get_mission_timeline": self._get_mission_timeline,
        }
        handler = handlers.get(call.name)
        if handler is None:
            return self._tool_error("unknown_tool", f"Unknown tool: {call.name}")
        try:
            return handler(arguments)
        except ValueError as exc:
            return self._tool_error("invalid_arguments", str(exc))
        except Exception:
            return self._tool_error(
                "execution_failed", "The tool failed. Try another route or explain the failure."
            )

    def chat(self, session_id: str, question: str, max_steps: int = 4) -> AgentReply:
        if not session_id.strip() or not question.strip():
            raise ValueError("session_id and question cannot be empty.")
        if max_steps < 1 or max_steps > 8:
            raise ValueError("max_steps must be between 1 and 8.")

        history = self.sessions.setdefault(session_id, [])
        model_input: list[Any] = [
            *history[-6:],
            {"role": "user", "content": question.strip()},
        ]
        trace: list[dict[str, Any]] = []

        for step in range(1, max_steps + 1):
            response = self.client.responses.create(
                model=GENERATION_MODEL,
                instructions=(
                    "You are a concise Apollo assistant. Use search_documents for "
                    "narrative facts and cite source filenames. Use "
                    "get_mission_timeline for exact dates. Use history only to "
                    "resolve follow-ups. Explain tool errors without inventing data."
                ),
                input=model_input,
                tools=TOOLS,
                parallel_tool_calls=True,
                store=False,
            )
            model_input.extend(response.output)
            calls = [item for item in response.output if item.type == "function_call"]

            if not calls:
                answer = response.output_text.strip()
                if not answer:
                    raise RuntimeError("The model stopped without a final answer.")
                history.extend(
                    [
                        {"role": "user", "content": question.strip()},
                        {"role": "assistant", "content": answer},
                    ]
                )
                return AgentReply(
                    answer=answer,
                    tools_used=[item["tool"] for item in trace],
                    trace=trace,
                )

            for call in calls:
                result = self.execute_tool_call(call)
                trace.append(
                    {
                        "step": step,
                        "tool": call.name,
                        "status": "ok" if result.get("ok") else "error",
                    }
                )
                model_input.append(
                    {
                        "type": "function_call_output",
                        "call_id": call.call_id,
                        "output": json.dumps(result),
                    }
                )

        raise RuntimeError(f"The agent did not finish within {max_steps} steps.")

    def reset(self, session_id: str) -> bool:
        return self.sessions.pop(session_id, None) is not None

    def _search_documents(self, arguments: dict[str, Any]) -> dict[str, Any]:
        question = arguments.get("question")
        if not isinstance(question, str):
            raise ValueError("question must be a string.")
        return {"ok": True, "results": self.search(question)}

    def _get_mission_timeline(self, arguments: dict[str, Any]) -> dict[str, Any]:
        requested = arguments.get("mission")
        if not isinstance(requested, str) or not requested.strip():
            raise ValueError("mission must be a non-empty string.")
        mission = next(
            (
                name
                for name in self.timelines
                if name.casefold() == requested.strip().casefold()
            ),
            None,
        )
        if mission is None:
            return self._tool_error("not_found", f"Mission not found: {requested}")
        return {
            "ok": True,
            "mission": mission,
            "timeline": self.timelines[mission],
        }

    @staticmethod
    def _tool_error(error_type: str, message: str) -> dict[str, Any]:
        return {"ok": False, "error": {"type": error_type, "message": message}}
