"""ContractCallTool — read from or write to any smart contract."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from langchain_keeperhub._types import EvmAddress, PositiveDecimalString
from langchain_keeperhub.tools._base import _KeeperHubToolBase


class ContractCallInput(BaseModel):
    """Input schema for ContractCallTool."""

    contract_address: EvmAddress = Field(
        description="Smart contract address (0x-prefixed)."
    )
    network: str = Field(
        description='Blockchain network name or chain ID (e.g. "ethereum", "8453").'
    )
    function_name: str = Field(
        description='Name of the contract function to call (e.g. "balanceOf").'
    )
    function_args: str | None = Field(
        default=None,
        description=(
            "JSON array string of function arguments. "
            'Example: \'["0x742d...bEb", "1000"]\'. '
            "Omit if function takes no parameters."
        ),
    )
    abi: str | None = Field(
        default=None,
        description=(
            "Contract ABI as a JSON string. "
            "Auto-fetched from block explorer if omitted."
        ),
    )
    value: str | None = Field(
        default=None,
        description="ETH value in wei to send with a payable function call.",
    )
    gas_limit_multiplier: PositiveDecimalString | None = Field(
        default=None,
        description='Gas limit multiplier as a positive decimal string (e.g. "1.2").',
    )


class ContractCallTool(_KeeperHubToolBase):
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
    args_schema: type[BaseModel] = ContractCallInput

    async def _arun(self, **kwargs: Any) -> dict[str, Any]:
        return await self.client.contract_call(
            contract_address=kwargs["contract_address"],
            network=kwargs["network"],
            function_name=kwargs["function_name"],
            function_args=kwargs.get("function_args"),
            abi=kwargs.get("abi"),
            value=kwargs.get("value"),
            gas_limit_multiplier=kwargs.get("gas_limit_multiplier"),
        )
