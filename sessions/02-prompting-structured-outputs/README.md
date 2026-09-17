# Session 2 — Prompting and structured outputs

This folder will contain the follow-up examples for the second three-hour
class.

## Run the baseline

From the repository root, after `uv sync` and creating a local `.env` file:

```text
uv run python sessions/02-prompting-structured-outputs/starter/01_prompt_lab.py
uv run python sessions/02-prompting-structured-outputs/starter/02_structured_output.py
```

`03_intent_classifier.py` is a challenge file and runs after its marked
functions are implemented.

Planned material:

- system prompts, context, and few-shot examples;
- prompt versions and small test cases;
- JSON-shaped responses and Pydantic validation;
- an intent-classification mini-build with a safe fallback.

## Learning path

1. `01_prompt_lab.py` is a complete baseline for comparing prompt versions.
2. `02_structured_output.py` is a complete example of a typed response.
3. `03_intent_classifier.py` is the main challenge. Complete its functions to
   turn a model output into a safe product decision.

Prompts, trusted course context, and test data are outside Python files so their
evolution is visible and can be discussed in class. The open work concerns
prompt design, schema design, ambiguity, and safe fallback behaviour — not
package or credential troubleshooting.
