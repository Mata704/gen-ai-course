---
id: pipeline-failure
title: Pipeline or source failure
version: 1
applies_to: incident:pipeline_failure
---
## Signals
- The run failed before the quality gate (source unavailable, pipeline error) or the delivery failed.

## Investigate
1. `get_run_summary`: which stage failed and the recorded errors.
2. `get_run_logs` with level `error`: the failing step.
3. `list_recent_runs`: is this the first failure or a repeated one?

## Likely causes
- The source is temporarily unavailable.
- A failure in the pipeline itself or in the destination.

## Possible remediation (each action needs approval)
- Single failure: retry the run once the source is reachable.
- Repeated failures: escalate instead of retrying again.

## Recovered when
- A new run of the pipeline passes the quality gate and the delivery is verified.
