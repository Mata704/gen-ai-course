"""Session 4 challenge: compare fixed-size and structure-aware chunking."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI


SESSIONS_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SESSIONS_DIR))

from rag_course_support import (  # noqa: E402
    Chunk,
    Document,
    create_embeddings,
    load_documents,
    load_evaluation_cases,
    markdown_sections,
    rank_by_embedding,
    require_api_key,
    save_chunks,
    source_recall,
)


load_dotenv()


def fixed_size_chunks(
    documents: list[Document], chunk_words: int, overlap_words: int
) -> list[Chunk]:
    """Split documents into overlapping word windows with stable IDs."""

    if chunk_words < 1:
        raise ValueError("chunk_words must be at least 1.")
    if overlap_words < 0 or overlap_words >= chunk_words:
        raise ValueError("overlap_words must be between 0 and chunk_words - 1.")

    chunks: list[Chunk] = []
    step = chunk_words - overlap_words
    for document in documents:
        words = document.text.split()
        for start in range(0, len(words), step):
            text = " ".join(words[start : start + chunk_words])
            if not text:
                continue
            chunk_number = start // step + 1
            chunks.append(
                Chunk(
                    chunk_id=f"{document.source}::fixed:{chunk_number:04d}",
                    source=document.source,
                    title=document.title,
                    text=text,
                )
            )
    return chunks


def structure_aware_chunks(
    documents: list[Document], chunk_words: int, overlap_words: int
) -> list[Chunk]:
    """Split by Markdown section, adding document and section headings."""
    if chunk_words < 1:
        raise ValueError("chunk_words must be at least 1.")
    if overlap_words < 0 or overlap_words >= chunk_words:
        raise ValueError("overlap_words must be between 0 and chunk_words - 1.")

    chunks: list[Chunk] = []
    step = chunk_words - overlap_words
    for document in documents:
        for section_number, (heading, content) in enumerate(
            markdown_sections(document), start=1
        ):
            words = content.split()
            for start in range(0, len(words), step):
                body = " ".join(words[start : start + chunk_words])
                if not body:
                    continue
                contextual_heading = (
                    document.title if heading == document.title
                    else f"{document.title} > {heading}"
                )
                chunk_number = start // step + 1
                chunks.append(
                    Chunk(
                        chunk_id=(
                            f"{document.source}::section:{section_number:03d}"
                            f":chunk:{chunk_number:03d}"
                        ),
                        source=document.source,
                        title=document.title,
                        text=f"{contextual_heading}\n\n{body}",
                    )
                )
    return chunks


def evaluate_strategy(
    client: OpenAI,
    name: str,
    chunks: list[Chunk],
    top_k: int,
) -> None:
    cases = [case for case in load_evaluation_cases() if case.split == "development"]
    chunk_embeddings = create_embeddings(client, [chunk.text for chunk in chunks])
    sizes = [len(chunk.text.split()) for chunk in chunks]
    recalls: list[float] = []

    print(f"\n{name.upper()}: {len(chunks)} chunks | words min/avg/max="
          f"{min(sizes)}/{sum(sizes) / len(sizes):.1f}/{max(sizes)}")
    for case in cases:
        query_embedding = create_embeddings(client, [case.question])[0]
        results = rank_by_embedding(chunks, chunk_embeddings, query_embedding, top_k)
        recall = source_recall(results, case.expected_sources)
        if case.expected_sources:
            recalls.append(recall)
        top_sources = ", ".join(result.chunk.source for result in results)
        recall_label = f"{recall:.2f}" if case.expected_sources else "n/a"
        print(
            f"[{case.case_id}] recall={recall_label} | "
            f"expected={list(case.expected_sources)} | retrieved={top_sources}"
        )

    print(f"mean_source_recall={sum(recalls) / len(recalls):.3f}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--strategy", choices=["fixed", "structure", "both"], default="both")
    parser.add_argument("--chunk-words", type=int, default=90)
    parser.add_argument("--overlap-words", type=int, default=20)
    parser.add_argument("--top-k", type=int, default=2)
    parser.add_argument("--export-strategy", choices=["fixed", "structure"])
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    require_api_key()
    documents = load_documents()
    client = OpenAI()
    created: dict[str, list[Chunk]] = {}

    if args.strategy in {"fixed", "both"}:
        created["fixed"] = fixed_size_chunks(documents, args.chunk_words, args.overlap_words)
        evaluate_strategy(
            client,
            "fixed-size",
            created["fixed"],
            args.top_k,
        )
    if args.strategy in {"structure", "both"}:
        created["structure"] = structure_aware_chunks(documents, args.chunk_words, args.overlap_words)
        evaluate_strategy(
            client,
            "structure-aware",
            created["structure"],
            args.top_k,
        )
    if args.export_strategy:
        if args.export_strategy not in created:
            raise ValueError("--export-strategy must be included in --strategy.")
        save_chunks(created[args.export_strategy])
        print(f"exported_strategy={args.export_strategy}")


if __name__ == "__main__":
    main()
