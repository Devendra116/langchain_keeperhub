"""Shared type helpers for toolkit input validation."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Annotated

from pydantic import AfterValidator, StringConstraints

EVM_ADDRESS_PATTERN = r"^0x[a-fA-F0-9]{40}$"
EvmAddress = Annotated[str, StringConstraints(pattern=EVM_ADDRESS_PATTERN)]

POSITIVE_DECIMAL_STRING_PATTERN = r"^(?:0|[1-9]\d*)(?:\.\d+)?$"


def _validate_positive_decimal_string(value: str) -> str:
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("Value must be a positive decimal string.") from exc
    if parsed <= 0:
        raise ValueError("Value must be greater than zero.")
    return value


PositiveDecimalString = Annotated[
    str,
    StringConstraints(pattern=POSITIVE_DECIMAL_STRING_PATTERN),
    AfterValidator(_validate_positive_decimal_string),
]
