"""ResolveENSTool — ENS / Basenames forward resolution (name → address)."""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, Field

from langchain_keeperhub.ens_chains import resolve_ens_chain
from langchain_keeperhub.tools._base import _ENSToolBase

logger = logging.getLogger(__name__)


class ResolveENSInput(BaseModel):
    """Input for ENS forward resolution."""

    name: str = Field(
        description=(
            "The ENS or Basenames name to resolve, e.g. 'vitalik.eth' "
            "or 'nick.base.eth'."
        ),
    )
    chain: int | str | None = Field(
        default=None,
        description=(
            "Optional chain override: 1 / 'ethereum', 8453 / 'base', "
            "11155111 / 'sepolia', 84532 / 'base-sepolia'. "
            "Omit to use the toolkit default chain."
        ),
    )


class ResolveENSTool(_ENSToolBase):
    """Resolve an ENS or Basenames name to its on-chain address.

    Performs a read-only ``eth_call`` against the chain's ENS Registry
    and resolver. No wallet or funds required.
    """

    name: str = "resolve_ens"
    description: str = (
        "Converts an ENS name (e.g. 'vitalik.eth') or Basenames name "
        "(e.g. 'nick.base.eth') to its hex address on the specified chain. "
        "Read-only. Use when the user provides a .eth or .base.eth name "
        "instead of a 0x address — before transfers, contract calls, "
        "workflows, or standalone lookups. Returns the address or an error."
    )
    args_schema: type[BaseModel] = ResolveENSInput

    async def _arun(self, **kwargs: Any) -> dict[str, Any]:
        ens_name: str = kwargs["name"]
        chain = kwargs.get("chain")
        try:
            address = await self.ens_client.resolve(ens_name, chain=chain)
        except ValueError as exc:
            logger.warning("resolve_ens failed: %s", exc)
            return {"name": ens_name, "address": None, "error": str(exc)}
        chain_id = (
            resolve_ens_chain(chain).chain_id
            if chain is not None
            else self.ens_client.default_chain_id
        )
        if address is None:
            return {
                "name": ens_name,
                "chain_id": chain_id,
                "address": None,
                "error": "ENS name not found or has no address record on this chain.",
            }
        return {"name": ens_name, "chain_id": chain_id, "address": address}
