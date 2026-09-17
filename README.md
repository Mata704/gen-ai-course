# Generative AI Course

Working material for the first two sessions of the course. The repository will
grow session by session; it deliberately starts with the minimum structure
needed to prepare participants and design the exercises well.

## Structure

- [`docs/pre-work.md`](docs/pre-work.md) — participant setup before Session 1.
- [`docs/sources.md`](docs/sources.md) — technical sources used to create the material.
- [`sessions/01-llm-apis/`](sessions/01-llm-apis/) — Session 1 plan and, later, its code.
- [`sessions/02-prompting-structured-outputs/`](sessions/02-prompting-structured-outputs/) — Session 2 plan and, later, its code.

## Getting started

This is a [uv](https://docs.astral.sh/uv/) project. Dependencies live in
`pyproject.toml`; we intentionally do not maintain a separate
`requirements.txt` with duplicate version information.

The course requires Python 3.10 or newer. `uv sync` will use a compatible
Python already installed on the computer; if none is available, uv can download
one automatically with its default configuration.

```text
uv sync
```

Create a local `.env` from `.env.example`, then add your personal API key. Do
not commit that file.

Run an exercise from the repository root with `uv run`, for example:

```text
uv run python sessions/01-llm-apis/starter/01_first_call.py
```

## Principles

- Keep API keys local; never commit `.env` files.
- Build small, runnable examples before introducing abstractions.
- Use the official SDK and course-specific examples rather than copying entire external lessons.
