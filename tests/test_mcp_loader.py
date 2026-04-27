"""Tests for KeeperHubMCPLoader — MCP client fully mocked."""

from __future__ import annotations

import logging
import sys
import types
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from langchain_keeperhub._exceptions import KeeperHubError, MCPDependencyError
from langchain_keeperhub.mcp import KeeperHubMCPLoader


class _FakeTool:
    """Minimal stand-in for ``langchain_core.tools.BaseTool``.

    The loader only reads ``.name`` to filter, so a thin object with that
    attribute is enough — keeps the test independent of langchain-core's
    internals.
    """

    def __init__(self, name: str) -> None:
        self.name = name


def _install_fake_adapter(monkeypatch: pytest.MonkeyPatch, tools: list[_FakeTool]):
    """Inject a fake ``langchain_mcp_adapters.client`` into ``sys.modules``.

    Returns the ``MultiServerMCPClient`` mock so tests can inspect calls.
    """
    client_instance = MagicMock()
    client_instance.get_tools = AsyncMock(return_value=list(tools))
    client_instance.aclose = AsyncMock()

    client_cls = MagicMock(return_value=client_instance)

    fake_pkg = types.ModuleType("langchain_mcp_adapters")
    fake_client_mod = types.ModuleType("langchain_mcp_adapters.client")
    fake_client_mod.MultiServerMCPClient = client_cls
    fake_pkg.client = fake_client_mod

    monkeypatch.setitem(sys.modules, "langchain_mcp_adapters", fake_pkg)
    monkeypatch.setitem(sys.modules, "langchain_mcp_adapters.client", fake_client_mod)
    return client_cls, client_instance


# -- construction --------------------------------------------------------------


def test_api_key_required(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("KEEPERHUB_API_KEY", raising=False)
    with pytest.raises(ValueError, match="api_key is required"):
        KeeperHubMCPLoader()


def test_env_var_fallback(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("KEEPERHUB_API_KEY", "kh_from_env")
    loader = KeeperHubMCPLoader()
    assert loader._api_key == "kh_from_env"


def test_invalid_url_or_timeout_rejected():
    with pytest.raises(ValueError, match="url"):
        KeeperHubMCPLoader(api_key="kh_x", url="")
    with pytest.raises(ValueError, match="timeout"):
        KeeperHubMCPLoader(api_key="kh_x", timeout=0)


# -- dependency handling -------------------------------------------------------


@pytest.mark.asyncio
async def test_missing_dependency_raises_typed_error(monkeypatch: pytest.MonkeyPatch):
    """Without ``langchain_mcp_adapters`` installed, raise ``MCPDependencyError``
    with the install hint, and confirm it inherits from ``KeeperHubError``
    so callers can catch the family."""
    monkeypatch.delitem(sys.modules, "langchain_mcp_adapters", raising=False)
    monkeypatch.delitem(sys.modules, "langchain_mcp_adapters.client", raising=False)

    real_import = __builtins__["__import__"] if isinstance(__builtins__, dict) else __builtins__.__import__  # type: ignore[index]

    def _blocked_import(name: str, *args: Any, **kwargs: Any):
        if name.startswith("langchain_mcp_adapters"):
            raise ImportError(f"No module named {name!r}")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", _blocked_import)

    loader = KeeperHubMCPLoader(api_key="kh_x")
    with pytest.raises(MCPDependencyError) as excinfo:
        await loader.aload_tools()

    msg = str(excinfo.value)
    assert "langchain-mcp-adapters" in msg
    assert "[workflows]" in msg
    assert isinstance(excinfo.value, KeeperHubError)


# -- transport configuration ---------------------------------------------------


@pytest.mark.asyncio
async def test_bearer_header_and_transport_passed(monkeypatch: pytest.MonkeyPatch):
    client_cls, _ = _install_fake_adapter(monkeypatch, [])
    loader = KeeperHubMCPLoader(api_key="kh_secret", server_name="kh")
    await loader.aload_tools()

    args, kwargs = client_cls.call_args
    connection = args[0] if args else kwargs.get("connections", kwargs.get("connection"))
    assert isinstance(connection, dict)
    cfg = connection["kh"]
    assert cfg["transport"] == "streamable_http"
    assert cfg["url"] == KeeperHubMCPLoader.DEFAULT_URL
    assert cfg["headers"] == {"Authorization": "Bearer kh_secret"}


@pytest.mark.asyncio
async def test_custom_transport_override(monkeypatch: pytest.MonkeyPatch):
    """If KeeperHub ever advertises plain ``http``, callers can override."""
    client_cls, _ = _install_fake_adapter(monkeypatch, [])
    loader = KeeperHubMCPLoader(api_key="kh_x", transport="http")
    await loader.aload_tools()
    cfg = client_cls.call_args[0][0]["keeperhub"]
    assert cfg["transport"] == "http"


# -- filtering -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_default_excludes_tools_documentation(monkeypatch: pytest.MonkeyPatch):
    tools = [_FakeTool("list_workflows"), _FakeTool("tools_documentation")]
    _install_fake_adapter(monkeypatch, tools)
    loader = KeeperHubMCPLoader(api_key="kh_x")
    result = await loader.aload_tools()
    names = {t.name for t in result}
    assert "tools_documentation" not in names
    assert "list_workflows" in names


@pytest.mark.asyncio
async def test_include_filter_warns_on_unknown_names(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    tools = [_FakeTool("list_workflows"), _FakeTool("execute_workflow")]
    _install_fake_adapter(monkeypatch, tools)
    loader = KeeperHubMCPLoader(api_key="kh_x")

    with caplog.at_level(logging.WARNING, logger="langchain_keeperhub.mcp"):
        result = await loader.aload_tools(
            include={"list_workflows", "does_not_exist"}
        )

    assert {t.name for t in result} == {"list_workflows"}
    assert any(
        "does_not_exist" in record.getMessage() for record in caplog.records
    ), "expected a warning naming the unknown filter entry"


@pytest.mark.asyncio
async def test_explicit_exclude_overrides_default(monkeypatch: pytest.MonkeyPatch):
    """Passing ``exclude=set()`` opts back into ``tools_documentation``."""
    tools = [_FakeTool("tools_documentation"), _FakeTool("list_workflows")]
    _install_fake_adapter(monkeypatch, tools)
    loader = KeeperHubMCPLoader(api_key="kh_x")
    result = await loader.aload_tools(exclude=set())
    assert {t.name for t in result} == {"tools_documentation", "list_workflows"}


# -- lifecycle -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_aclose_idempotent(monkeypatch: pytest.MonkeyPatch):
    _install_fake_adapter(monkeypatch, [])
    loader = KeeperHubMCPLoader(api_key="kh_x")
    await loader.aload_tools()
    await loader.aclose()
    await loader.aclose()  # second close must not raise
    with pytest.raises(RuntimeError, match="closed"):
        await loader.aload_tools()


@pytest.mark.asyncio
async def test_async_context_manager(monkeypatch: pytest.MonkeyPatch):
    _, client_instance = _install_fake_adapter(monkeypatch, [_FakeTool("x")])
    async with KeeperHubMCPLoader(api_key="kh_x") as loader:
        tools = await loader.aload_tools(exclude=set())
        assert [t.name for t in tools] == ["x"]
    client_instance.aclose.assert_awaited()


@pytest.mark.asyncio
async def test_repeated_load_reuses_single_client(monkeypatch: pytest.MonkeyPatch):
    """Second ``aload_tools`` call must not reopen the MCP session."""
    client_cls, _ = _install_fake_adapter(monkeypatch, [_FakeTool("x")])
    loader = KeeperHubMCPLoader(api_key="kh_x")
    await loader.aload_tools(exclude=set())
    await loader.aload_tools(exclude=set())
    assert client_cls.call_count == 1
