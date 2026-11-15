---
id: unknown-references
title: References to unknown entities
version: 1
applies_to: rule:referential_integrity
---
## Signals
- The `referential_integrity` rule fails: records point at an entity that is not in the reference list.

## Investigate
1. `get_affected_records` for the rule: which references are unknown.
2. `list_quality_rules`: the reference values the rule currently accepts.

## Likely causes
- The entity is new and the reference data is out of date.
- A typo or corrupted identifier in the source.

## Possible remediation (each action needs approval)
- Quarantine the affected rows until the reference is confirmed.
- If the entity is legitimate, the reference data must be updated by its owner.

## Recovered when
- A revalidation passes the rule and the delivery is verified.
