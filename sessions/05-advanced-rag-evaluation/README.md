# Session 5 — Advanced RAG and Evaluation

This session starts from the Session 4 baseline and asks a harder question:
how do we know that a change made the RAG system better rather than merely
different?

The core loop is:

`define cases → run baseline → diagnose failures → change one component → compare → gate`

Run commands from the repository root after `uv sync` and after setting
`OPENAI_API_KEY` in a local `.env` file when the exercise uses the API.

## 1. Evaluate the baseline

`01_evaluate_rag_baseline.py` is complete. It runs the development cases and
reports retrieval source recall, expected-fact coverage, answerability accuracy,
citation validity, latency and prompt tokens.

```bash
uv run python sessions/05-advanced-rag-evaluation/starter/01_evaluate_rag_baseline.py --split development
```

Run the holdout cases only after making a decision on the development set:

```bash
uv run python sessions/05-advanced-rag-evaluation/starter/01_evaluate_rag_baseline.py --split holdout
```

There is nothing to implement. Before changing the system, identify whether
each failure belongs to retrieval, context selection, generation, citation or
the evaluation rule itself.

## 2. Implement hybrid retrieval

`02_hybrid_retrieval.py` prepares contextual section chunks and semantic
ranking. Implement:

- `lexical_rank`: a small BM25-style ranker that rewards exact terms while
  accounting for document frequency and chunk length;
- `reciprocal_rank_fusion`: merge semantic and lexical rankings without
  comparing incompatible raw score scales, and deduplicate by `chunk_id`.

```bash
uv run python sessions/05-advanced-rag-evaluation/starter/02_hybrid_retrieval.py --top-k 3
```

Inspect exact identifiers and numbers separately from paraphrases. Hybrid
retrieval is useful only if it improves important cases without creating new
failures elsewhere.

The exercise is complete when:

- lexical ranking handles repeated terms and rare exact identifiers;
- fusion uses rank positions, not raw semantic and lexical scores;
- duplicate chunks appear only once;
- semantic and hybrid source recall are shown case by case;
- students can explain at least one improvement and one unchanged/failing case.

## 3. Compare versions and enforce a quality gate

`03_compare_rag_versions.py` is deliberately offline: the supplied fixture
freezes two RAG runs so every student diagnoses the same evidence without
spending API calls. Implement:

- `evaluate_case`: score retrieval recall, fact coverage, answerability and
  citation validity for both versions;
- `aggregate_metrics`: compute version-level means without mixing latency into
  quality scores;
- `find_regressions`: surface per-case quality drops, especially critical ones;
- `passes_quality_gate`: make an explicit release decision using the supplied
  thresholds.

```bash
uv run python sessions/05-advanced-rag-evaluation/starter/03_compare_rag_versions.py
```

The script must write both JSON and Markdown reports. The exercise is complete
when a better average cannot hide a critical regression and when the release
decision is traceable to named metrics and thresholds.

## Scope boundary

The implemented exercises stay on the Session 5 core: failure diagnosis,
contextual chunks, hybrid search, task-specific metrics and systematic
comparison. Query rewriting and reranking are documented for optional classroom
discussion in `private/session-05/additional-topics-query-rewriting-reranking.md`;
they are intentionally not extra implementation requirements.

