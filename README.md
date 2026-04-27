# langchain-keeperhub

**LangChain toolkit for reliable Web3 execution via [KeeperHub](https://keeperhub.com).**

Give any LangChain agent the ability to transfer tokens, call smart contracts, and monitor on-chain executions — all backed by KeeperHub's retry logic, gas optimization, MEV protection, and full audit trail.

Built for the [ETHGlobal OpenAgents](https://ethglobal.com/events/openagents) hackathon.

## Install

```bash
pip install langchain-keeperhub
```

Or install locally for development:

```bash
git clone https://github.com/devendra116/langchain-keeperhub.git
cd langchain-keeperhub
pip install -e ".[dev]"
```

## Quick Start

```bash
pip install langchain-keeperhub langchain-google-genai langgraph python-dotenv
```

```python
from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.prebuilt import create_react_agent

from langchain_keeperhub import KeeperHubToolkit

load_dotenv()

toolkit = KeeperHubToolkit()  # reads KEEPERHUB_API_KEY from env
tools = toolkit.get_tools()

agent = create_react_agent(
    ChatGoogleGenerativeAI(model="gemini-3-flash-preview", temperature=0),
    tools,
)
result = agent.invoke(
    {"messages": [("user", "What blockchain networks does KeeperHub support?")]}
)
print(result["messages"][-1].content)
```

For safer local development, you can force write tools to only target testnets:

```python
toolkit = KeeperHubToolkit(testnet_only=True)
```

This blocks `transfer_funds`, `contract_call`, and `check_and_execute` when the
resolved network is not marked as a testnet by KeeperHub's chain registry.
For stricter control, also allowlist the exact chain IDs your app may write to:

```python
toolkit = KeeperHubToolkit(
    testnet_only=True,
    allowed_chain_ids={"11155111", "84532"},  # Sepolia, Base Sepolia
)
```

With an allowlist, all other write networks are treated as unsupported before
any transaction request is sent.

See `examples/basic_agent.py` for a complete runnable script.

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `KEEPERHUB_API_KEY` | Yes | Org-scoped API key (`kh_` prefix) from [app.keeperhub.com](https://app.keeperhub.com) |
| `GOOGLE_API_KEY` | For example | Required by `langchain-google-genai` for Gemini |

## Tools

| Tool | API Endpoint | Description |
|---|---|---|
| `keeperhub_list_chains` | `GET /api/chains` | List supported blockchain networks |
| `keeperhub_fetch_contract_abi` | `GET /api/chains/{id}/abi` | Fetch verified contract ABI |
| `keeperhub_get_wallet_address` | `GET /api/user` | Get the connected KeeperHub wallet address from the user profile |
| `keeperhub_transfer_funds` | `POST /api/execute/transfer` | Send native or ERC-20 tokens |
| `keeperhub_contract_call` | `POST /api/execute/contract-call` | Read/write any smart contract |
| `keeperhub_check_and_execute` | `POST /api/execute/check-and-execute` | Conditional read-then-write |
| `keeperhub_get_execution_status` | `GET /api/execute/{id}/status` | Poll execution status and tx hash |
| `keeperhub_list_executions` | local DB | Query past write executions (only available when `history=...` is enabled) |

`keeperhub_get_wallet_address` reads the authenticated KeeperHub user profile and
returns its `walletAddress`. If no wallet is connected, the tool returns a
warning telling the agent to ask the user to create/connect a KeeperHub wallet
or explicitly provide the address to use.

## Retries, timeouts & errors

`KeeperHubClient` keeps retry behavior narrow and explicit:

| Failure | Retries | Backoff |
|---|---|---|
| Network error (`httpx.HTTPError`) on `GET` | 3 | linear: 1s, 2s, 3s |
| Network error (`httpx.HTTPError`) on non-`GET` | 0 | no retry (prevents duplicate writes) |
| HTTP 429 (rate limit) | 3 | honors `Retry-After` header |
| HTTP 4xx (other) / 5xx | 0 — raises typed exception immediately | — |

- Per-request timeout: **60s** (override via `KeeperHubClient(timeout=...)`).
- Every retry and every 4xx/5xx response body is logged at `WARNING` /
  `ERROR` on the `langchain_keeperhub.client` logger.
- LangGraph agents have their own retry loop: when a tool raises, the error
  is fed back to the LLM as a `ToolMessage` and the model may call the tool
  again. Cap this with `config={"recursion_limit": N}` on
  `agent.invoke` / `agent.stream` (see `examples/basic_agent.py`).

To see retry/error logs, configure logging in your app:

```python
import logging
logging.basicConfig(level=logging.INFO)
```

## Write + poll pattern

Write tools (`transfer_funds`, `contract_call`, `check_and_execute`) return
structured output containing an `execution_id`. The agent should follow up with
`get_execution_status` to poll until the transaction settles and surface the
final tx hash to the user.

## Execution history (opt-in)

Off by default. Pass `history=True` (or any custom `ExecutionStore`) and every
successful write — `transfer_funds`, `contract_call` writes, and
`check_and_execute` runs that fired — is persisted locally. Status polls are
folded back into the same row, so the DB always reflects the latest tx hash,
gas used, and terminal state. Reads are never persisted.

```python
from langchain_keeperhub import KeeperHubToolkit

# Default: SqliteExecutionStore at ~/.keeperhub/executions.db
toolkit = KeeperHubToolkit(history=True)

# Or point at a custom path / swap in your own ExecutionStore
from langchain_keeperhub import SqliteExecutionStore
toolkit = KeeperHubToolkit(history=SqliteExecutionStore("./executions.db"))
```

When history is enabled, the toolkit additionally exposes
`keeperhub_list_executions`, which the agent can call to answer questions
about past activity. Direct (non-LLM) callers can use the same store from
Python:

```python
recent = await toolkit.history.list(status="pending", limit=10)
for r in recent:
    print(r.execution_id, r.kind, r.status, r.transaction_hash)
```

Why it's useful:

- **Receipts / audit.** "Show me everything I sent today" becomes one tool call.
- **Don't double-pay.** Agent checks history before issuing a similar transfer.
- **Crash recovery.** A new session can resume polling rows that were left in `pending` / `running`.
- **Long-running automation.** Treasury bots and streaming-payment loops get an audit trail without shipping their own DB layer.

The store interface is a small Protocol (`record`, `update_status`, `list`,
`get`, `aclose`); the SQLite default is stdlib-only and serializes blocking
calls through `asyncio.to_thread`. Failures from the store are logged but
never raised — history can never be the reason a successful transaction
looks like a failure.

## Direct client usage (no LLM)

```python
import asyncio
from langchain_keeperhub import KeeperHubClient

async def main():
    client = KeeperHubClient()  # reads KEEPERHUB_API_KEY from env
    chains = await client.list_chains()
    print(chains)
    await client.aclose()

asyncio.run(main())
```

## Workflow management (opt-in)

KeeperHub also runs an officially maintained **MCP server** (~20 tools)
covering the *cold path* — workflow CRUD, AI workflow generation,
plugin/template catalogs, integrations, action-schema introspection,
and workflow-run polling. The toolkit can bridge that surface into
LangChain too: same toolkit, same API key, opt-in via a flag.

```bash
pip install "langchain-keeperhub[workflows]"
```

```python
import asyncio
from langchain_keeperhub import KeeperHubToolkit

async def main():
    toolkit = KeeperHubToolkit(
        workflows=True,
        # Server-side names — the toolkit applies the keeperhub_ prefix
        # (and any rename) before the agent sees them.
        mcp_include={
            "ai_generate_workflow",
            "create_workflow",
            "execute_workflow",
            "get_execution_status",
            "list_workflows",
        },
    )
    try:
        tools = await toolkit.aget_tools()  # async — MCP loads asynchronously
        # ... pass *tools* to create_react_agent / LangGraph
    finally:
        await toolkit.aclose()

asyncio.run(main())
```

See `examples/workflow_agent.py` for an end-to-end demo: an agent
generates a workflow from natural language, persists it, executes it,
polls the run, and prints the resulting tx hash.

### Hot path vs cold path — when to use which

| You want to… | Path | Tool flavor |
|---|---|---|
| Send a transfer or contract call **right now** | Hot | Native: `keeperhub_transfer_funds`, `keeperhub_contract_call` |
| Read on-chain data, fetch ABIs, list chains | Hot | Native: `keeperhub_*` REST tools |
| Compose / persist / run a recurring workflow | Cold | MCP: `keeperhub_create_workflow`, `keeperhub_execute_workflow` |
| Have AI draft a workflow graph from a prompt | Cold | MCP: `keeperhub_ai_generate_workflow` |
| Browse plugin / template / integration catalog | Cold | MCP catalog tools |

Reach for the **native** tools when the agent's job is to act on chain
in this turn — they are synchronous, REST-thin, and ship the testnet
guardrails and history persistence described above. Reach for the
**MCP-bridged** tools only when the user is composing or operating
KeeperHub-managed workflow graphs; those tools have larger schemas and
extra round-trips that you don't want in a hot loop.

### Tool naming and prefix policy

Every KeeperHub tool — native or MCP-bridged — lives under the
`keeperhub_` namespace. When an MCP tool name collides with a native
tool, the MCP version is renamed to `keeperhub_workflow_<name>` so an
agent can disambiguate. Today the only collision is around execution
status:

| Tool | What it tracks |
|---|---|
| `keeperhub_get_execution_status` | A *direct* (single REST call) execution — the kind `transfer_funds` / `contract_call` / `check_and_execute` create. |
| `keeperhub_workflow_get_execution_status` | A *workflow run* started by `keeperhub_execute_workflow`. |

Renames are logged at `INFO` on the `langchain_keeperhub.toolkit`
logger, so you can grep for them during integration. The system prompt
in `examples/workflow_agent.py` explicitly tells the model which tool
to use when, which is the recommended pattern.

### Filtering the tool surface

`mcp_include` and `mcp_exclude` accept the **server-side** tool names
(without the `keeperhub_` prefix). `tools_documentation` is excluded by
default because it is a meta-tool that confuses agents and burns prompt
tokens. To opt back in, pass an explicit `mcp_exclude=set()` or your
own collection.

```python
toolkit = KeeperHubToolkit(
    workflows=True,
    mcp_include={"list_workflows", "execute_workflow", "get_execution_status"},
)
```

Unknown names in `mcp_include` log a `WARNING` but do not raise —
server tool names can change between KeeperHub releases and we'd
rather your agent keep running on the tools that *did* match.

### `get_tools()` vs `aget_tools()`

When `workflows=True`, MCP tools must be loaded asynchronously, so
`KeeperHubToolkit.get_tools()` raises a clear `RuntimeError` directing
you to `await toolkit.aget_tools()`. We deliberately do not spin up a
hidden event loop here — agents using workflow tools are already in
async land (LangGraph), and a silent `asyncio.run` would only paper
over a real architectural mismatch. Existing sync callers (no
workflows) keep working unchanged.

## Architecture

```
LangChain Agent
  └── KeeperHubToolkit
        ├── Native tools — hot path (always on)
        │     ├── ListChainsTool ─────────┐
        │     ├── FetchContractABITool ───┤
        │     ├── GetWalletAddressTool ───┤
        │     ├── TransferFundsTool ──────┤
        │     ├── ContractCallTool ───────┼── KeeperHubClient (httpx) ──► KeeperHub REST API
        │     ├── CheckAndExecuteTool ────┤        │                       (app.keeperhub.com)
        │     ├── GetExecutionStatusTool ─┤        │
        │     └── ListExecutionsTool* ────┘        ▼
        │                                    ExecutionStore
        │                                    (SQLite default, optional)
        │
        └── MCP-bridged tools — cold path (workflows=True)
              └── KeeperHubMCPLoader ──► langchain-mcp-adapters ──► KeeperHub MCP Server
                                                                   (app.keeperhub.com/mcp)

* ListExecutionsTool only registered when history=... is set.
```

## Development

```bash
pip install -e ".[dev]"
pytest
```

## License

MIT
