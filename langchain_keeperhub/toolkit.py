"""KeeperHubToolkit — single entry point bundling all KeeperHub tools.

The toolkit always exposes the native REST tools (the *hot path* —
transfers, contract calls, status, chains/ABI, wallet address). When
``workflows=True``, it also bridges KeeperHub's hosted MCP server (the
*cold path* — workflow CRUD, AI generation, plugin/template catalogs)
via :class:`KeeperHubMCPLoader`. MCP loading is async, so opting in
forces use of :meth:`aget_tools` instead of :meth:`get_tools`.

Naming policy for MCP tools
---------------------------

When an MCP tool name collides with a native tool name (today:
``get_execution_status`` exists for both direct and workflow execution),
the MCP tool is renamed to ``workflow_<orig>`` instead. The rename is
logged at ``INFO`` so it is visible during integration.

JSON Schema on MCP tools
------------------------

MCP tools often ship draft-07 JSON Schemas with ``$schema`` / ``$id``
metadata. Several LLM tool-binding layers (notably Google GenAI) log
warnings or drop those keys on every request. The toolkit strips that
metadata once when MCP tools are merged, so callers do not need to
post-process tool definitions.
"""

from __future__ import annotations

import copy
import logging
import os
from collections.abc import Collection
from typing import Any

from langchain_core.tools import BaseTool, BaseToolkit

from langchain_keeperhub.client import KeeperHubClient
from langchain_keeperhub.ens import ENSClient
from langchain_keeperhub.history._store import ExecutionStore
from langchain_keeperhub.tools.check_and_execute import CheckAndExecuteTool
from langchain_keeperhub.tools.contract_call import ContractCallTool
from langchain_keeperhub.tools.execution_status import GetExecutionStatusTool
from langchain_keeperhub.tools.fetch_abi import FetchContractABITool
from langchain_keeperhub.tools.get_wallet_address import GetWalletAddressTool
from langchain_keeperhub.tools.list_chains import ListChainsTool
from langchain_keeperhub.tools.list_executions import ListExecutionsTool
from langchain_keeperhub.tools.resolve_ens import ResolveENSTool
from langchain_keeperhub.tools.reverse_resolve_ens import ReverseResolveENSTool
from langchain_keeperhub.tools.transfer import TransferFundsTool

_WORKFLOW_PREFIX = "workflow_"

# Keys JSON Schema uses for meta / cross-document identity. Google GenAI
# and other binders reject or warn on these on every tool round-trip.
_JSON_SCHEMA_LLM_METADATA_KEYS: frozenset[str] = frozenset({"$schema", "$id"})

logger = logging.getLogger(__name__)


def _ens_chain_from_env() -> int | str:
    raw = os.environ.get("ENS_CHAIN_ID", "").strip()
    if not raw:
        return 1
    if raw.isdigit():
        return int(raw)
    return raw


def _strip_json_schema_llm_metadata(value: Any) -> Any:
    """Recursively drop JSON Schema keys that LLM function APIs often reject.

    MCP servers commonly attach ``$schema`` (draft-07) and ``$id`` to tool
    input schemas. Stripping them here avoids per-request warnings (e.g.
    ``langchain_google_genai``) and slightly shrinks serialized tool defs.
    """
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, child in value.items():
            if key in _JSON_SCHEMA_LLM_METADATA_KEYS:
                continue
            out[key] = _strip_json_schema_llm_metadata(child)
        return out
    if isinstance(value, list):
        return [_strip_json_schema_llm_metadata(item) for item in value]
    return value


def _sanitize_mcp_tool_json_schema(tool: BaseTool) -> BaseTool:
    """Return a copy of ``tool`` with dict ``args_schema`` cleaned for LLMs."""
    schema = getattr(tool, "args_schema", None)
    if not isinstance(schema, dict):
        return tool
    cleaned = _strip_json_schema_llm_metadata(copy.deepcopy(schema))
    return tool.model_copy(update={"args_schema": cleaned})


class KeeperHubToolkit(BaseToolkit):
    """Bundle of LangChain tools for reliable Web3 execution via KeeperHub.

    Usage::

        from langchain_keeperhub import KeeperHubToolkit

        toolkit = KeeperHubToolkit(api_key="kh_...")
        tools = toolkit.get_tools()
        # pass *tools* to create_agent, AgentExecutor, or LangGraph

    Workflow-management tools (opt-in)::

        toolkit = KeeperHubToolkit(api_key="kh_...", workflows=True)
        tools = await toolkit.aget_tools()   # async — MCP loads asynchronously

    Args:
        api_key: Organisation-scoped KeeperHub API key (``kh_`` prefix).
            Falls back to ``KEEPERHUB_API_KEY`` env var. The same key
            is reused for both the REST client and the MCP loader.
        base_url: Override the KeeperHub API root
            (default ``https://app.keeperhub.com``).
        testnet_only: When true, write tools reject chains not marked as
            testnets by KeeperHub.
        allowed_chain_ids: Optional allowlist of chain IDs for write tools.
        history: Optional :class:`ExecutionStore` to persist write executions.
            Pass ``True`` to use the default :class:`SqliteExecutionStore`
            at ``~/.keeperhub/executions.db``. When set, the toolkit also
            exposes a ``list_execution_history`` tool the agent can use
            to query past activity.
        workflows: When true, :meth:`aget_tools` also returns workflow
            management tools loaded from KeeperHub's MCP server. Off by
            default — existing users see no behaviour change. MCP tools
            whose ``args_schema`` is a JSON dict are sanitized (e.g.
            ``$schema`` / ``$id`` removed) for LLM compatibility.
        mcp_url: MCP endpoint URL. Defaults to KeeperHub's hosted server.
        mcp_include: Optional whitelist of MCP tool names (server-side names).
        mcp_exclude: Optional blacklist of MCP tool names. When ``None``
            (default), ``tools_documentation`` is excluded; pass an empty
            set to keep every tool the server returns.
        ens_rpc_url: JSON-RPC URL used for **all** ENS calls when set (also
            ``ENS_RPC_URL`` / ``ETH_RPC_URL``). When unset, each built-in
            ``ens_chain`` uses that network's default public RPC.
        ens_chain: Default chain for ENS tools: id (``1``, ``8453``, …) or
            alias (``\"ethereum\"``, ``\"base\"``, ``\"sepolia\"``, ``\"base-sepolia\"``).
            Falls back to ``ENS_CHAIN_ID`` env, then Ethereum mainnet (``1``).
        ens_registry: Optional custom ENS registry (``0x`` + 40 hex). When set,
            ``ens_rpc_url`` (or ``ENS_RPC_URL`` / ``ETH_RPC_URL``) is required.
            Per-call ``chain`` on ENS tools is disabled.
    """

    def __init__(
        self,
        api_key: str | None = None,
        *,
        base_url: str | None = None,
        testnet_only: bool = False,
        allowed_chain_ids: Collection[int | str] | None = None,
        history: ExecutionStore | bool | None = None,
        workflows: bool = False,
        mcp_url: str | None = None,
        mcp_include: Collection[str] | None = None,
        mcp_exclude: Collection[str] | None = None,
        ens_rpc_url: str | None = None,
        ens_chain: int | str | None = None,
        ens_registry: str | None = None,
    ) -> None:
        self._client = KeeperHubClient(
            api_key,
            base_url=base_url,
            testnet_only=testnet_only,
            allowed_chain_ids=allowed_chain_ids,
            history=history,
        )
        chain = ens_chain if ens_chain is not None else _ens_chain_from_env()
        self._ens_client = ENSClient(
            ens_rpc_url,
            chain=chain,
            registry=ens_registry,
        )
        self._workflows = workflows
        self._mcp_url = mcp_url
        self._mcp_include = (
            tuple(mcp_include) if mcp_include is not None else None
        )
        self._mcp_exclude = (
            tuple(mcp_exclude) if mcp_exclude is not None else None
        )
        # Lazily built on first aget_tools() call so default users (and
        # users who never opt into workflows=True) never import or
        # instantiate the optional MCP adapter.
        self._mcp_loader: object | None = None
        self._mcp_tools_cache: list[BaseTool] | None = None

    # -- public surface ------------------------------------------------------

    @property
    def client(self) -> KeeperHubClient:
        """The shared HTTP client used by all native tools."""
        return self._client

    @property
    def history(self) -> ExecutionStore | None:
        """The execution-history store, or ``None`` when persistence is off."""
        return self._client.history

    async def aclose(self) -> None:
        """Close the shared KeeperHub client, ENS client, and the MCP loader (if used)."""
        await self._client.aclose()
        await self._ens_client.aclose()
        loader = self._mcp_loader
        if loader is not None:
            self._mcp_loader = None
            close = getattr(loader, "aclose", None)
            if close is not None:
                await close()

    async def __aenter__(self) -> "KeeperHubToolkit":
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        await self.aclose()

    # -- tool surface --------------------------------------------------------

    def _native_tools(self) -> list[BaseTool]:
        """Build the native (REST-backed) tool list. Cheap; no caching."""
        c = self._client
        e = self._ens_client
        tools: list[BaseTool] = [
            ListChainsTool(client=c),
            FetchContractABITool(client=c),
            GetWalletAddressTool(client=c),
            TransferFundsTool(client=c),
            ContractCallTool(client=c),
            CheckAndExecuteTool(client=c),
            GetExecutionStatusTool(client=c),
            ResolveENSTool(ens_client=e),
            ReverseResolveENSTool(ens_client=e),
        ]
        if c.history is not None:
            tools.append(ListExecutionsTool(client=c))
        return tools

    def get_tools(self) -> list[BaseTool]:
        """Return native tools synchronously.

        When ``workflows=True``, MCP tools must be loaded asynchronously,
        so this raises a clear error pointing to :meth:`aget_tools`. We
        deliberately do not spin up a background event loop here — users
        opting into workflows are already in async land (LangGraph) and
        a hidden ``asyncio.run`` would only paper over a real
        architectural mismatch.
        """
        if self._workflows:
            raise RuntimeError(
                "KeeperHubToolkit was created with workflows=True; "
                "use 'await toolkit.aget_tools()' instead of get_tools(). "
                "MCP tool loading is asynchronous."
            )
        return self._native_tools()

    async def aget_tools(self) -> list[BaseTool]:
        """Return native tools, plus MCP-bridged tools when ``workflows=True``.

        MCP tools are loaded once and cached on the toolkit instance.
        Subsequent calls reuse the same loader and tool list.
        """
        tools = self._native_tools()
        if self._workflows:
            tools.extend(await self._aget_mcp_tools(tools))
        return tools

    # -- MCP bridge ---------------------------------------------------------

    async def _aget_mcp_tools(
        self, native_tools: list[BaseTool]
    ) -> list[BaseTool]:
        if self._mcp_tools_cache is not None:
            return self._mcp_tools_cache

        loader = self._mcp_loader
        if loader is None:
            # Lazy import keeps the optional dependency genuinely
            # optional: nobody pays for the MCP module unless they ask.
            from langchain_keeperhub.mcp import KeeperHubMCPLoader

            loader = KeeperHubMCPLoader(
                api_key=self._client.api_key,
                url=self._mcp_url or KeeperHubMCPLoader.DEFAULT_URL,
            )
            self._mcp_loader = loader

        raw = await loader.aload_tools(  # type: ignore[attr-defined]
            include=self._mcp_include,
            exclude=self._mcp_exclude,
        )
        renamed = self._namespace_mcp_tools(raw, native_tools)
        self._mcp_tools_cache = renamed
        return renamed

    def _namespace_mcp_tools(
        self,
        mcp_tools: list[BaseTool],
        native_tools: list[BaseTool],
    ) -> list[BaseTool]:
        """Resolve name collisions between MCP tools and native tools.

        MCP tools keep their original name unless it collides with a
        native tool, in which case the MCP tool is renamed to
        ``workflow_<orig>`` and the rename is logged at INFO.
        """
        native_names = {t.name for t in native_tools}
        result: list[BaseTool] = []
        for tool in mcp_tools:
            original = tool.name
            if original in native_names:
                final = f"{_WORKFLOW_PREFIX}{original}"
                logger.info(
                    "MCP tool '%s' collides with native '%s'; "
                    "renaming to '%s' for the workflow surface",
                    original, original, final,
                )
            else:
                final = original
            renamed = _rename_tool(tool, final) if final != original else tool
            result.append(_sanitize_mcp_tool_json_schema(renamed))
        return result


def _rename_tool(tool: BaseTool, new_name: str) -> BaseTool:
    """Return a copy of ``tool`` with its ``name`` rewritten.

    ``BaseTool`` is a Pydantic model; ``model_copy(update=...)`` keeps
    the original schema, description, and async callable intact while
    producing a fresh instance — safer than mutating the original in
    place, which could surprise callers who hold references.
    """
    return tool.model_copy(update={"name": new_name})
