"""ReverseResolveENSTool — address → ENS / Basenames primary name."""

from __future__ import annotations

import logging
import re
from typing import Any

from pydantic import BaseModel, Field, field_validator

from langchain_keeperhub.ens_chains import resolve_ens_chain
from langchain_keeperhub.tools._base import _ENSToolBase

logger = logging.getLogger(__name__)

_HEX40_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")


class ReverseResolveENSInput(BaseModel):
    """Input for ENS reverse resolution."""

    address: str = Field(
        description="Ethereum address to look up (0x-prefixed, 40 hex chars).",
    )
    chain: int | str | None = Field(
        default=None,
        description=(
            "Optional chain override: 1 / 'ethereum', 8453 / 'base', "
            "11155111 / 'sepolia', 84532 / 'base-sepolia'. "
            "Omit to use the toolkit default chain."
        ),
    )

    @field_validator("address")
    @classmethod
    def _validate_address(cls, v: str) -> str:
        v = v.strip()
        if not _HEX40_RE.match(v):
            raise ValueError(
                "address must be a 0x-prefixed Ethereum address (40 hex chars)."
            )
        return v


class ReverseResolveENSTool(_ENSToolBase):
    """Look up the primary ENS / Basenames name for an address.

    Queries the chain's reverse registrar on-chain (ENSIP-19).
    Read-only — no wallet or funds required.
    """

    name: str = "reverse_resolve_ens"
    description: str = (
        "Looks up the primary ENS or Basenames name for a given 0x address "
        "on the specified chain (e.g. Ethereum, Base). Read-only. Use when "
        "you have a hex address and want to display the human-readable name, "
        "or to verify name ↔ address ownership. Returns the name or null "
        "if no primary is set."
    )
    args_schema: type[BaseModel] = ReverseResolveENSInput

    async def _arun(self, **kwargs: Any) -> dict[str, Any]:
        address: str = kwargs["address"]
        chain = kwargs.get("chain")
        try:
            ens_name = await self.ens_client.reverse_resolve(
                address, chain=chain
            )
        except ValueError as exc:
            logger.warning("reverse_resolve_ens failed: %s", exc)
            return {"address": address, "name": None, "error": str(exc)}
        chain_id = (
            resolve_ens_chain(chain).chain_id
            if chain is not None
            else self.ens_client.default_chain_id
        )
        if ens_name is None:
            return {
                "address": address,
                "chain_id": chain_id,
                "name": None,
                "error": "No primary name set for this address on this chain.",
            }
        return {"address": address, "chain_id": chain_id, "name": ens_name}
