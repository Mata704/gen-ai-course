"""Shared building blocks for the Session 4 and 5 RAG exercises.

The exercise files keep the decisions students must make. This module keeps
the repetitive plumbing (loading data, API calls, vector math and display)
out of the way so each exercise can focus on one learning objective.
"""

from __future__ import annotations

import json
import math
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

import tiktoken
from openai import OpenAI


REPO_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = (
    REPO_ROOT
    / "projects"
    / "course-01-generative-ai"
    / "knowledge-copilot"
)
CORPUS_DIR = PROJECT_ROOT / "data" / "rag-corpus"
PDF_CORPUS_DIR = PROJECT_ROOT / "data" / "rag-corpus-pdf"
EVALUATION_FILE = PROJECT_ROOT / "data" / "evaluations" / "rag_cases.json"
SESSION_04_CHUNKS_FILE = REPO_ROOT / ".chroma" / "session-04-chunks.json"

EMBEDDING_MODEL = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
GENERATION_MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")


@dataclass(frozen=True)
class Document:
    source: str
    title: str
    text: str


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    source: str
    title: str
    text: str


@dataclass(frozen=True)
class SearchResult:
    chunk: Chunk
    score: float


@dataclass(frozen=True)
class EvaluationCase:
    case_id: str
    question: str
    expected_sources: tuple[str, ...]
    expected_sections: tuple[str, ...]
    expected_facts: tuple[str, ...]
    should_answer: bool
    critical: bool
    split: str
    category: str


def load_documents(directory: Path = CORPUS_DIR) -> list[Document]:
    """Load the teaching Markdown corpus in a stable order."""
    documents: list[Document] = []
    for path in sorted(directory.glob("*.md")):
        text = path.read_text(encoding="utf-8").strip()
        first_line = text.splitlines()[0] if text else path.stem
        title = first_line.lstrip("# ").strip()
        documents.append(Document(source=path.name, title=title, text=text))
    if not documents:
        raise FileNotFoundError(f"No Markdown documents found in {directory}")
    return documents


def load_pdf_documents(directory: Path = PDF_CORPUS_DIR) -> list[Document]:
    """Convert the supplied PDF example to Markdown before retrieval."""
    import pymupdf4llm

    documents: list[Document] = []
    for path in sorted(directory.glob("*.pdf")):
        text = pymupdf4llm.to_markdown(str(path)).strip()
        if not text:
            raise ValueError(f"No text was extracted from {path}")
        heading = next((line for line in text.splitlines() if line.startswith("# ")), path.stem)
        title = heading.lstrip("# *").rstrip("* ").strip()
        documents.append(Document(source=path.name, title=title, text=text))
    return documents


def save_chunks(chunks: list[Chunk], path: Path = SESSION_04_CHUNKS_FILE) -> None:
    """Pass the chosen Session 4 chunks from exercise 2 to exercise 3."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps([asdict(chunk) for chunk in chunks], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_chunks(path: Path = SESSION_04_CHUNKS_FILE) -> list[Chunk]:
    """Load the chunks created by exercise 2, retaining citation identity."""
    if not path.is_file():
        raise FileNotFoundError(
            f"No chunks found at {path}. Complete exercise 2 and export a strategy first."
        )
    raw_chunks = json.loads(path.read_text(encoding="utf-8"))
    chunks = [Chunk(**item) for item in raw_chunks]
    if not chunks:
        raise ValueError(f"No chunks found in {path}")
    ids = [chunk.chunk_id for chunk in chunks]
    if len(ids) != len(set(ids)):
        raise ValueError(f"Duplicate chunk IDs found in {path}")
    return chunks


def load_evaluation_cases(path: Path = EVALUATION_FILE) -> list[EvaluationCase]:
    """Load labelled RAG cases shared by both sessions."""
    raw_cases = json.loads(path.read_text(encoding="utf-8"))
    return [
        EvaluationCase(
            case_id=item["id"],
            question=item["question"],
            expected_sources=tuple(item["expected_sources"]),
            expected_sections=tuple(item.get("expected_sections", [])),
            expected_facts=tuple(item["expected_facts"]),
            should_answer=item["should_answer"],
            critical=item["critical"],
            split=item["split"],
            category=item["category"],
        )
        for item in raw_cases
    ]


def whole_document_chunks(documents: Iterable[Document]) -> list[Chunk]:
    """Create one deliberately simple baseline chunk per document."""
    return [
        Chunk(
            chunk_id=f"{document.source}::document",
            source=document.source,
            title=document.title,
            text=document.text,
        )
        for document in documents
    ]


def markdown_sections(document: Document) -> list[tuple[str, str]]:
    """Split a Markdown document into (heading, content) sections."""
    sections: list[tuple[str, str]] = []
    heading = document.title
    body: list[str] = []

    for line in document.text.splitlines():
        if re.match(r"^#{2,6}\s+", line):
            if body and "\n".join(body).strip():
                sections.append((heading, "\n".join(body).strip()))
            heading = line.lstrip("# ").strip()
            body = []
        elif not line.startswith("# "):
            body.append(line)

    if body and "\n".join(body).strip():
        sections.append((heading, "\n".join(body).strip()))
    return sections


def create_embeddings(client: OpenAI, texts: list[str]) -> list[list[float]]:
    """Embed a batch of texts with one API request."""
    if not texts:
        return []
    response = client.embeddings.create(model=EMBEDDING_MODEL, input=texts)
    return [item.embedding for item in response.data]


def cosine_similarity(left: list[float], right: list[float]) -> float:
    """Return cosine similarity and reject invalid vector pairs."""
    if not left or not right or len(left) != len(right):
        raise ValueError("Vectors must be non-empty and have the same dimensions.")
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        raise ValueError("Cosine similarity is undefined for a zero vector.")
    return sum(a * b for a, b in zip(left, right, strict=True)) / (
        left_norm * right_norm
    )


def rank_by_embedding(
    chunks: list[Chunk],
    chunk_embeddings: list[list[float]],
    query_embedding: list[float],
    top_k: int,
) -> list[SearchResult]:
    """Rank chunks by semantic similarity."""
    if top_k < 1:
        raise ValueError("top_k must be at least 1.")
    if len(chunks) != len(chunk_embeddings):
        raise ValueError("Every chunk must have exactly one embedding.")

    results = [
        SearchResult(chunk=chunk, score=cosine_similarity(query_embedding, vector))
        for chunk, vector in zip(chunks, chunk_embeddings, strict=True)
    ]
    return sorted(results, key=lambda result: result.score, reverse=True)[:top_k]


def count_tokens(text: str, model: str = GENERATION_MODEL) -> int:
    """Count tokens, falling back to a general encoding for unknown models."""
    try:
        encoding = tiktoken.encoding_for_model(model)
    except KeyError:
        encoding = tiktoken.get_encoding("cl100k_base")
    return len(encoding.encode(text))


def format_context(results: Iterable[SearchResult]) -> str:
    """Format retrieval results with stable citation labels."""
    blocks = []
    for result in results:
        blocks.append(
            f"[SOURCE: {result.chunk.source} | CHUNK: {result.chunk.chunk_id}]\n"
            f"{result.chunk.text}"
        )
    return "\n\n---\n\n".join(blocks)


def source_recall(results: Iterable[SearchResult], expected_sources: Iterable[str]) -> float:
    """Measure how many expected source files occur in retrieved results."""
    expected = set(expected_sources)
    if not expected:
        return 1.0
    retrieved = {result.chunk.source for result in results}
    return len(expected & retrieved) / len(expected)


def normalize_terms(text: str) -> list[str]:
    """Tokenize text for the small lexical baseline used in Session 5."""
    return re.findall(r"[a-z0-9]+", text.casefold())


def require_api_key() -> None:
    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("Set OPENAI_API_KEY in your local .env file first.")
