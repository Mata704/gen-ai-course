"""Session 5 baseline: run a small, reproducible RAG evaluation."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from time import perf_counter

from dotenv import load_dotenv
from openai import OpenAI
from pydantic import BaseModel, Field


SESSIONS_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SESSIONS_DIR))

from rag_course_support import (  # noqa: E402
    GENERATION_MODEL,
    EvaluationCase,
    SearchResult,
    count_tokens,
    create_embeddings,
    format_context,
    load_documents,
    load_evaluation_cases,
    rank_by_embedding,
    require_api_key,
    source_recall,
    whole_document_chunks,
)


load_dotenv()


class EvaluatedAnswer(BaseModel):
    answer: str
    answerable: bool
    sources: list[str] = Field(default_factory=list)


def fact_coverage(answer: str, expected_facts: tuple[str, ...]) -> float:
    if not expected_facts:
        return 1.0
    normalized = " ".join(answer.casefold().split())
    hits = sum(" ".join(fact.casefold().split()) in normalized for fact in expected_facts)
    return hits / len(expected_facts)


def citation_validity(answer: EvaluatedAnswer, results: list[SearchResult]) -> float:
    retrieved = {result.chunk.source for result in results}
    if not answer.answerable:
        return 1.0 if not answer.sources else 0.0
    if not answer.sources:
        return 0.0
    return 1.0 if set(answer.sources).issubset(retrieved) else 0.0


def generate_answer(
    client: OpenAI, question: str, results: list[SearchResult]
) -> EvaluatedAnswer:
    context = format_context(results)
    response = client.responses.parse(
        model=GENERATION_MODEL,
        input=[
            {
                "role": "system",
                "content": (
                    "Answer only from the supplied context. Set answerable=false "
                    "and return no sources if it is insufficient. Otherwise include "
                    "only source filenames that directly support the answer."
                ),
            },
            {
                "role": "user",
                "content": f"Question:\n{question}\n\nContext:\n{context}",
            },
        ],
        text_format=EvaluatedAnswer,
    )
    if response.output_parsed is None:
        raise RuntimeError("The model did not return a parsed answer.")
    return response.output_parsed


def run_case(
    client: OpenAI,
    case: EvaluationCase,
    chunks,
    chunk_embeddings,
    top_k: int,
) -> dict:
    started = perf_counter()
    query_embedding = create_embeddings(client, [case.question])[0]
    results = rank_by_embedding(chunks, chunk_embeddings, query_embedding, top_k)
    context = format_context(results)
    answer = generate_answer(client, case.question, results)
    elapsed_ms = (perf_counter() - started) * 1000

    return {
        "case_id": case.case_id,
        "critical": case.critical,
        "category": case.category,
        "retrieval_source_recall": source_recall(results, case.expected_sources),
        "fact_coverage": fact_coverage(answer.answer, case.expected_facts),
        "answerability_correct": float(answer.answerable == case.should_answer),
        "citation_validity": citation_validity(answer, results),
        "latency_ms": round(elapsed_ms, 1),
        "context_tokens": count_tokens(context),
        "answerable": answer.answerable,
        "retrieved_sources": [result.chunk.source for result in results],
        "cited_sources": answer.sources,
        "answer": answer.answer,
    }


def print_summary(rows: list[dict]) -> None:
    metric_names = (
        "retrieval_source_recall",
        "fact_coverage",
        "answerability_correct",
        "citation_validity",
        "latency_ms",
        "context_tokens",
    )
    print("\nSUMMARY")
    for metric in metric_names:
        mean = sum(row[metric] for row in rows) / len(rows)
        print(f"{metric}={mean:.3f}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", choices=["development", "holdout", "all"], default="development")
    parser.add_argument("--top-k", type=int, default=2)
    parser.add_argument("--max-cases", type=int)
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    require_api_key()
    if args.top_k < 1:
        raise ValueError("--top-k must be at least 1.")

    cases = load_evaluation_cases()
    if args.split != "all":
        cases = [case for case in cases if case.split == args.split]
    if args.max_cases is not None:
        cases = cases[: args.max_cases]
    if not cases:
        raise ValueError("No evaluation cases selected.")

    client = OpenAI()
    chunks = whole_document_chunks(load_documents())
    chunk_embeddings = create_embeddings(client, [chunk.text for chunk in chunks])
    rows = []
    for case in cases:
        row = run_case(client, case, chunks, chunk_embeddings, args.top_k)
        rows.append(row)
        print(
            f"[{row['case_id']}] retrieval={row['retrieval_source_recall']:.2f} "
            f"facts={row['fact_coverage']:.2f} answerability={row['answerability_correct']:.0f} "
            f"citations={row['citation_validity']:.0f}"
        )
    print_summary(rows)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(rows, indent=2), encoding="utf-8")
        print(f"\nWrote {args.output}")


if __name__ == "__main__":
    main()

