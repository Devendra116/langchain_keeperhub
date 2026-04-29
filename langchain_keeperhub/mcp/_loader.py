"""Load KeeperHub MCP-server tools as LangChain BaseTools.

This module bridges KeeperHub's hosted MCP server into LangChain via the
official ``langchain-mcp-adapters`` package. The resulting tools cover
the *cold path*: workflow CRUD, AI generation, plugin/template catalogs,
and integrations. The *hot path* (transfers, contract calls, status)
stays on the native REST tools defined in ``langchain_keeperhub.tools``.

Design notes
------------

* The ``langchain_mcp_adapters`` import is deferred to call time so the
  SDK keeps importing without the optional dependency installed.
* Authentication uses an org-scoped API key (``kh_`` prefix) passed as a
  Bearer header. OAuth flows are intentionally out of scope for the SDK.
* The loader caches the underlying ``MultiServerMCPClient`` for the
  lifetime of the instance so repeated ``aload_tools`` calls do not
  reopen sessions.
* Tools are returned with their server-side names. Collision and prefix
  policy is the toolkit's job, not the loader's.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Collection
from typing import TYPE_CHECKING, Any

from langchain_keeperhub._exceptions import MCPDependencyError

if TYPE_CHECKING:  # pragma: no cover - typing only
    from langchain_core.tools import BaseTool

_DEFAULT_URL = "https://app.keeperhub.com/mcp"
_DEFAULT_TIMEOUT = 30.0
_DEFAULT_TRANSPORT = "streamable_http"
_DEFAULT_SERVER_NAME = "keeperhub"

# tools_documentation is a meta-tool that returns docs for other MCP
# tools. It tends to confuse agents and burn prompt tokens; users who
# want it can pass exclude=set() (or a set without it) to opt back in.
_DEFAULT_EXCLUDE: frozenset[str] = frozenset({"tools_documentation"})

logger = logging.getLogger(__name__)


class KeeperHubMCPLoader:
    """Load KeeperHub MCP tools as LangChain ``BaseTool`` instances.

    Args:
        api_key: Organisation-scoped KeeperHub API key (``kh_`` prefix).
            Falls back to the ``KEEPERHUB_API_KEY`` env var.
        url: MCP endpoint. Defaults to KeeperHub's hosted server.
        timeout: Per-request timeout in seconds for the underlying MCP
            transport.
        transport: Transport string passed to ``MultiServerMCPClient``.
            Defaults to ``"streamable_http"`` (the modern MCP HTTP
            transport with SSE fallback). Override only if KeeperHub
            advertises a different transport in the future.
        server_name: Logical server name used inside the MCP client's
            connection map. Surfaces in some error messages; defaults
            to ``"keeperhub"``.

    Usage::

        loader = KeeperHubMCPLoader(api_key="kh_...")
        try:
            tools = await loader.aload_tools(include={"list_workflows"})
        finally:
            await loader.aclose()
    """

    DEFAULT_URL = _DEFAULT_URL
    DEFAULT_EXCLUDE = _DEFAULT_EXCLUDE

    def __init__(
        self,
        api_key: str | None = None,
        *,
        url: str = _DEFAULT_URL,
        timeout: float = _DEFAULT_TIMEOUT,
        transport: str = _DEFAULT_TRANSPORT,
        server_name: str = _DEFAULT_SERVER_NAME,
    ) -> None:
        resolved_key = api_key or os.environ.get("KEEPERHUB_API_KEY", "")
        if not resolved_key:
            raise ValueError(
                "api_key is required. Pass it directly or set KEEPERHUB_API_KEY."
            )
        if not url:
            raise ValueError("url cannot be empty.")
        if timeout <= 0:
            raise ValueError("timeout must be positive.")
        self._api_key = resolved_key
        self._url = url
        self._timeout = timeout
        self._transport = transport
        self._server_name = server_name
        self._client: Any | None = None
        self._closed = False

    # -- lifecycle ----------------------------------------------------------

    def _build_connection(self) -> dict[str, Any]:
        return {
            self._server_name: {
                "transport": self._transport,
                "url": self._url,
                "headers": {"Authorization": f"Bearer {self._api_key}"},
            }
        }

    def _ensure_client(self) -> Any:
        """Lazily import the adapter and build the cached MCP client."""
        if self._closed:
            raise RuntimeError(
                "KeeperHubMCPLoader is closed; create a new instance."
            )
        if self._client is not None:
            return self._client
        try:
            from langchain_mcp_adapters.client import (  # type: ignore[import-not-found]
                MultiServerMCPClient,
            )
        except ImportError as exc:
            raise MCPDependencyError(
                "Workflow tools require the optional 'langchain-mcp-adapters' "
                "dependency. Install with: "
                'pip install "langchain-keeperhub[workflows]"'
            ) from exc

        connection = self._build_connection()
        self._client = MultiServerMCPClient(connection)
        logger.info(
            "opened MCP session to %s (transport=%s)",
            self._url,
            self._transport,
        )
        return self._client

    async def aload_tools(
        self,
        *,
        include: Collection[str] | None = None,
        exclude: Collection[str] | None = None,
    ) -> list[BaseTool]:
        """Return KeeperHub MCP tools, optionally filtered by name.

        Args:
            include: When provided, only tools whose name matches an
                entry are returned. Unknown names emit a ``WARNING`` log
                but do not raise — server tool names can change between
                releases.
            exclude: Names to drop. Defaults to
                :attr:`DEFAULT_EXCLUDE` (which removes the noisy
                ``tools_documentation`` meta-tool). Pass ``set()`` to
                disable the default.

        Returns:
            A list of LangChain-compatible ``BaseTool`` objects.
        """
        client = self._ensure_client()
        tools: list[BaseTool] = await client.get_tools()
        available = {t.name for t in tools}

        excluded = set(self.DEFAULT_EXCLUDE if exclude is None else exclude)

        if include is not None:
            wanted = set(include)
            unknown = wanted - available
            if unknown:
                logger.warning(
                    "unknown MCP tool names in include filter: %s "
                    "(available: %s)",
                    sorted(unknown),
                    sorted(available),
                )
            tools = [t for t in tools if t.name in wanted]

        tools = [t for t in tools if t.name not in excluded]

        logger.debug(
            "loaded %d MCP tools from %s: %s",
            len(tools),
            self._url,
            [t.name for t in tools],
        )
        return tools

    async def aclose(self) -> None:
        """Release MCP-client resources. Idempotent."""
        if self._closed:
            return
        self._closed = True
        client = self._client
        self._client = None
        if client is None:
            return
        # MultiServerMCPClient is stateless per-call by default and may
        # not expose an explicit close. Call it if it does; otherwise
        # the GC handles transient sessions.
        close = getattr(client, "aclose", None) or getattr(client, "close", None)
        if close is None:
            return
        try:
            result = close()
            if hasattr(result, "__await__"):
                await result
        except Exception as exc:  # noqa: BLE001 - best-effort cleanup
            logger.warning("MCP client close failed: %s", exc)

    async def __aenter__(self) -> KeeperHubMCPLoader:
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        await self.aclose()
