"""TransferFundsTool — send native or ERC-20 tokens via KeeperHub."""

from __future__ import annotations

import json
from typing import Any, Optional, Type

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

from langchain_keeperhub._async_utils import run_sync
from langchain_keeperhub._types import EvmAddress, PositiveDecimalString
from langchain_keeperhub.client import KeeperHubClient


class TransferFundsInput(BaseModel):
    """Input schema for TransferFundsTool."""

    network: str = Field(
        description=(
            'Blockchain network name (e.g. "ethereum", "base", "polygon") '
            "or chain ID as string."
        )
    )
    recipient_address: EvmAddress = Field(
        description="Destination wallet address (0x-prefixed, 42 chars)."
    )
    amount: str = Field(
        description=(
            'Amount in human-readable units (e.g. "0.1" for 0.1 ETH '
            'or "10" for 10 USDC).'
        )
    )
    token_address: Optional[EvmAddress] = Field(
        default=None,
        description=(
            "ERC-20 token contract address. "
            "Omit for native token (ETH/MATIC/etc.) transfers."
        ),
    )
    gas_limit_multiplier: Optional[PositiveDecimalString] = Field(
        default=None,
        description='Gas limit multiplier as a positive decimal string (e.g. "1.5" for 50% buffer).',
    )


class TransferFundsTool(BaseTool):
    """Send native tokens or ERC-20 tokens to an address on any supported chain.

    Returns a JSON object with ``execution_id`` and ``status``.
    After a write, call ``get_execution_status`` with the returned
    ``execution_id`` to poll until the transaction completes.
    """

    name: str = "keeperhub_transfer_funds"
    description: str = (
        "Transfer native tokens (ETH, MATIC, etc.) or ERC-20 tokens to a "
        "recipient address on a supported blockchain network via KeeperHub. "
        "Returns an execution_id to poll with get_execution_status."
    )
    args_schema: Type[BaseModel] = TransferFundsInput
    client: KeeperHubClient = Field(exclude=True)

    model_config = {"arbitrary_types_allowed": True}

    def _run(self, **kwargs: Any) -> str:
        return run_sync(self._arun(**kwargs))

    async def _arun(self, **kwargs: Any) -> str:
        result = await self.client.transfer(
            network=kwargs["network"],
            recipient_address=kwargs["recipient_address"],
            amount=kwargs["amount"],
            token_address=kwargs.get("token_address"),
            gas_limit_multiplier=kwargs.get("gas_limit_multiplier"),
        )
        return json.dumps(result)
