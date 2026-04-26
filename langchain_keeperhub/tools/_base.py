"""Shared LangChain tool plumbing for KeeperHub tools."""

from __future__ import annotations

from typing import Any

from langchain_core.tools import BaseTool
from pydantic import Field

from langchain_keeperhub._async_utils import run_sync
from langchain_keeperhub.client import KeeperHubClient


class _KeeperHubToolBase(BaseTool):
    """Base class for KeeperHub tools with a shared client and sync bridge."""

    client: KeeperHubClient = Field(exclude=True)

    model_config = {"arbitrary_types_allowed": True}

    def _run(self, **kwargs: Any) -> dict[str, Any]:
        return run_sync(self._arun(**kwargs))
