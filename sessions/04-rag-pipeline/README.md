# Session 4 — Retrieval-Augmented Generation

This session turns semantic search into a complete RAG pipeline:

`load → chunk → embed → store → retrieve → augment → generate`

Run every command from the repository root after `uv sync` and after creating
a local `.env` file containing `OPENAI_API_KEY`.

The exercises are implemented in the starter scripts. For a concise, step-by-step
workflow in Portuguese, see [workflows.md](workflows.md). For visual code flows,
see [workflows-mermaid.md](workflows-mermaid.md).

## 1. Run the complete baseline

`01_rag_baseline.py` is complete. It loads four Markdown documents and converts
the supplied Apollo 16 PDF to Markdown with PyMuPDF4LLM. It uses one document
as one baseline chunk, stores the vectors in an ephemeral Chroma collection,
retrieves evidence and asks the model for a structured answer with sources.

```bash
uv run python sessions/04-rag-pipeline/starter/01_rag_baseline.py --query "Which lunar region did Apollo 16 explore?" --show-loaded-pdf
```

Use `--show-context` to inspect exactly what reached the model:

```bash
uv run python sessions/04-rag-pipeline/starter/01_rag_baseline.py --query "Which lunar region did Apollo 16 explore?" --show-loaded-pdf --show-context
```

There is nothing to implement. Trace one question through all seven stages and
identify which outputs are deterministic and which are generated.
Inspect the PDF and its converted Markdown, including the small crew table.
The answer uses the Descartes fact from the PDF; it does not need to use a table cell.
The later exercises use only the four Markdown documents to keep chunking comparable.

## 2. Compare chunking strategies

`02_chunking_lab.py` keeps loading, embeddings, retrieval and the evaluation
loop ready. It implements:

- `fixed_size_chunks`: sliding word windows with validated overlap and stable
  chunk IDs;
- `structure_aware_chunks`: preserve Markdown headings as contextual headers,
  while still splitting sections that exceed the body word limit.

Run the comparison:

```bash
uv run python sessions/04-rag-pipeline/starter/02_chunking_lab.py --strategy both --chunk-words 90 --overlap-words 20
```

Try at least two configurations. This lab prints only `development` cases,
leaving `holdout` cases unseen for Session 5. Do not choose a winner only from the average:
inspect failures involving exact names, numbers, multi-fact questions and
unanswerable questions.

Export the strategy you choose for exercise 3. This example exports the
structure-aware chunks to `.chroma/session-04-chunks.json`:

```bash
uv run python sessions/04-rag-pipeline/starter/02_chunking_lab.py --strategy both --chunk-words 90 --overlap-words 20 --export-strategy structure
```

The exported file carries chunk text, source, title and stable ID. It is a
handoff between two separate exercises, not a permanent vector index.

The exercise is complete when:

- invalid sizes and overlaps fail clearly;
- no text is silently dropped at a chunk boundary;
- every chunk retains its source and a stable ID;
- structure-aware chunks include enough heading context to remain meaningful;
- the report shows source recall and the number/size of chunks for each strategy.

## 3. Build grounded generation with a context budget

`03_grounded_rag.py` loads the chunks exported by exercise 2 and provides the
retrieval flow, CLI and output models. It implements:

- `select_context`: apply a similarity threshold and fit evidence into a token
  budget without reordering the ranking;
- `generate_grounded_answer`: make one structured Responses API call using only
  the selected context and explicitly allow abstention;
- `validate_citations`: reject unknown sources, unknown chunks and quotations
  that do not occur in the cited chunk.

```bash
uv run python sessions/04-rag-pipeline/starter/03_grounded_rag.py --query "How far did Apollo 15 travel with the rover?" --max-context-tokens 450
```

Test the abstention path:

```bash
uv run python sessions/04-rag-pipeline/starter/03_grounded_rag.py --query "What experiments did Apollo 14 deploy?"
```

The exercise is complete when:

- the context budget is measured before generation;
- low-scoring chunks do not enter the prompt;
- answerable claims carry verifiable citations;
- the program distinguishes an LLM answer from a validated grounded answer;
- a missing answer in the corpus produces an explicit abstention.

Inspect one generated answer manually as well: check whether the quoted text
actually supports the associated claim. Automatic citation validation checks
the target and quote, but cannot prove every claim is true.

## Supplied data

- `data/rag-corpus/` contains four multi-section Apollo Markdown documents.
- `data/rag-corpus-pdf/` contains a short Apollo 16 teaching PDF with a table.
- `data/evaluations/rag_cases.json` contains development and holdout cases.
- `sessions/rag_course_support.py` contains shared plumbing, not the decisions
  requested in the exercises.
