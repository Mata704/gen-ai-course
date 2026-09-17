# Session 1 — LLMs and APIs

This folder will contain the smallest possible runnable examples for the first
three-hour class.

## Run the baseline

From the repository root, after `uv sync` and creating a local `.env` file:

```text
uv run python sessions/01-llm-apis/starter/01_first_call.py
```

`02_streaming.py` also runs as-is. `03_smart_qa.py` is a challenge file and
runs after its marked functions are implemented.

Planned material:

- first API call and message roles;
- model parameters, tokens, and cost awareness;
- streaming responses;
- a terminal-based Smart Q&A mini-build.

## Learning path

1. `01_first_call.py` is a complete, runnable baseline.
2. `02_streaming.py` runs, but its context behaviour is deliberately minimal.
   Improve it by completing the marked design decisions.
3. `03_smart_qa.py` is the main challenge: the final Smart Q&A retains streaming
   while its missing functions define the behaviour learners must design and
   defend.

The challenge is never to repair a broken environment. The application has
working dependencies and API setup; the open work is about assistant behaviour,
context, user experience, and responsible answers.

## Student material

- [`exercise-brief.md`](exercise-brief.md) — requirements, acceptance cases,
  and optional graduated hints.
- [`test-data/acceptance-cases.md`](test-data/acceptance-cases.md) — manual
  cases used to demonstrate behaviour.
