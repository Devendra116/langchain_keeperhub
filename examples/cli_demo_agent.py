"""Interactive KeeperHub CLI demo agent with real-time tool streaming.

Run:
    python examples/cli_demo_agent.py

Optional:
    python examples/cli_demo_agent.py --once "transfer 1 USDC on chain 42431 ..."

The CLI prints a demo restriction banner (chains 80002 and 42431, limited tokens).
Use ``/tokens`` to show it again. Import ``resolve_demo_token`` if you need the
same mappings from another script.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
from typing import Any

from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain.agents.middleware import ToolRetryMiddleware
from langchain_keeperhub import KeeperHubToolkit, SqliteExecutionStore
from langchain_openai import ChatOpenAI

MUTED, GREEN, CYAN, RED, RESET = (
    "\033[90m",
    "\033[32m",
    "\033[36m",
    "\033[31m",
    "\033[0m",
)

# Demo scope: must match KeeperHubToolkit(..., allowed_chain_ids=...) below.
DEMO_ALLOWED_CHAIN_IDS: frozenset[int] = frozenset({80002, 42431})
DEMO_CHAIN_NAMES: dict[int, str] = {
    80002: "Polygon Amoy (testnet)",
    42431: "Tempo testnet",
}
# chain_id -> SYMBOL -> contract (0x + lowercase hex)
DEMO_TOKEN_REGISTRY: dict[int, dict[str, str]] = {
    80002: {"USDC": "0x41e94eb019c0762f9bfcf9fb1e58725bfb0e7582"},
    42431: {
        "PathUSD": "0x20c0000000000000000000000000000000000000",
    },
}


def _normalize_hex_address(addr: str) -> str:
    a = addr.strip()
    if not a.startswith("0x"):
        a = "0x" + a[2:] if a.startswith("0X") else "0x" + a
    return "0x" + a[2:].lower()


def _allowed_raw_addresses_for_chain(chain_id: int) -> frozenset[str]:
    return frozenset(DEMO_TOKEN_REGISTRY.get(chain_id, {}).values())


def resolve_demo_token(chain_id: int | str, query: str) -> str | None:
    """Resolve a symbol or an allowlisted 0x address for a demo chain.

    Returns a normalized ``0x`` + 40 hex (lowercase) contract address, or
    ``None`` if the chain is not in the demo set or the token is unknown.
    """
    cid = int(str(chain_id).strip())
    if cid not in DEMO_ALLOWED_CHAIN_IDS:
        return None
    q = query.strip()
    if not q:
        return None
    allowed_raw = _allowed_raw_addresses_for_chain(cid)
    if q.startswith(("0x", "0X")) and len(q) == 42:
        hx = _normalize_hex_address(q)
        return hx if hx in allowed_raw else None
    sym = q.upper()
    return DEMO_TOKEN_REGISTRY.get(cid, {}).get(sym)


def print_demo_scope_banner() -> None:
    print(f"{MUTED}Demo Agent to execute onchain actions in secure and auditable KeeperHub environment with ENS resolution functionality...{RESET}\n", flush=True)

def supported_tokens() -> list[str]:
    """Print which chains and tokens this CLI build is limited to."""
    print("Tokens supported by this demo agent:", flush=True)
    for cid in sorted(DEMO_ALLOWED_CHAIN_IDS):
        reg = DEMO_TOKEN_REGISTRY.get(cid, {})
        if not reg:
            continue
        print(f"    {CYAN}{cid}{RESET}:", flush=True)
        for sym, addr in sorted(reg.items()):
            print(f"      {sym} -> {addr}", flush=True)

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


def _demo_token_rules_for_prompt() -> str:
    cids = ", ".join(str(x) for x in sorted(DEMO_ALLOWED_CHAIN_IDS))
    lines = [
        f"Demo/network bounds: only chain IDs {cids} are in scope for this session.",
        "Resolve user token nicknames to these contracts before building workflows or transfers:",
    ]
    for cid in sorted(DEMO_ALLOWED_CHAIN_IDS):
        label = DEMO_CHAIN_NAMES.get(cid, str(cid))
        lines.append(f"- {cid} ({label}):")
        for sym, addr in sorted(DEMO_TOKEN_REGISTRY.get(cid, {}).items()):
            lines.append(f"  - {sym} -> {addr}")
    lines.append("Native: omit token_address. Unlisted tokens: not supported in this demo.")
    return "\n".join(lines)


SYSTEM_PROMPT = (
    "You are a KeeperHub Web3 execution agent. Your role is to understand user intent "
    "and use the available tools to perform real on-chain actions or workflows.\n\n"

    "GENERAL RULES:\n"
    "- Use only the provided tools and strictly follow their schemas.\n"
    "- Do not guess parameters—derive them from user input or prior tool responses.\n"
    "- Prefer execution over explanation when user intent is clear.\n"
    "- If the request is unclear or unsafe, ask a concise clarification.\n\n"

    "EXECUTION DECISION FLOW:\n"
    "- For direct actions (e.g., transfer, contract call): execute using the correct tool.\n"
    "- For workflows:\n"
    "  1. Create or generate the workflow.\n"
    "  2. Call get_workflow (or equivalent) to fetch full definition.\n"
    "  3. Infer required arguments from the workflow payload.\n"
    "  4. Execute the workflow.\n"
    "  5. Poll execution status using workflow_get_execution_status until terminal.\n"
    "- Before executing, optionally check execution history to avoid duplicates.\n\n"

    "OUTPUT RULES:\n"
    "- Always return a concise, structured response.\n"
    "- If response includes transactions, workflows, or executions:\n"
    "  • Show transaction hash(es).\n"
    "  • Show explorer URL(s) if available.\n"
    "  • Show workflow_id and execution_id if present.\n"
    "  • If multiple items exist, display them as a list.\n"
    "- Clearly indicate status (pending, success, failed).\n\n"

    "BEHAVIOR:\n"
    "- Be deterministic, reliable, and execution-focused.\n"
    "- Do not mention internal tool names unless necessary.\n"
    "- Avoid unnecessary explanations—prioritize actionable results.\n\n"

    + _demo_token_rules_for_prompt()
)


def _stringify_tool_output(raw: object) -> str:
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return "<empty>"
        try:
            return json.dumps(json.loads(text), indent=2, ensure_ascii=False)
        except Exception:
            return text
    if isinstance(raw, (dict, list, tuple)):
        value = list(raw) if isinstance(raw, tuple) else raw
        return json.dumps(value, indent=2, ensure_ascii=False)
    return str(raw).strip() or "<empty>"


def _tool_message_succeeded(msg: Any) -> bool:
    """Best-effort success vs failure for a tool result message."""
    if getattr(msg, "status", None) == "error":
        return False
    raw = getattr(msg, "content", "")
    txt = _stringify_tool_output(raw)
    try:
        parsed = json.loads(txt)
    except Exception:
        parsed = None
    if isinstance(parsed, dict) and parsed.get("error"):
        return False
    if isinstance(parsed, list):
        for item in parsed:
            if isinstance(item, dict) and item.get("type") == "text" and isinstance(item.get("text"), str):
                try:
                    inner = json.loads(item["text"])
                except Exception:
                    continue
                if isinstance(inner, dict) and inner.get("error"):
                    return False
    low = txt.lower()
    if "tool exception" in low or "mcp error" in low or "error -326" in low:
        return False
    return True


def _text_from_message_content(content: object) -> str:
    """Turn AIMessage.content (str or provider block list) into plain text for the console."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                btype = block.get("type")
                if btype == "text" and isinstance(block.get("text"), str):
                    parts.append(block["text"])
                elif isinstance(block.get("text"), str):
                    parts.append(block["text"])
        return "\n".join(parts).strip()
    return str(content).strip()


def _pretty_if_json(text: str) -> str:
    """If the whole string is JSON, pretty-print for readability."""
    t = text.strip()
    if not t or t[0] not in "{[":
        return text
    try:
        obj = json.loads(t)
    except Exception:
        return text
    if isinstance(obj, (dict, list)):
        return json.dumps(obj, indent=2, ensure_ascii=False)
    return text


def _last_ai_text(messages: list[Any]) -> str:
    """Last non-empty text from an AIMessage (skips trailing ToolMessages etc.)."""
    for msg in reversed(messages):
        if getattr(msg, "type", None) != "ai":
            continue
        raw = _text_from_message_content(getattr(msg, "content", ""))
        if raw:
            return _pretty_if_json(raw)
    return ""


async def _run_turn(agent: Any, user_text: str) -> None:
    payload = {"messages": [("system", SYSTEM_PROMPT), ("user", user_text)]}
    seen = 0
    result = None
    run_error: str | None = None

    try:
        async for state in agent.astream(
            payload, config={"recursion_limit": 40}, stream_mode="values"
        ):
            result = state
            msgs = state.get("messages", [])
            for msg in msgs[seen:]:
                if msg.type == "ai":
                    for call in getattr(msg, "tool_calls", None) or []:
                        print(
                            f"{MUTED}[TOOL CALL]{RESET} {CYAN}{call.get('name', '<unknown-tool>')}{RESET}",
                            flush=True,
                        )
                elif msg.type == "tool":
                    name = getattr(msg, "name", "tool")
                    ok = _tool_message_succeeded(msg)
                    status_bit = f"{GREEN}succeeded{RESET}" if ok else f"{RED}failed{RESET}"
                    print(
                        f"{MUTED}[TOOL RESULT]{RESET} {CYAN}{name}{RESET} — {status_bit}",
                        flush=True,
                    )
            seen = len(msgs)
    except Exception as e:
        run_error = str(e)
        print(f"{MUTED}[RUN ERROR]{RESET} {RED}{e}{RESET}", flush=True)

    print(f"{GREEN}Assistant{RESET}", flush=True)
    final = ""
    if result and result.get("messages"):
        final = _last_ai_text(result["messages"])
    if run_error:
        note = f"(Model call failed: {run_error})"
        final = f"{final}\n\n{note}" if final else note
    print(final or "No final assistant message returned.", flush=True)


async def amain() -> None:
    parser = argparse.ArgumentParser(description="KeeperHub interactive CLI demo agent")
    parser.add_argument(
        "--once",
        type=str,
        default="",
        help="Run a single request and exit.",
    )
    args = parser.parse_args()

    load_dotenv()
    logging.basicConfig(level=logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.CRITICAL)

    asi_key = os.environ.get("ASI_ONE_API_KEY", "").strip()
    if not asi_key:
        raise ValueError("Set ASI_ONE_API_KEY in your environment or .env file.")

    print_demo_scope_banner()

    async with KeeperHubToolkit(
        workflows=True,
        history=SqliteExecutionStore("./ledger_demo.db"),
        testnet_only=True,
        allowed_chain_ids=DEMO_ALLOWED_CHAIN_IDS,
        mcp_include=MCP_INCLUDE,
    ) as toolkit:
        tools = await toolkit.aget_tools()
        print(f"KeeperHub CLI Demo Agent | tools={len(tools)}", flush=True)
        print(f"{MUTED}Available commands: /help /tokens /tools /exit{RESET}", flush=True)

        agent = create_agent(
            model=ChatOpenAI(
                model="asi1-mini",
                api_key=asi_key,
                base_url="https://api.asi1.ai/v1",
                temperature=0,
                max_retries=0,
            ),
            tools=tools,
            middleware=[ToolRetryMiddleware(max_retries=0, on_failure="continue")],
        )

        if args.once:
            print(f"{MUTED}Request:{RESET} {args.once}", flush=True)
            await _run_turn(agent, args.once)
            return

        while True:
            try:
                user_text = input(f"{CYAN}you>{RESET} ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nExiting.", flush=True)
                return

            if not user_text:
                continue
            if user_text in {"/exit", "exit", "quit", "/quit"}:
                print("Exiting.", flush=True)
                return
            if user_text in {"/help", "help"}:
                print("Commands: /help, /tools, /tokens, /exit", flush=True)
                continue
            if user_text == "/tokens":
                supported_tokens()
                continue
            if user_text == "/tools":
                for t in tools:
                    print(f"  - {t.name}", flush=True)
                continue

            await _run_turn(agent, user_text)


if __name__ == "__main__":
    asyncio.run(amain())
