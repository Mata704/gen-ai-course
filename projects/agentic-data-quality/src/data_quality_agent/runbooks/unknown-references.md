---
id: unknown-references
title: References to unknown entities
version: 2
applies_to: rule:referential_integrity
---
## Signals
- The `referential_integrity` rule fails: records point at an entity that is not in the reference list.

## Investigate
1. `get_quality_findings`: how many rows have unknown references, and their positions.
2. `list_quality_rules`: the reference values the rule currently accepts.

## Likely causes
- The entity is new and the reference data is out of date.
- A typo or corrupted identifier in the source.

## Possible remediation
- Few rows, within the pipeline's quarantine limit: `quarantine_failed_records` holds them
  back until the reference is confirmed and delivers the rest.
- If the entity is legitimate, the reference data must be updated by its owner.

## Recovered when
- A revalidation passes the rule and the delivery is verified.
