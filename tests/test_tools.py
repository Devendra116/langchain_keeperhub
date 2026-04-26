"""Tests for LangChain tool wrappers — mock the client, verify output."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from langchain_keeperhub.client import KeeperHubClient
from langchain_keeperhub.tools.check_and_execute import (
    ActionInput,
    CheckAndExecuteInput,
    CheckAndExecuteTool,
)
from langchain_keeperhub.tools.contract_call import ContractCallInput
from langchain_keeperhub.tools.execution_status import GetExecutionStatusTool
from langchain_keeperhub.tools.fetch_abi import FetchContractABIInput
from langchain_keeperhub.tools.list_chains import ListChainsTool
from langchain_keeperhub.tools.transfer import TransferFundsInput, TransferFundsTool



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


async def test_check_and_execute_tool_serializes_action_to_api_shape():
    client = _mock_client()
    client.check_and_execute = AsyncMock(
        return_value={"executed": True, "executionId": "direct_100"}
    )
    tool = CheckAndExecuteTool(client=client)

    raw = await tool._arun(
        contract_address="0x742d35Cc6634C0532925a3b844Bc454e4438f44e",
        network="ethereum",
        function_name="latestAnswer",
        abi='[{"type":"function","name":"latestAnswer"}]',
        condition={"operator": "gt", "value": "100"},
        action={
            "contract_address": "0x742d35Cc6634C0532925a3b844Bc454e4438f44e",
            "function_name": "swapExactTokensForTokens",
            "function_args": '["0xabc", "500"]',
            "abi": '[{"type":"function","name":"swapExactTokensForTokens"}]',
            "gas_limit_multiplier": "1.5",
        },
    )

    parsed = json.loads(raw)
    assert parsed["executionId"] == "direct_100"
    client.check_and_execute.assert_awaited_once_with(
        contract_address="0x742d35Cc6634C0532925a3b844Bc454e4438f44e",
        network="ethereum",
        function_name="latestAnswer",
        function_args=None,
        abi='[{"type":"function","name":"latestAnswer"}]',
        condition={"operator": "gt", "value": "100"},
        action={
            "contractAddress": "0x742d35Cc6634C0532925a3b844Bc454e4438f44e",
            "functionName": "swapExactTokensForTokens",
            "functionArgs": '["0xabc", "500"]',
            "abi": '[{"type":"function","name":"swapExactTokensForTokens"}]',
            "gasLimitMultiplier": "1.5",
        },
    )


def test_transfer_input_rejects_invalid_recipient_address():
    with pytest.raises(ValidationError):
        TransferFundsInput.model_validate(
            {
                "network": "ethereum",
                "recipient_address": "0x742d35Cc6634C0532925a3b844Bc9e7595f0bEb",
                "amount": "1",
            }
        )


def test_contract_call_input_rejects_invalid_contract_address():
    with pytest.raises(ValidationError):
        ContractCallInput.model_validate(
            {
                "contract_address": "0xabc",
                "network": "ethereum",
                "function_name": "balanceOf",
            }
        )


def test_fetch_abi_input_rejects_invalid_address():
    with pytest.raises(ValidationError):
        FetchContractABIInput.model_validate(
            {"chain_id": "1", "address": "not-an-address"}
        )


def test_check_and_execute_input_rejects_invalid_action_address():
    with pytest.raises(ValidationError):
        CheckAndExecuteInput.model_validate(
            {
                "contract_address": "0x742d35Cc6634C0532925a3b844Bc454e4438f44e",
                "network": "ethereum",
                "function_name": "balanceOf",
                "condition": {"operator": "gt", "value": "100"},
                "action": {
                    "contract_address": "0x123",
                    "function_name": "transfer",
                },
            }
        )


def test_transfer_input_rejects_invalid_gas_limit_multiplier():
    with pytest.raises(ValidationError):
        TransferFundsInput.model_validate(
            {
                "network": "ethereum",
                "recipient_address": "0x742d35Cc6634C0532925a3b844Bc454e4438f44e",
                "amount": "1",
                "gas_limit_multiplier": "1.2x",
            }
        )


def test_contract_call_input_rejects_non_positive_gas_limit_multiplier():
    with pytest.raises(ValidationError):
        ContractCallInput.model_validate(
            {
                "contract_address": "0x742d35Cc6634C0532925a3b844Bc454e4438f44e",
                "network": "ethereum",
                "function_name": "balanceOf",
                "gas_limit_multiplier": "0",
            }
        )


def test_check_and_execute_action_rejects_invalid_gas_limit_multiplier():
    with pytest.raises(ValidationError):
        CheckAndExecuteInput.model_validate(
            {
                "contract_address": "0x742d35Cc6634C0532925a3b844Bc454e4438f44e",
                "network": "ethereum",
                "function_name": "balanceOf",
                "condition": {"operator": "gt", "value": "100"},
                "action": {
                    "contract_address": "0x742d35Cc6634C0532925a3b844Bc454e4438f44e",
                    "function_name": "transfer",
                    "gas_limit_multiplier": "50%",
                },
            }
        )


def test_check_and_execute_action_schema_uses_snake_case_only():
    properties = ActionInput.model_json_schema()["properties"]
    assert "contract_address" in properties
    assert "contractAddress" not in properties
    assert "function_name" in properties
    assert "functionName" not in properties
    assert "gas_limit_multiplier" in properties
    assert "gasLimitMultiplier" not in properties


def test_check_and_execute_action_rejects_camel_case_input():
    with pytest.raises(ValidationError):
        ActionInput.model_validate(
            {
                "contractAddress": "0x742d35Cc6634C0532925a3b844Bc454e4438f44e",
                "functionName": "transfer",
            }
        )
