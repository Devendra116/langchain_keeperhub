"""ExecutionStore protocol — the swappable backend interface for history."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from langchain_keeperhub.history._models import ExecutionKind, ExecutionRecord


@runtime_checkable
class ExecutionStore(Protocol):
    """Persistent log of KeeperHub write executions.

    Any class implementing these async methods can be passed as
    ``KeeperHubClient(history=...)``. The default implementation is
    :class:`langchain_keeperhub.history.SqliteExecutionStore`.

    The contract is intentionally narrow:

    * ``record`` is invoked once per write, as soon as the API returns an
      ``executionId``. Implementations should be idempotent on
      ``execution_id`` (treat a second ``record`` for the same id as a
      no-op or upsert).
    * ``update_status`` is invoked every time ``get_execution_status`` is
      called for a known id. It must be a no-op when the id is unknown
      (returns ``None``) — never raise.
    * ``list`` and ``get`` are read APIs for both Python users and the
      ``list_execution_history`` agent tool.
    * ``aclose`` releases any resources the store holds. It must be safe
      to call multiple times.
    """

    async def record(self, record: ExecutionRecord) -> None:
        ...

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
        ...

    async def list(
        self,
        *,
        kind: ExecutionKind | None = None,
        status: str | None = None,
        network: str | None = None,
        since: str | None = None,
        limit: int = 50,
    ) -> list[ExecutionRecord]:
        ...

    async def get(self, execution_id: str) -> ExecutionRecord | None:
        ...

    async def aclose(self) -> None:
        ...


__all__ = ["ExecutionStore"]
