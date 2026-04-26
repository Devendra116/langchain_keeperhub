"""Shared type helpers for toolkit input validation."""

from __future__ import annotations

from typing import Annotated

from pydantic import StringConstraints

EVM_ADDRESS_PATTERN = r"^0x[a-fA-F0-9]{40}$"
EvmAddress = Annotated[str, StringConstraints(pattern=EVM_ADDRESS_PATTERN)]
