---
id: duplicate-records
title: Duplicate records
version: 1
applies_to: rule:unique
---
## Signals
- The `unique` rule fails: the same key appears more than once in the batch.

## Investigate
1. `get_affected_records` for the rule: compare each duplicate with its first occurrence.
2. `get_run_logs` for ingestion: were records read more than once?

## Likely causes
- Exact duplicates: the source re-sent records or a read was retried.
- Same key, different content: two real records share a key; this is a source defect.

## Possible remediation (each action needs approval)
- Exact duplicates: propose keeping the first occurrence of each key.
- Conflicting duplicates: do not choose one; escalate to the source owner.

## Recovered when
- A revalidation passes the `unique` rule and the delivery is verified.
