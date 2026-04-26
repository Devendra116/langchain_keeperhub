"""Tests for sync/async bridging helpers."""

from __future__ import annotations

import asyncio

import pytest

from langchain_keeperhub._async_utils import run_sync


async def _value() -> int:
    return 7


async def _raises() -> int:
    raise ValueError("boom")


def test_run_sync_without_running_loop() -> None:
    assert run_sync(_value()) == 7


@pytest.mark.asyncio
async def test_run_sync_inside_running_loop() -> None:
    assert run_sync(_value()) == 7


@pytest.mark.asyncio
async def test_run_sync_inside_running_loop_propagates_error() -> None:
    with pytest.raises(ValueError, match="boom"):
        run_sync(_raises())
