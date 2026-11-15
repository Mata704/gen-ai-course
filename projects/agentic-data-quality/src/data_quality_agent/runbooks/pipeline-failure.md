---
id: pipeline-failure
title: Pipeline or source failure
version: 2
applies_to: incident:pipeline_failure
---
## Signals
- The run failed before the quality gate (source unavailable, pipeline error) or the delivery failed.

## Investigate
1. `get_run_summary`: which stage failed and the recorded errors.
2. `get_run_logs` with level `error`: the failing step.
3. `list_recent_runs`: is this the first failure or a repeated one?
4. `get_source_status` and `list_upstream_incidents`: does the producing team report it available?

## Likely causes
- The source is temporarily unavailable.
- A failure in the pipeline itself or in the destination.

## Possible remediation
- Source reported available: `retry_ingestion` runs the ingestion again as a new attempt, within
  the pipeline's retry budget (policy checked in code). Ask the reviewer to verify the new attempt.
- Source still down or budget used up: do not retry; escalate to the source owner.

## Recovered when
- A new run of the pipeline passes the quality gate and the delivery is verified.
