"""Complete Session 6 baseline: conversational RAG with isolated sessions."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from openai import OpenAI
from pydantic import BaseModel, Field


SESSIONS_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SESSIONS_DIR))

from rag_course_support import (  # noqa: E402
    GENERATION_MODEL,
    Chunk,
    SearchResult,
    create_embeddings,
    format_context,
    load_documents,
    rank_by_embedding,
    require_api_key,
    whole_document_chunks,
)


load_dotenv()


class TurnPlan(BaseModel):
    route: Literal["retrieval", "history", "clarify"]
    standalone_question: str
    clarification_question: str | None = None


class ChatAnswer(BaseModel):
    answer: str
    sources: list[str] = Field(default_factory=list)


def plan_turn(
    client: OpenAI,
    history: list[dict[str, str]],
    question: str,
) -> TurnPlan:
    response = client.responses.parse(
        model=GENERATION_MODEL,
        instructions=(
            "Plan one conversational turn. Use retrieval for every Apollo factual "
            "question, including a follow-up whose entity can be resolved from "
            "history. Make that question standalone. Use history only to rephrase "
            "or summarize an existing answer. Use clarify when a reference remains "
            "ambiguous, and provide one focused clarification question."
        ),
        input=[*history[-6:], {"role": "user", "content": question}],
        text_format=TurnPlan,
        store=False,
    )
    if response.output_parsed is None:
        raise RuntimeError("The model did not return a parsed turn plan.")
    return response.output_parsed


def retrieve(
    client: OpenAI,
    chunks: list[Chunk],
    chunk_embeddings: list[list[float]],
    question: str,
) -> list[SearchResult]:
    query_embedding = create_embeddings(client, [question])[0]
    return rank_by_embedding(chunks, chunk_embeddings, query_embedding, top_k=2)


def generate_answer(
    client: OpenAI,
    history: list[dict[str, str]],
    question: str,
    results: list[SearchResult],
) -> ChatAnswer:
    if results:
        rule = (
            "Answer only from the evidence. Include only source filenames that "
            "directly support the answer."
        )
        evidence = format_context(results)
    else:
        rule = "Only rephrase or summarize information already in the history."
        evidence = "No documentary evidence was requested for this turn."

    response = client.responses.parse(
        model=GENERATION_MODEL,
        instructions=f"You are a concise Apollo course assistant. {rule}",
        input=[
            *history[-6:],
            {
                "role": "user",
                "content": f"Question:\n{question}\n\nEvidence:\n{evidence}",
            },
        ],
        text_format=ChatAnswer,
        store=False,
    )
    if response.output_parsed is None:
        raise RuntimeError("The model did not return a parsed answer.")

    answer = response.output_parsed
    allowed_sources = {result.chunk.source for result in results}
    if not set(answer.sources).issubset(allowed_sources):
        raise ValueError("The answer cited a source that was not retrieved.")
    return answer


def answer_turn(
    client: OpenAI,
    sessions: dict[str, list[dict[str, str]]],
    session_id: str,
    question: str,
    chunks: list[Chunk],
    chunk_embeddings: list[list[float]],
) -> tuple[TurnPlan, ChatAnswer]:
    if not session_id.strip() or not question.strip():
        raise ValueError("session_id and question cannot be empty.")

    history = sessions.setdefault(session_id, [])
    plan = plan_turn(client, history, question)

    if plan.route == "retrieval":
        if not plan.standalone_question.strip():
            raise ValueError("A retrieval plan requires a standalone question.")
        results = retrieve(client, chunks, chunk_embeddings, plan.standalone_question)
        answer = generate_answer(client, history, question, results)
    elif plan.route == "history":
        answer = generate_answer(client, history, question, [])
    else:
        answer = ChatAnswer(
            answer=plan.clarification_question
            or "Which mission or earlier answer are you referring to?",
            sources=[],
        )

    history.extend(
        [
            {"role": "user", "content": question.strip()},
            {"role": "assistant", "content": answer.answer},
        ]
    )
    return plan, answer


def reset_session(
    sessions: dict[str, list[dict[str, str]]], session_id: str
) -> None:
    sessions.pop(session_id, None)


def print_turn(session_id: str, question: str, plan: TurnPlan, answer: ChatAnswer) -> None:
    print(f"\n[{session_id}] User: {question}")
    print(f"[{session_id}] route={plan.route} | standalone={plan.standalone_question!r}")
    print(f"[{session_id}] Assistant: {answer.answer}")
    if answer.sources:
        print(f"[{session_id}] sources={answer.sources}")


def main() -> None:
    require_api_key()
    client = OpenAI()
    chunks = whole_document_chunks(load_documents())
    embeddings = create_embeddings(client, [chunk.text for chunk in chunks])
    sessions: dict[str, list[dict[str, str]]] = {}
    turns = [
        ("alice", "Which Apollo mission first used the lunar rover?"),
        ("bob", "Why did Apollo 13 not land on the Moon?"),
        ("alice", "How far did it travel?"),
        ("alice", "Repeat that answer more briefly."),
    ]

    for session_id, question in turns:
        plan, answer = answer_turn(
            client, sessions, session_id, question, chunks, embeddings
        )
        print_turn(session_id, question, plan, answer)

    print(
        f"\nBefore reset: alice={len(sessions['alice'])} messages, "
        f"bob={len(sessions['bob'])} messages"
    )
    reset_session(sessions, "alice")
    print(
        f"After reset: alice={len(sessions.get('alice', []))} messages, "
        f"bob={len(sessions['bob'])} messages"
    )


if __name__ == "__main__":
    main()
