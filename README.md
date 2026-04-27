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

## Architecture

```
LangChain Agent
  └── KeeperHubToolkit
        ├── ListChainsTool ─────────┐
        ├── FetchContractABITool ───┤
        ├── GetWalletAddressTool ───┤
        ├── TransferFundsTool ──────┤
        ├── ContractCallTool ───────┼── KeeperHubClient (httpx)
        ├── CheckAndExecuteTool ────┤       │
        └── GetExecutionStatusTool ─┘       ▼
                                     KeeperHub REST API
                                     app.keeperhub.com
```

## Development

```bash
pip install -e ".[dev]"
pytest
```

## License

MIT
