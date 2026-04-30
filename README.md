# langchain-keeperhub

**Drop‑in Web3 capability for any LangChain agent or LangGraph workflow — no private keys, no RPC plumbing, full audit trail.**

`langchain-keeperhub` is a LangChain SDK for [KeeperHub](https://keeperhub.com), the execution layer for onchain agents. Give your agent a single API key and it can transfer tokens, call any verified smart contract, run conditional read‑then‑write logic, and track every transaction it ever sent — across every supported EVM chain.

Built for the [ETHGlobal OpenAgents](https://ethglobal.com/events/openagents) hackathon.

> **Independent community project.** This package is built and maintained by [@devendra116](https://github.com/devendra116) on top of KeeperHub's public REST and MCP APIs. It is **not** an official KeeperHub product and is not affiliated with, endorsed by, or sponsored by KeeperHub. "KeeperHub" and any KeeperHub logos are property of their respective owners.

## Why use this SDK?

- **No private keys in your agent.** KeeperHub provisions a non‑custodial wallet for your org through [Turnkey](https://turnkey.com). The signing key is generated and lives inside a TEE (Trusted Execution Environment) — it never touches KeeperHub's servers, and it never touches your agent process. Your code holds *only* an API key, yet every onchain action (transfer, contract write, conditional execute) still works.
- **Built‑in execution history.** Every successful write is persisted with its `execution_id`, tx hash, gas used, and final status. The agent can answer "did I already send this?", "what failed today?", or "resume polling after a crash" with one tool call — no custom DB layer.
- **Modular SDK, not a raw HTTP wrapper.** Use the prebuilt `KeeperHubToolkit` with `create_agent` for the fast path, or compose individual tool classes (`TransferFundsTool`, `ContractCallTool`, …) into your own LangGraph nodes. Need direct programmatic control? Use the underlying `KeeperHubClient` with no LLM in the loop. Swap in your own `ExecutionStore` if SQLite isn't where you want history.
- **Reliability that an LLM can't fake.** KeeperHub handles retries, gas optimization, and MEV protection server‑side. The SDK adds narrow, write‑safe retry rules on top (no duplicate writes, ever) and structured error types the model can reason about.
- **Testnet guardrails.** One flag (`testnet_only=True`) blocks every write tool from touching mainnet. Optional chain‑id allowlist locks writes to exactly the networks you approve.
- **Hot path / cold path split.** Native REST tools for actions the agent takes *right now*; an opt‑in MCP bridge for the cold path (workflow CRUD, AI‑generated workflows, plugin/template catalogs). Pay for the surface you actually use.

## Install

```bash
pip install langchain-keeperhub
```

With workflow management (cold path, MCP‑bridged):

```bash
pip install "langchain-keeperhub[workflows]"
```

## Quick start

```bash
pip install langchain-keeperhub langchain langchain-google-genai langgraph python-dotenv
```

```python
from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain_google_genai import ChatGoogleGenerativeAI

from langchain_keeperhub import KeeperHubToolkit

load_dotenv()  # KEEPERHUB_API_KEY, GOOGLE_API_KEY

toolkit = KeeperHubToolkit()
agent = create_agent(
    model=ChatGoogleGenerativeAI(model="gemini-2.5-flash", temperature=0),
    tools=toolkit.get_tools(),
)

result = agent.invoke({"messages": [
    ("user", "Send 1 USDC on Base Sepolia to 0x3E67…B296"),
]})
print(result["messages"][-1].content)
```

Get an API key at [app.keeperhub.com](https://app.keeperhub.com) (it starts with `kh_`).
A complete script lives at `examples/basic_agent.py`.

## What the agent can do

| Tool | Purpose |
|---|---|
| `keeperhub_list_chains` | List supported EVM networks |
| `keeperhub_fetch_contract_abi` | Auto‑fetch verified ABIs |
| `keeperhub_get_wallet_address` | Read the agent's KeeperHub wallet address |
| `keeperhub_transfer_funds` | Send native or ERC‑20 tokens |
| `keeperhub_contract_call` | Read or write any smart contract |
| `keeperhub_check_and_execute` | Conditional read‑then‑write in one call |
| `keeperhub_get_execution_status` | Poll execution and surface tx hash |
| `keeperhub_list_executions` | Query past write executions *(when history is enabled)* |

Write tools return an `execution_id`; the agent calls `get_execution_status` to confirm the tx settled and report the hash back to the user.

## Safety: testnet‑only mode

```python
toolkit = KeeperHubToolkit(
    testnet_only=True,
    allowed_chain_ids={"11155111", "84532"},  # Sepolia, Base Sepolia
)
```

`testnet_only=True` blocks `transfer_funds`, `contract_call`, and `check_and_execute` whenever the resolved chain is not flagged as a testnet by KeeperHub's chain registry. Add `allowed_chain_ids` to lock writes to a specific subset.

## Execution history (opt‑in)

Off by default. Pass `history=True` and every successful write — and every status poll for it — is recorded locally.

```python
from langchain_keeperhub import KeeperHubToolkit, SqliteExecutionStore

# Default: SqliteExecutionStore at ~/.keeperhub/executions.db
toolkit = KeeperHubToolkit(history=True)

# Or point at a custom path / plug in your own ExecutionStore
toolkit = KeeperHubToolkit(history=SqliteExecutionStore("./executions.db"))
```

When history is on, the toolkit also exposes `keeperhub_list_executions`, so the agent itself can answer questions like *"what did I send today?"* or *"did this transfer already go through?"* before issuing a new write.

Direct (non‑LLM) callers can use the same store from Python:

```python
recent = await toolkit.history.list(status="pending", limit=10)
for r in recent:
    print(r.execution_id, r.kind, r.status, r.transaction_hash)
```

What it unlocks:

- **Receipts / audit trail** for every onchain action the agent took.
- **Deduplication** — the agent checks history before re‑issuing similar writes.
- **Crash recovery** — a new session resumes polling rows left in `pending` / `running`.
- **Long‑running automation** — treasury bots and streaming‑payment loops get an audit log without shipping their own database.

The store is a small Protocol (`record`, `update_status`, `list`, `get`, `aclose`). The default SQLite implementation is stdlib‑only and serializes blocking calls through `asyncio.to_thread`. Failures from the store are logged but never raised — history can never be the reason a successful transaction looks like a failure.

## Reliability

`KeeperHubClient` keeps retry behavior narrow and explicit:

| Failure | Retries | Notes |
|---|---|---|
| Network error on `GET` | 3 | Linear backoff |
| Network error on write (`POST/PUT/PATCH/DELETE`) | 0 | Never auto‑retried — prevents duplicate writes |
| HTTP 429 | 3 | Honors `Retry-After` |
| HTTP 4xx / 5xx | 0 | Raises a typed exception immediately |

Per‑request timeout is 60s (override with `KeeperHubClient(timeout=...)`). All retry/error events are logged on the `langchain_keeperhub.client` logger.

## Workflow management (opt‑in)

KeeperHub also runs a hosted MCP server (~20 tools) for the *cold path*: workflow CRUD, AI workflow generation, plugin/template catalogs, integrations, and workflow‑run polling. This SDK can bridge that surface into LangChain — same toolkit, same API key.

```python
toolkit = KeeperHubToolkit(
    workflows=True,
    mcp_include={
        "ai_generate_workflow",
        "create_workflow",
        "execute_workflow",
        "list_workflows",
        "get_execution_status",
    },
)
tools = await toolkit.aget_tools()  # async — MCP loads asynchronously
```

When to reach for which:

| You want to… | Path | Tools |
|---|---|---|
| Send a transfer or contract call right now | Hot | Native REST tools |
| Read on‑chain data, fetch ABIs, list chains | Hot | Native REST tools |
| Compose / persist / run a recurring workflow | Cold | MCP‑bridged tools |
| Have AI draft a workflow from a prompt | Cold | `keeperhub_ai_generate_workflow` |

When an MCP tool name collides with a native one (today only `get_execution_status`), the MCP version is renamed to `keeperhub_workflow_<name>` and the rename is logged. See `examples/workflow_agent.py` for an end‑to‑end demo where an agent generates a workflow from natural language, persists it, executes it, polls the run, and prints the resulting tx hash.

## Direct client usage (no LLM)

```python
import asyncio
from langchain_keeperhub import KeeperHubClient

async def main():
    async with KeeperHubClient() as client:  # reads KEEPERHUB_API_KEY
        chains = await client.list_chains()
        print(chains)

asyncio.run(main())
```

## Architecture

```
LangChain / LangGraph agent
  └── KeeperHubToolkit
        ├── Native tools (hot path, always on)
        │     └── KeeperHubClient (httpx) ──► KeeperHub REST API
        │                  │
        │                  ▼
        │            ExecutionStore (optional; SQLite default)
        │
        └── MCP-bridged tools (cold path, workflows=True)
              └── langchain-mcp-adapters ──► KeeperHub MCP server

Signing: KeeperHub → Turnkey TEE  (your code never sees the private key)
```

## Compatibility

- `langchain-keeperhub >= 0.4.0` targets the LangChain v1 ecosystem (`langchain-core>=1.3,<2`).
- Apps still on `langchain-core 0.3.x` should stay on `langchain-keeperhub 0.3.x`.
- Python 3.10+.

## Environment variables

| Variable | Required | Purpose |
|---|---|---|
| `KEEPERHUB_API_KEY` | Yes | Org‑scoped API key (`kh_` prefix) from [app.keeperhub.com](https://app.keeperhub.com) |
| `GOOGLE_API_KEY` | For the example | Required by `langchain-google-genai` for Gemini |

## Development

```bash
git clone https://github.com/devendra116/langchain-keeperhub.git
cd langchain-keeperhub
pip install -e ".[dev]"
pytest
```

## Links

- KeeperHub: <https://keeperhub.com>
- Docs: <https://docs.keeperhub.com>
- Turnkey signer write‑up: <https://keeperhub.com/blog/009-turnkey-signer-integration>
- Examples: [`examples/`](./examples)

## License & disclaimer

MIT — see [`LICENSE`](./LICENSE).

This is an independent, community‑maintained package. It is not an official KeeperHub release and is not affiliated with, endorsed by, or sponsored by KeeperHub. All KeeperHub‑related names, logos, and trademarks belong to their respective owners and are used here for descriptive interoperability only. The package talks to KeeperHub's public APIs using your own API key; the maintainer does not operate or warrant the upstream service.
