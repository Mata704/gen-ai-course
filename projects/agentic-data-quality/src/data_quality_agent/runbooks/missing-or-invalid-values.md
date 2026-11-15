---
id: missing-or-invalid-values
title: Missing or invalid field values
version: 2
applies_to: rule:not_null, rule:numeric_range, rule:allowed_values
---
## Signals
- A `not_null`, `numeric_range` or `allowed_values` rule fails for some rows.

## Investigate
1. `get_quality_findings`: which rules failed and how many rows each affects.
2. `get_batch_profile`: is the problem isolated or spread across the batch? (counts and ranges
   per column; no records are returned)

## Likely causes
- Isolated rows: a data-entry or upstream defect in individual records.
- Many rows: a source change (new status value, unit or sign convention).

## Possible remediation
- Isolated rows within the pipeline's quarantine limit: `quarantine_failed_records` holds them
  back for review and delivers the rest after every rule runs again (policy checked in code).
- A new legitimate value (for example a new status) needs a rule change, not a data fix.
- Never invent a replacement value for a required field.

## Recovered when
- A revalidation passes the failed rules and the delivery is verified.
