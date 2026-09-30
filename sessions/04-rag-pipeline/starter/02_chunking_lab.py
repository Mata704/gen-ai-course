"""Session 4 challenge: compare fixed-size and structure-aware chunking."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI


SESSIONS_DIR = Path(__file__).resolve().parents[2]
SESSION_DIR = Path(__file__).resolve().parents[1]
DEFAULT_CHUNKS_DIR = SESSION_DIR / "chunks"
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


def _validate_sizes(chunk_words: int, overlap_words: int) -> int:
    if chunk_words < 1:
        raise ValueError("chunk_words must be at least 1.")
    if overlap_words < 0 or overlap_words >= chunk_words:
        raise ValueError("overlap_words must be >= 0 and smaller than chunk_words.")
    return chunk_words - overlap_words


def fixed_size_chunks(
    documents: list[Document], chunk_words: int, overlap_words: int
) -> list[Chunk]:
    """Split documents into overlapping word windows with stable IDs."""

    raise NotImplementedError


def structure_aware_chunks(
    documents: list[Document], chunk_words: int, overlap_words: int
) -> list[Chunk]:
    """Split by Markdown section, adding document and section headings."""
    raise NotImplementedError


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
        top_chunks = ", ".join(
            f"{result.chunk.chunk_id} ({result.score:.3f})" for result in results
        )
        recall_label = f"{recall:.2f}" if case.expected_sources else "n/a"
        print(
            f"[{case.case_id}] recall={recall_label} | "
            f"expected={list(case.expected_sources)} | retrieved={top_chunks}"
        )

    print(f"mean_source_recall={sum(recalls) / len(recalls):.3f}")


def write_chunks(
    output_dir: Path,
    strategy: str,
    chunks: list[Chunk],
    chunk_words: int,
    overlap_words: int,
) -> Path:
    """Save the chunks as Markdown, grouped by document, for visual comparison."""
    lines = [
        f"# {strategy} chunks",
        "",
        f"chunk_words={chunk_words} · overlap_words={overlap_words} · {len(chunks)} chunks",
    ]
    current_source = None
    for chunk in chunks:
        if chunk.source != current_source:
            current_source = chunk.source
            lines += ["", f"## {chunk.source}"]
        chunk_label = chunk.chunk_id.split("::", 1)[1]
        lines += [
            "",
            f"**{chunk_label}** · {len(chunk.text.split())} words",
            "",
            "```text",
            chunk.text,
            "```",
        ]

    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{strategy}-{chunk_words}w-{overlap_words}o.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--strategy", choices=["fixed", "structure", "both"], default="both")
    parser.add_argument("--chunk-words", type=int, default=90)
    parser.add_argument("--overlap-words", type=int, default=20)
    parser.add_argument("--top-k", type=int, default=2)
    parser.add_argument("--export-strategy", choices=["fixed", "structure"])
    parser.add_argument(
        "--save-chunks",
        action="store_true",
        help="Save each strategy's chunks to Markdown so they can be compared.",
    )
    parser.add_argument("--chunks-dir", type=Path, default=DEFAULT_CHUNKS_DIR)
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
    if args.save_chunks:
        for strategy, chunks in created.items():
            path = write_chunks(
                args.chunks_dir, strategy, chunks, args.chunk_words, args.overlap_words
            )
            print(f"chunks_saved={path}")
    if args.export_strategy:
        if args.export_strategy not in created:
            raise ValueError("--export-strategy must be included in --strategy.")
        save_chunks(created[args.export_strategy])
        print(f"exported_strategy={args.export_strategy}")


if __name__ == "__main__":
    main()
