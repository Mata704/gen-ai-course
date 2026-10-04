# Session 6 — Conversational RAG and Basic Tool Calling

Session 5 improved and evaluated retrieval. This session turns that pipeline
into a small conversational agent that must decide what kind of context it
needs before answering.

The progression is deliberately narrow:

`conversational RAG → one tool call → bounded RAG agent loop`

Run the commands from the repository root after `uv sync` and after setting
`OPENAI_API_KEY` in a local `.env` file.

## 1. Inspect a complete conversational RAG flow

`01_conversational_rag.py` is complete and runs as supplied. It uses a
structured plan to choose one of three routes:

- `retrieval` for an Apollo fact, including a follow-up resolved from history;
- `history` to rephrase or summarize an answer already given;
- `clarify` when the reference is still ambiguous.

```bash
uv run python sessions/06-conversational-ai/starter/01_conversational_rag.py
```

There is nothing to implement. Follow the two independent sessions and inspect
why history helps interpret a question but retrieved documents remain the
evidence for factual answers.

## 2. Complete one tool-calling lifecycle

`02_tool_calling.py` provides a local, read-only mission timeline and a CLI.
Implement:

- `build_tool_definition`: describe `get_mission_timeline` with a strict JSON
  schema;
- `execute_tool_call`: validate the requested tool and arguments, then return a
  JSON result or a useful JSON error;
- `answer_with_tool`: send the question, preserve the first response output,
  append the matching `function_call_output`, and ask the model for the final
  answer.

```bash
uv run python sessions/06-conversational-ai/starter/02_tool_calling.py "When did Apollo 11 land?"
```

The exercise is complete when a valid date question performs two model calls,
the second call receives the first call's output plus the local tool result,
and invalid missions fail as data rather than crashing the program.

## 3. Build a bounded agent loop

`03_basic_agent_loop.py` supplies two tools and their execution logic:

- `search_documents` retrieves narrative evidence from the Apollo corpus;
- `get_mission_timeline` reads exact dates from the local JSON file.

Implement `run_agent_loop`. On every step it must preserve all response output,
execute every requested function call, append each result using the matching
`call_id`, and stop when the model returns a final answer. It must also enforce
`max_steps`, update conversation history only after success, and expose only a
high-level list of tools used.

```bash
uv run python sessions/06-conversational-ai/starter/03_basic_agent_loop.py
```

The exercise is complete when the model can choose the correct source, use a
previous turn to resolve a follow-up, and cannot continue beyond the explicit
step limit.

## Scope boundary

This session uses the OpenAI SDK directly, local in-memory history, one
read-only structured data source and a short agent loop. Tool registries,
parallel calls, API exposure and stronger failure handling belong to Session 7.
PydanticAI, MCP, long-term memory, autonomous planning and multi-agent systems
remain outside this course session.
