"""Tests for KeeperHubClient — all HTTP mocked via respx."""

from __future__ import annotations

import json
from unittest.mock import Mock

import pytest
import respx
import httpx
from httpx import Response

from langchain_keeperhub._exceptions import (
    AuthenticationError,
    KeeperHubError,
    NotFoundError,
    RateLimitError,
    ServerError,
    SpendingCapExceededError,
    ValidationError,
    WalletNotConfiguredError,
    raise_for_status,
)
from langchain_keeperhub._types import _validate_positive_decimal_string
from langchain_keeperhub.client import KeeperHubClient, _redact

from .conftest import TEST_API_KEY, TEST_BASE_URL


def _sent_json(route: respx.Route) -> dict[str, object]:
    return json.loads(route.calls.last.request.content)



# -- construction ------------------------------------------------------------


def test_missing_api_key_raises():
    with pytest.raises(ValueError, match="api_key is required"):
        KeeperHubClient(api_key="")


def test_env_var_fallback(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("KEEPERHUB_API_KEY", "kh_from_env")
    c = KeeperHubClient()
    assert c._api_key == "kh_from_env"


def test_allowed_chain_ids_rejects_empty_values():
    with pytest.raises(ValueError, match="allowed_chain_ids cannot contain empty"):
        KeeperHubClient(api_key=TEST_API_KEY, allowed_chain_ids={" "})


def test_redact_shortens_large_abi_payload():
    assert _redact({"abi": "x" * 65}) == {"abi": "<abi 65 chars>"}


def test_positive_decimal_validator_rejects_invalid_decimal():
    with pytest.raises(ValueError, match="positive decimal string"):
        _validate_positive_decimal_string("not-a-decimal")


@respx.mock
async def test_client_async_context_manager_closes_http():
    respx.get(f"{TEST_BASE_URL}/api/chains").mock(
        return_value=Response(200, json={"data": []})
    )
    async with KeeperHubClient(
        api_key=TEST_API_KEY,
        base_url=TEST_BASE_URL,
    ) as client:
        await client.list_chains()
        assert client._http is not None
        assert not client._http.is_closed
    assert client._http is not None
    assert client._http.is_closed


# -- list_chains --------------------------------------------------------------


@respx.mock
async def test_list_chains(client: KeeperHubClient):
    payload = {
        "data": [
            {
                "id": "chain_1",
                "chainId": 1,
                "name": "Ethereum Mainnet",
                "symbol": "ETH",
                "chainType": "evm",
                "isTestnet": False,
                "isEnabled": True,
            }
        ]
    }
    respx.get(f"{TEST_BASE_URL}/api/chains").mock(
        return_value=Response(200, json=payload)
    )
    result = await client.list_chains()
    assert result["data"][0]["chainId"] == 1
    await client.aclose()


@respx.mock
async def test_list_chains_include_disabled_sets_query_param(
    client: KeeperHubClient,
):
    route = respx.get(f"{TEST_BASE_URL}/api/chains").mock(
        return_value=Response(200, json={"data": []})
    )
    await client.list_chains(include_disabled=True)

    assert route.calls.last.request.url.params["includeDisabled"] == "true"
    await client.aclose()


# -- fetch_abi ----------------------------------------------------------------


@respx.mock
async def test_fetch_abi(client: KeeperHubClient):
    abi_payload = {
        "abi": [
            {
                "type": "function",
                "name": "balanceOf",
                "inputs": [{"name": "account", "type": "address"}],
                "outputs": [{"name": "", "type": "uint256"}],
            }
        ]
    }
    respx.get(f"{TEST_BASE_URL}/api/chains/1/abi").mock(
        return_value=Response(200, json=abi_payload)
    )
    result = await client.fetch_abi(chain_id=1, address="0xA0b8699")
    assert result["abi"][0]["name"] == "balanceOf"
    await client.aclose()


# -- transfer -----------------------------------------------------------------


@respx.mock
async def test_transfer(client: KeeperHubClient):
    respx.get(f"{TEST_BASE_URL}/api/chains").mock(
        return_value=Response(
            200,
            json={"data": [{"chainId": 1, "name": "ethereum", "id": "ethereum"}]},
        )
    )
    route = respx.post(f"{TEST_BASE_URL}/api/execute/transfer").mock(
        return_value=Response(
            200, json={"executionId": "direct_42", "status": "completed"}
        )
    )
    result = await client.transfer(
        network="ethereum",
        recipient_address="0xabc",
        amount="0.1",
    )
    assert result["executionId"] == "direct_42"
    assert result["status"] == "completed"
    assert _sent_json(route) == {
        "network": "1",
        "recipientAddress": "0xabc",
        "amount": "0.1",
    }
    await client.aclose()


@respx.mock
async def test_transfer_with_token(client: KeeperHubClient):
    respx.get(f"{TEST_BASE_URL}/api/chains").mock(
        return_value=Response(
            200,
            json={"data": [{"chainId": 8453, "name": "base", "id": "base"}]},
        )
    )
    route = respx.post(f"{TEST_BASE_URL}/api/execute/transfer").mock(
        return_value=Response(
            200, json={"executionId": "direct_43", "status": "completed"}
        )
    )
    await client.transfer(
        network="base",
        recipient_address="0xabc",
        amount="10",
        token_address="0xUSDC",
    )
    assert _sent_json(route) == {
        "network": "8453",
        "recipientAddress": "0xabc",
        "amount": "10",
        "tokenAddress": "0xUSDC",
    }
    await client.aclose()


@respx.mock
async def test_transfer_includes_optional_token_config_and_gas_multiplier(
    client: KeeperHubClient,
):
    respx.get(f"{TEST_BASE_URL}/api/chains").mock(
        return_value=Response(
            200,
            json={"data": [{"chainId": 8453, "name": "base", "id": "base"}]},
        )
    )
    route = respx.post(f"{TEST_BASE_URL}/api/execute/transfer").mock(
        return_value=Response(200, json={"executionId": "direct_44"})
    )
    await client.transfer(
        network="base",
        recipient_address="0xabc",
        amount="10",
        token_config='{"decimals":6}',
        gas_limit_multiplier="1.5",
    )
    assert _sent_json(route) == {
        "network": "8453",
        "recipientAddress": "0xabc",
        "amount": "10",
        "tokenConfig": '{"decimals":6}',
        "gasLimitMultiplier": "1.5",
    }
    await client.aclose()


# -- contract_call ------------------------------------------------------------


@respx.mock
async def test_contract_call_read(client: KeeperHubClient):
    respx.get(f"{TEST_BASE_URL}/api/chains").mock(
        return_value=Response(
            200,
            json={"data": [{"chainId": 1, "name": "ethereum", "id": "ethereum"}]},
        )
    )
    route = respx.post(f"{TEST_BASE_URL}/api/execute/contract-call").mock(
        return_value=Response(200, json={"result": "1500000000000000000"})
    )
    result = await client.contract_call(
        contract_address="0xDAI",
        network="ethereum",
        function_name="balanceOf",
        function_args='["0xabc"]',
    )
    assert result["result"] == "1500000000000000000"
    assert _sent_json(route) == {
        "contractAddress": "0xDAI",
        "network": "1",
        "functionName": "balanceOf",
        "functionArgs": '["0xabc"]',
    }
    await client.aclose()


@respx.mock
async def test_contract_call_write_includes_optional_fields(
    client: KeeperHubClient,
):
    respx.get(f"{TEST_BASE_URL}/api/chains").mock(
        return_value=Response(
            200,
            json={"data": [{"chainId": 1, "name": "ethereum", "id": "ethereum"}]},
        )
    )
    route = respx.post(f"{TEST_BASE_URL}/api/execute/contract-call").mock(
        return_value=Response(200, json={"executionId": "direct_47"})
    )
    result = await client.contract_call(
        contract_address="0xDAI",
        network="ethereum",
        function_name="deposit",
        abi='[{"type":"function","name":"deposit"}]',
        value="1000000000000000000",
        gas_limit_multiplier="1.2",
    )
    assert result["executionId"] == "direct_47"
    assert _sent_json(route) == {
        "contractAddress": "0xDAI",
        "network": "1",
        "functionName": "deposit",
        "abi": '[{"type":"function","name":"deposit"}]',
        "value": "1000000000000000000",
        "gasLimitMultiplier": "1.2",
    }
    await client.aclose()


# -- check_and_execute --------------------------------------------------------


@respx.mock
async def test_check_and_execute_not_met(client: KeeperHubClient):
    respx.get(f"{TEST_BASE_URL}/api/chains").mock(
        return_value=Response(
            200,
            json={"data": [{"chainId": 1, "name": "ethereum", "id": "ethereum"}]},
        )
    )
    route = respx.post(f"{TEST_BASE_URL}/api/execute/check-and-execute").mock(
        return_value=Response(
            200,
            json={
                "executed": False,
                "condition": {
                    "met": False,
                    "observedValue": "500",
                    "targetValue": "1000",
                    "operator": "gt",
                },
            },
        )
    )
    result = await client.check_and_execute(
        contract_address="0xDAI",
        network="ethereum",
        function_name="balanceOf",
        condition={"operator": "gt", "value": "1000"},
        action={
            "contractAddress": "0xDAI",
            "functionName": "transfer",
            "functionArgs": '["0xabc", "500"]',
        },
    )
    assert result["executed"] is False
    assert _sent_json(route) == {
        "contractAddress": "0xDAI",
        "network": "1",
        "functionName": "balanceOf",
        "condition": {"operator": "gt", "value": "1000"},
        "action": {
            "contractAddress": "0xDAI",
            "functionName": "transfer",
            "functionArgs": '["0xabc", "500"]',
        },
    }
    await client.aclose()


@respx.mock
async def test_check_and_execute_includes_optional_read_fields(
    client: KeeperHubClient,
):
    respx.get(f"{TEST_BASE_URL}/api/chains").mock(
        return_value=Response(
            200,
            json={"data": [{"chainId": 1, "name": "ethereum", "id": "ethereum"}]},
        )
    )
    route = respx.post(f"{TEST_BASE_URL}/api/execute/check-and-execute").mock(
        return_value=Response(200, json={"executed": True})
    )
    result = await client.check_and_execute(
        contract_address="0xDAI",
        network="ethereum",
        function_name="balanceOf",
        function_args='["0xabc"]',
        abi='[{"type":"function","name":"balanceOf"}]',
        condition={"operator": "gt", "value": "1000"},
        action={"contractAddress": "0xDAI", "functionName": "transfer"},
    )
    assert result["executed"] is True
    assert _sent_json(route) == {
        "contractAddress": "0xDAI",
        "network": "1",
        "functionName": "balanceOf",
        "condition": {"operator": "gt", "value": "1000"},
        "action": {"contractAddress": "0xDAI", "functionName": "transfer"},
        "functionArgs": '["0xabc"]',
        "abi": '[{"type":"function","name":"balanceOf"}]',
    }
    await client.aclose()


# -- get_execution_status -----------------------------------------------------


@respx.mock
async def test_get_execution_status(client: KeeperHubClient):
    respx.get(f"{TEST_BASE_URL}/api/execute/direct_42/status").mock(
        return_value=Response(
            200,
            json={
                "executionId": "direct_42",
                "status": "completed",
                "transactionHash": "0xtxhash",
            },
        )
    )
    result = await client.get_execution_status("direct_42")
    assert result["status"] == "completed"
    assert result["transactionHash"] == "0xtxhash"
    await client.aclose()


# -- get_user -----------------------------------------------------------------


@respx.mock
async def test_get_user(client: KeeperHubClient):
    payload = {
        "id": "user_123",
        "name": "John Doe",
        "email": "john@example.com",
        "image": "https://example.com/avatar.png",
        "isAnonymous": False,
        "providerId": "google",
        "walletAddress": "0x742d35Cc6634C0532925a3b844Bc454e4438f44e",
    }
    respx.get(f"{TEST_BASE_URL}/api/user").mock(
        return_value=Response(200, json=payload)
    )

    result = await client.get_user()

    assert result == payload
    await client.aclose()


@respx.mock
async def test_get_user_raises_for_422(client: KeeperHubClient):
    respx.get(f"{TEST_BASE_URL}/api/user").mock(
        return_value=Response(422, json={"error": "Wallet not configured"})
    )

    with pytest.raises(WalletNotConfiguredError):
        await client.get_user()
    await client.aclose()


# -- error handling -----------------------------------------------------------


@respx.mock
async def test_401_raises_auth_error(client: KeeperHubClient):
    respx.get(f"{TEST_BASE_URL}/api/chains").mock(
        return_value=Response(401, json={"error": "Invalid API key"})
    )
    with pytest.raises(AuthenticationError):
        await client.list_chains()
    await client.aclose()


@respx.mock
async def test_422_raises_wallet_error(client: KeeperHubClient):
    respx.get(f"{TEST_BASE_URL}/api/chains").mock(
        return_value=Response(
            200,
            json={"data": [{"chainId": 1, "name": "ethereum", "id": "ethereum"}]},
        )
    )
    respx.post(f"{TEST_BASE_URL}/api/execute/transfer").mock(
        return_value=Response(422, json={"error": "Wallet not configured"})
    )
    with pytest.raises(WalletNotConfiguredError):
        await client.transfer(
            network="ethereum", recipient_address="0x1", amount="1"
        )
    await client.aclose()


@respx.mock
async def test_422_spending_cap_raises_spending_cap_error(
    client: KeeperHubClient,
):
    respx.get(f"{TEST_BASE_URL}/api/chains").mock(
        return_value=Response(
            200,
            json={"data": [{"chainId": 1, "name": "ethereum", "id": "ethereum"}]},
        )
    )
    respx.post(f"{TEST_BASE_URL}/api/execute/transfer").mock(
        return_value=Response(
            422,
            json={
                "error": "Spending cap exceeded",
                "code": "SPENDING_CAP_EXCEEDED",
            },
        )
    )
    with pytest.raises(SpendingCapExceededError):
        await client.transfer(
            network="ethereum", recipient_address="0x1", amount="1"
        )
    await client.aclose()


@respx.mock
async def test_429_retries_then_raises(client: KeeperHubClient):
    route = respx.get(f"{TEST_BASE_URL}/api/chains").mock(
        return_value=Response(
            429,
            json={"error": "Rate limited"},
            headers={"Retry-After": "0"},
        )
    )
    with pytest.raises(RateLimitError):
        await client.list_chains()
    assert route.call_count == 3
    await client.aclose()


@respx.mock
async def test_get_429_retry_can_recover(client: KeeperHubClient):
    route = respx.get(f"{TEST_BASE_URL}/api/chains").mock(
        side_effect=[
            Response(
                429,
                json={"error": "Rate limited"},
                headers={"Retry-After": "0"},
            ),
            Response(200, json={"data": [{"chainId": 1}]}),
        ]
    )

    result = await client.list_chains()

    assert result == {"data": [{"chainId": 1}]}
    assert route.call_count == 2
    await client.aclose()


@respx.mock
async def test_post_429_raises_without_retry(client: KeeperHubClient):
    respx.get(f"{TEST_BASE_URL}/api/chains").mock(
        return_value=Response(
            200,
            json={"data": [{"chainId": 1, "name": "ethereum", "id": "ethereum"}]},
        )
    )
    route = respx.post(f"{TEST_BASE_URL}/api/execute/transfer").mock(
        return_value=Response(
            429,
            json={"error": "Rate limited"},
            headers={"Retry-After": "0"},
        )
    )
    with pytest.raises(RateLimitError, match="Rate limit exceeded"):
        await client.transfer(
            network="ethereum",
            recipient_address="0x1",
            amount="1",
        )
    assert route.call_count == 1
    await client.aclose()


@respx.mock
async def test_non_dict_error_body_does_not_crash(client: KeeperHubClient):
    respx.get(f"{TEST_BASE_URL}/api/chains").mock(
        return_value=Response(502, json=["upstream timeout"])
    )
    with pytest.raises(ServerError, match="Unknown error"):
        await client.list_chains()
    await client.aclose()


def test_raise_for_status_includes_details():
    with pytest.raises(KeeperHubError, match="Bad request: bad network"):
        raise_for_status(400, {"error": "Bad request", "details": "bad network"})


def test_raise_for_status_maps_404():
    with pytest.raises(NotFoundError):
        raise_for_status(404, {"message": "Missing"})


def test_raise_for_status_maps_429():
    with pytest.raises(RateLimitError):
        raise_for_status(429, {"error": "Rate limited"})


def test_raise_for_status_maps_generic_client_error():
    with pytest.raises(KeeperHubError):
        raise_for_status(400, {"error": "Bad request"})


@respx.mock
async def test_get_network_error_retries_three_times(client: KeeperHubClient):
    route = respx.get(f"{TEST_BASE_URL}/api/chains").mock(
        side_effect=httpx.ReadTimeout("network timeout")
    )
    with pytest.raises(KeeperHubError, match="after 3 network attempts"):
        await client.list_chains()
    assert route.call_count == 3
    await client.aclose()


@respx.mock
async def test_get_network_error_retry_can_recover(client: KeeperHubClient):
    route = respx.get(f"{TEST_BASE_URL}/api/chains").mock(
        side_effect=[
            httpx.ReadTimeout("network timeout"),
            Response(200, json={"data": [{"chainId": 1}]}),
        ]
    )

    result = await client.list_chains()

    assert result == {"data": [{"chainId": 1}]}
    assert route.call_count == 2
    await client.aclose()


@respx.mock
async def test_post_network_error_does_not_retry(client: KeeperHubClient):
    respx.get(f"{TEST_BASE_URL}/api/chains").mock(
        return_value=Response(
            200,
            json={"data": [{"chainId": 1, "name": "ethereum", "id": "ethereum"}]},
        )
    )
    route = respx.post(f"{TEST_BASE_URL}/api/execute/transfer").mock(
        side_effect=httpx.ReadTimeout("network timeout")
    )
    with pytest.raises(KeeperHubError, match="after 1 network attempt"):
        await client.transfer(
            network="ethereum",
            recipient_address="0x1",
            amount="1",
        )
    assert route.call_count == 1
    await client.aclose()


@pytest.mark.asyncio
async def test_get_http_closes_previous_client_on_loop_change(
    monkeypatch: pytest.MonkeyPatch,
):
    class DummyAsyncClient:
        def __init__(self, *args, **kwargs):
            self.is_closed = False

        async def aclose(self):
            self.is_closed = True

    loop_a = object()
    loop_b = object()
    get_loop = Mock(side_effect=[loop_a, loop_b])

    monkeypatch.setattr(
        "langchain_keeperhub.client.httpx.AsyncClient", DummyAsyncClient
    )
    monkeypatch.setattr(
        "langchain_keeperhub.client.asyncio.get_running_loop", get_loop
    )

    client = KeeperHubClient(
        api_key=TEST_API_KEY,
        base_url=TEST_BASE_URL,
    )
    first = await client._get_http()
    second = await client._get_http()

    assert first is not second
    assert first.is_closed
    assert not second.is_closed


@respx.mock
async def test_write_network_is_normalized_to_chain_id(client: KeeperHubClient):
    respx.get(f"{TEST_BASE_URL}/api/chains").mock(
        return_value=Response(
            200,
            json={"data": [{"chainId": 1, "name": "ethereum", "id": "eth-main"}]},
        )
    )
    route = respx.post(f"{TEST_BASE_URL}/api/execute/transfer").mock(
        return_value=Response(200, json={"executionId": "direct_44"})
    )
    await client.transfer(
        network="ethereum",
        recipient_address="0xabc",
        amount="1",
    )
    assert _sent_json(route)["network"] == "1"
    await client.aclose()


@respx.mock
async def test_write_network_unknown_fails_fast(client: KeeperHubClient):
    respx.get(f"{TEST_BASE_URL}/api/chains").mock(
        return_value=Response(
            200,
            json={"data": [{"chainId": 1, "name": "ethereum", "id": "eth-main"}]},
        )
    )
    with pytest.raises(ValueError, match="Unsupported network"):
        await client.transfer(
            network="unknown-net",
            recipient_address="0xabc",
            amount="1",
        )
    await client.aclose()


@respx.mock
async def test_blank_write_network_fails_fast(client: KeeperHubClient):
    with pytest.raises(ValueError, match="network is required"):
        await client.transfer(
            network=" ",
            recipient_address="0xabc",
            amount="1",
        )
    await client.aclose()


@respx.mock
async def test_network_resolution_ignores_invalid_chain_entries(
    client: KeeperHubClient,
):
    respx.get(f"{TEST_BASE_URL}/api/chains").mock(
        return_value=Response(
            200,
            json={
                "data": [
                    "not-a-dict",
                    {"name": "missing-chain-id"},
                    {"chainId": 1, "name": "ethereum", "id": "eth-main"},
                ]
            },
        )
    )
    route = respx.post(f"{TEST_BASE_URL}/api/execute/transfer").mock(
        return_value=Response(200, json={"executionId": "direct_48"})
    )
    await client.transfer(
        network="ethereum",
        recipient_address="0xabc",
        amount="1",
    )
    assert route.call_count == 1
    await client.aclose()


@respx.mock
async def test_testnet_only_allows_write_to_testnet():
    client = KeeperHubClient(
        api_key=TEST_API_KEY,
        base_url=TEST_BASE_URL,
        testnet_only=True,
    )
    respx.get(f"{TEST_BASE_URL}/api/chains").mock(
        return_value=Response(
            200,
            json={
                "data": [
                    {
                        "chainId": 11155111,
                        "name": "sepolia",
                        "id": "eth-sepolia",
                        "isTestnet": True,
                    }
                ]
            },
        )
    )
    route = respx.post(f"{TEST_BASE_URL}/api/execute/transfer").mock(
        return_value=Response(200, json={"executionId": "direct_45"})
    )
    await client.transfer(
        network="sepolia",
        recipient_address="0xabc",
        amount="1",
    )
    assert route.call_count == 1
    await client.aclose()


@respx.mock
async def test_testnet_only_blocks_unknown_testnet_status():
    client = KeeperHubClient(
        api_key=TEST_API_KEY,
        base_url=TEST_BASE_URL,
        testnet_only=True,
    )
    respx.get(f"{TEST_BASE_URL}/api/chains").mock(
        return_value=Response(
            200,
            json={"data": [{"chainId": 1, "name": "ethereum", "id": "eth-main"}]},
        )
    )
    route = respx.post(f"{TEST_BASE_URL}/api/execute/transfer").mock(
        return_value=Response(200, json={"executionId": "should-not-be-called"})
    )
    with pytest.raises(ValueError, match="Cannot determine testnet status"):
        await client.transfer(
            network="ethereum",
            recipient_address="0xabc",
            amount="1",
        )
    assert route.call_count == 0
    await client.aclose()


@respx.mock
async def test_testnet_only_blocks_write_to_mainnet():
    client = KeeperHubClient(
        api_key=TEST_API_KEY,
        base_url=TEST_BASE_URL,
        testnet_only=True,
    )
    respx.get(f"{TEST_BASE_URL}/api/chains").mock(
        return_value=Response(
            200,
            json={
                "data": [
                    {
                        "chainId": 1,
                        "name": "ethereum",
                        "id": "eth-main",
                        "isTestnet": False,
                    }
                ]
            },
        )
    )
    route = respx.post(f"{TEST_BASE_URL}/api/execute/transfer").mock(
        return_value=Response(200, json={"executionId": "should-not-be-called"})
    )
    with pytest.raises(ValueError, match="testnet_only is enabled"):
        await client.transfer(
            network="ethereum",
            recipient_address="0xabc",
            amount="1",
        )
    assert route.call_count == 0
    await client.aclose()


@respx.mock
async def test_allowed_chain_ids_allows_write_to_listed_chain():
    client = KeeperHubClient(
        api_key=TEST_API_KEY,
        base_url=TEST_BASE_URL,
        allowed_chain_ids={11155111},
    )
    respx.get(f"{TEST_BASE_URL}/api/chains").mock(
        return_value=Response(
            200,
            json={
                "data": [
                    {
                        "chainId": 11155111,
                        "name": "sepolia",
                        "id": "eth-sepolia",
                        "isTestnet": True,
                    }
                ]
            },
        )
    )
    route = respx.post(f"{TEST_BASE_URL}/api/execute/transfer").mock(
        return_value=Response(200, json={"executionId": "direct_46"})
    )
    await client.transfer(
        network="sepolia",
        recipient_address="0xabc",
        amount="1",
    )
    assert route.call_count == 1
    await client.aclose()


@respx.mock
async def test_allowed_chain_ids_blocks_unlisted_write_network():
    client = KeeperHubClient(
        api_key=TEST_API_KEY,
        base_url=TEST_BASE_URL,
        testnet_only=True,
        allowed_chain_ids={"84532"},
    )
    respx.get(f"{TEST_BASE_URL}/api/chains").mock(
        return_value=Response(
            200,
            json={
                "data": [
                    {
                        "chainId": 11155111,
                        "name": "sepolia",
                        "id": "eth-sepolia",
                        "isTestnet": True,
                    },
                    {
                        "chainId": 84532,
                        "name": "base-sepolia",
                        "id": "base-sepolia",
                        "isTestnet": True,
                    },
                ]
            },
        )
    )
    route = respx.post(f"{TEST_BASE_URL}/api/execute/transfer").mock(
        return_value=Response(200, json={"executionId": "should-not-be-called"})
    )
    with pytest.raises(ValueError, match="Unsupported write network"):
        await client.transfer(
            network="sepolia",
            recipient_address="0xabc",
            amount="1",
        )
    assert route.call_count == 0
    await client.aclose()
