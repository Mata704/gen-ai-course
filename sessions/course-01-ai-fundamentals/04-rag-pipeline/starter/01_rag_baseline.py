"""Session 4 baseline: a complete RAG pipeline with inspectable evidence."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import chromadb
from dotenv import load_dotenv
from openai import OpenAI
from pydantic import BaseModel, Field


SESSIONS_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SESSIONS_DIR))

from rag_course_support import (  # noqa: E402
    GENERATION_MODEL,
    SearchResult,
    create_embeddings,
    format_context,
    load_documents,
    load_pdf_documents,
    require_api_key,
    whole_document_chunks,
)


load_dotenv()


class BaselineAnswer(BaseModel):
    answer: str
    answerable: bool
    sources: list[str] = Field(default_factory=list)


def build_collection(chunks, embeddings):
    """Store the baseline chunks in a disposable local vector collection."""
    collection = chromadb.EphemeralClient().get_or_create_collection(
        name="session_04_baseline",
        metadata={"hnsw:space": "cosine"},
    )
    collection.upsert(
        ids=[chunk.chunk_id for chunk in chunks],
        documents=[chunk.text for chunk in chunks],
        embeddings=embeddings,
        metadatas=[
            {"source": chunk.source, "title": chunk.title} for chunk in chunks
        ],
    )
    return collection


def retrieve(collection, chunks_by_id, query_embedding, top_k: int) -> list[SearchResult]:
    raw = collection.query(
        query_embeddings=[query_embedding],
        n_results=min(top_k, collection.count()),
        include=["distances"],
    )
    ids = raw["ids"][0]
    distances = raw["distances"][0]
    return [
        SearchResult(chunk=chunks_by_id[chunk_id], score=1.0 - distance)
        for chunk_id, distance in zip(ids, distances, strict=True)
    ]


def generate_answer(client: OpenAI, question: str, results: list[SearchResult]) -> BaselineAnswer:
    context = format_context(results)
    response = client.responses.parse(
        model=GENERATION_MODEL,
        input=[
            {
                "role": "system",
                "content": (
                    "Answer only from the supplied context. If the context does not "
                    "support the answer, set answerable=false and say that the corpus "
                    "does not contain enough information. List only source filenames "
                    "that directly support the answer."
                ),
            },
            {
                "role": "user",
                "content": f"Question:\n{question}\n\nContext:\n{context}",
            },
        ],
        text_format=BaselineAnswer,
    )
    if response.output_parsed is None:
        raise RuntimeError("The model did not return a parsed answer.")
    return response.output_parsed


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--query", required=True)
    parser.add_argument("--top-k", type=int, default=3)
    parser.add_argument("--show-context", action="store_true")
    parser.add_argument("--show-loaded-pdf", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.top_k < 1:
        raise ValueError("--top-k must be at least 1.")
    require_api_key()

    client = OpenAI()
    pdf_documents = load_pdf_documents()
    documents = [*load_documents(), *pdf_documents]
    if args.show_loaded_pdf:
        for document in pdf_documents:
            print(f"\nPDF CONVERTED TO MARKDOWN: {document.source}\n{document.text}")
    chunks = whole_document_chunks(documents)
    chunk_embeddings = create_embeddings(client, [chunk.text for chunk in chunks])
    collection = build_collection(chunks, chunk_embeddings)
    query_embedding = create_embeddings(client, [args.query])[0]
    results = retrieve(
        collection,
        {chunk.chunk_id: chunk for chunk in chunks},
        query_embedding,
        args.top_k,
    )

    print("\nRETRIEVAL")
    for rank, result in enumerate(results, start=1):
        print(f"{rank}. {result.chunk.source} | score={result.score:.3f}")

    if args.show_context:
        print(f"\nAUGMENTED CONTEXT\n{format_context(results)}")

    answer = generate_answer(client, args.query, results)
    print("\nGENERATION")
    print(f"answerable={answer.answerable}")
    print(answer.answer)
    print(f"sources={answer.sources}")


if __name__ == "__main__":
    main()
