---
id: late-or-incomplete-source
title: Late or incomplete source data
version: 1
applies_to: rule:freshness, rule:min_rows
---
## Signals
- The `freshness` rule fails (data older than allowed) or `min_rows` fails (too few records).

## Investigate
1. `get_run_summary`: observed delay and record count.
2. `compare_with_last_success`: how far volume and delay are from the last delivered batch.
3. `get_run_logs` for ingestion: how many records were read.

## Likely causes
- Low volume together with a delay: the source has not finished producing the batch.
- Low volume without a delay: records were lost upstream.

## Possible remediation (each action needs approval)
- Wait and re-read the source, then revalidate.
- Do not lower the thresholds to make the batch pass.

## Recovered when
- A revalidation passes `freshness` and `min_rows` and the delivery is verified.
