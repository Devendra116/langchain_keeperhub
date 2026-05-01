"""TransferFundsTool — send native or ERC-20 tokens via KeeperHub."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from langchain_keeperhub._types import EvmAddress, PositiveDecimalString
from langchain_keeperhub.tools._base import _KeeperHubToolBase


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
    token_address: EvmAddress | None = Field(
        default=None,
        description=(
            "ERC-20 token contract address. "
            "Omit for native token (ETH/MATIC/etc.) transfers."
        ),
    )
    gas_limit_multiplier: PositiveDecimalString | None = Field(
        default=None,
        description='Gas limit multiplier as a positive decimal string (e.g. "1.5" for 50% buffer).',
    )


class TransferFundsTool(_KeeperHubToolBase):
    """Send native tokens or ERC-20 tokens to an address on any supported chain.

    Returns a JSON object with ``execution_id`` and ``status``.
    After a write, call ``get_execution_status`` with the returned
    ``execution_id`` to poll until the transaction completes.
    """

    name: str = "transfer_funds"
    description: str = (
        "Sends native coin (omit token_address) or an ERC-20 (pass token contract) "
        "from the KeeperHub wallet to a recipient. "
        "Use for simple sends/payments — not for arbitrary contract logic "
        "(use `contract_call`). "
        "Needs a linked wallet with enough balance and gas; confirm recipient and "
        "amount with the user. Returns `execution_id` — then call "
        "`get_execution_status` until done."
    )
    args_schema: type[BaseModel] = TransferFundsInput

    async def _arun(self, **kwargs: Any) -> dict[str, Any]:
        return await self.client.transfer(
            network=kwargs["network"],
            recipient_address=kwargs["recipient_address"],
            amount=kwargs["amount"],
            token_address=kwargs.get("token_address"),
            gas_limit_multiplier=kwargs.get("gas_limit_multiplier"),
        )
