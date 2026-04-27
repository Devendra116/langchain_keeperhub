"""Tests for LangChain tool wrappers — mock the client, verify output."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from langchain_keeperhub._exceptions import WalletNotConfiguredError
from langchain_keeperhub.client import KeeperHubClient
from langchain_keeperhub.history import (
    ExecutionKind,
    ExecutionRecord,
    SqliteExecutionStore,
)
from langchain_keeperhub.tools.check_and_execute import (
    ActionInput,
    CheckAndExecuteInput,
    ConditionInput,
    CheckAndExecuteTool,
)
from langchain_keeperhub.tools.contract_call import (
    ContractCallInput,
    ContractCallTool,
)
from langchain_keeperhub.tools.execution_status import GetExecutionStatusTool
from langchain_keeperhub.tools.fetch_abi import (
    FetchContractABIInput,
    FetchContractABITool,
)
from langchain_keeperhub.tools.get_wallet_address import GetWalletAddressTool
from langchain_keeperhub.tools.list_chains import ListChainsTool
from langchain_keeperhub.tools.list_executions import (
    ListExecutionsInput,
    ListExecutionsTool,
)
from langchain_keeperhub.tools.transfer import TransferFundsInput, TransferFundsTool



def _mock_client() -> KeeperHubClient:
    """Create a client with a fake key (methods will be patched)."""
    return KeeperHubClient(api_key="kh_test_mock", base_url="https://mock.local")


def test_sync_run_methods_return_structured_output():
    client = _mock_client()
    client.list_chains = AsyncMock(return_value={"data": []})
    client.fetch_abi = AsyncMock(return_value={"abi": []})
    client.transfer = AsyncMock(return_value={"executionId": "transfer_1"})
    client.contract_call = AsyncMock(return_value={"result": "42"})
    client.check_and_execute = AsyncMock(return_value={"executed": False})
    client.get_execution_status = AsyncMock(return_value={"status": "completed"})
    client.get_user = AsyncMock(
        return_value={
            "id": "user_123",
            "walletAddress": "0x742d35Cc6634C0532925a3b844Bc454e4438f44e",
        }
    )

    assert ListChainsTool(client=client)._run(include_disabled=False) == {"data": []}
    assert FetchContractABITool(client=client)._run(
        chain_id="1",
        address="0x742d35Cc6634C0532925a3b844Bc454e4438f44e",
    ) == {"abi": []}
    assert TransferFundsTool(client=client)._run(
        network="ethereum",
        recipient_address="0x742d35Cc6634C0532925a3b844Bc454e4438f44e",
        amount="1",
    ) == {"executionId": "transfer_1"}
    assert ContractCallTool(client=client)._run(
        contract_address="0x742d35Cc6634C0532925a3b844Bc454e4438f44e",
        network="ethereum",
        function_name="balanceOf",
    ) == {"result": "42"}
    assert CheckAndExecuteTool(client=client)._run(
        contract_address="0x742d35Cc6634C0532925a3b844Bc454e4438f44e",
        network="ethereum",
        function_name="balanceOf",
        condition={"operator": "gt", "value": "100"},
        action={
            "contract_address": "0x742d35Cc6634C0532925a3b844Bc454e4438f44e",
            "function_name": "transfer",
        },
    ) == {"executed": False}
    assert GetExecutionStatusTool(client=client)._run(
        execution_id="direct_99"
    ) == {"status": "completed"}
    assert GetWalletAddressTool(client=client)._run() == {
        "wallet_connected": True,
        "address": "0x742d35Cc6634C0532925a3b844Bc454e4438f44e",
        "user": {
            "id": "user_123",
            "walletAddress": "0x742d35Cc6634C0532925a3b844Bc454e4438f44e",
        },
    }


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
    result = await tool._arun(include_disabled=False)
    assert result["data"][0]["chainId"] == 1
    client.list_chains.assert_awaited_once()


# -- TransferFundsTool --------------------------------------------------------


async def test_transfer_tool():
    client = _mock_client()
    client.transfer = AsyncMock(
        return_value={"executionId": "direct_99", "status": "completed"}
    )
    tool = TransferFundsTool(client=client)
    result = await tool._arun(
        network="ethereum",
        recipient_address="0xabc",
        amount="1.0",
    )
    assert result["executionId"] == "direct_99"
    client.transfer.assert_awaited_once_with(
        network="ethereum",
        recipient_address="0xabc",
        amount="1.0",
        token_address=None,
        gas_limit_multiplier=None,
    )


# -- ContractCallTool ----------------------------------------------------------


async def test_contract_call_tool_returns_structured_output():
    client = _mock_client()
    client.contract_call = AsyncMock(return_value={"result": "42"})
    tool = ContractCallTool(client=client)

    result = await tool._arun(
        contract_address="0x742d35Cc6634C0532925a3b844Bc454e4438f44e",
        network="ethereum",
        function_name="balanceOf",
        function_args='["0xabc"]',
    )

    assert result == {"result": "42"}
    client.contract_call.assert_awaited_once_with(
        contract_address="0x742d35Cc6634C0532925a3b844Bc454e4438f44e",
        network="ethereum",
        function_name="balanceOf",
        function_args='["0xabc"]',
        abi=None,
        value=None,
        gas_limit_multiplier=None,
    )


# -- FetchContractABITool ------------------------------------------------------


async def test_fetch_contract_abi_tool_returns_structured_output():
    client = _mock_client()
    client.fetch_abi = AsyncMock(
        return_value={"abi": [{"type": "function", "name": "balanceOf"}]}
    )
    tool = FetchContractABITool(client=client)

    result = await tool._arun(
        chain_id="1",
        address="0x742d35Cc6634C0532925a3b844Bc454e4438f44e",
    )

    assert result["abi"][0]["name"] == "balanceOf"
    client.fetch_abi.assert_awaited_once_with(
        chain_id="1",
        address="0x742d35Cc6634C0532925a3b844Bc454e4438f44e",
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
    result = await tool._arun(execution_id="direct_99")
    assert result["status"] == "completed"
    assert result["transactionHash"] == "0xdeadbeef"


async def test_get_wallet_address_tool_returns_connected_wallet():
    client = _mock_client()
    client.get_user = AsyncMock(
        return_value={
            "id": "user_123",
            "name": "John Doe",
            "email": "john@example.com",
            "image": "https://example.com/avatar.png",
            "isAnonymous": False,
            "providerId": "google",
            "walletAddress": "0x742d35Cc6634C0532925a3b844Bc454e4438f44e",
        }
    )
    tool = GetWalletAddressTool(client=client)

    result = await tool._arun()

    assert result == {
        "wallet_connected": True,
        "address": "0x742d35Cc6634C0532925a3b844Bc454e4438f44e",
        "user": {
            "id": "user_123",
            "name": "John Doe",
            "email": "john@example.com",
            "image": "https://example.com/avatar.png",
            "isAnonymous": False,
            "providerId": "google",
            "walletAddress": "0x742d35Cc6634C0532925a3b844Bc454e4438f44e",
        },
    }
    client.get_user.assert_awaited_once()


async def test_get_wallet_address_tool_warns_when_wallet_not_connected():
    client = _mock_client()
    client.get_user = AsyncMock(
        side_effect=WalletNotConfiguredError(
            "Wallet not configured",
            status_code=422,
            body={"error": "Wallet not configured"},
        )
    )
    tool = GetWalletAddressTool(client=client)

    result = await tool._arun()

    assert result["wallet_connected"] is False
    assert "No wallet is connected" in result["warning"]
    assert "explicitly pass" in result["warning"]
    assert result["details"] == {"error": "Wallet not configured"}


async def test_get_wallet_address_tool_warns_when_user_has_no_wallet_address():
    client = _mock_client()
    client.get_user = AsyncMock(
        return_value={
            "id": "user_123",
            "email": "john@example.com",
            "walletAddress": None,
        }
    )
    tool = GetWalletAddressTool(client=client)

    result = await tool._arun()

    assert result["wallet_connected"] is False
    assert "No wallet is connected" in result["warning"]
    assert result["user"]["walletAddress"] is None


async def test_check_and_execute_tool_serializes_action_to_api_shape():
    client = _mock_client()
    client.check_and_execute = AsyncMock(
        return_value={"executed": True, "executionId": "direct_100"}
    )
    tool = CheckAndExecuteTool(client=client)

    result = await tool._arun(
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

    assert result["executionId"] == "direct_100"
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


async def test_check_and_execute_tool_accepts_condition_model():
    client = _mock_client()
    client.check_and_execute = AsyncMock(return_value={"executed": False})
    tool = CheckAndExecuteTool(client=client)

    result = await tool._arun(
        contract_address="0x742d35Cc6634C0532925a3b844Bc454e4438f44e",
        network="ethereum",
        function_name="balanceOf",
        condition=ConditionInput(operator="gt", value="100"),
        action=ActionInput(
            contract_address="0x742d35Cc6634C0532925a3b844Bc454e4438f44e",
            function_name="transfer",
        ),
    )

    assert result == {"executed": False}
    client.check_and_execute.assert_awaited_once_with(
        contract_address="0x742d35Cc6634C0532925a3b844Bc454e4438f44e",
        network="ethereum",
        function_name="balanceOf",
        function_args=None,
        abi=None,
        condition={"operator": "gt", "value": "100"},
        action={
            "contractAddress": "0x742d35Cc6634C0532925a3b844Bc454e4438f44e",
            "functionName": "transfer",
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


# -- ListExecutionsTool ------------------------------------------------------


def _client_with_store(tmp_path) -> tuple[KeeperHubClient, SqliteExecutionStore]:
    store = SqliteExecutionStore(tmp_path / "h.db")
    client = KeeperHubClient(
        api_key="kh_test_mock", base_url="https://mock.local", history=store
    )
    return client, store


async def _seed(store: SqliteExecutionStore) -> None:
    await store.record(
        ExecutionRecord(
            execution_id="ex_1",
            kind=ExecutionKind.TRANSFER,
            network="1",
            status="completed",
            transaction_hash="0xa",
            created_at="2026-04-01T00:00:00+00:00",
            updated_at="2026-04-01T00:00:00+00:00",
        )
    )
    await store.record(
        ExecutionRecord(
            execution_id="ex_2",
            kind=ExecutionKind.CONTRACT_CALL,
            network="8453",
            status="pending",
            created_at="2026-04-15T00:00:00+00:00",
            updated_at="2026-04-15T00:00:00+00:00",
        )
    )


async def test_list_executions_tool_returns_to_dict_payload(tmp_path):
    client, store = _client_with_store(tmp_path)
    await _seed(store)
    try:
        tool = ListExecutionsTool(client=client)
        result = await tool._arun()
        assert "executions" in result
        ids = [e["execution_id"] for e in result["executions"]]
        # newest first
        assert ids == ["ex_2", "ex_1"]
        assert result["executions"][0]["kind"] == "contract_call"
    finally:
        store._close_sync()


async def test_list_executions_tool_filters_by_status_and_kind(tmp_path):
    client, store = _client_with_store(tmp_path)
    await _seed(store)
    try:
        tool = ListExecutionsTool(client=client)
        result = await tool._arun(status="completed", kind="transfer")
        ids = [e["execution_id"] for e in result["executions"]]
        assert ids == ["ex_1"]
    finally:
        store._close_sync()


async def test_list_executions_tool_filters_by_since_and_network(tmp_path):
    client, store = _client_with_store(tmp_path)
    await _seed(store)
    try:
        tool = ListExecutionsTool(client=client)
        result = await tool._arun(
            since="2026-04-10T00:00:00+00:00", network="8453"
        )
        ids = [e["execution_id"] for e in result["executions"]]
        assert ids == ["ex_2"]
    finally:
        store._close_sync()


async def test_list_executions_tool_warns_when_history_disabled():
    client = KeeperHubClient(api_key="kh_test_mock", base_url="https://mock.local")
    tool = ListExecutionsTool(client=client)
    result = await tool._arun()
    assert result["executions"] == []
    assert "Execution history is disabled" in result["warning"]


def test_list_executions_input_rejects_unknown_status():
    with pytest.raises(ValidationError):
        ListExecutionsInput.model_validate({"status": "weird"})


def test_list_executions_input_rejects_out_of_range_limit():
    with pytest.raises(ValidationError):
        ListExecutionsInput.model_validate({"limit": 0})
    with pytest.raises(ValidationError):
        ListExecutionsInput.model_validate({"limit": 1000})
