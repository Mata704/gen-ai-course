"""Read and prepare simulated batches, including scenario data faults."""

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any, TypeVar

from data_quality_agent.simulator.models import Fault, FaultKind, PipelineDefinition

DATASETS_DIR = Path(__file__).parent / "datasets"
T = TypeVar("T")


def load_records(
    pipeline: PipelineDefinition,
    seed: int,
    input_path: str | Path | None,
) -> list[dict[str, Any]]:
    if input_path is not None:
        path = Path(input_path)
    else:
        filename = Path(pipeline.dataset_file)
        if filename.name != pipeline.dataset_file:
            raise ValueError("Dataset file must be a filename inside the simulator dataset directory.")
        path = DATASETS_DIR / filename
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list) or not all(isinstance(row, dict) for row in payload):
        raise ValueError(f"Input dataset must contain a JSON array of records: {path}")
    records = [dict(row) for row in payload]
    if input_path is None:
        random.Random(seed).shuffle(records)
    return records


def transform(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    transformed = []
    for record in records:
        row = dict(record)
        if isinstance(row.get("status"), str):
            row["status"] = row["status"].strip().lower()
        transformed.append(row)
    return transformed


def required_fault_value(value: T | None, name: str, fault: Fault) -> T:
    if value is None:
        raise ValueError(f"Fault '{fault.kind}' requires '{name}'.")
    return value


def apply_data_fault(records: list[dict[str, Any]], fault: Fault) -> None:
    if fault.kind == FaultKind.DROP_ROWS:
        count = required_fault_value(fault.count, "count", fault)
        if count > len(records):
            raise ValueError("drop_rows count exceeds the number of records.")
        del records[-count:]
        return

    if fault.kind in (FaultKind.DUPLICATE_ROW, FaultKind.NULL_VALUE, FaultKind.SET_VALUE):
        row_index = required_fault_value(fault.row_index, "row_index", fault)
        if row_index >= len(records):
            raise ValueError(f"row_index {row_index} is outside the current dataset.")
        if fault.kind == FaultKind.DUPLICATE_ROW:
            records.append(dict(records[row_index]))
            return

        field = required_fault_value(fault.field, "field", fault)
        records[row_index][field] = None if fault.kind == FaultKind.NULL_VALUE else fault.value
        return

    if fault.kind in (FaultKind.DROP_COLUMN, FaultKind.ADD_COLUMN):
        field = required_fault_value(fault.field, "field", fault)
        if fault.kind == FaultKind.DROP_COLUMN:
            for row in records:
                row.pop(field, None)
        else:
            for row in records:
                row[field] = fault.value


def describe_fault(fault: Fault) -> str:
    details = fault.model_dump(exclude={"kind"}, exclude_none=True)
    if not details:
        return fault.kind.value
    return f"{fault.kind.value} " + ", ".join(f"{key}={value!r}" for key, value in details.items())
