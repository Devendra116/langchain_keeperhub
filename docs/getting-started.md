# Getting Started

This guide takes you from zero to a working onchain agent in about 5 minutes.

## Prerequisites

- Python 3.10+
- A KeeperHub API key — sign up at [app.keeperhub.com](https://app.keeperhub.com) (key starts with `kh_`)
- An LLM API key (examples use Google Gemini, but any LangChain-compatible model works)

## Install

Pick what you need:

```bash
# Core SDK
pip install langchain-keeperhub

# If you want MCP workflow tools
pip install "langchain-keeperhub[workflows]"

# If ENS resolution fails with a keccak error
pip install "langchain-keeperhub[ens]"
```

For the examples below, also install:

```bash
pip install langchain langchain-google-genai langgraph python-dotenv
```

## Configure

You can configure the SDK in two ways. Pick whichever you prefer.

**Option A: Environment variables** (via `.env` file or shell exports)

```bash
KEEPERHUB_API_KEY=kh_your_key_here
GOOGLE_API_KEY=your_google_api_key   # only needed for Gemini examples
```

**Option B: Pass directly in code**

```python
toolkit = KeeperHubToolkit(api_key="kh_...")
```

Both work. You can mix them too — for example, set the API key in `.env` and pass safety options in code.

## Your first agent

```python
from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_keeperhub import KeeperHubToolkit

load_dotenv()

toolkit = KeeperHubToolkit()
agent = create_agent(
    model=ChatGoogleGenerativeAI(model="gemini-2.5-flash", temperature=0),
    tools=toolkit.get_tools(),
)

result = agent.invoke({"messages": [
    ("user", "What chains does KeeperHub support?"),
]})
print(result["messages"][-1].content)
```

That's it. The agent now has access to all KeeperHub tools and will decide which ones to call.

## Lock it to testnets

For safety, restrict writes to testnet chains only:

```python
toolkit = KeeperHubToolkit(
    testnet_only=True,
    allowed_chain_ids={"11155111", "84532"},  # Sepolia + Base Sepolia
)
```

Now the agent physically cannot send transactions on mainnet, even if the user asks it to.

## What the agent can do

Here are the main things your agent can handle. You don't need to write code for each — just describe what you want in natural language and the agent calls the right tools.

### Send tokens

Ask: *"Send 0.01 ETH on Sepolia to 0x3E67...B296"*

The agent calls `transfer_funds`, gets back an `execution_id`, then polls `get_execution_status` until the transaction confirms.

### Call smart contracts

Ask: *"What's the total supply of USDC on Base Sepolia?"*

The agent calls `fetch_contract_abi` to get the ABI, then `contract_call` to read the value.

For writes (like approvals), the agent will also poll `get_execution_status` afterward.

### Conditional execution

Ask: *"If my balance is above 10 USDC, send 5 USDC to 0xABC..."*

The agent uses `check_and_execute`, which reads a value and only writes if the condition passes — all in one atomic call.

### Resolve ENS names

Ask: *"What address is vitalik.eth?"*

The agent calls `resolve_ens` and returns the address. This uses public JSON-RPC (no KeeperHub API call needed).

Basenames work too: *"Resolve nick.base.eth"* (set `ens_chain="base"` on the toolkit).

### Track history

Enable history to log every write the agent makes:

```python
toolkit = KeeperHubToolkit(history=True)
```

Then ask: *"What transactions did I send today?"* or *"Did this transfer already go through?"*

History is stored in SQLite at `~/.keeperhub/executions.db` by default. You can pass a custom path:

```python
from langchain_keeperhub import SqliteExecutionStore
toolkit = KeeperHubToolkit(history=SqliteExecutionStore("./my_executions.db"))
```

### Workflow management (optional)

If you want access to KeeperHub's workflow tools (create, list, execute workflows), enable the MCP bridge:

```python
toolkit = KeeperHubToolkit(workflows=True)
tools = await toolkit.aget_tools()  # async required for MCP
```

This requires the `[workflows]` extra: `pip install "langchain-keeperhub[workflows]"`.

## Use without an LLM

For scripting or automation, use `KeeperHubClient` directly:

```python
import asyncio
from langchain_keeperhub import KeeperHubClient

async def main():
    async with KeeperHubClient() as client:
        chains = await client.list_chains()
        print(chains)

        result = await client.transfer(
            network="84532",
            recipient_address="0x3E67...B296",
            amount="1000000",
            token_address="0x036C...dCF7e",
        )
        status = await client.get_execution_status(result["executionId"])
        print(status)

asyncio.run(main())
```

### ENS without an agent

```python
import asyncio
from langchain_keeperhub import ENSClient

async def main():
    client = ENSClient()  # defaults to Ethereum mainnet
    addr = await client.resolve("vitalik.eth")
    print(addr)
    await client.aclose()

asyncio.run(main())
```

## Pick individual tools

If you don't want all tools, compose your own set:

```python
from langchain_keeperhub import (
    KeeperHubClient, ENSClient,
    TransferFundsTool, ResolveENSTool, GetExecutionStatusTool,
)

client = KeeperHubClient(testnet_only=True)
ens = ENSClient(chain="base")

tools = [
    TransferFundsTool(client=client),
    ResolveENSTool(ens_client=ens),
    GetExecutionStatusTool(client=client),
]
```

## Error handling

The SDK throws typed exceptions so you can catch specific failures:

```python
from langchain_keeperhub import KeeperHubClient
from langchain_keeperhub._exceptions import (
    AuthenticationError,
    ValidationError,
    RateLimitError,
    SpendingCapExceededError,
)

async with KeeperHubClient() as client:
    try:
        await client.transfer(...)
    except AuthenticationError:
        print("Bad API key")
    except SpendingCapExceededError:
        print("Spending cap hit")
    except RateLimitError as e:
        print(f"Rate limited, retry after {e.retry_after}s")
```

## Logging

```python
import logging
logging.getLogger("langchain_keeperhub").setLevel(logging.DEBUG)
```

Sub-loggers: `langchain_keeperhub.client` (HTTP), `langchain_keeperhub.ens` (ENS resolution).

## Next steps

- [Architecture](architecture.md) — how the SDK works under the hood
- [ENS Integration](ens-integration.md) — ENS and Basenames details
- [Examples](../examples/) — working scripts
- [KeeperHub API docs](https://docs.keeperhub.com)
