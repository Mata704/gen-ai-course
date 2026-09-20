# Session 1 — LLMs and APIs

Material for the first session of the Generative AI course. It introduces a
small terminal application that calls an LLM through the OpenAI API.

## Run an example

From the repository root, install the project dependencies once:

```text
uv sync
```

Create a local `.env` file from `.env.example` and add your API key. Then run
any Python file in `starter/`, for example:

```text
uv run python sessions/01-llm-apis/starter/01_first_call.py
```

## Structure

- `starter/` — runnable Python examples.
- `test-data/` — manual acceptance cases for testing application behaviour.
