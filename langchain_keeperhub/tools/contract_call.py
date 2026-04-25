"""ContractCallTool — read from or write to any smart contract."""

from __future__ import annotations

import asyncio
import json
from typing import Any, Optional, Type

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

from langchain_keeperhub.client import KeeperHubClient


class ContractCallInput(BaseModel):
    """Input schema for ContractCallTool."""

    contract_address: str = Field(
        description="Smart contract address (0x-prefixed)."
    )
    network: str = Field(
        description='Blockchain network name or chain ID (e.g. "ethereum", "8453").'
    )
    function_name: str = Field(
        description='Name of the contract function to call (e.g. "balanceOf").'
    )
    function_args: Optional[str] = Field(
        default=None,
        description=(
            "JSON array string of function arguments. "
            'Example: \'["0x742d...bEb", "1000"]\'. '
            "Omit if function takes no parameters."
        ),
    )
    abi: Optional[str] = Field(
        default=None,
        description=(
            "Contract ABI as a JSON string. "
            "Auto-fetched from block explorer if omitted."
        ),
    )
    value: Optional[str] = Field(
        default=None,
        description="ETH value in wei to send with a payable function call.",
    )
    gas_limit_multiplier: Optional[str] = Field(
        default=None,
        description='Gas limit multiplier (e.g. "1.2").',
    )


class ContractCallTool(BaseTool):
    """Call any smart contract function (read or write).

    Read (view/pure) functions return the result directly.
    Write functions return an ``execution_id`` — poll with
    ``get_execution_status`` until the transaction settles.
    """

    name: str = "keeperhub_contract_call"
    description: str = (
        "Read from or write to any smart contract function on a supported "
        "chain via KeeperHub. Read calls return the result directly. "
        "Write calls return an execution_id to poll with get_execution_status."
    )
    args_schema: Type[BaseModel] = ContractCallInput
    client: KeeperHubClient = Field(exclude=True)

    model_config = {"arbitrary_types_allowed": True}

    def _run(self, **kwargs: Any) -> str:
        return asyncio.get_event_loop().run_until_complete(self._arun(**kwargs))

    async def _arun(self, **kwargs: Any) -> str:
        result = await self.client.contract_call(
            contract_address=kwargs["contract_address"],
            network=kwargs["network"],
            function_name=kwargs["function_name"],
            function_args=kwargs.get("function_args"),
            abi=kwargs.get("abi"),
            value=kwargs.get("value"),
            gas_limit_multiplier=kwargs.get("gas_limit_multiplier"),
        )
        return json.dumps(result)
