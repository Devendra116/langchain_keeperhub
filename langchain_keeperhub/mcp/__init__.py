"""KeeperHub MCP-server bridge — internal helpers for workflow tools.

The MCP loader turns KeeperHub's officially hosted MCP server
(``https://app.keeperhub.com/mcp``) into a list of LangChain ``BaseTool``
instances. It is consumed by :class:`KeeperHubToolkit` when the user opts
into ``workflows=True``; nothing in this package imports it eagerly.

The dependency on ``langchain-mcp-adapters`` is optional and only
required when this module is actually used. Install via the
``[workflows]`` extra::

    pip install "langchain-keeperhub[workflows]"
"""

from langchain_keeperhub.mcp._loader import KeeperHubMCPLoader

__all__ = ["KeeperHubMCPLoader"]
