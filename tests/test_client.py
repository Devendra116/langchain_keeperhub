"""Tests for KeeperHubClient — all HTTP mocked via respx."""

from __future__ import annotations

import pytest
import respx
import httpx
from unittest.mock import Mock
from httpx import Response

from langchain_keeperhub._exceptions import (
    AuthenticationError,
    KeeperHubError,
    RateLimitError,
    ValidationError,
    WalletNotConfiguredError,
)
from langchain_keeperhub.client import KeeperHubClient

from .conftest import TEST_API_KEY, TEST_BASE_URL



# -- construction ------------------------------------------------------------


def test_missing_api_key_raises():
    with pytest.raises(ValueError, match="api_key is required"):
        KeeperHubClient(api_key="")


def test_env_var_fallback(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("KEEPERHUB_API_KEY", "kh_from_env")
    c = KeeperHubClient()
    assert c._api_key == "kh_from_env"


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
    respx.post(f"{TEST_BASE_URL}/api/execute/transfer").mock(
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
    await client.aclose()


@respx.mock
async def test_transfer_with_token(client: KeeperHubClient):
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
    sent_body = route.calls.last.request.content
    assert b"tokenAddress" in sent_body
    await client.aclose()


# -- contract_call ------------------------------------------------------------


@respx.mock
async def test_contract_call_read(client: KeeperHubClient):
    respx.post(f"{TEST_BASE_URL}/api/execute/contract-call").mock(
        return_value=Response(200, json={"result": "1500000000000000000"})
    )
    result = await client.contract_call(
        contract_address="0xDAI",
        network="ethereum",
        function_name="balanceOf",
        function_args='["0xabc"]',
    )
    assert result["result"] == "1500000000000000000"
    await client.aclose()


# -- check_and_execute --------------------------------------------------------


@respx.mock
async def test_check_and_execute_not_met(client: KeeperHubClient):
    respx.post(f"{TEST_BASE_URL}/api/execute/check-and-execute").mock(
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
    respx.post(f"{TEST_BASE_URL}/api/execute/transfer").mock(
        return_value=Response(422, json={"error": "Wallet not configured"})
    )
    with pytest.raises(WalletNotConfiguredError):
        await client.transfer(
            network="ethereum", recipient_address="0x1", amount="1"
        )
    await client.aclose()


@respx.mock
async def test_429_retries_then_raises(client: KeeperHubClient):
    respx.get(f"{TEST_BASE_URL}/api/chains").mock(
        return_value=Response(
            429,
            json={"error": "Rate limited"},
            headers={"Retry-After": "0"},
        )
    )
    with pytest.raises(RateLimitError):
        await client.list_chains()
    await client.aclose()


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
async def test_post_network_error_does_not_retry(client: KeeperHubClient):
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
