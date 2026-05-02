"""Built-in ENS / Basenames registry + default RPC per chain.

Use a numeric chain id or a short alias with :class:`~langchain_keeperhub.ens.ENSClient`
(``chain=`` / per-call ``chain`` on ``resolve`` / ``reverse_resolve``). For
other networks pass ``registry`` and ``rpc_url`` explicitly on the client.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True, slots=True)
class ENSChainProfile:
    """Registry + default public RPC for one network."""

    chain_id: int
    name: str
    registry: str
    default_rpc_url: str


# Canonical ENS registry (L1) — same contract address on Ethereum mainnet and Sepolia.
_REGISTRY_ETH: Final = "0x00000000000C2E074eC69A0dFb2997BA6C7d2e1e"

_PROFILES: Final[tuple[ENSChainProfile, ...]] = (
    ENSChainProfile(
        chain_id=1,
        name="ethereum",
        registry=_REGISTRY_ETH,
        default_rpc_url="https://ethereum.publicnode.com",
    ),
    ENSChainProfile(
        chain_id=11155111,
        name="sepolia",
        registry=_REGISTRY_ETH,
        default_rpc_url="https://ethereum-sepolia.publicnode.com",
    ),
    ENSChainProfile(
        chain_id=8453,
        name="base",
        registry="0xb94704422c2a1e396835a571837aa5ae53285a95",
        default_rpc_url="https://base.publicnode.com",
    ),
    ENSChainProfile(
        chain_id=84532,
        name="base-sepolia",
        registry="0x1493b2567056c2181630115660963E13A8E32735",
        default_rpc_url="https://base-sepolia.publicnode.com",
    ),
)

_BY_ID: dict[int, ENSChainProfile] = {p.chain_id: p for p in _PROFILES}


def _norm_alias(s: str) -> str:
    return s.strip().lower().replace("_", "-").replace(" ", "-")


_ALIASES: dict[str, int] = {}
for p in _PROFILES:
    _ALIASES[_norm_alias(p.name)] = p.chain_id
for alias, cid in (
    ("eth", 1),
    ("mainnet", 1),
    ("ethereum-mainnet", 1),
    ("sepolia-testnet", 11155111),
    ("basesepolia", 84532),
):
    _ALIASES[_norm_alias(alias)] = cid


def list_ens_chain_profiles() -> tuple[ENSChainProfile, ...]:
    """Built-in chain profiles (Ethereum, Sepolia, Base, Base Sepolia)."""
    return _PROFILES


def reverse_primary_name(address: str, chain_id: int) -> str:
    """ENSIP-19-style reverse record FQDN for ``address`` on ``chain_id``.

    Only **Ethereum mainnet** (``chain_id == 1``) uses the legacy
    ``{addr}.addr.reverse`` tree. Every other chain (including Sepolia and
    L2s) uses ``{addr}.{0x80000000|chainId as lowercase hex}.reverse`` (e.g.
    Base → ``… .80002105.reverse``, Sepolia → ``… .80aa36a7.reverse``).

    For unknown ``chain_id <= 0`` (e.g. custom registry clients), falls back
    to ``addr.reverse``.
    """
    addr_bare = address.lower().removeprefix("0x")
    if len(addr_bare) != 40 or any(c not in "0123456789abcdef" for c in addr_bare):
        raise ValueError("address must be 20-byte hex (optionally 0x-prefixed).")
    if chain_id == 1:
        return f"{addr_bare}.addr.reverse"
    if chain_id <= 0:
        return f"{addr_bare}.addr.reverse"
    slip = 0x80000000 | (chain_id & 0xFFFFFFFF)
    return f"{addr_bare}.{slip:x}.reverse"


def resolve_ens_chain(chain: int | str) -> ENSChainProfile:
    """Resolve a built-in ``chain`` id or alias to a profile.

    Raises:
        ValueError: if the chain is not built-in.
    """
    if isinstance(chain, int):
        prof = _BY_ID.get(chain)
        if prof is not None:
            return prof
        raise ValueError(
            f"Unknown ENS chain_id={chain}. "
            f"Built-in ids: {sorted(_BY_ID)}. "
            "Use ``ENSClient(registry=..., rpc_url=...)`` for other networks."
        )
    raw = str(chain).strip()
    if raw.isdigit():
        return resolve_ens_chain(int(raw))
    key = _norm_alias(raw)
    cid = _ALIASES.get(key)
    if cid is not None:
        return _BY_ID[cid]
    raise ValueError(
        f"Unknown ENS chain={chain!r}. "
        f"Try one of: {', '.join(p.name for p in _PROFILES)} "
        f"(or chain id {', '.join(str(i) for i in sorted(_BY_ID))})."
    )
