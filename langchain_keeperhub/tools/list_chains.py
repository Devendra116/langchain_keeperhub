"""ListChainsTool — discover supported blockchain networks."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from langchain_keeperhub.tools._base import _KeeperHubToolBase


class ListChainsInput(BaseModel):
    """Input schema for ListChainsTool."""

    include_disabled: bool = Field(
        default=False,
        description="Include disabled chains in the response.",
    )


class ListChainsTool(_KeeperHubToolBase):
    """List all blockchain networks supported by KeeperHub.

    Returns chain IDs, names, symbols, explorer URLs, and testnet flags.
    Call this first when you need to verify which networks are available
    or to look up a chain ID for a subsequent operation.
    """

    name: str = "list_chains"
    description: str = (
        "Lists supported chains (id, name, symbol, explorer, testnet flag). "
        "Use when you are unsure of the `network` string or chain ID before "
        "`transfer_funds` or `contract_call`, or when the user "
        "asks what networks are available. Read-only — no wallet or funds required."
    )
    args_schema: type[BaseModel] = ListChainsInput

    async def _arun(self, **kwargs: Any) -> dict[str, Any]:
        return await self.client.list_chains(
            include_disabled=kwargs.get("include_disabled", False)
        )
