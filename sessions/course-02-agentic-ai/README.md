# Course 2 — Agentic AI: sessions

Session material for Course 2, added session by session. Each session has its
own folder with a `README.md`, a `starter/` agent and the test cases it adds.

All sessions use the Meridian Exchange simulator in [`meridian/`](../../meridian/).
The simulator, its scenarios and the evaluation runner are shared by every
session and by the project.

| Session | Folder | Focus |
|---|---|---|
| 1 | [`01-agent-harness/`](01-agent-harness/) | Diagnose an agent run from its trace, change one part of the harness, compare versions. |
| 2 | [`02-context-tools-skills/`](02-context-tools-skills/) | Decide what the agent sees, design tools and procedures, make actions idempotent. |

Run a harness on a case from the repository root:

```bash
uv run python -m meridian.run --harness <harness.py> --scenario <case.yaml>
```
