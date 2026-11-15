---
id: missing-or-invalid-values
title: Missing or invalid field values
version: 1
applies_to: rule:not_null, rule:numeric_range, rule:allowed_values
---
## Signals
- A `not_null`, `numeric_range` or `allowed_values` rule fails for some rows.

## Investigate
1. `get_quality_findings`: which rules failed and how many rows each affects.
2. `get_affected_records` for each rule: look at the offending values only.
3. `get_batch_profile`: is the problem isolated or spread across the batch?

## Likely causes
- Isolated rows: a data-entry or upstream defect in individual records.
- Many rows: a source change (new status value, unit or sign convention).

## Possible remediation (each action needs approval)
- Quarantine the affected rows and deliver the rest only if the pipeline owner allows partial loads.
- A new legitimate value (for example a new status) needs a rule change, not a data fix.
- Never invent a replacement value for a required field.

## Recovered when
- A revalidation passes the failed rules and the delivery is verified.
