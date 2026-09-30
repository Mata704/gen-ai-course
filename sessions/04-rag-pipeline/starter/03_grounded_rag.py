"""Session 4 challenge: budget context and validate grounded citations."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI
from pydantic import BaseModel, Field


SESSIONS_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SESSIONS_DIR))

from rag_course_support import (  # noqa: E402
    GENERATION_MODEL,
    SESSION_04_CHUNKS_FILE,
    SearchResult,
    count_tokens,
    create_embeddings,
    format_context,
    load_chunks,
    rank_by_embedding,
    require_api_key,
)


load_dotenv()


class Citation(BaseModel):
    source: str
    chunk_id: str
    quote: str = Field(description="A short verbatim quotation from the cited chunk")


class GroundedAnswer(BaseModel):
    answer: str
    answerable: bool
    citations: list[Citation] = Field(default_factory=list)


def select_context(
    ranked_results: list[SearchResult],
    max_tokens: int,
    min_score: float,
) -> list[SearchResult]:
    """Keep ranked evidence above threshold while respecting a token budget."""
    if max_tokens < 1:
        raise ValueError("max_tokens must be at least 1.")
    selected: list[SearchResult] = []
    for result in ranked_results:
        if result.score < min_score:
            continue
        candidate = [*selected, result]
        if count_tokens(format_context(candidate)) <= max_tokens:
            selected.append(result)
    return selected


def generate_grounded_answer(
    client: OpenAI,
    question: str,
    selected_results: list[SearchResult],
) -> GroundedAnswer:
    """Generate one structured answer constrained to the selected evidence."""
    context = format_context(selected_results) or "No evidence was selected."
    response = client.responses.parse(
        model=GENERATION_MODEL,
        input=[
            {
                "role": "system",
                "content": (
                    "Use only the supplied evidence. Do not use background knowledge. "
                    "If the evidence is insufficient, set answerable=false, explain "
                    "that the corpus is insufficient, and return no citations. If it "
                    "is sufficient, cite every material claim. Each citation must use "
                    "the exact source and chunk ID and a short verbatim quote."
                ),
            },
            {
                "role": "user",
                "content": f"Question:\n{question}\n\nEvidence:\n{context}",
            },
        ],
        text_format=GroundedAnswer,
    )
    if response.output_parsed is None:
        raise RuntimeError("The model did not return a parsed answer.")
    return response.output_parsed

def _normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().casefold()

def validate_citations(
    answer: GroundedAnswer,
    selected_results: list[SearchResult],
) -> list[str]:
    """Return validation errors instead of trusting model citations blindly."""
    errors: list[str] = []
    available = {
        (result.chunk.source, result.chunk.chunk_id): result.chunk.text
        for result in selected_results
    }

    if answer.answerable and not answer.citations:
        errors.append("An answerable response must include at least one citation.")
    if not answer.answerable and answer.citations:
        errors.append("An abstention must not include citations.")

    for citation in answer.citations:
        key = (citation.source, citation.chunk_id)
        if key not in available:
            errors.append(f"Unknown citation target: {citation.source} / {citation.chunk_id}")
            continue
        quote = _normalize_whitespace(citation.quote)
        chunk_text = _normalize_whitespace(available[key])
        if not quote:
            errors.append(f"Empty quote for {citation.chunk_id}")
        elif quote not in chunk_text:
            errors.append(f"Quote does not occur in {citation.chunk_id}: {citation.quote!r}")
    return errors


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--query", required=True)
    parser.add_argument("--top-k", type=int, default=4)
    parser.add_argument("--min-score", type=float, default=0.15)
    parser.add_argument("--max-context-tokens", type=int, default=600)
    parser.add_argument("--chunks-file", type=Path, default=SESSION_04_CHUNKS_FILE)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    require_api_key()
    client = OpenAI()
    chunks = load_chunks(args.chunks_file)
    chunk_embeddings = create_embeddings(client, [chunk.text for chunk in chunks])
    query_embedding = create_embeddings(client, [args.query])[0]
    ranked = rank_by_embedding(chunks, chunk_embeddings, query_embedding, args.top_k)
    selected = select_context(ranked, args.max_context_tokens, args.min_score)

    print("\nSELECTED CONTEXT")
    for result in selected:
        print(f"- {result.chunk.chunk_id} | score={result.score:.3f}")
    print(f"context_tokens={count_tokens(format_context(selected))}")

    answer = generate_grounded_answer(client, args.query, selected)
    errors = validate_citations(answer, selected)

    print("\nANSWER")
    print(f"answerable={answer.answerable}")
    print(answer.answer)
    for citation in answer.citations:
        print(f"- {citation.source} / {citation.chunk_id}: {citation.quote}")

    print("\nVALIDATION")
    print("PASS" if not errors else "FAIL")
    for error in errors:
        print(f"- {error}")


if __name__ == "__main__":
    main()
