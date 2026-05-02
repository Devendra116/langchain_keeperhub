"""Tests for ENSClient and ENS LangChain tools (JSON-RPC mocked via respx)."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import httpx
import pytest
import respx

from langchain_keeperhub.ens import ENSClient, _decode_addr_abi_return, namehash
from langchain_keeperhub.ens_chains import resolve_ens_chain, reverse_primary_name
from langchain_keeperhub.tools.resolve_ens import ResolveENSTool
from langchain_keeperhub.tools.reverse_resolve_ens import ReverseResolveENSTool

_RPC = "https://ens-test.invalid/v1"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _json_rpc(result: str, req_id: int = 1) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _padded_addr(addr: str) -> str:
    bare = addr.lower().removeprefix("0x")
    return "0x" + ("0" * 24) + bare


def _abi_string(s: str) -> str:
    """Minimal ABI-encoded ``string`` return (single dynamic tail)."""
    b = s.encode("utf-8")
    length = len(b)
    pad = (32 - (length % 32)) % 32
    body = b.hex() + ("00" * pad)
    off = 32
    return f"{off:064x}{length:064x}{body}"


# ---------------------------------------------------------------------------
# Pure unit tests (no network)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("name", "expected_hex"),
    [
        ("", "0" * 64),
        ("eth", "93cdeb708b7545dc668eb9280176169d1c33cfd8ed6f04690a0bcc88a93fc4ae"),
    ],
)
def test_namehash(name: str, expected_hex: str) -> None:
    assert namehash(name).hex() == expected_hex


def test_decode_addr_abi_dynamic_bytes() -> None:
    inner = "d8da6bf26964af9d7eed9e03e53415d37aa96045"
    raw = (
        "0x"
        "0000000000000000000000000000000000000000000000000000000000000020"
        "0000000000000000000000000000000000000000000000000000000000000014"
        f"{inner}"
        "000000000000000000000000"
    )
    assert _decode_addr_abi_return(raw) == "0x" + inner


def test_decode_addr_abi_single_word() -> None:
    padded = _padded_addr("0x1111111111111111111111111111111111111111")
    assert _decode_addr_abi_return(padded) == "0x1111111111111111111111111111111111111111"


def test_decode_addr_abi_malformed_returns_none() -> None:
    assert _decode_addr_abi_return("0xgarbage") is None
    assert _decode_addr_abi_return("") is None
    assert _decode_addr_abi_return("0x") is None


# -- ens_chains -----------------------------------------------------------

def test_resolve_ens_chain_aliases() -> None:
    assert resolve_ens_chain("base").chain_id == 8453
    assert resolve_ens_chain(11155111).name == "sepolia"


def test_resolve_ens_chain_unknown() -> None:
    with pytest.raises(ValueError, match="Unknown ENS"):
        resolve_ens_chain(999999)


def test_reverse_primary_name_l1_vs_base_vs_sepolia() -> None:
    a = "0x79523ac558b3a47e8930e5df6436340b8fc854fa"
    bare = a[2:].lower()
    assert reverse_primary_name(a, 1) == f"{bare}.addr.reverse"
    assert reverse_primary_name(a, 8453) == f"{bare}.80002105.reverse"
    slip_sep = 0x80000000 | 11155111
    assert reverse_primary_name(a, 11155111) == f"{bare}.{slip_sep:x}.reverse"


def test_reverse_primary_name_invalid_address() -> None:
    with pytest.raises(ValueError):
        reverse_primary_name("0xbad", 1)


# -- ENSClient constructor validation ------------------------------------

def test_ens_client_custom_registry_requires_rpc() -> None:
    with pytest.raises(ValueError, match="rpc_url"):
        ENSClient(registry="0xb94704422c2a1e396835a571837aa5ae53285a95")


@pytest.mark.asyncio
async def test_ens_client_per_call_chain_disallowed_with_custom_registry() -> None:
    c = ENSClient(
        rpc_url=_RPC,
        registry="0xb94704422c2a1e396835a571837aa5ae53285a95",
    )
    try:
        with pytest.raises(ValueError, match="Per-call"):
            await c.resolve("x.base.eth", chain=1)
    finally:
        await c.aclose()


# -- Input validation -----------------------------------------------------

async def test_resolve_empty_name_raises() -> None:
    c = ENSClient(rpc_url=_RPC)
    try:
        with pytest.raises(ValueError, match="non-empty"):
            await c.resolve("")
        with pytest.raises(ValueError, match="non-empty"):
            await c.resolve("   ")
    finally:
        await c.aclose()


async def test_reverse_resolve_bad_address_raises() -> None:
    c = ENSClient(rpc_url=_RPC)
    try:
        with pytest.raises(ValueError, match="valid"):
            await c.reverse_resolve("0xbad")
        with pytest.raises(ValueError, match="valid"):
            await c.reverse_resolve("")
    finally:
        await c.aclose()


# -- Mocked JSON-RPC integration tests -----------------------------------

@respx.mock
async def test_ens_client_resolve_success() -> None:
    node = namehash("foo.eth").hex()
    resolver = "0x1111111111111111111111111111111111111111"
    target = "0xd8da6bf26964af9d7eed9e03e53415ed37aa0395"

    calls: list[dict] = []

    def eth_response(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode())
        calls.append(body)
        req_id = body["id"]
        param0 = body["params"][0]
        data = str(param0["data"]).lower()
        to_addr = str(param0.get("to", "")).lower()
        if "0178b8bf" in data and node in data:
            return httpx.Response(200, json=_json_rpc(_padded_addr(resolver), req_id))
        if to_addr == resolver.lower() and "f1cb7e06" in data and node in data:
            return httpx.Response(200, json=_json_rpc(_padded_addr(target), req_id))
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": req_id, "error": {"code": -1, "message": data}})

    respx.post(_RPC).mock(side_effect=eth_response)

    client = ENSClient(rpc_url=_RPC, timeout=5.0)
    try:
        out = await client.resolve("foo.eth")
    finally:
        await client.aclose()

    assert out == target
    assert len(calls) == 2


@respx.mock
async def test_ens_client_resolve_no_resolver() -> None:
    node = namehash("missing.eth").hex()

    def eth_response(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode())
        data = str(body["params"][0]["data"]).lower()
        if "0178b8bf" in data and node in data:
            return httpx.Response(
                200,
                json=_json_rpc(
                    "0x" + ("0" * 64),
                    body["id"],
                ),
            )
        return httpx.Response(
            200,
            json={"jsonrpc": "2.0", "id": body["id"], "error": {"code": -1}},
        )

    respx.post(_RPC).mock(side_effect=eth_response)

    client = ENSClient(rpc_url=_RPC, timeout=5.0)
    try:
        assert await client.resolve("missing.eth") is None
    finally:
        await client.aclose()


@respx.mock
async def test_ens_client_reverse_resolve_success() -> None:
    addr = "0xd8da6bf26964af9d7eed9e03e53415ed37aa0395"
    node = namehash(reverse_primary_name(addr, 1)).hex()
    resolver = "0x2222222222222222222222222222222222222222"
    name = "vitalik.eth"

    def eth_response(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode())
        req_id = body["id"]
        param0 = body["params"][0]
        data = str(param0["data"]).lower()
        to_addr = str(param0.get("to", "")).lower()
        if "0178b8bf" in data and node in data:
            return httpx.Response(200, json=_json_rpc(_padded_addr(resolver), req_id))
        if to_addr == resolver.lower() and "691f3431" in data and node in data:
            return httpx.Response(
                200,
                json=_json_rpc("0x" + _abi_string(name), req_id),
            )
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": req_id, "error": {"code": -1}})

    respx.post(_RPC).mock(side_effect=eth_response)

    client = ENSClient(rpc_url=_RPC, timeout=5.0)
    try:
        out = await client.reverse_resolve(addr)
    finally:
        await client.aclose()

    assert out == name


@respx.mock
async def test_eth_call_rpc_error_is_valueerror() -> None:
    respx.post(_RPC).mock(
        return_value=httpx.Response(
            200, json={"jsonrpc": "2.0", "id": 1, "error": {"code": -32000, "message": "boom"}}
        )
    )
    client = ENSClient(rpc_url=_RPC)
    try:
        with pytest.raises(ValueError, match="RPC error"):
            await client.resolve("fail.eth")
    finally:
        await client.aclose()


@respx.mock
async def test_eth_call_non_json_is_valueerror() -> None:
    respx.post(_RPC).mock(
        return_value=httpx.Response(502, content=b"Bad Gateway")
    )
    client = ENSClient(rpc_url=_RPC)
    try:
        with pytest.raises(ValueError, match="non-JSON"):
            await client.resolve("fail.eth")
    finally:
        await client.aclose()


# -- Tool sync / mock tests -----------------------------------------------

def test_resolve_ens_tool_sync_mock() -> None:
    ens = ENSClient(rpc_url=_RPC)
    ens.resolve = AsyncMock(return_value="0xabc")
    tool = ResolveENSTool(ens_client=ens)
    assert tool._run(name="x.eth") == {
        "name": "x.eth",
        "chain_id": 1,
        "address": "0xabc",
    }
    ens.resolve = AsyncMock(return_value=None)
    result = tool._run(name="nope.eth")
    assert result["address"] is None
    assert "error" in result


def test_resolve_ens_tool_catches_valueerror() -> None:
    ens = ENSClient(rpc_url=_RPC)
    ens.resolve = AsyncMock(side_effect=ValueError("RPC boom"))
    tool = ResolveENSTool(ens_client=ens)
    result = tool._run(name="broken.eth")
    assert result["address"] is None
    assert "RPC boom" in result["error"]


def test_reverse_resolve_ens_tool_sync_mock() -> None:
    ens = ENSClient(rpc_url=_RPC)
    ens.reverse_resolve = AsyncMock(return_value="foo.eth")
    tool = ReverseResolveENSTool(ens_client=ens)
    assert tool._run(address="0x" + "ab" * 20) == {
        "address": "0x" + "ab" * 20,
        "chain_id": 1,
        "name": "foo.eth",
    }
    ens.reverse_resolve = AsyncMock(return_value=None)
    result = tool._run(address="0x" + "cd" * 20)
    assert result["name"] is None
    assert "error" in result


def test_reverse_resolve_ens_tool_catches_valueerror() -> None:
    ens = ENSClient(rpc_url=_RPC)
    ens.reverse_resolve = AsyncMock(side_effect=ValueError("RPC boom"))
    tool = ReverseResolveENSTool(ens_client=ens)
    result = tool._run(address="0x" + "ab" * 20)
    assert result["name"] is None
    assert "RPC boom" in result["error"]


def test_reverse_resolve_ens_tool_bad_address_returns_error() -> None:
    """Bad address via _run returns an error dict (not a crash)."""
    ens = ENSClient(rpc_url=_RPC)
    tool = ReverseResolveENSTool(ens_client=ens)
    result = tool._run(address="0xbad")
    assert result["name"] is None
    assert "error" in result


def test_reverse_resolve_ens_pydantic_rejects_bad_address() -> None:
    """Pydantic validation catches bad address on the agent invoke() path."""
    from pydantic import ValidationError
    from langchain_keeperhub.tools.reverse_resolve_ens import ReverseResolveENSInput

    with pytest.raises(ValidationError):
        ReverseResolveENSInput(address="0xbad")
