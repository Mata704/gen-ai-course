---
id: schema-drift
title: Schema drift in the source batch
version: 1
applies_to: rule:schema
---
## Signals
- The `schema` rule fails with missing or unexpected columns.

## Investigate
1. `get_batch_profile`: which columns are missing or unexpected, and in how many rows.
2. `compare_with_last_success`: did the columns change since the last delivered batch?
3. `get_run_logs` for the ingestion stage: was the batch read in full?

## Likely causes
- The source added a column (new feature, campaign field) without a contract change.
- The source removed or renamed a column.

## Possible remediation (each action needs approval)
- Unexpected column with no downstream use: propose dropping it in the transformation.
- Missing or renamed column: do not guess a mapping; escalate to the source owner.

## Recovered when
- A revalidation of the batch passes the `schema` rule and the delivery is verified.
