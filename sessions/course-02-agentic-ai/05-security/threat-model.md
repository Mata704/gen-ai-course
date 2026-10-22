# Threat model — <group name>

Keep it short. One line per item is enough. Update it when a case breaks your controls.

## What we protect

| Asset | Why it matters | Who may change or read it |
|---|---|---|
| e.g. matching-engine availability | | |
| e.g. member personal data in logs | | |

## Who can influence the agent's context

| Source | Trusted? | How it reaches the model | Example of abuse |
|---|---|---|---|
| Incident brief | | | |
| Logs | | | |
| Tickets | | | |
| Memory | | | |
| Tool descriptions (MCP) | | | |

## How data can leave

| Channel | Who sees it | What may never go there |
|---|---|---|
| members-status | | |
| ops-internal | | |
| email:<address> | | |
| Tickets and comments | | |
| The model provider (everything in the prompt) | | |

## Controls

| Control | Where it runs (input, tool, output, executor) | Deterministic or model-based | Case that tests it |
|---|---|---|---|
| | | | |

## Accepted risks

What you decided not to handle, and why.
