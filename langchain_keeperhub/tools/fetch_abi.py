"""FetchContractABITool — fetch verified ABI from block explorer."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from langchain_keeperhub._types import EvmAddress
from langchain_keeperhub.tools._base import _KeeperHubToolBase


class FetchContractABIInput(BaseModel):
    """Input schema for FetchContractABITool."""

    chain_id: str = Field(
        description='Chain ID as string (e.g. "1" for Ethereum, "8453" for Base).'
    )
    address: EvmAddress = Field(
        description="Contract address to fetch the ABI for (0x-prefixed)."
    )


class FetchContractABITool(_KeeperHubToolBase):
    """Fetch the ABI for a verified smart contract from the block explorer.

    Useful before calling ``contract_call`` when you need to know
    available functions, their parameters, and return types.
    """

    name: str = "fetch_contract_abi"
    description: str = (
        "Loads a verified contract's ABI from the block explorer (JSON array of functions). "
        "Use when you must know exact function names and argument shapes before "
        "`contract_call` or `check_and_execute`, or when ABI "
        "auto-fetch may fail. Only works if the contract is verified on that chain."
    )
    args_schema: type[BaseModel] = FetchContractABIInput

    async def _arun(self, **kwargs: Any) -> dict[str, Any]:
        return await self.client.fetch_abi(
            chain_id=kwargs["chain_id"],
            address=kwargs["address"],
        )
