from __future__ import annotations

import json
import math
from typing import Any

from data_quality_agent.simulator.models import PipelineDefinition, QualityFinding, RuleKind


def check_quality(
    pipeline: PipelineDefinition,
    records: list[dict[str, Any]],
    delay_minutes: int,
) -> list[QualityFinding]:
    """Evaluate the deterministic quality gate without modifying the input records."""
    findings: list[QualityFinding] = []
    expected_columns = set(pipeline.expected_columns)
    observed_columns = {column for row in records for column in row}

    for rule in pipeline.rules:
        indexes: list[int] = []
        message: str | None = None

        if rule.kind == RuleKind.SCHEMA:
            missing = sorted(
                {column for row in records for column in expected_columns - set(row)}
                if records else expected_columns
            )
            unexpected = sorted(observed_columns - expected_columns)
            if missing or unexpected:
                parts = []
                if missing:
                    parts.append(f"missing columns: {', '.join(missing)}")
                if unexpected:
                    parts.append(f"unexpected columns: {', '.join(unexpected)}")
                indexes = [
                    index for index, row in enumerate(records)
                    if set(row) != expected_columns
                ]
                message = "; ".join(parts)
        elif rule.kind == RuleKind.NOT_NULL:
            field = _rule_field(rule.field, rule.kind)
            indexes = [i for i, row in enumerate(records) if row.get(field) is None]
            message = f"'{field}' is null or missing in {len(indexes)} record(s)." if indexes else None
        elif rule.kind == RuleKind.UNIQUE:
            field = _rule_field(rule.field, rule.kind)
            seen: set[str] = set()
            for index, row in enumerate(records):
                value = json.dumps(row.get(field), sort_keys=True)
                if value in seen:
                    indexes.append(index)
                else:
                    seen.add(value)
            message = f"'{field}' has {len(indexes)} duplicate record(s)." if indexes else None
        elif rule.kind == RuleKind.NUMERIC_RANGE:
            field = _rule_field(rule.field, rule.kind)
            for index, row in enumerate(records):
                value = row.get(field)
                if value is None:
                    continue
                if not isinstance(value, (int, float)) or isinstance(value, bool):
                    indexes.append(index)
                elif isinstance(value, float) and not math.isfinite(value):
                    indexes.append(index)
                elif ((rule.minimum is not None and value < rule.minimum)
                      or (rule.maximum is not None and value > rule.maximum)):
                    indexes.append(index)
            message = f"'{field}' is outside its numeric range in {len(indexes)} record(s)." if indexes else None
        elif rule.kind == RuleKind.ALLOWED_VALUES:
            field = _rule_field(rule.field, rule.kind)
            indexes = [
                i for i, row in enumerate(records)
                if row.get(field) is not None and row.get(field) not in rule.allowed_values
            ]
            message = f"'{field}' contains {len(indexes)} unsupported value(s)." if indexes else None
        elif rule.kind == RuleKind.REFERENTIAL_INTEGRITY:
            field = _rule_field(rule.field, rule.kind)
            indexes = [
                i for i, row in enumerate(records)
                if row.get(field) is not None and row.get(field) not in rule.reference_values
            ]
            message = f"'{field}' references an unknown entity in {len(indexes)} record(s)." if indexes else None
        elif rule.kind == RuleKind.MIN_ROWS:
            minimum_count = _rule_value(rule.minimum_count, rule.kind)
            if len(records) < minimum_count:
                message = f"Expected at least {minimum_count} records; observed {len(records)}."
        elif rule.kind == RuleKind.FRESHNESS:
            maximum_delay = _rule_value(rule.maximum_delay_minutes, rule.kind)
            if delay_minutes > maximum_delay:
                message = f"Data delay is {delay_minutes} minutes; maximum allowed is {maximum_delay}."

        if message is not None:
            findings.append(QualityFinding(
                rule_id=rule.rule_id,
                rule_name=rule.name,
                severity=rule.severity,
                message=message,
                affected_rows=len(indexes),
                row_indexes=indexes,
            ))

    return findings


def _rule_field(field: str | None, kind: RuleKind) -> str:
    if field is None:
        raise ValueError(f"Rule '{kind}' requires a field.")
    return field


def _rule_value(value: int | None, kind: RuleKind) -> int:
    if value is None:
        raise ValueError(f"Rule '{kind}' is missing its configured threshold.")
    return value
