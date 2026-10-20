# Session 5 — Advanced RAG and Evaluation

**Goal:** compare RAG changes with evidence instead of intuition.

`define cases → run baseline → diagnose → change → compare → gate`

Run all commands from the repository root after `uv sync`. Exercise 2 also
requires `OPENAI_API_KEY` in `.env`.

## 1. Evaluate the baseline

- **Objective:** identify whether each failure comes from retrieval, generation,
  citations or the evaluation rule.
- **Code:** complete; nothing to implement.
- **Output:** question, expected evidence, retrieved and cited sources, answer
  and metrics per case, plus overall averages. With `--output`, both JSON and a
  readable Markdown report are saved.

```bash
uv run python sessions/05-advanced-rag-evaluation/starter/01_evaluate_rag_baseline.py --split development
```

Use the holdout only after reaching a conclusion with the development cases:

```bash
uv run python sessions/05-advanced-rag-evaluation/starter/01_evaluate_rag_baseline.py --split holdout
```

## 2. Compare retrieval methods

- **Objective:** see how semantic, lexical and hybrid retrieval change the
  chunks found.
- **Code:** the retrieval algorithms are supplied.
- **Output:** Markdown tables in the terminal and
  `reports/hybrid-retrieval-development.md`. This exercise stops after
  retrieval, so answers and cited sources are explicitly marked as `N/A`.

```bash
uv run python sessions/05-advanced-rag-evaluation/starter/02_hybrid_retrieval.py --split development --top-k 2
```

Answer:

1. Which method found the most useful chunks? Show one example.
2. Would you use semantic, lexical or hybrid retrieval? Why?

After recording the decision, run the holdout once:

```bash
uv run python sessions/05-advanced-rag-evaluation/starter/02_hybrid_retrieval.py --split holdout --top-k 2
```

## 3. Compare two RAG versions

- **Objective:** decide whether a new RAG version is safe to release.
- **Code:** the frozen runs, metrics and quality gate are supplied.
- **Output:** averages, improvements and regressions, followed by each
  question and the retrieved sources, cited sources and answer for both
  versions, in the terminal and `reports/rag-comparison.md`.

```bash
uv run python sessions/05-advanced-rag-evaluation/starter/03_compare_rag_versions.py
```

Answer:

1. Would you release the candidate? Show one improvement and one serious
   problem.
2. Does a good metric hide an error in any case? Which one?

## Scope

- Core: failure diagnosis, hybrid retrieval, task-specific metrics and version
  comparison.
- Optional discussion: query rewriting and reranking in
  `private/session-05/additional-topics-query-rewriting-reranking.md`.
