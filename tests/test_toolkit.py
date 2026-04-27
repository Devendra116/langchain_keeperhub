"""Tests for KeeperHubToolkit surface shape."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

from langchain_core.tools import BaseToolkit

from langchain_keeperhub.history import SqliteExecutionStore
from langchain_keeperhub.toolkit import KeeperHubToolkit
from langchain_keeperhub.tools.list_executions import ListExecutionsTool


def test_toolkit_is_a_basetoolkit() -> None:
    toolkit = KeeperHubToolkit(api_key="kh_test")
    assert isinstance(toolkit, BaseToolkit)


def test_toolkit_exposes_shared_client_and_tools() -> None:
    toolkit = KeeperHubToolkit(api_key="kh_test")
    tools = toolkit.get_tools()

    assert toolkit.client is toolkit._client
    assert len(tools) == 7
    assert all(tool.client is toolkit.client for tool in tools)
    assert toolkit.history is None
    assert not any(isinstance(t, ListExecutionsTool) for t in tools)


def test_toolkit_with_history_exposes_list_executions_tool(tmp_path: Path) -> None:
    store = SqliteExecutionStore(tmp_path / "h.db")
    try:
        toolkit = KeeperHubToolkit(api_key="kh_test", history=store)
        tools = toolkit.get_tools()

        assert toolkit.history is store
        assert len(tools) == 8
        assert any(isinstance(t, ListExecutionsTool) for t in tools)
    finally:
        store._close_sync()


async def test_toolkit_aclose_delegates_to_shared_client() -> None:
    toolkit = KeeperHubToolkit(api_key="kh_test")
    toolkit.client.aclose = AsyncMock()

    await toolkit.aclose()

    toolkit.client.aclose.assert_awaited_once()


async def test_toolkit_async_context_manager_closes_shared_client() -> None:
    toolkit = KeeperHubToolkit(api_key="kh_test")
    toolkit.client.aclose = AsyncMock()

    async with toolkit as entered:
        assert entered is toolkit

    toolkit.client.aclose.assert_awaited_once()
