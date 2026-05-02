# ENS Integration

`langchain-keeperhub` can resolve **ENS names** (`.eth`) and **Basenames** (`.base.eth`) to wallet addresses, and do reverse lookups (address → name). This all happens over public JSON-RPC — no KeeperHub API call is needed for reads.

## Supported chains

| Network | Chain ID | Registry |
|---------|----------|----------|
| Ethereum | 1 | `0x00000000000C2E074eC69A0dFb2997BA6C7d2e1e` |
| Sepolia | 11155111 | same as Ethereum |
| Base | 8453 | `0xb94704422c2a1e396835a571837aa5ae53285a95` |
| Base Sepolia | 84532 | `0x1493b2567056c2181630115660963E13A8E32735` |

For other chains, pass a custom registry: `ENSClient(rpc_url=..., registry="0x...", chain=...)`.

## How it works

**Forward lookup** (`resolve_ens` tool / `ENSClient.resolve`): queries the registry for the resolver, then calls `addr(node, coinType)` (EIP-2304), falling back to `addr(node)` if needed.

**Reverse lookup** (`reverse_resolve_ens` tool / `ENSClient.reverse_resolve`): uses ENSIP-19 reverse records.

**Chain selection:** The client has a default chain (set at construction). Each call can override it with `chain=`. Names are not auto-routed by suffix — for `*.base.eth`, explicitly use `chain="base"`.

## Using with the toolkit

ENS tools are always included when you call `get_tools()`. To change the default chain:

```python
toolkit = KeeperHubToolkit(ens_chain="base")
tools = toolkit.get_tools()
```

Other options: `ens_rpc_url` (custom RPC endpoint), `ens_registry` (custom registry address).

## Using ENSClient directly

```python
from langchain_keeperhub import ENSClient

client = ENSClient(chain="base")
addr = await client.resolve("nick.base.eth")
name = await client.reverse_resolve(addr)
await client.aclose()
```

- `resolve(name, *, chain=None)` → `str | None`
- `reverse_resolve(address, *, chain=None)` → `str | None`
- Raises `ValueError` on bad input or RPC errors.

## Tool reference

| Tool | Arguments | Returns |
|------|-----------|---------|
| `resolve_ens` | `name`, optional `chain` | `name`, `chain_id`, `address` (or `error`) |
| `reverse_resolve_ens` | `address`, optional `chain` | `address`, `chain_id`, `name` (or `error`) |

## Environment variables (all optional)

You only need these if you don't pass the values in code.

| Variable | Purpose |
|----------|---------|
| `ENS_CHAIN_ID` | Default ENS chain (id or alias like `base`, `11155111`) |
| `ENS_RPC_URL` / `ETH_RPC_URL` | Custom RPC endpoint for all ENS calls |

## Dependencies

- Uses `httpx` for JSON-RPC. No `web3.py` needed.
- Namehash requires **keccak-256**. OpenSSL 3.x provides this by default. If you get a keccak error, install the fallback: `pip install "langchain-keeperhub[ens]"`.

## Default RPCs

When no custom URL is set, the SDK uses built-in public RPC endpoints (see `langchain_keeperhub/ens_chains.py`). For production traffic, use your own RPC URL.
