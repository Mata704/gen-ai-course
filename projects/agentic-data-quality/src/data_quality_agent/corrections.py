"""Validate a user-submitted batch before creating a correction attempt."""

import json
import math
from typing import Any

MAX_BATCH_BYTES = 1_000_000


def _reject_constant(value: str) -> None:
    raise ValueError(f"JSON inválido: {value} não é um valor permitido.")


def _finite_float(value: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("O lote corrigido contém um número não finito.")
    return number


def parse_corrected_batch(payload: str) -> list[dict[str, Any]]:
    if len(payload.encode("utf-8")) > MAX_BATCH_BYTES:
        raise ValueError("O lote corrigido excede o limite de 1 MB.")
    data = json.loads(payload, parse_constant=_reject_constant, parse_float=_finite_float)
    if not isinstance(data, list) or not all(isinstance(row, dict) for row in data):
        raise ValueError("O lote corrigido deve ser uma lista JSON de objetos.")
    return data
