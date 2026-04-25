"""ListChainsTool — discover supported blockchain networks."""

from __future__ import annotations

import asyncio
import json
from typing import Any, Type

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

from langchain_keeperhub.client import KeeperHubClient


class ListChainsInput(BaseModel):
    """Input schema for ListChainsTool."""

    include_disabled: bool = Field(
        default=False,
        description="Include disabled chains in the response.",
    )


class ListChainsTool(BaseTool):
    """List all blockchain networks supported by KeeperHub.

    Returns chain IDs, names, symbols, explorer URLs, and testnet flags.
    Call this first when you need to verify which networks are available
    or to look up a chain ID for a subsequent operation.
    """

    name: str = "keeperhub_list_chains"
    description: str = (
        "List all blockchain networks supported by KeeperHub. "
        "Returns chain IDs, names, native token symbols, block explorer URLs, "
        "and whether each chain is a testnet. Call this before transfer or "
        "contract_call if you need to confirm a network name or chain ID."
    )
    args_schema: Type[BaseModel] = ListChainsInput
    client: KeeperHubClient = Field(exclude=True)

    model_config = {"arbitrary_types_allowed": True}

    def _run(self, **kwargs: Any) -> str:
        return asyncio.get_event_loop().run_until_complete(self._arun(**kwargs))

    async def _arun(self, **kwargs: Any) -> str:
        result = await self.client.list_chains(
            include_disabled=kwargs.get("include_disabled", False)
        )
        return json.dumps(result)
