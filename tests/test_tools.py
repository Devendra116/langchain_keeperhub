"""Tests for LangChain tool wrappers — mock the client, verify output."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from langchain_keeperhub.client import KeeperHubClient
from langchain_keeperhub.tools.execution_status import GetExecutionStatusTool
from langchain_keeperhub.tools.list_chains import ListChainsTool
from langchain_keeperhub.tools.transfer import TransferFundsTool



def _mock_client() -> KeeperHubClient:
    """Create a client with a fake key (methods will be patched)."""
    return KeeperHubClient(api_key="kh_test_mock", base_url="https://mock.local")


# -- ListChainsTool -----------------------------------------------------------


async def test_list_chains_tool():
    client = _mock_client()
    client.list_chains = AsyncMock(
        return_value={
            "data": [
                {"chainId": 1, "name": "Ethereum Mainnet", "symbol": "ETH"}
            ]
        }
    )
    tool = ListChainsTool(client=client)
    raw = await tool._arun(include_disabled=False)
    parsed = json.loads(raw)
    assert parsed["data"][0]["chainId"] == 1
    client.list_chains.assert_awaited_once()


# -- TransferFundsTool --------------------------------------------------------


async def test_transfer_tool():
    client = _mock_client()
    client.transfer = AsyncMock(
        return_value={"executionId": "direct_99", "status": "completed"}
    )
    tool = TransferFundsTool(client=client)
    raw = await tool._arun(
        network="ethereum",
        recipient_address="0xabc",
        amount="1.0",
    )
    parsed = json.loads(raw)
    assert parsed["executionId"] == "direct_99"
    client.transfer.assert_awaited_once_with(
        network="ethereum",
        recipient_address="0xabc",
        amount="1.0",
        token_address=None,
        gas_limit_multiplier=None,
    )


# -- GetExecutionStatusTool ---------------------------------------------------


async def test_execution_status_tool():
    client = _mock_client()
    client.get_execution_status = AsyncMock(
        return_value={
            "executionId": "direct_99",
            "status": "completed",
            "transactionHash": "0xdeadbeef",
        }
    )
    tool = GetExecutionStatusTool(client=client)
    raw = await tool._arun(execution_id="direct_99")
    parsed = json.loads(raw)
    assert parsed["status"] == "completed"
    assert parsed["transactionHash"] == "0xdeadbeef"
