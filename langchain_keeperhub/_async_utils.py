"""Helpers for bridging sync LangChain tool calls to async client methods."""

from __future__ import annotations

import asyncio
from typing import Any, Coroutine, TypeVar

T = TypeVar("T")


def run_sync(coro: Coroutine[Any, Any, T]) -> T:
    """Run an async coroutine from a synchronous context.

    LangGraph executes ``BaseTool._run`` in a worker thread that has no
    event loop attached. ``asyncio.get_event_loop()`` no longer auto-creates
    one there on Python 3.10+, so we use ``asyncio.run`` instead. If a loop
    is already running we fail loudly: callers should await ``_arun``.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    raise RuntimeError(
        "run_sync() called from inside a running event loop; "
        "use the tool's async _arun() coroutine instead."
    )
