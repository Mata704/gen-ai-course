"""Session 6 exercise 3: build a bounded loop over RAG and a local tool."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI


SESSIONS_DIR = Path(__file__).resolve().parents[2]
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

DATA_FILE = Path(__file__).resolve().parents[1] / "test-data" / "mission-timelines.json"
Timeline = dict[str, str | None]

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
                    "description": "Apollo mission name, for example Apollo 13.",
                }
            },
            "required": ["mission"],
            "additionalProperties": False,
        },
        "strict": True,
    },
]


def load_timelines(path: Path = DATA_FILE) -> dict[str, Timeline]:
    timelines = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(timelines, dict) or not timelines:
        raise ValueError(f"No mission timelines found in {path}")
    return timelines


def execute_tool_call(
    call: Any,
    client: OpenAI,
    chunks: list[Chunk],
    chunk_embeddings: list[list[float]],
    timelines: dict[str, Timeline],
) -> str:
    """Execute either supplied read-only tool and return JSON for the model."""
    try:
        arguments = json.loads(call.arguments)
    except (TypeError, json.JSONDecodeError):
        return json.dumps({"ok": False, "error": "Arguments are not valid JSON."})
    if not isinstance(arguments, dict):
        return json.dumps({"ok": False, "error": "Arguments must be an object."})

    if call.name == "search_documents":
        question = arguments.get("question")
        if not isinstance(question, str) or not question.strip():
            return json.dumps({"ok": False, "error": "question must be a string."})
        query_embedding = create_embeddings(client, [question])[0]
        results = rank_by_embedding(chunks, chunk_embeddings, query_embedding, top_k=2)
        return json.dumps(
            {
                "ok": True,
                "results": [
                    {
                        "source": result.chunk.source,
                        "text": result.chunk.text,
                        "score": round(result.score, 3),
                    }
                    for result in results
                ],
            }
        )

    if call.name == "get_mission_timeline":
        requested = arguments.get("mission")
        if not isinstance(requested, str) or not requested.strip():
            return json.dumps({"ok": False, "error": "mission must be a string."})
        mission = next(
            (name for name in timelines if name.casefold() == requested.strip().casefold()),
            None,
        )
        if mission is None:
            return json.dumps({"ok": False, "error": f"Mission not found: {requested}"})
        return json.dumps(
            {"ok": True, "mission": mission, "timeline": timelines[mission]}
        )

    return json.dumps({"ok": False, "error": f"Unknown tool: {call.name}"})


def run_agent_loop(
    client: OpenAI,
    question: str,
    history: list[dict[str, str]],
    chunks: list[Chunk],
    chunk_embeddings: list[list[float]],
    timelines: dict[str, Timeline],
    max_steps: int = 3,
) -> tuple[str, list[str]]:
    """Run tools until the model answers or the explicit step limit is reached."""
    raise NotImplementedError


def main() -> None:
    require_api_key()
    client = OpenAI()
    chunks = whole_document_chunks(load_documents())
    embeddings = create_embeddings(client, [chunk.text for chunk in chunks])
    timelines = load_timelines()
    history: list[dict[str, str]] = []

    questions = [
        "Why was Apollo 13 described as a successful failure?",
        "When did that mission launch and splash down?",
    ]
    for question in questions:
        answer, trace = run_agent_loop(
            client, question, history, chunks, embeddings, timelines
        )
        print(f"\nUser: {question}")
        print(f"Tools used: {trace or ['none']}")
        print(f"Assistant: {answer}")


if __name__ == "__main__":
    main()
