"""Tests for the execution-history models and SqliteExecutionStore."""

from __future__ import annotations

from pathlib import Path

import pytest

from langchain_keeperhub.history import (
    ExecutionKind,
    ExecutionRecord,
    SqliteExecutionStore,
    is_terminal_status,
    normalize_status,
    utc_now_iso,
)


def _make_record(
    execution_id: str,
    *,
    kind: ExecutionKind = ExecutionKind.TRANSFER,
    network: str = "1",
    status: str = "pending",
    created_at: str | None = None,
) -> ExecutionRecord:
    now = created_at or utc_now_iso()
    return ExecutionRecord(
        execution_id=execution_id,
        kind=kind,
        network=network,
        status=status,
        request={"recipientAddress": "0xabc", "amount": "1"},
        response={"executionId": execution_id, "status": status},
        created_at=now,
        updated_at=now,
        metadata={"agent": "tests"},
    )


# -- model helpers -----------------------------------------------------------


def test_normalize_status_lowercases_and_defaults_pending():
    assert normalize_status("Completed") == "completed"
    assert normalize_status(None) == "pending"
    assert normalize_status("   ") == "pending"


def test_is_terminal_status_only_completed_and_failed():
    assert is_terminal_status("completed")
    assert is_terminal_status("FAILED")
    assert not is_terminal_status("running")
    assert not is_terminal_status(None)


def test_execution_record_to_dict_round_trip():
    record = _make_record("ex_1")
    payload = record.to_dict()
    assert payload["execution_id"] == "ex_1"
    assert payload["kind"] == "transfer"
    assert payload["status"] == "pending"
    assert payload["request"]["amount"] == "1"
    assert payload["metadata"] == {"agent": "tests"}


# -- SqliteExecutionStore ----------------------------------------------------


@pytest.fixture
async def store(tmp_path: Path):
    store = SqliteExecutionStore(tmp_path / "exec.db")
    try:
        yield store
    finally:
        await store.aclose()


@pytest.mark.asyncio
async def test_record_then_get_round_trips_payload(store: SqliteExecutionStore):
    record = _make_record("ex_1")
    await store.record(record)

    fetched = await store.get("ex_1")
    assert fetched is not None
    assert fetched.execution_id == "ex_1"
    assert fetched.kind == ExecutionKind.TRANSFER
    assert fetched.network == "1"
    assert fetched.status == "pending"
    assert fetched.request == {"recipientAddress": "0xabc", "amount": "1"}
    assert fetched.response == {"executionId": "ex_1", "status": "pending"}
    assert fetched.metadata == {"agent": "tests"}


@pytest.mark.asyncio
async def test_record_is_idempotent_on_execution_id(store: SqliteExecutionStore):
    await store.record(_make_record("ex_dup", status="pending"))
    await store.record(_make_record("ex_dup", status="running"))

    rows = await store.list()
    assert len(rows) == 1
    assert rows[0].status == "running"


@pytest.mark.asyncio
async def test_update_status_overwrites_status_and_tx_metadata(
    store: SqliteExecutionStore,
):
    await store.record(_make_record("ex_1"))

    updated = await store.update_status(
        "ex_1",
        status="completed",
        transaction_hash="0xdead",
        transaction_link="https://example.com/tx/0xdead",
        gas_used_wei="21000",
    )
    assert updated is not None
    assert updated.status == "completed"
    assert updated.transaction_hash == "0xdead"
    assert updated.transaction_link == "https://example.com/tx/0xdead"
    assert updated.gas_used_wei == "21000"


@pytest.mark.asyncio
async def test_update_status_is_a_noop_for_unknown_id(
    store: SqliteExecutionStore,
):
    result = await store.update_status("never-seen", status="completed")
    assert result is None


@pytest.mark.asyncio
async def test_update_status_preserves_existing_fields_when_args_omitted(
    store: SqliteExecutionStore,
):
    record = _make_record("ex_keep")
    record.transaction_hash = "0xprev"
    record.gas_used_wei = "12345"
    await store.record(record)

    updated = await store.update_status("ex_keep", status="running")
    assert updated is not None
    assert updated.status == "running"
    assert updated.transaction_hash == "0xprev"
    assert updated.gas_used_wei == "12345"


@pytest.mark.asyncio
async def test_list_filters_by_kind_status_and_network(
    store: SqliteExecutionStore,
):
    await store.record(
        _make_record("ex_t1", kind=ExecutionKind.TRANSFER, network="1")
    )
    await store.record(
        _make_record(
            "ex_t2",
            kind=ExecutionKind.TRANSFER,
            network="8453",
            status="completed",
        )
    )
    await store.record(
        _make_record(
            "ex_c1",
            kind=ExecutionKind.CONTRACT_CALL,
            network="1",
            status="failed",
        )
    )

    only_transfers = await store.list(kind=ExecutionKind.TRANSFER)
    assert {r.execution_id for r in only_transfers} == {"ex_t1", "ex_t2"}

    on_base = await store.list(network="8453")
    assert [r.execution_id for r in on_base] == ["ex_t2"]

    failed = await store.list(status="failed")
    assert [r.execution_id for r in failed] == ["ex_c1"]


@pytest.mark.asyncio
async def test_list_orders_newest_first_and_respects_limit(
    store: SqliteExecutionStore,
):
    # Spaced timestamps so ordering is deterministic regardless of clock.
    await store.record(_make_record("ex_old", created_at="2026-04-01T00:00:00+00:00"))
    await store.record(_make_record("ex_mid", created_at="2026-04-15T00:00:00+00:00"))
    await store.record(_make_record("ex_new", created_at="2026-04-27T00:00:00+00:00"))

    rows = await store.list(limit=2)
    assert [r.execution_id for r in rows] == ["ex_new", "ex_mid"]


@pytest.mark.asyncio
async def test_list_filters_by_since(store: SqliteExecutionStore):
    await store.record(_make_record("ex_old", created_at="2026-04-01T00:00:00+00:00"))
    await store.record(_make_record("ex_new", created_at="2026-04-26T00:00:00+00:00"))

    recent = await store.list(since="2026-04-15T00:00:00+00:00")
    assert [r.execution_id for r in recent] == ["ex_new"]


@pytest.mark.asyncio
async def test_list_clamps_extreme_limit_values(store: SqliteExecutionStore):
    await store.record(_make_record("ex_1"))
    # Negative or zero limits should still return at least the requested rows
    # without raising.
    rows = await store.list(limit=0)
    assert len(rows) == 1
    rows = await store.list(limit=-5)
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_separate_stores_are_isolated(tmp_path: Path):
    a = SqliteExecutionStore(tmp_path / "a.db")
    b = SqliteExecutionStore(tmp_path / "b.db")
    try:
        await a.record(_make_record("ex_in_a"))
        assert await b.list() == []
        rows = await a.list()
        assert [r.execution_id for r in rows] == ["ex_in_a"]
    finally:
        await a.aclose()
        await b.aclose()


@pytest.mark.asyncio
async def test_in_memory_store_is_supported():
    store = SqliteExecutionStore(":memory:")
    try:
        await store.record(_make_record("ex_mem"))
        assert (await store.get("ex_mem")) is not None
        assert store.path == ":memory:"
    finally:
        await store.aclose()


@pytest.mark.asyncio
async def test_aclose_is_idempotent_and_blocks_further_writes(tmp_path: Path):
    store = SqliteExecutionStore(tmp_path / "c.db")
    await store.aclose()
    await store.aclose()  # second close must not raise
    with pytest.raises(RuntimeError, match="closed"):
        await store.record(_make_record("ex_after_close"))


@pytest.mark.asyncio
async def test_default_path_under_user_home(monkeypatch, tmp_path: Path):
    # Redirect ~ to tmp_path so we don't pollute the developer's machine.
    monkeypatch.setenv("HOME", str(tmp_path))
    # Reload the module path constants to pick up the new HOME.
    from importlib import reload

    import langchain_keeperhub.history.sqlite as sqlite_mod

    reload(sqlite_mod)
    store = sqlite_mod.SqliteExecutionStore()
    try:
        assert store.path.endswith("/.keeperhub/executions.db")
        assert (tmp_path / ".keeperhub").is_dir()
    finally:
        await store.aclose()
