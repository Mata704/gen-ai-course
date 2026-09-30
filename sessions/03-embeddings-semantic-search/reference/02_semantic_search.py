"""Session 3 reference solution: semantic search without a vector DB."""

import argparse
import json
import math
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI


load_dotenv()

EMBEDDING_MODEL = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
DEFAULT_MIN_SCORE = float(os.getenv("MIN_SIMILARITY", "0.50"))
SESSION_DIR = Path(__file__).resolve().parent.parent
DOCUMENTS_DIR = (
    Path(__file__).resolve().parents[3]
    / "projects"
    / "course-01-generative-ai"
    / "knowledge-copilot"
    / "data"
    / "documents"
)
EVALUATION_CASES_PATH = SESSION_DIR / "test-data" / "search-cases.json"


@dataclass(frozen=True)
class Passage:
    """A prepared passage and the embedding used to search it."""

    source: str
    text: str
    embedding: list[float]


@dataclass(frozen=True)
class SearchResult:
    """One passage ranked by semantic similarity."""

    source: str
    text: str
    score: float


@dataclass(frozen=True)
class SearchOutcome:
    """The ranked evidence and the decision to use it or abstain."""

    has_enough_context: bool
    message: str
    results: list[SearchResult]


@dataclass(frozen=True)
class EvaluationCase:
    """One labelled query used to evaluate retrieval behaviour."""

    question: str
    expected_source: str | None


def load_texts() -> list[tuple[str, str]]:
    """Load the supplied documents; each file is one passage in this session."""
    return [
        (path.name, path.read_text(encoding="utf-8"))
        for path in sorted(DOCUMENTS_DIR.glob("*.md"))
    ]


def load_evaluation_cases() -> list[EvaluationCase]:
    """Load labelled questions without mixing them into the search corpus."""
    raw_cases = json.loads(EVALUATION_CASES_PATH.read_text(encoding="utf-8"))
    return [
        EvaluationCase(
            question=case["question"], expected_source=case["expected_source"]
        )
        for case in raw_cases
    ]


def create_embeddings(client: OpenAI, texts: list[str]) -> list[list[float]]:
    """Create vectors for a batch of text inputs."""
    response = client.embeddings.create(model=EMBEDDING_MODEL, input=texts)
    return [item.embedding for item in response.data]


def cosine_similarity(left: list[float], right: list[float]) -> float:
    """Return the cosine similarity between two non-empty, non-zero vectors."""
    if len(left) != len(right):
        raise ValueError("Vectors must have the same number of dimensions.")
    if not left:
        raise ValueError("Vectors must not be empty.")

    left_magnitude = math.sqrt(sum(value * value for value in left))
    right_magnitude = math.sqrt(sum(value * value for value in right))
    if left_magnitude == 0 or right_magnitude == 0:
        raise ValueError("Vectors must have non-zero magnitude.")

    dot_product = sum(left_value * right_value for left_value, right_value in zip(
        left, right, strict=True
    ))
    return dot_product / (left_magnitude * right_magnitude)


def rank_passages(
    passages: list[Passage], query_embedding: list[float], top_k: int = 3
) -> list[SearchResult]:
    """Return the top_k passages ordered from highest to lowest similarity."""
    if top_k < 1:
        raise ValueError("top_k must be at least 1.")

    results = [
        SearchResult(
            source=passage.source,
            text=passage.text,
            score=cosine_similarity(passage.embedding, query_embedding),
        )
        for passage in passages
    ]
    results.sort(key=lambda result: result.score, reverse=True)
    return results[:top_k]


def decide_search_outcome(
    results: list[SearchResult], min_score: float
) -> SearchOutcome:
    has_enough_context = bool(results) and results[0].score >= min_score
 
    return SearchOutcome(
        has_enough_context=has_enough_context,
        message= "Contexto Suficiente."
                if has_enough_context
                else "Sem contexto suficiente, abster de responder.",
        results=results,
    )


def search_passages(
    passages: list[Passage],
    query_embedding: list[float],
    top_k: int,
    min_score: float,
) -> SearchOutcome:
    """Run ranking and the evidence decision as one search operation."""
    results = rank_passages(passages, query_embedding, top_k=top_k)
    return decide_search_outcome(results, min_score=min_score)


def evaluate_search(
    client: OpenAI,
    passages: list[Passage],
    cases: list[EvaluationCase],
    top_k: int,
    min_score: float,
) -> None:
    """Report whether each expected source, or expected abstention, is correct."""
    query_embeddings = create_embeddings(client, [case.question for case in cases])
    passed = 0

    for case, query_embedding in zip(cases, query_embeddings, strict=True):
        outcome = search_passages(passages, query_embedding, top_k, min_score)
        returned_sources = {result.source for result in outcome.results}

        if case.expected_source is None:
            case_passed = not outcome.has_enough_context
            expected = "abstain"
        else:
            case_passed = (
                outcome.has_enough_context
                and case.expected_source in returned_sources
            )
            expected = case.expected_source

        passed += int(case_passed)
        status = "PASS" if case_passed else "FAIL"
        best_score = outcome.results[0].score if outcome.results else float("nan")
        print(f"{status}  best={best_score:.3f}  expected={expected}")
        print(f"      {case.question}")

    print(f"\nPassed: {passed}/{len(cases)}")
    print(f"Configuration: top_k={top_k}, min_score={min_score:.2f}")


def print_outcome(outcome: SearchOutcome) -> None:
    """Print the decision first and keep candidate scores visible."""
    print(f"\n{outcome.message}\n")
    for result in outcome.results:
        print(f"{result.score:.3f}  {result.source}")
        print(f"{result.text.strip()}\n")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--query", help="Question to search for.")
    parser.add_argument(
        "--evaluate",
        action="store_true",
        help="Run all labelled search cases instead of one question.",
    )
    parser.add_argument("--top-k", type=int, default=3)
    parser.add_argument("--min-score", type=float, default=DEFAULT_MIN_SCORE)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("Set OPENAI_API_KEY in your local .env file first.")

    client = OpenAI()
    source_texts = load_texts()
    document_embeddings = create_embeddings(
        client, [text for _, text in source_texts]
    )
    passages = [
        Passage(source=source, text=text, embedding=embedding)
        for (source, text), embedding in zip(
            source_texts, document_embeddings, strict=True
        )
    ]

    if args.evaluate:
        evaluate_search(
            client,
            passages,
            load_evaluation_cases(),
            top_k=args.top_k,
            min_score=args.min_score,
        )
        return

    question = (
        args.query or input("Ask a question about the Apollo missions: ")
    ).strip()
    if not question:
        raise ValueError("Please enter a question.")

    query_embedding = create_embeddings(client, [question])[0]
    outcome = search_passages(
        passages,
        query_embedding,
        top_k=args.top_k,
        min_score=args.min_score,
    )
    print_outcome(outcome)


if __name__ == "__main__":
    main()