"""KeeperHubToolkit — single entry point bundling all KeeperHub tools."""

from __future__ import annotations

from collections.abc import Collection

from langchain_core.tools import BaseTool, BaseToolkit

from langchain_keeperhub.client import KeeperHubClient
from langchain_keeperhub.history._store import ExecutionStore
from langchain_keeperhub.tools.check_and_execute import CheckAndExecuteTool
from langchain_keeperhub.tools.contract_call import ContractCallTool
from langchain_keeperhub.tools.execution_status import GetExecutionStatusTool
from langchain_keeperhub.tools.fetch_abi import FetchContractABITool
from langchain_keeperhub.tools.get_wallet_address import GetWalletAddressTool
from langchain_keeperhub.tools.list_chains import ListChainsTool
from langchain_keeperhub.tools.list_executions import ListExecutionsTool
from langchain_keeperhub.tools.transfer import TransferFundsTool


class KeeperHubToolkit(BaseToolkit):
    """Bundle of LangChain tools for reliable Web3 execution via KeeperHub.

    Usage::

        from langchain_keeperhub import KeeperHubToolkit

        toolkit = KeeperHubToolkit(api_key="kh_...")
        tools = toolkit.get_tools()
        # pass *tools* to create_react_agent, AgentExecutor, or LangGraph

    Args:
        api_key: Organisation-scoped KeeperHub API key (``kh_`` prefix).
            Falls back to ``KEEPERHUB_API_KEY`` env var.
        base_url: Override the KeeperHub API root
            (default ``https://app.keeperhub.com``).
        testnet_only: When true, write tools reject chains not marked as
            testnets by KeeperHub.
        allowed_chain_ids: Optional allowlist of chain IDs for write tools.
        history: Optional :class:`ExecutionStore` to persist write executions.
            Pass ``True`` to use the default :class:`SqliteExecutionStore`
            at ``~/.keeperhub/executions.db``. When set, the toolkit also
            exposes a ``keeperhub_list_executions`` tool the agent can use
            to query past activity.
    """

    def __init__(
        self,
        api_key: str | None = None,
        *,
        base_url: str | None = None,
        testnet_only: bool = False,
        allowed_chain_ids: Collection[int | str] | None = None,
        history: ExecutionStore | bool | None = None,
    ) -> None:
        self._client = KeeperHubClient(
            api_key,
            base_url=base_url,
            testnet_only=testnet_only,
            allowed_chain_ids=allowed_chain_ids,
            history=history,
        )

    @property
    def client(self) -> KeeperHubClient:
        """The shared HTTP client used by all tools."""
        return self._client

    @property
    def history(self) -> ExecutionStore | None:
        """The execution-history store, or ``None`` when persistence is off."""
        return self._client.history

    async def aclose(self) -> None:
        """Close the shared KeeperHub client."""
        await self._client.aclose()

    async def __aenter__(self) -> "KeeperHubToolkit":
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        await self.aclose()

    def get_tools(self) -> list[BaseTool]:
        """Return the list of LangChain tools backed by this toolkit's client.

        ``ListExecutionsTool`` is included only when history is enabled, so
        the agent never gets a tool that always returns an empty list.
        """
        c = self._client
        tools: list[BaseTool] = [
            ListChainsTool(client=c),
            FetchContractABITool(client=c),
            GetWalletAddressTool(client=c),
            TransferFundsTool(client=c),
            ContractCallTool(client=c),
            CheckAndExecuteTool(client=c),
            GetExecutionStatusTool(client=c),
        ]
        if c.history is not None:
            tools.append(ListExecutionsTool(client=c))
        return tools
