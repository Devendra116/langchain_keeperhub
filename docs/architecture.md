# Architecture

How `langchain-keeperhub` works under the hood. Read this if you want to extend the SDK, write custom tools, or understand the security and reliability guarantees.

## System overview

```
┌──────────────────────────────────────────────────────────────┐
│                   Your Application / Agent                   │
├──────────────────────────────────────────────────────────────┤
│                                                              │
│   KeeperHubToolkit                                           │
│   ├── Native tools ──► KeeperHubClient (httpx, REST)         │
│   │                    └── ExecutionStore (SQLite, optional)  │
│   ├── ENS tools ─────► ENSClient (httpx, JSON-RPC)           │
│   └── MCP tools ─────► KeeperHubMCPLoader (optional)         │
│                                                              │
└──────────┬──────────────────┬───────────────────┬────────────┘
           │                  │                   │
   KeeperHub REST API   Public JSON-RPC    KeeperHub MCP Server
   (app.keeperhub.com)  (ENS reads only)   (hosted SSE, optional)
           │
     Turnkey TEE
     (signing happens here,
      private key never leaves)
```

## Components

### KeeperHubToolkit

The main entry point. It creates all tools and manages shared clients.

```python
toolkit = KeeperHubToolkit(api_key="kh_...")
tools = toolkit.get_tools()           # native tools only
tools = await toolkit.aget_tools()    # native + MCP workflow tools
```

### KeeperHubClient

Async HTTP client mapping 1:1 to KeeperHub REST endpoints:

| Method | Endpoint | Type |
|--------|----------|------|
| `transfer()` | `POST /api/execute/transfer` | Write |
| `contract_call()` | `POST /api/execute/contract-call` | Read/Write |
| `check_and_execute()` | `POST /api/execute/check-and-execute` | Write |
| `get_execution_status()` | `GET /api/execute/{id}/status` | Read |
| `list_chains()` | `GET /api/chains` | Read |
| `fetch_abi()` | `GET /api/chains/{chainId}/abi` | Read |
| `get_user()` | `GET /api/user` | Read |

Key behaviors:
- Recreates the httpx client when the event loop changes (sync tool calls spin a new loop each time).
- Resolves chain aliases (`"base-sepolia"`, `"11155111"`) via a cached chain listing.
- Enforces `testnet_only` and `allowed_chain_ids` before any HTTP call leaves the process.

### ENSClient

Resolves ENS names and Basenames using raw `eth_call` over JSON-RPC. No `web3.py` dependency.

- Implements EIP-137 namehash
- Supports `addr(bytes32)` (legacy) and `addr(bytes32, uint256)` (EIP-2304/ENSIP-9)
- Reverse resolution via ENSIP-19
- Keccak-256: prefers OpenSSL 3.x, falls back to pycryptodome

See [ENS Integration](./ens-integration.md) for chain profiles and configuration.

### ExecutionStore (history)

Optional SQLite store that records every write operation. Default path: `~/.keeperhub/executions.db`.

Store failures are logged but never raised — history can never be the reason a successful transaction appears to fail.

### MCP bridge

Bridges KeeperHub's hosted MCP server (~20 workflow tools) into LangChain via `langchain-mcp-adapters`. Only loaded when `workflows=True`.

## Native tools vs. MCP tools

| | Native tools | MCP tools |
|---|---|---|
| **Transport** | REST (httpx) | MCP (SSE) |
| **Latency** | ~100ms | Higher (SSE connection overhead) |
| **Always available** | Yes | Opt-in (`workflows=True`) |
| **Use case** | Transfers, contract calls, reads, ENS | Workflow CRUD, AI generation, templates |
| **Async required** | No (`get_tools()` works) | Yes (`aget_tools()` only) |
| **Extra dependency** | None | `langchain-mcp-adapters` |

## Security model

### Key management

```
Your code ──(API key)──► KeeperHub ──(internal)──► Turnkey TEE
                                                       │
                                                 Private key lives here.
                                                 Never leaves the enclave.
```

- Your agent holds an API key (`kh_`), not a private key.
- KeeperHub delegates signing to a [Turnkey](https://turnkey.com) TEE (Trusted Execution Environment).
- The signing key is generated inside the TEE and cannot be exported.

### Write safety

1. **No write retries.** POST/PUT/PATCH/DELETE are never auto-retried. A network error on a write is surfaced immediately.
2. **Testnet lockdown.** `testnet_only=True` blocks writes to any chain not flagged as testnet.
3. **Chain allowlist.** `allowed_chain_ids` restricts to a specific set.
4. **Deduplication via history.** When the execution store is enabled, the agent can check if a similar write already succeeded.

## Typed exceptions

| Exception | HTTP code | Meaning |
|-----------|-----------|---------|
| `AuthenticationError` | 401 | Invalid or missing API key |
| `ValidationError` | 400 | Bad request parameters |
| `WalletNotConfiguredError` | 422 | Wallet not set up |
| `SpendingCapExceededError` | 422 | Spending cap limit hit |
| `RateLimitError` | 429 | Too many requests |
| `NotFoundError` | 404 | Resource not found |
| `ServerError` | 5xx | KeeperHub server issue |

## Retry behavior

| Failure | Retries | Behavior |
|---------|---------|----------|
| Network error on GET | 3 | Linear backoff (1s, 2s, 3s) |
| Network error on write | 0 | Raised immediately |
| HTTP 429 | 3 | Honors `Retry-After` header |
| HTTP 4xx | 0 | Typed exception immediately |
| HTTP 5xx | 0 | `ServerError` immediately |

Default timeout: 60s per request (override with `KeeperHubClient(timeout=...)`).

## Package layout

```
langchain_keeperhub/
├── __init__.py          # Public API
├── client.py            # KeeperHubClient (REST)
├── toolkit.py           # KeeperHubToolkit (entry point)
├── ens.py               # ENSClient (JSON-RPC)
├── ens_chains.py        # Chain profiles for ENS
├── _exceptions.py       # Typed errors
├── _async_utils.py      # Sync/async bridge
├── _types.py            # Shared types
├── history/
│   ├── _models.py       # ExecutionRecord, ExecutionKind
│   ├── _store.py        # ExecutionStore protocol
│   └── sqlite.py        # SQLite implementation
├── mcp/
│   └── _loader.py       # MCP bridge
└── tools/
    ├── _base.py         # Tool base classes
    ├── transfer.py
    ├── contract_call.py
    ├── check_and_execute.py
    ├── execution_status.py
    ├── fetch_abi.py
    ├── get_wallet_address.py
    ├── list_chains.py
    ├── list_executions.py
    ├── resolve_ens.py
    └── reverse_resolve_ens.py
```

## Extending the SDK

### Custom execution store

Implement the `ExecutionStore` protocol:

```python
from langchain_keeperhub.history import ExecutionStore, ExecutionRecord

class MyStore:
    async def record(self, record: ExecutionRecord) -> None: ...
    async def update_status(self, execution_id: str, **kwargs) -> None: ...
    async def list(self, *, status=None, kind=None, limit=50) -> list[ExecutionRecord]: ...
    async def get(self, execution_id: str) -> ExecutionRecord | None: ...
    async def aclose(self) -> None: ...

toolkit = KeeperHubToolkit(history=MyStore())
```

### Custom tool composition

Pick individual tool classes and wire them into your own LangGraph graph:

```python
from langchain_keeperhub import KeeperHubClient, ENSClient, TransferFundsTool, ResolveENSTool

client = KeeperHubClient()
transfer = TransferFundsTool(client=client)
resolve = ResolveENSTool(ens_client=ENSClient())
```
