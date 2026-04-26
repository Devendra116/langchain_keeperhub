"""KeeperHubToolkit — single entry point bundling all KeeperHub tools."""

from __future__ import annotations

from langchain_core.tools import BaseTool, BaseToolkit

from langchain_keeperhub.client import KeeperHubClient
from langchain_keeperhub.tools.check_and_execute import CheckAndExecuteTool
from langchain_keeperhub.tools.contract_call import ContractCallTool
from langchain_keeperhub.tools.execution_status import GetExecutionStatusTool
from langchain_keeperhub.tools.fetch_abi import FetchContractABITool
from langchain_keeperhub.tools.list_chains import ListChainsTool
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
    """

    def __init__(
        self,
        api_key: str | None = None,
        *,
        base_url: str | None = None,
    ) -> None:
        self._client = KeeperHubClient(api_key, base_url=base_url)

    @property
    def client(self) -> KeeperHubClient:
        """The shared HTTP client used by all tools."""
        return self._client

    def get_tools(self) -> list[BaseTool]:
        """Return the list of LangChain tools backed by this toolkit's client."""
        c = self._client
        return [
            ListChainsTool(client=c),
            FetchContractABITool(client=c),
            TransferFundsTool(client=c),
            ContractCallTool(client=c),
            CheckAndExecuteTool(client=c),
            GetExecutionStatusTool(client=c),
        ]
