"""ledger_agent.py — meet "Ledger", a KeeperHub agent that remembers.

Same shape as ``examples/basic_agent.py``, but with the new execution-history
store turned on. The example runs in two halves on the *same* SQLite file:

  1. *Act* — something writes a transaction. In real code this is the
     toolkit auto-persisting whenever the agent calls
     ``keeperhub_transfer_funds`` / ``keeperhub_contract_call`` / etc. (writes
     only — reads are skipped). For a self-contained demo we seed two rows
     programmatically so this example runs with just a ``KEEPERHUB_API_KEY``
     and no funded wallet.

  2. *Recall* — a *fresh* agent is spun up with zero chat memory of step 1
     and asked "what did I just do?". The only way it can answer is by
     calling ``keeperhub_list_executions``, which reads the same SQLite
     file we wrote to above.

That second turn is the bit that wasn't possible before the history store
landed: the SDK now has a memory that survives process restarts and shared
deployments.

Prerequisites:
    pip install langchain-keeperhub langchain-google-genai langgraph python-dotenv

Environment variables:
    KEEPERHUB_API_KEY  -- your org-scoped kh_ key
    GOOGLE_API_KEY     -- your Gemini API key
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.prebuilt import create_react_agent

from langchain_keeperhub import (
    ExecutionKind,
    ExecutionRecord,
    KeeperHubToolkit,
    SqliteExecutionStore,
)
from langchain_keeperhub.history import utc_now_iso
import logging
logging.basicConfig(level=logging.DEBUG)

# A visible artifact next to this script so devs can poke at it
# (e.g. ``sqlite3 ledger_demo.db ".schema"``) once the demo finishes.
DB_PATH = Path(__file__).with_name("ledger_demo.db")


async def seed(db_path: Path) -> None:
    """Stand in for two real writes the toolkit would otherwise persist for free.

    Swap this for a real transfer once you have a funded testnet wallet:

        toolkit = KeeperHubToolkit(history=True, testnet_only=True)
        agent   = create_react_agent(llm, toolkit.get_tools())
        agent.invoke({"messages": [
            ("user", "Transfer 0.01 native to 0x... on Polygon Amoy"),
        ]})

    The bytes on disk are the same either way.
    """
    store = SqliteExecutionStore(db_path)
    try:
        now = utc_now_iso()
        await store.record(
            ExecutionRecord(
                execution_id="demo_xfer_1",
                kind=ExecutionKind.TRANSFER,
                network="80002",  # Polygon Amoy
                status="completed",
                request={
                    "recipientAddress": "0x3E67cc2C7fFf86d9870dB9D02c43e789B52FB296",
                    "amount": "2",
                    "tokenAddress": "0x41E94Eb019C0762f9Bfcf9Fb1E58725BfB0e7582",
                },
                response={"executionId": "demo_xfer_1", "status": "completed"},
                transaction_hash="0xseed11111111111111111111111111111111111111111111111111111111aaaa",
                transaction_link="https://amoy.polygonscan.com/tx/0xseed11...aaaa",
                created_at=now,
                updated_at=now,
            )
        )
        await store.record(
            ExecutionRecord(
                execution_id="demo_xfer_2",
                kind=ExecutionKind.TRANSFER,
                network="84532",  # Base Sepolia
                status="pending",
                request={
                    "recipientAddress": "0x3E67cc2C7fFf86d9870dB9D02c43e789B52FB296",
                    "amount": "0.5",
                },
                response={"executionId": "demo_xfer_2", "status": "pending"},
                created_at=now,
                updated_at=now,
            )
        )
    finally:
        await store.aclose()


def recall(db_path: Path) -> None:
    """Spin up Ledger on the same DB file and let it explain itself."""
    toolkit = KeeperHubToolkit(
        history=SqliteExecutionStore(db_path),
        testnet_only=True,
    )
    try:
        llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash", temperature=0)
        agent = create_react_agent(llm, toolkit.get_tools())

        # Fresh message thread — no chat memory of the seed step. The agent
        # has to reach for keeperhub_list_executions to answer at all.
        result = agent.invoke(
            {
                "messages": [
                    (
                        "system",
                        "You are Ledger, a treasurer agent for a KeeperHub user. "
                        "For any question about past activity, ALWAYS call "
                        "keeperhub_list_executions first. Render the result as a "
                        "compact markdown table with columns: execution_id, kind, "
                        "network, status, tx hash. After the table, add one short "
                        "sentence highlighting anything still pending so the user "
                        "knows what to re-poll.",
                    ),
                    (
                        "user",
                        "Give me a recap of every write you've issued so far. "
                        "Flag anything still pending.",
                    ),
                ]
            }
        )

        print("--- Ledger says ---")
        print(result["messages"][-1].content)
    finally:
        asyncio.run(toolkit.aclose())


def main() -> None:
    load_dotenv()
    # Step 1: pretend two writes happened (or replace with a real agent.invoke).
    asyncio.run(seed(DB_PATH))
    # Step 2: a brand-new agent answers using only the history store.
    recall(DB_PATH)


if __name__ == "__main__":
    main()
