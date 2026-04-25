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

```python
from langchain_keeperhub import KeeperHubToolkit
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent

toolkit = KeeperHubToolkit()  # reads KEEPERHUB_API_KEY from env
tools = toolkit.get_tools()

agent = create_react_agent(ChatOpenAI(model="gpt-4o-mini"), tools)
result = agent.invoke(
    {"messages": [("user", "What blockchain networks does KeeperHub support?")]}
)
print(result["messages"][-1].content)
```

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `KEEPERHUB_API_KEY` | Yes | Org-scoped API key (`kh_` prefix) from [app.keeperhub.com](https://app.keeperhub.com) |
| `OPENAI_API_KEY` | For examples | Required if using `langchain-openai` as the LLM |

## Tools

| Tool | API Endpoint | Description |
|---|---|---|
| `keeperhub_list_chains` | `GET /api/chains` | List supported blockchain networks |
| `keeperhub_fetch_contract_abi` | `GET /api/chains/{id}/abi` | Fetch verified contract ABI |
| `keeperhub_transfer_funds` | `POST /api/execute/transfer` | Send native or ERC-20 tokens |
| `keeperhub_contract_call` | `POST /api/execute/contract-call` | Read/write any smart contract |
| `keeperhub_check_and_execute` | `POST /api/execute/check-and-execute` | Conditional read-then-write |
| `keeperhub_get_execution_status` | `GET /api/execute/{id}/status` | Poll execution status and tx hash |

## Usage Patterns

### Read-only: check a balance

```python
result = agent.invoke({
    "messages": [(
        "user",
        "Read the balanceOf function on USDC contract "
        "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48 on ethereum "
        "for address 0x742d35Cc6634C0532925a3b844Bc9e7595f0bEb"
    )]
})
```

### Write + poll: transfer tokens

The agent will call `transfer_funds`, receive an `execution_id`, then call
`get_execution_status` to poll until the transaction completes:

```python
result = agent.invoke({
    "messages": [(
        "user",
        "Transfer 0.001 ETH to 0x742d35Cc6634C0532925a3b844Bc9e7595f0bEb "
        "on sepolia, then check the execution status and give me the tx hash."
    )]
})
```

### Direct client usage (no LLM)

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
