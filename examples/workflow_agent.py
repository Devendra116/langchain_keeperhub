"""KeeperHub workflow demo (compact)."""

from __future__ import annotations
import asyncio
import json
import logging
import os
from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain_openai import ChatOpenAI
from langchain_keeperhub import KeeperHubToolkit

MUTED, GREEN, CYAN, RESET = "\033[90m", "\033[32m", "\033[36m", "\033[0m"
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
SYSTEM_PROMPT = (
    "You are the KeeperHub demo agent. Complete the user’s request using the available capabilities. "
    "Keep responses concise. For any on-chain or workflow action, include proof such as transaction hash, "
    "explorer link, workflow id, execution id, and final status when available."
)
USER_PROMPT = "Build a workflow that transfer 1 0x20c0000000000000000000000000000000000000 token to 0x3E67cc2C7fFf86d9870dB9D02c43e789B52FB296 on chainid: 42431. Run it once and tell me what happened."


def _stringify_tool_output(raw: object) -> str:
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return "<empty>"
        try:
            parsed = json.loads(text)
        except Exception:
            return text
        return json.dumps(parsed, indent=2, ensure_ascii=False)
    if isinstance(raw, (dict, list)):
        return json.dumps(raw, indent=2, ensure_ascii=False)
    if isinstance(raw, tuple):
        return json.dumps(list(raw), indent=2, ensure_ascii=False)
    return str(raw).strip() or "<empty>"


def _apply_tool_payload_to_ctx(ctx: dict[str, str], payload: object) -> None:
    """Fill ctx from a tool JSON object, including nested MCP {type,text} blobs."""
    if isinstance(payload, dict):
        ctx["workflow_id"] = str(payload.get("id") or ctx["workflow_id"])
        ctx["workflow_name"] = str(payload.get("name") or ctx["workflow_name"])
        ctx["execution_id"] = str(
            payload.get("executionId") or ctx["execution_id"]
        )
        ctx["status"] = str(payload.get("status") or ctx["status"])
        ctx["tx_hash"] = str(
            payload.get("transactionHash") or ctx["tx_hash"]
        )
        ctx["tx_link"] = str(
            payload.get("transactionLink") or ctx["tx_link"]
        )
        if payload.get("error"):
            ctx["error"] = str(payload["error"])
        return
    if isinstance(payload, list):
        for item in payload:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                try:
                    inner = json.loads(item["text"])
                except Exception:
                    continue
                _apply_tool_payload_to_ctx(ctx, inner)
            else:
                _apply_tool_payload_to_ctx(ctx, item)


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
        "tx_link": "",
        "error": "",
        "last": "",
    }
    result = None

    try:
        async with KeeperHubToolkit(
            workflows=True,
            testnet_only=True,
            allowed_chain_ids={80002,42431},
            mcp_include=MCP_INCLUDE,
        ) as toolkit:
            tools = await toolkit.aget_tools()
            print(f"\nKeeperHub Workflow Demo | tools={len(tools)}", flush=True)
            for t in tools:
                print(f"  - {t.name}", flush=True)
            agent = create_agent(
                model=ChatOpenAI(
                    model="asi1-mini",
                    api_key=os.environ.get("ASI_ONE_API_KEY", "").strip(),
                    base_url="https://api.asi1.ai/v1",
                    temperature=0,
                    max_retries=0,
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
                                f"\n{MUTED}[TOOL CALL]{RESET} {CYAN}{call.get('name', '<unknown-tool>')}{RESET}",
                                flush=True,
                            )
                    elif msg.type == "tool":
                        name = getattr(msg, "name", "tool")
                        raw = getattr(msg, "content", "")
                        txt = _stringify_tool_output(raw)
                        ctx["last"] = txt
                        print(
                            f"{MUTED}[TOOL RESULT]{RESET} {CYAN}{name}{RESET}",
                            flush=True,
                        )
                        print(txt, flush=True)
                        try:
                            obj = json.loads(txt)
                        except Exception:
                            obj = None
                        if obj is not None:
                            _apply_tool_payload_to_ctx(ctx, obj)
                            if isinstance(obj, dict) and obj.get("name"):
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
                f"Context: workflow_id={ctx['workflow_id'] or 'n/a'} execution_id={ctx['execution_id'] or 'n/a'} tx_link={ctx['tx_link'] or 'n/a'}",
                flush=True,
            )
        if ctx["last"]:
            print("\nLast MCP response:\n" + ctx["last"], flush=True)
        return

    print("\nResult", flush=True)
    if ctx["workflow_name"]:
        print(f"Workflow: {GREEN}{ctx['workflow_name']}{RESET}", flush=True)
    if ctx["tx_link"]:
        print(f"Transaction link: {CYAN}{ctx['tx_link']}{RESET}", flush=True)
    elif ctx["tx_hash"]:
        print(f"Transaction hash: {CYAN}{ctx['tx_hash']}{RESET}", flush=True)
    final = "" if result is None else str(result["messages"][-1].content).strip()
    if final:
        print(final, flush=True)
    else:
        print("No final agent message returned.", flush=True)
        print(
            f"Context: workflow_id={ctx['workflow_id'] or 'n/a'}, execution_id={ctx['execution_id'] or 'n/a'}, status={ctx['status'] or 'n/a'}, tx_hash={ctx['tx_hash'] or 'n/a'}, tx_link={ctx['tx_link'] or 'n/a'}",
            flush=True,
        )
        if ctx["last"]:
            print("\nFull MCP response:\n" + ctx["last"], flush=True)
        if ctx["error"]:
            print(f"Error: {ctx['error']}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
