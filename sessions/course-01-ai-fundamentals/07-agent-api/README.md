# Session 7 — Robust Agent and API Integration

Make agent failures explicit, expose the same agent through an API, and
continue a conversation from a separate client.

Run commands from the repository root after `uv sync` and after configuring
`OPENAI_API_KEY` in `.env`.

## 1. Run the prepared robust agent

Run the complete `01_robust_agent.py`; there is nothing to implement.

- **Goal:** understand which failures allow another model decision and which
  stop the run.
- **Observe:** two related Apollo 13 questions, the answers, the high-level
  trace and the session reset.
- **Inspect:** the allowlist, structured tool errors, handling of zero/one/
  multiple calls and `max_steps` in `agent_service.py`. The normal demo does
  not inject those errors.

```bash
uv run python sessions/07-agent-api/starter/01_robust_agent.py
```

## 2. Expose the agent through FastAPI

Complete the handlers in `02_fastapi_service.py`:

- `GET /health` must stay independent of the OpenAI connection;
- `POST /chat` validates the request, calls the agent and maps input versus
  upstream failures to different status codes;
- `POST /search` exposes retrieval without running the agent loop;
- `POST /sessions/reset` clears only the requested session.

**Goal:** let another application use the agent without duplicating its logic.

Start the development server:

```bash
uv run uvicorn --app-dir sessions/07-agent-api/starter 02_fastapi_service:app --reload
```

**Verify in `/docs`:** a valid chat returns answer, tools used and trace; search
returns retrieval results without an agent run; reset affects only the chosen
session. Compare a missing field, whitespace-only input and a low step limit.
The low-limit failure depends on the model requesting a tool.

Discuss where the agent logic lives and whether errors distinguish invalid
input from an agent run that did not produce a final answer.

## 3. Build a resilient API client

Complete `_request` and `run_demo` in `03_http_client.py`. The client must keep
one session across two related questions, distinguish timeout/connection failures
from HTTP errors, validate the minimum response contract and reset the session
in a `finally` block.

**Goal:** preserve the conversation from a separate client and make failures
visible instead of displaying them as successful answers.

With the completed API running:

```bash
uv run python sessions/07-agent-api/starter/03_http_client.py
```

**Verify:** the second question still refers to Apollo 13, both requests use
the same session ID, answers and trace are printed, and reset is attempted.
Test an unreachable API with `--base-url http://127.0.0.1:9999` when that port
has no server. Invalid payloads require a controlled response or code inspection;
the normal demo does not inject them.

Discuss what preserves the mission reference and whether a reset failure can
hide the original chat error.

## Scope boundary

The session uses an in-memory service and synchronous endpoints to keep the
agent/API boundary visible. Authentication, persistent storage, distributed
workers, advanced retries, rate limiting and production observability are not
implemented here. Parallel tool calls may be returned by the model, but the
example executes them sequentially for clarity.
