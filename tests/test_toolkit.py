"""Tests for KeeperHubToolkit surface shape."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.tools import BaseToolkit, StructuredTool

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


# -- workflows=True (MCP bridge) ---------------------------------------------


def _stub_tool(name: str) -> StructuredTool:
    """Build a minimal real BaseTool so model_copy works exactly as in prod."""

    def _noop(x: int = 0) -> str:
        """Stub callable used only to satisfy StructuredTool construction."""
        return str(x)

    return StructuredTool.from_function(_noop, name=name)


def _stub_tool_with_json_schema_dict(name: str) -> StructuredTool:
    """MCP-style tool: ``args_schema`` is a raw JSON Schema dict with metadata."""

    async def _noop(**_kwargs: Any) -> str:
        return "ok"

    return StructuredTool(
        name=name,
        description="stub",
        coroutine=_noop,
        args_schema={
            "$schema": "http://json-schema.org/draft-07/schema#",
            "$id": "urn:keeperhub:test-tool",
            "type": "object",
            "properties": {
                "projectId": {
                    "$schema": "http://json-schema.org/draft-07/schema#",
                    "type": "string",
                },
            },
        },
    )


def _dict_contains_key(obj: Any, key: str) -> bool:
    if isinstance(obj, dict):
        if key in obj:
            return True
        return any(_dict_contains_key(v, key) for v in obj.values())
    if isinstance(obj, list):
        return any(_dict_contains_key(v, key) for v in obj)
    return False


def _patch_loader(
    monkeypatch: pytest.MonkeyPatch,
    raw_tools: list[StructuredTool],
) -> tuple[Any, AsyncMock]:
    """Replace KeeperHubMCPLoader with a mock returning ``raw_tools``.

    Returns the (loader_class, aload_tools_mock) pair so individual
    tests can assert on call arguments.
    """
    aload = AsyncMock(return_value=raw_tools)
    aclose = AsyncMock()
    instance = MagicMock()
    instance.aload_tools = aload
    instance.aclose = aclose

    cls = MagicMock(return_value=instance)
    cls.DEFAULT_URL = "https://app.keeperhub.com/mcp"

    import langchain_keeperhub.mcp as mcp_pkg

    monkeypatch.setattr(mcp_pkg, "KeeperHubMCPLoader", cls)
    return cls, aload


def test_get_tools_raises_when_workflows_enabled() -> None:
    toolkit = KeeperHubToolkit(api_key="kh_test", workflows=True)
    with pytest.raises(RuntimeError, match="aget_tools"):
        toolkit.get_tools()


async def test_aget_tools_returns_native_only_when_workflows_off() -> None:
    """Async path still works without workflows; just returns natives."""
    toolkit = KeeperHubToolkit(api_key="kh_test")
    tools = await toolkit.aget_tools()
    assert len(tools) == 7


async def test_aget_tools_appends_mcp_tools_with_prefix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cls, aload = _patch_loader(
        monkeypatch,
        [_stub_tool("list_workflows"), _stub_tool("execute_workflow")],
    )
    toolkit = KeeperHubToolkit(api_key="kh_test", workflows=True)

    tools = await toolkit.aget_tools()
    names = [t.name for t in tools]

    assert "keeperhub_list_workflows" in names
    assert "keeperhub_execute_workflow" in names
    assert len([n for n in names if not n.startswith("keeperhub_")]) == 0
    cls.assert_called_once()
    kwargs = cls.call_args.kwargs
    assert kwargs["api_key"] == "kh_test"


async def test_mcp_dict_args_schema_strips_json_schema_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SDK removes ``$schema`` / ``$id`` from MCP dict schemas for LLM binders."""
    _patch_loader(
        monkeypatch,
        [_stub_tool_with_json_schema_dict("list_workflows")],
    )
    toolkit = KeeperHubToolkit(api_key="kh_test", workflows=True)
    tools = await toolkit.aget_tools()
    mcp = next(t for t in tools if t.name == "keeperhub_list_workflows")
    schema = mcp.args_schema
    assert isinstance(schema, dict)
    assert not _dict_contains_key(schema, "$schema")
    assert not _dict_contains_key(schema, "$id")


async def test_collision_renamed_to_workflow_alias(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """``get_execution_status`` exists natively → MCP version gets renamed."""
    _patch_loader(monkeypatch, [_stub_tool("get_execution_status")])
    toolkit = KeeperHubToolkit(api_key="kh_test", workflows=True)

    with caplog.at_level(logging.INFO, logger="langchain_keeperhub.toolkit"):
        tools = await toolkit.aget_tools()

    names = {t.name for t in tools}
    assert "keeperhub_get_execution_status" in names
    assert "keeperhub_workflow_get_execution_status" in names
    # Native + renamed MCP both present, no duplicate names.
    assert len(names) == len(tools)
    assert any(
        "renaming to 'keeperhub_workflow_get_execution_status'"
        in record.getMessage()
        for record in caplog.records
    )


async def test_mcp_filters_pass_through(monkeypatch: pytest.MonkeyPatch) -> None:
    _, aload = _patch_loader(monkeypatch, [])
    toolkit = KeeperHubToolkit(
        api_key="kh_test",
        workflows=True,
        mcp_include={"list_workflows", "execute_workflow"},
        mcp_exclude={"tools_documentation"},
    )
    await toolkit.aget_tools()

    aload.assert_awaited_once()
    kwargs = aload.call_args.kwargs
    assert set(kwargs["include"]) == {"list_workflows", "execute_workflow"}
    assert set(kwargs["exclude"]) == {"tools_documentation"}


async def test_aget_tools_caches_mcp_tools(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, aload = _patch_loader(monkeypatch, [_stub_tool("list_workflows")])
    toolkit = KeeperHubToolkit(api_key="kh_test", workflows=True)

    first = await toolkit.aget_tools()
    second = await toolkit.aget_tools()

    assert [t.name for t in first] == [t.name for t in second]
    aload.assert_awaited_once()  # second call reused cache; no reload


async def test_aclose_closes_both_subsystems(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cls, _ = _patch_loader(monkeypatch, [])
    toolkit = KeeperHubToolkit(api_key="kh_test", workflows=True)
    toolkit.client.aclose = AsyncMock()

    await toolkit.aget_tools()  # forces loader instantiation
    await toolkit.aclose()
    await toolkit.aclose()  # idempotent

    toolkit.client.aclose.assert_awaited()
    cls.return_value.aclose.assert_awaited()


async def test_workflows_off_never_imports_mcp_module(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A user who never sets workflows=True must never trigger the lazy
    import of ``langchain_keeperhub.mcp``. We guard this by replacing
    the loader class with one that explodes on construction; if the
    default path imports it, this test fails."""
    import langchain_keeperhub.mcp as mcp_pkg

    def _boom(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("MCP loader must not be constructed when workflows=False")

    monkeypatch.setattr(mcp_pkg, "KeeperHubMCPLoader", _boom)

    toolkit = KeeperHubToolkit(api_key="kh_test")
    tools = await toolkit.aget_tools()
    assert len(tools) == 7
