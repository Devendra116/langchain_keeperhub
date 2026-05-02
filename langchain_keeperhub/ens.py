"""Lightweight ENS / Basenames resolution via JSON-RPC.

Uses httpx, keccak-256 (OpenSSL 3.x or pycryptodome). No web3.py.

Chain selection: pass ``chain`` (id or alias: ``"ethereum"``, ``"sepolia"``,
``"base"``, ``"base-sepolia"``) to :class:`ENSClient` or per-call on
:meth:`ENSClient.resolve` / :meth:`ENSClient.reverse_resolve`. Override the
registry with ``registry=`` for unsupported chains (requires ``rpc_url``).
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from typing import Callable

import httpx

from langchain_keeperhub.ens_chains import (
    ENSChainProfile,
    resolve_ens_chain,
    reverse_primary_name,
)

logger = logging.getLogger(__name__)

_ZERO_ADDR = "0x" + "00" * 20
_HEX40_RE = re.compile(r"^(0x)?[0-9a-fA-F]{40}$")
_ENS_NAME_RE = re.compile(r"^[^\s]{1,512}$")

# Function selectors: first 4 bytes of keccak256(signature)
_SEL_RESOLVER = "0178b8bf"  # resolver(bytes32)
_SEL_ADDR = "3b3b57de"  # addr(bytes32) legacy
_SEL_ADDR_COIN = "f1cb7e06"  # addr(bytes32,uint256) — EIP-2304 / ENSIP-9
_SEL_NAME = "691f3431"  # name(bytes32)

_COIN_TYPE_ETH = 60


# ---------------------------------------------------------------------------
# keccak-256 with cached backend selection
# ---------------------------------------------------------------------------

_keccak_fn: Callable[[bytes], bytes] | None = None


def _init_keccak() -> Callable[[bytes], bytes]:
    """Select and cache the fastest available keccak-256 backend."""
    import hashlib

    for algo in ("keccak-256", "keccak_256"):
        try:
            h = hashlib.new(algo, b"")
            _ = h.digest()

            def _openssl(data: bytes, _algo: str = algo) -> bytes:
                return hashlib.new(_algo, data).digest()

            return _openssl
        except (ValueError, TypeError):
            continue

    try:
        from Crypto.Hash import keccak as _kmod

        _kmod.new(digest_bits=256, data=b"").digest()

        def _pycryptodome(data: bytes) -> bytes:
            return _kmod.new(digest_bits=256, data=data).digest()

        return _pycryptodome
    except ImportError:
        pass

    raise ImportError(
        "ENS resolution requires keccak-256. Use Python with OpenSSL 3.x+ "
        "or: pip install 'langchain-keeperhub[ens]'"
    )


def _keccak256(data: bytes) -> bytes:
    global _keccak_fn
    if _keccak_fn is None:
        _keccak_fn = _init_keccak()
    return _keccak_fn(data)


# ---------------------------------------------------------------------------
# EIP-137 namehash
# ---------------------------------------------------------------------------

def namehash(name: str) -> bytes:
    """EIP-137 namehash."""
    node = b"\x00" * 32
    if not name:
        return node
    for label in reversed(name.split(".")):
        node = _keccak256(node + _keccak256(label.encode("utf-8")))
    return node


# ---------------------------------------------------------------------------
# ABI decoding helpers (safe against malformed RPC data)
# ---------------------------------------------------------------------------

def _decode_address(result: str) -> str | None:
    """Extract address from a 32-byte ABI-encoded ``address`` word."""
    try:
        if not result or result == "0x" or len(result) < 42:
            return None
        addr = "0x" + result[-40:]
        return None if addr == _ZERO_ADDR else addr
    except Exception:
        return None


def _decode_addr_abi_return(result: str) -> str | None:
    """Decode ``addr(bytes32,uint256)`` (ABI ``bytes``) or legacy ``address``."""
    try:
        raw = result[2:] if result.startswith("0x") else result
        if len(raw) < 64:
            return None
        first = int(raw[:64], 16)
        if first == 32 and len(raw) >= 128:
            length = int(raw[64:128], 16)
            if length == 0:
                return None
            end = 128 + length * 2
            if end > len(raw):
                return None
            blob = raw[128:end]
            if length == 20 and len(blob) == 40:
                addr = "0x" + blob
                return None if addr == _ZERO_ADDR else addr
            return None
        return _decode_address(result)
    except Exception:
        return None


def _decode_string(result: str) -> str | None:
    """Decode an ABI-encoded ``string`` return value."""
    try:
        raw = result[2:] if result.startswith("0x") else result
        if len(raw) < 128:
            return None
        offset = int(raw[:64], 16) * 2
        length = int(raw[offset : offset + 64], 16)
        if length == 0:
            return None
        s = bytes.fromhex(raw[offset + 64 : offset + 64 + length * 2])
        return s.decode("utf-8") or None
    except Exception:
        return None


def _is_valid_registry(addr: str) -> bool:
    return bool(_HEX40_RE.match(addr.strip()))


# ---------------------------------------------------------------------------
# ENSClient
# ---------------------------------------------------------------------------

class ENSClient:
    """Async ENS / Basenames resolver via ``eth_call``.

    Args:
        rpc_url: Optional JSON-RPC URL used for **every** chain when set
            (also ``ENS_RPC_URL`` / ``ETH_RPC_URL`` env). When unset, each
            built-in ``chain`` uses that network's default public RPC.
        chain: Default chain id or alias (``1``, ``"base"``, ``"sepolia"``, …).
        registry: Custom ENS registry (``0x`` + 40 hex). Requires ``rpc_url``
            or ``ENS_RPC_URL`` / ``ETH_RPC_URL``. Disables per-call ``chain``.
        timeout: HTTP timeout in seconds.
    """

    def __init__(
        self,
        rpc_url: str | None = None,
        *,
        chain: int | str = 1,
        registry: str | None = None,
        timeout: float = 15.0,
    ) -> None:
        self._timeout = timeout
        self._http: httpx.AsyncClient | None = None
        self._http_loop_id: int | None = None
        self._req_id = 0

        self._forced_rpc = (
            rpc_url
            or os.environ.get("ENS_RPC_URL", "").strip()
            or os.environ.get("ETH_RPC_URL", "").strip()
            or None
        )

        if registry is not None:
            reg = registry.strip().lower()
            if not _is_valid_registry(reg):
                raise ValueError("registry must be a 20-byte hex address (0x + 40 hex).")
            if not self._forced_rpc:
                raise ValueError(
                    "rpc_url (or ENS_RPC_URL / ETH_RPC_URL) is required when "
                    "registry= is set."
                )
            self._custom_registry = True
            self._default_profile: ENSChainProfile | None = None
            self._default_registry = reg
            self._default_chain_id = int(chain) if isinstance(chain, int) else 0
        else:
            self._custom_registry = False
            prof = resolve_ens_chain(chain)
            self._default_profile = prof
            self._default_registry = prof.registry.lower()
            self._default_chain_id = prof.chain_id

    @property
    def default_chain_id(self) -> int:
        """Chain id used when ``chain`` is omitted on resolve / reverse_resolve."""
        return self._default_chain_id

    def _rpc_url(self, profile: ENSChainProfile | None) -> str:
        if self._forced_rpc:
            return self._forced_rpc.rstrip("/")
        if profile is not None:
            return profile.default_rpc_url.rstrip("/")
        raise RuntimeError("forced RPC required for custom registry client")

    def _target(
        self, chain: int | str | None
    ) -> tuple[int, str, str]:
        """``(chain_id, registry_lower, rpc_url)`` for this call."""
        if chain is None:
            return (
                self._default_chain_id,
                self._default_registry,
                self._rpc_url(self._default_profile),
            )
        if self._custom_registry:
            raise ValueError(
                "Per-call 'chain' is not supported when ENSClient was created "
                "with registry=. Use one client per custom network."
            )
        prof = resolve_ens_chain(chain)
        return (prof.chain_id, prof.registry.lower(), self._rpc_url(prof))

    # -- HTTP lifecycle (event-loop aware) -----------------------------------

    async def _get_http(self) -> httpx.AsyncClient:
        loop_id = id(asyncio.get_running_loop())
        if (
            self._http is None
            or self._http.is_closed
            or self._http_loop_id != loop_id
        ):
            if self._http is not None and not self._http.is_closed:
                try:
                    await self._http.aclose()
                except RuntimeError:
                    pass
            self._http = httpx.AsyncClient(timeout=self._timeout)
            self._http_loop_id = loop_id
        return self._http

    async def aclose(self) -> None:
        if self._http and not self._http.is_closed:
            await self._http.aclose()

    # -- JSON-RPC plumbing ---------------------------------------------------

    async def _eth_call(self, to: str, data: str, *, rpc_url: str) -> str:
        http = await self._get_http()
        self._req_id += 1
        try:
            resp = await http.post(
                rpc_url,
                json={
                    "jsonrpc": "2.0",
                    "method": "eth_call",
                    "params": [{"to": to, "data": f"0x{data}"}, "latest"],
                    "id": self._req_id,
                },
            )
        except httpx.HTTPError as exc:
            logger.warning("ENS eth_call network error: %s", exc)
            raise ValueError(f"ENS RPC request failed: {exc}") from exc

        try:
            body = resp.json()
        except Exception:
            logger.warning("ENS RPC returned non-JSON (HTTP %d)", resp.status_code)
            raise ValueError(
                f"ENS RPC returned non-JSON response (HTTP {resp.status_code})"
            )

        if "error" in body:
            raise ValueError(f"RPC error: {body['error']}")
        return body.get("result", "0x")

    # -- Resolution ----------------------------------------------------------

    async def _get_resolver(
        self, node: bytes, *, chain: int | str | None = None
    ) -> tuple[str | None, str]:
        """Returns ``(resolver_address_or_none, rpc_url)``."""
        _cid, registry, rpc_url = self._target(chain)
        result = await self._eth_call(
            registry, _SEL_RESOLVER + node.hex(), rpc_url=rpc_url
        )
        return (_decode_address(result), rpc_url)

    async def resolve(
        self, name: str, *, chain: int | str | None = None
    ) -> str | None:
        """ENS name → address on ``chain`` (default: client default chain).

        Returns ``None`` when the name has no resolver or no address record.
        Raises ``ValueError`` on invalid input or RPC failure.
        """
        if not name or not name.strip():
            raise ValueError("name must be a non-empty ENS name.")
        name = name.strip()
        node = namehash(name)
        resolver, rpc_url = await self._get_resolver(node, chain=chain)
        if not resolver:
            return None
        coin_data = _SEL_ADDR_COIN + node.hex() + f"{_COIN_TYPE_ETH:064x}"
        result = await self._eth_call(resolver, coin_data, rpc_url=rpc_url)
        out = _decode_addr_abi_return(result)
        if out is not None:
            return out
        result = await self._eth_call(
            resolver, _SEL_ADDR + node.hex(), rpc_url=rpc_url
        )
        return _decode_addr_abi_return(result)

    async def reverse_resolve(
        self, address: str, *, chain: int | str | None = None
    ) -> str | None:
        """Address → primary ENS name on ``chain`` (default: client default).

        Uses ENSIP-19: ``*.addr.reverse`` only on Ethereum mainnet (1);
        ``*.<0x80000000|chainId>.reverse`` on Sepolia, Base, and other chains.

        Returns ``None`` when no primary name is set for this address+chain.
        Raises ``ValueError`` on invalid input or RPC failure.
        """
        if not address or not _HEX40_RE.match(address.strip()):
            raise ValueError(
                "address must be a valid 0x-prefixed Ethereum address (40 hex chars)."
            )
        address = address.strip()
        cid, _reg, _rpc = self._target(chain)
        node = namehash(reverse_primary_name(address, cid))
        resolver, rpc_url = await self._get_resolver(node, chain=chain)
        if not resolver:
            return None
        result = await self._eth_call(
            resolver, _SEL_NAME + node.hex(), rpc_url=rpc_url
        )
        return _decode_string(result)
