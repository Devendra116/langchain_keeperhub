"""KeeperHub workflow demo (compact)."""

from __future__ import annotations
import asyncio
import json
import logging
from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_keeperhub import KeeperHubToolkit

YELLOW, GREEN, CYAN, RESET = "\033[93m", "\033[92m", "\033[96m", "\033[0m"
MCP_INCLUDE = frozenset(
    {
        "ai_generate_workflow",
        "create_workflow",
        "execute_workflow",
        "get_execution_status",
        "list_workflows",
        "get_workflow",
    }
)
SYSTEM_PROMPT = "You are a helpful KeeperHub developer assistant. Use available KeeperHub tools to build and run workflows, explain outcomes clearly, and include useful execution context like ids, status, transaction details, and errors when present. Always call tools by their exact runtime names shown in the tool list (for example, keeperhub_* names)."
USER_PROMPT = "Build a workflow that transfer 1 0x20c0000000000000000000000000000000000000 token to 0x3E67cc2C7fFf86d9870dB9D02c43e789B52FB296 on chainid: 42431. Run it once and tell me what happened."


async def main() -> None:
    load_dotenv()
    logging.basicConfig(level=logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.CRITICAL)

    ctx = {
        "workflow_id": "",
        "workflow_name": "",
        "execution_id": "",
        "status": "",
        "tx_hash": "",
        "error": "",
        "last": "",
    }
    result = None

    try:
        async with KeeperHubToolkit(
            workflows=True,
            testnet_only=True,
            allowed_chain_ids={80002},
            mcp_include=MCP_INCLUDE,
        ) as toolkit:
            tools = await toolkit.aget_tools()
            print(f"\nKeeperHub Workflow Demo | tools={len(tools)}", flush=True)
            for t in tools:
                print(f"  - {t.name}", flush=True)
            agent = create_agent(
                model=ChatGoogleGenerativeAI(
                    model="gemini-2.5-flash", temperature=0, max_retries=0
                ),
                tools=tools,
            )
            payload = {"messages": [("system", SYSTEM_PROMPT), ("user", USER_PROMPT)]}
            print("\nRunning...", flush=True)
            seen = 0
            async for state in agent.astream(
                payload, config={"recursion_limit": 30}, stream_mode="values"
            ):
                result = state
                msgs = state.get("messages", [])
                for msg in msgs[seen:]:
                    if msg.type == "ai":
                        for call in getattr(msg, "tool_calls", None) or []:
                            print(
                                f" -> {YELLOW}{call.get('name', '<unknown-tool>')}{RESET}",
                                flush=True,
                            )
                    elif msg.type == "tool":
                        name = getattr(msg, "name", "tool")
                        raw = getattr(msg, "content", "")
                        if isinstance(raw, str):
                            txt = raw.strip()
                        elif isinstance(raw, list):
                            txt = "\n".join(
                                str(i.get("text", i)) if isinstance(i, dict) else str(i)
                                for i in raw
                            ).strip()
                        else:
                            txt = str(raw).strip()
                        ctx["last"] = txt
                        print(f"\n <- {YELLOW}{name}{RESET} full response:", flush=True)
                        print(txt or "<empty>", flush=True)
                        try:
                            obj = json.loads(txt)
                        except Exception:
                            obj = None
                        if isinstance(obj, dict):
                            ctx["workflow_id"] = obj.get("id", ctx["workflow_id"])
                            ctx["workflow_name"] = obj.get("name", ctx["workflow_name"])
                            ctx["execution_id"] = obj.get(
                                "executionId", ctx["execution_id"]
                            )
                            ctx["status"] = obj.get("status", ctx["status"])
                            ctx["tx_hash"] = obj.get("transactionHash", ctx["tx_hash"])
                            if obj.get("error"):
                                ctx["error"] = str(obj["error"])
                            if obj.get("name"):
                                print(
                                    f"    workflow: {CYAN}{obj['name']}{RESET}",
                                    flush=True,
                                )
                        elif "error" in txt.lower():
                            ctx["error"] = txt
                seen = len(msgs)
    except Exception as exc:
        print("\nWorkflow failed", flush=True)
        print(f"Reason: {exc}", flush=True)
        if "google" in exc.__class__.__module__.lower() or "gemini" in str(exc).lower():
            print("Gemini error: stopping immediately.", flush=True)
        if ctx["workflow_id"] or ctx["execution_id"]:
            print(
                f"Context: workflow_id={ctx['workflow_id'] or 'n/a'} execution_id={ctx['execution_id'] or 'n/a'}",
                flush=True,
            )
        if ctx["last"]:
            print("\nLast MCP response:\n" + ctx["last"], flush=True)
        return

    print("\nResult", flush=True)
    if ctx["workflow_name"]:
        print(f"Workflow: {GREEN}{ctx['workflow_name']}{RESET}", flush=True)
    final = "" if result is None else str(result["messages"][-1].content).strip()
    if final:
        print(final, flush=True)
    else:
        print("No final agent message returned.", flush=True)
        print(
            f"Context: workflow_id={ctx['workflow_id'] or 'n/a'}, execution_id={ctx['execution_id'] or 'n/a'}, status={ctx['status'] or 'n/a'}, tx_hash={ctx['tx_hash'] or 'n/a'}",
            flush=True,
        )
        if ctx["last"]:
            print("\nFull MCP response:\n" + ctx["last"], flush=True)
        if ctx["error"]:
            print(f"Error: {ctx['error']}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
