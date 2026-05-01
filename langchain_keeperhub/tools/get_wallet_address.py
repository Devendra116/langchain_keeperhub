"""GetWalletAddressTool — fetch the KeeperHub account wallet address."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from langchain_keeperhub._exceptions import WalletNotConfiguredError
from langchain_keeperhub.tools._base import _KeeperHubToolBase


class GetWalletAddressInput(BaseModel):
    """Input schema for GetWalletAddressTool."""


_WALLET_NOT_CONNECTED_WARNING = (
    "No wallet is connected to this KeeperHub account. Create or connect a "
    "KeeperHub wallet, or explicitly pass the wallet address you want to use."
)


class GetWalletAddressTool(_KeeperHubToolBase):
    """Fetch the wallet address connected to the authenticated account."""

    name: str = "get_wallet_address"
    description: str = (
        "Returns this account's linked EVM wallet address. "
        "Use when the user asks for their wallet, 'my address', or the sender/from "
        "address tied to KeeperHub. If no wallet is linked, the response says so "
        "instead of returning an address."
    )
    args_schema: type[BaseModel] = GetWalletAddressInput

    async def _arun(self, **kwargs: Any) -> dict[str, Any]:
        try:
            user = await self.client.get_user()
        except WalletNotConfiguredError as exc:
            return {
                "warning": _WALLET_NOT_CONNECTED_WARNING,
                "wallet_connected": False,
                "details": exc.body or {"error": str(exc)},
            }

        wallet_address = user.get("walletAddress")
        if not wallet_address:
            return {
                "warning": _WALLET_NOT_CONNECTED_WARNING,
                "wallet_connected": False,
                "user": user,
            }

        return {
            "wallet_connected": True,
            "address": wallet_address,
            "user": user,
        }
