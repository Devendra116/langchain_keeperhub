"""SqliteExecutionStore — stdlib-only default ExecutionStore.

Single SQLite file, JSON-encoded blob columns for the request/response/metadata
payloads, indexed for the common ``list(...)`` filters. All blocking sqlite3
calls are off-loaded to a worker thread so the asyncio event loop never stalls.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sqlite3
import threading
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from langchain_keeperhub.history._models import (
    ExecutionKind,
    ExecutionRecord,
    normalize_status,
    utc_now_iso,
)

logger = logging.getLogger(__name__)

_DEFAULT_DB_DIR = Path("~/.keeperhub").expanduser()
_DEFAULT_DB_PATH = _DEFAULT_DB_DIR / "executions.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS executions (
    execution_id      TEXT PRIMARY KEY,
    kind              TEXT NOT NULL,
    network           TEXT NOT NULL,
    status            TEXT NOT NULL,
    request           TEXT NOT NULL,
    response          TEXT NOT NULL,
    transaction_hash  TEXT,
    transaction_link  TEXT,
    gas_used_wei      TEXT,
    error             TEXT,
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL,
    metadata          TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_executions_kind_status_created
    ON executions (kind, status, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_executions_network_created
    ON executions (network, created_at DESC);
"""


def _row_to_record(row: sqlite3.Row | tuple[Any, ...]) -> ExecutionRecord:
    """Inflate a stored row back to an ExecutionRecord."""
    if isinstance(row, sqlite3.Row):
        data: dict[str, Any] = dict(row)
    else:
        # Fallback for tuple rows; column order matches _SCHEMA.
        cols = (
            "execution_id", "kind", "network", "status",
            "request", "response", "transaction_hash", "transaction_link",
            "gas_used_wei", "error", "created_at", "updated_at", "metadata",
        )
        data = dict(zip(cols, row))
    return ExecutionRecord(
        execution_id=data["execution_id"],
        kind=ExecutionKind(data["kind"]),
        network=data["network"],
        status=data["status"],
        request=json.loads(data["request"] or "{}"),
        response=json.loads(data["response"] or "{}"),
        transaction_hash=data["transaction_hash"],
        transaction_link=data["transaction_link"],
        gas_used_wei=data["gas_used_wei"],
        error=data["error"],
        created_at=data["created_at"],
        updated_at=data["updated_at"],
        metadata=json.loads(data["metadata"] or "{}"),
    )


class SqliteExecutionStore:
    """Default ExecutionStore — single sqlite3 file, async-friendly.

    Args:
        path: Database file path. Defaults to ``~/.keeperhub/executions.db``.
            The parent directory is created if missing. Pass ``":memory:"``
            for an ephemeral in-process store (useful in tests).
    """

    def __init__(self, path: str | os.PathLike[str] | None = None) -> None:
        if path is None:
            db_path: str = str(_DEFAULT_DB_PATH)
            _DEFAULT_DB_DIR.mkdir(parents=True, exist_ok=True)
        elif str(path) == ":memory:":
            db_path = ":memory:"
        else:
            p = Path(path).expanduser()
            p.parent.mkdir(parents=True, exist_ok=True)
            db_path = str(p)

        self._path = db_path
        # check_same_thread=False because we drive sqlite3 from
        # asyncio.to_thread workers; we serialize access via _lock.
        self._conn = sqlite3.connect(
            db_path, check_same_thread=False, isolation_level=None
        )
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        self._closed = False
        self._init_schema()

    @property
    def path(self) -> str:
        """Filesystem path of the SQLite file (or ``:memory:``)."""
        return self._path

    def _init_schema(self) -> None:
        with self._lock:
            self._conn.executescript(_SCHEMA)
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")

    # -- record ---------------------------------------------------------------

    def _record_sync(self, record: ExecutionRecord) -> None:
        if self._closed:
            raise RuntimeError("SqliteExecutionStore is closed")
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO executions (
                    execution_id, kind, network, status,
                    request, response, transaction_hash, transaction_link,
                    gas_used_wei, error, created_at, updated_at, metadata
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(execution_id) DO UPDATE SET
                    kind             = excluded.kind,
                    network          = excluded.network,
                    status           = excluded.status,
                    request          = excluded.request,
                    response         = excluded.response,
                    transaction_hash = excluded.transaction_hash,
                    transaction_link = excluded.transaction_link,
                    gas_used_wei     = excluded.gas_used_wei,
                    error            = excluded.error,
                    updated_at       = excluded.updated_at,
                    metadata         = excluded.metadata
                """,
                (
                    record.execution_id,
                    record.kind.value,
                    record.network,
                    normalize_status(record.status),
                    json.dumps(record.request, default=str),
                    json.dumps(record.response, default=str),
                    record.transaction_hash,
                    record.transaction_link,
                    record.gas_used_wei,
                    record.error,
                    record.created_at,
                    record.updated_at,
                    json.dumps(record.metadata, default=str),
                ),
            )

    async def record(self, record: ExecutionRecord) -> None:
        await asyncio.to_thread(self._record_sync, record)

    # -- update_status --------------------------------------------------------

    def _update_status_sync(
        self,
        execution_id: str,
        *,
        status: str,
        transaction_hash: str | None,
        transaction_link: str | None,
        gas_used_wei: str | None,
        error: str | None,
    ) -> ExecutionRecord | None:
        if self._closed:
            raise RuntimeError("SqliteExecutionStore is closed")
        with self._lock:
            existing = self._conn.execute(
                "SELECT * FROM executions WHERE execution_id = ?",
                (execution_id,),
            ).fetchone()
            if existing is None:
                return None

            # COALESCE semantics: only overwrite when caller passed something.
            new_hash = transaction_hash if transaction_hash is not None else existing["transaction_hash"]
            new_link = transaction_link if transaction_link is not None else existing["transaction_link"]
            new_gas = gas_used_wei if gas_used_wei is not None else existing["gas_used_wei"]
            new_error = error if error is not None else existing["error"]
            new_updated = utc_now_iso()
            new_status = normalize_status(status)

            self._conn.execute(
                """
                UPDATE executions
                SET status = ?, transaction_hash = ?, transaction_link = ?,
                    gas_used_wei = ?, error = ?, updated_at = ?
                WHERE execution_id = ?
                """,
                (
                    new_status,
                    new_hash,
                    new_link,
                    new_gas,
                    new_error,
                    new_updated,
                    execution_id,
                ),
            )

            row = self._conn.execute(
                "SELECT * FROM executions WHERE execution_id = ?",
                (execution_id,),
            ).fetchone()
        return _row_to_record(row) if row is not None else None

    async def update_status(
        self,
        execution_id: str,
        *,
        status: str,
        transaction_hash: str | None = None,
        transaction_link: str | None = None,
        gas_used_wei: str | None = None,
        error: str | None = None,
    ) -> ExecutionRecord | None:
        return await asyncio.to_thread(
            self._update_status_sync,
            execution_id,
            status=status,
            transaction_hash=transaction_hash,
            transaction_link=transaction_link,
            gas_used_wei=gas_used_wei,
            error=error,
        )

    # -- list / get -----------------------------------------------------------

    def _list_sync(
        self,
        *,
        kind: ExecutionKind | None,
        status: str | None,
        network: str | None,
        since: str | None,
        limit: int,
    ) -> list[ExecutionRecord]:
        if self._closed:
            raise RuntimeError("SqliteExecutionStore is closed")
        clauses: list[str] = []
        params: list[Any] = []
        if kind is not None:
            clauses.append("kind = ?")
            params.append(kind.value)
        if status is not None:
            clauses.append("status = ?")
            params.append(normalize_status(status))
        if network is not None:
            clauses.append("network = ?")
            params.append(str(network))
        if since is not None:
            clauses.append("created_at >= ?")
            params.append(since)

        # Defensive bounds: callers (including LLMs) can pass arbitrary ints.
        bounded_limit = max(1, min(int(limit), 1000))
        params.append(bounded_limit)

        sql = "SELECT * FROM executions"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY created_at DESC LIMIT ?"

        with self._lock:
            rows: Iterable[sqlite3.Row] = self._conn.execute(sql, params).fetchall()
        return [_row_to_record(r) for r in rows]

    async def list(
        self,
        *,
        kind: ExecutionKind | None = None,
        status: str | None = None,
        network: str | None = None,
        since: str | None = None,
        limit: int = 50,
    ) -> list[ExecutionRecord]:
        return await asyncio.to_thread(
            self._list_sync,
            kind=kind,
            status=status,
            network=network,
            since=since,
            limit=limit,
        )

    def _get_sync(self, execution_id: str) -> ExecutionRecord | None:
        if self._closed:
            raise RuntimeError("SqliteExecutionStore is closed")
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM executions WHERE execution_id = ?",
                (execution_id,),
            ).fetchone()
        return _row_to_record(row) if row is not None else None

    async def get(self, execution_id: str) -> ExecutionRecord | None:
        return await asyncio.to_thread(self._get_sync, execution_id)

    # -- lifecycle ------------------------------------------------------------

    def _close_sync(self) -> None:
        with self._lock:
            if self._closed:
                return
            try:
                self._conn.close()
            finally:
                self._closed = True

    async def aclose(self) -> None:
        await asyncio.to_thread(self._close_sync)


__all__ = ["SqliteExecutionStore"]
