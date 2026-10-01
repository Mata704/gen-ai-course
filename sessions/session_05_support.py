"""Supplied implementation details for the Session 5 experiments."""

from __future__ import annotations

import json
import math
from collections import Counter
from pathlib import Path

from openai import OpenAI

from rag_course_support import (
    Chunk,
    SearchResult,
    create_embeddings,
    load_documents,
    load_evaluation_cases,
    markdown_sections,
    normalize_terms,
    rank_by_embedding,
    source_recall,
)


def _section_chunks() -> list[Chunk]:
    chunks = []
    for document in load_documents():
        for index, (heading, body) in enumerate(markdown_sections(document)):
            chunks.append(Chunk(
                chunk_id=f"{document.source}::section-{index:02d}",
                source=document.source,
                title=heading,
                text=f"Document: {document.title}\nSection: {heading}\n{body}",
            ))
    return chunks


def _lexical_rank(query: str, chunks: list[Chunk], top_k: int) -> list[SearchResult]:
    query_terms = normalize_terms(query)
    tokenized = [normalize_terms(chunk.text) for chunk in chunks]
    document_frequency = Counter(term for terms in tokenized for term in set(terms))
    average_length = sum(map(len, tokenized)) / len(tokenized)
    scored = []
    for chunk, terms in zip(chunks, tokenized, strict=True):
        frequencies = Counter(terms)
        score = 0.0
        for term in query_terms:
            if not frequencies[term]:
                continue
            inverse_frequency = math.log(
                1 + (len(chunks) - document_frequency[term] + 0.5)
                / (document_frequency[term] + 0.5)
            )
            length_factor = 0.25 + 0.75 * len(terms) / average_length
            score += inverse_frequency * (
                frequencies[term] * 2.5 / (frequencies[term] + 1.5 * length_factor)
            )
        if score:
            scored.append(SearchResult(chunk=chunk, score=score))
    return sorted(scored, key=lambda result: result.score, reverse=True)[:top_k]


def _fuse_rankings(
    semantic: list[SearchResult], lexical: list[SearchResult], top_k: int
) -> list[SearchResult]:
    scores: dict[str, float] = {}
    chunks: dict[str, Chunk] = {}
    for ranking in (semantic, lexical):
        for rank, result in enumerate(ranking, start=1):
            chunk_id = result.chunk.chunk_id
            chunks[chunk_id] = result.chunk
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1 / (60 + rank)
    results = [SearchResult(chunks[chunk_id], score) for chunk_id, score in scores.items()]
    return sorted(results, key=lambda result: result.score, reverse=True)[:top_k]


def run_retrieval_comparison(client: OpenAI, split: str, top_k: int) -> list[dict]:
    """Run semantic, lexical and hybrid retrieval over the same cases."""
    chunks = _section_chunks()
    chunk_embeddings = create_embeddings(client, [chunk.text for chunk in chunks])
    comparisons = []
    for case in load_evaluation_cases():
        if case.split != split:
            continue
        query_embedding = create_embeddings(client, [case.question])[0]
        semantic = rank_by_embedding(chunks, chunk_embeddings, query_embedding, max(8, top_k))
        lexical = _lexical_rank(case.question, chunks, max(8, top_k))
        comparisons.append({
            "case": case,
            "rankings": {
                "semantic": semantic[:top_k],
                "lexical": lexical[:top_k],
                "hybrid": _fuse_rankings(semantic, lexical, top_k),
            },
        })
    if not comparisons:
        raise ValueError(f"No evaluation cases found for split '{split}'.")
    return comparisons


def render_retrieval_report(comparisons: list[dict], split: str, top_k: int) -> str:
    """Render rankings as Markdown tables that are also readable in a terminal."""
    lines = [
        f"# Hybrid retrieval comparison — {split}", "",
        f"All methods use the same final top_k: **{top_k}**.",
    ]
    recalls = {method: [] for method in ("semantic", "lexical", "hybrid")}
    for comparison in comparisons:
        case = comparison["case"]
        expected = set(case.expected_sources)
        lines.extend([
            "", f"## {case.case_id}", "", case.question, "",
            f"Expected source: {', '.join(expected) if expected else 'none (test abstention)'}", "",
            "| Method | Rank | Source | Section | Preview | Source found? |",
            "|---|---:|---|---|---|---|",
        ])
        for method, results in comparison["rankings"].items():
            found = "n/a" if not expected else (
                "yes" if expected & {result.chunk.source for result in results} else "no"
            )
            if expected:
                recalls[method].append(source_recall(results, expected))
            for rank, result in enumerate(results, start=1):
                title = result.chunk.title.replace("|", "/")
                preview = " ".join(result.chunk.text.split())[:90].replace("|", "/")
                lines.append(
                    f"| {method} | {rank} | {result.chunk.source} | {title} | {preview} | {found} |"
                )
    lines.extend([
        "", "## Answerable cases: mean source recall", "",
        "| Semantic | Lexical | Hybrid |", "|---:|---:|---:|",
        "| " + " | ".join(f"{sum(values) / len(values):.3f}" for values in recalls.values()) + " |",
        "", "## Questions", "",
        "1. Which method found the most useful chunks? Show one example.",
        "2. Would you use semantic, lexical or hybrid retrieval? Why?",
    ])
    return "\n".join(lines) + "\n"


def compare_rag_versions(cases: list[dict]) -> dict:
    """Calculate the supplied metrics and find candidate regressions."""
    metrics = ("retrieval_recall", "fact_coverage", "answerability", "citation_validity")
    rows = []
    for case in cases:
        for version in ("baseline", "candidate"):
            run = case[version]
            expected_sources = set(case["expected_sources"])
            retrieved_sources = set(run["retrieved_sources"])
            expected_facts = [" ".join(f.casefold().split()) for f in case["expected_facts"]]
            answer = " ".join(run["answer"].casefold().split())
            citations = set(run["citations"])
            rows.append({
                "case_id": case["id"], "version": version, "critical": case["critical"],
                "retrieval_recall": (
                    len(expected_sources & retrieved_sources) / len(expected_sources)
                    if expected_sources else 1.0
                ),
                "fact_coverage": (
                    sum(fact in answer for fact in expected_facts) / len(expected_facts)
                    if expected_facts else 1.0
                ),
                "answerability": float(run["answerable"] == case["should_answer"]),
                "citation_validity": float(
                    (bool(citations) and citations.issubset(retrieved_sources))
                    if run["answerable"] else not citations
                ),
                "latency_ms": run["latency_ms"],
                "context_tokens": run["context_tokens"],
            })
    aggregates = {}
    for version in ("baseline", "candidate"):
        version_rows = [row for row in rows if row["version"] == version]
        aggregates[version] = {
            metric: sum(row[metric] for row in version_rows) / len(version_rows)
            for metric in (*metrics, "latency_ms", "context_tokens")
        }
    regressions = []
    improvements = []
    for case in cases:
        versions = {row["version"]: row for row in rows if row["case_id"] == case["id"]}
        for metric in metrics:
            if versions["candidate"][metric] < versions["baseline"][metric]:
                regressions.append({
                    "case_id": case["id"], "critical": case["critical"], "metric": metric,
                    "baseline": versions["baseline"][metric],
                    "candidate": versions["candidate"][metric],
                })
            elif versions["candidate"][metric] > versions["baseline"][metric]:
                improvements.append({
                    "case_id": case["id"], "metric": metric,
                    "baseline": versions["baseline"][metric],
                    "candidate": versions["candidate"][metric],
                })
    reasons = []
    if aggregates["candidate"]["answerability"] < 0.90:
        reasons.append("candidate answerability is below 0.90")
    if aggregates["candidate"]["citation_validity"] < 0.95:
        reasons.append("candidate citation validity is below 0.95")
    if any(regression["critical"] for regression in regressions):
        reasons.append("candidate has a critical per-case regression")
    return {
        "passed": not reasons,
        "reasons": reasons or ["all quality checks passed"],
        "aggregates": aggregates,
        "improvements": improvements,
        "regressions": regressions,
        "cases": rows,
    }


def render_version_report(report: dict, source_cases: list[dict]) -> str:
    """Render the release evidence as a compact Markdown report."""
    lines = [
        "# RAG version comparison", "",
        f"**Quality gate: {'PASS' if report['passed'] else 'FAIL'}**", "",
        "## Average results", "",
        "| Version | Retrieval | Fact coverage | Answerability | Citation validity | Latency ms | Tokens |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for version, values in report["aggregates"].items():
        lines.append(
            f"| {version} | {values['retrieval_recall']:.3f} | {values['fact_coverage']:.3f} | "
            f"{values['answerability']:.3f} | {values['citation_validity']:.3f} | "
            f"{values['latency_ms']:.1f} | {values['context_tokens']:.1f} |"
        )
    lines.extend([
        "", "## Improvements", "",
        "| Case | Metric | Baseline | Candidate |",
        "|---|---|---:|---:|",
    ])
    for improvement in report["improvements"]:
        lines.append(
            f"| {improvement['case_id']} | {improvement['metric']} | "
            f"{improvement['baseline']:.3f} | {improvement['candidate']:.3f} |"
        )
    lines.extend(["", "## Why the gate failed", ""])
    lines.extend(f"- {reason}" for reason in report["reasons"])
    lines.extend([
        "", "## Regressions", "",
        "| Case | Critical? | Metric | Baseline | Candidate |",
        "|---|---|---|---:|---:|",
    ])
    for regression in report["regressions"]:
        lines.append(
            f"| {regression['case_id']} | {'yes' if regression['critical'] else 'no'} | "
            f"{regression['metric']} | {regression['baseline']:.3f} | {regression['candidate']:.3f} |"
        )
    lines.extend(["", "## Answers and citations to inspect", ""])
    regressed_ids = {item["case_id"] for item in report["regressions"]}
    for case in source_cases:
        if case["id"] in regressed_ids:
            lines.extend([
                f"### {case['id']}", "",
                f"- Baseline: {case['baseline']['answer']}",
                f"- Candidate: {case['candidate']['answer']}",
                f"- Candidate citations: {', '.join(case['candidate']['citations']) or 'none'}", "",
            ])
    lines.extend([
        "Citation validity only checks whether the cited file was retrieved. It does not prove that the file supports the claim.",
        "", "## Questions", "",
        "1. Would you release the candidate? Show one improvement and one serious problem.",
        "2. Does a good metric hide an error in any case? Which one?",
    ])
    return "\n".join(lines) + "\n"


def load_json(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))
