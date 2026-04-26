"""Tests for KeeperHubToolkit surface shape."""

from __future__ import annotations

from langchain_core.tools import BaseToolkit

from langchain_keeperhub.toolkit import KeeperHubToolkit


def test_toolkit_is_a_basetoolkit() -> None:
    toolkit = KeeperHubToolkit(api_key="kh_test")
    assert isinstance(toolkit, BaseToolkit)


def test_toolkit_exposes_shared_client_and_tools() -> None:
    toolkit = KeeperHubToolkit(api_key="kh_test")
    tools = toolkit.get_tools()

    assert toolkit.client is toolkit._client
    assert len(tools) == 6
    assert all(tool.client is toolkit.client for tool in tools)
