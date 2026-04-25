"""Minimal example: wire up a LangChain ReAct agent with KeeperHub tools.

Prerequisites:
    pip install langchain-keeperhub langchain-openai langgraph

Environment variables:
    KEEPERHUB_API_KEY  -- your org-scoped kh_ key
    OPENAI_API_KEY     -- for the LLM

Source: https://github.com/devendra116/langchain-keeperhub
"""

import os

from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent

from langchain_keeperhub import KeeperHubToolkit


def main() -> None:
    toolkit = KeeperHubToolkit()  # reads KEEPERHUB_API_KEY from env
    tools = toolkit.get_tools()

    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
    agent = create_react_agent(llm, tools)

    # --- Read-only demo: list supported chains ---
    print("=== List chains ===")
    result = agent.invoke(
        {"messages": [("user", "What blockchain networks does KeeperHub support?")]}
    )
    print(result["messages"][-1].content)

    # --- Read-only demo: fetch a contract ABI ---
    print("\n=== Fetch ABI ===")
    result = agent.invoke(
        {
            "messages": [
                (
                    "user",
                    "Fetch the ABI for the USDC contract on Ethereum mainnet: "
                    "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48 (chain ID 1)",
                )
            ]
        }
    )
    print(result["messages"][-1].content)

    # --- Write demo (requires funded wallet on KeeperHub) ---
    # Uncomment to test a real transfer:
    #
    # result = agent.invoke(
    #     {
    #         "messages": [
    #             (
    #                 "user",
    #                 "Transfer 0.001 ETH to 0x742d35Cc6634C0532925a3b844Bc9e7595f0bEb "
    #                 "on sepolia, then check the execution status.",
    #             )
    #         ]
    #     }
    # )
    # print(result["messages"][-1].content)


if __name__ == "__main__":
    main()
