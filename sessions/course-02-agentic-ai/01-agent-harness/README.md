# Session 1 — Agent Harnesses and PydanticAI

The Meridian Exchange is a fictional stock exchange that runs in a local
simulator (`meridian/`). Incidents happen in the simulator; your agent
investigates them through tools and the simulator reacts to what it does.

This session starts from an agent that already works but cannot be trusted.
The goal is to find which part of the harness causes the problem, change one
part at a time, and check whether the change holds on new cases.

Run every command from the repository root after `uv sync` and after setting
`OPENAI_API_KEY` in a local `.env` file.

## What you have

```text
01-agent-harness/
├── starter/harness.py   # the agent: instructions, output type and tools
└── cases/               # incidents for this session (scenario files)
```

- `starter/harness.py` builds a PydanticAI agent with three tools:
  `read_alert`, `read_metrics` and `read_runbook`.
- Each file in `cases/` describes what happens in the simulator. It does not
  contain the expected answer.
- `python -m meridian.run` runs a harness on a case and prints the trace: every
  tool call, its arguments, a short result and the final report.

You can also watch a case without any agent:

```bash
uv run mrx-chaos run sessions/course-02-agentic-ai/01-agent-harness/cases/s01-gateway-latency.yaml --ticks 10
```

## Exercise 1 — Why did the agent conclude that?

Run the starter on the first incident:

```bash
uv run python -m meridian.run \
  --harness sessions/course-02-agentic-ai/01-agent-harness/starter/harness.py \
  --scenario sessions/course-02-agentic-ai/01-agent-harness/cases/s01-gateway-latency.yaml
```

1. Read the trace. Which tools were called, with which arguments, and what did
   each one return?
2. Compare the report with what the trace shows.
3. Write down your hypothesis for the behaviour you see, and the observation in
   the trace that supports it.
4. Copy the starter to `harness_v2.py` in the same folder and change **one**
   part of the harness: the instructions, the output type, a tool interface or
   a tool result.
5. Run the same case with `harness_v2.py` and compare the two traces.

## Exercise 2 — Does the change hold on other cases?

Run both versions on every case of the session:

```bash
uv run python -m meridian.run \
  --harness sessions/course-02-agentic-ai/01-agent-harness/starter/harness.py \
  --harness sessions/course-02-agentic-ai/01-agent-harness/starter/harness_v2.py \
  --cases-dir sessions/course-02-agentic-ai/01-agent-harness/cases \
  --summary
```

1. Look at the summary table. Where does your version behave differently from
   the starter?
2. For each case, decide whether the report is supported by what the agent
   actually read.
3. Write one new case in `cases/` (copy an existing file and change the
   faults, the incident text or the tool behaviour) that your version should
   handle. Run it.
4. Keep the version, the cases and a short note: hypothesis, part changed,
   what improved and what is still not demonstrated.

## Conventions

- Keep a `status` field in the report. The evaluation reads it.
- Do not edit `meridian/`. The simulator, the scenarios and the evaluation are
  shared infrastructure.
- A model can answer differently on two runs. Run a case more than once before
  drawing a conclusion.

## Scope boundary

One agent, a few read-only tools, typed output and comparison of harness
versions. Actions with side effects, tool selection and procedures belong to
Session 2. MCP, memory, security policies and multi-agent coordination come
later in the course.
