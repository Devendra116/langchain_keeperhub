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
| `keeperhub_transfer_funds` | `POST /api/execute/transfer` | Send native or ERC-20 tokens |
| `keeperhub_contract_call` | `POST /api/execute/contract-call` | Read/write any smart contract |
| `keeperhub_check_and_execute` | `POST /api/execute/check-and-execute` | Conditional read-then-write |
| `keeperhub_get_execution_status` | `GET /api/execute/{id}/status` | Poll execution status and tx hash |

## Write + poll pattern

Write tools (`transfer_funds`, `contract_call`, `check_and_execute`) return
JSON containing an `execution_id`. The agent should follow up with
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
