"""ListExecutionsTool — query the local KeeperHub execution-history store."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from langchain_keeperhub.history._models import ExecutionKind
from langchain_keeperhub.tools._base import _KeeperHubToolBase


class ListExecutionsInput(BaseModel):
    """Input schema for ListExecutionsTool."""

    status: Literal["pending", "running", "completed", "failed"] | None = Field(
        default=None,
        description=(
            "Filter by execution status. "
            'Use "pending" or "running" to find unsettled transactions, '
            '"completed" to confirm a tx settled, "failed" to surface errors.'
        ),
    )
    kind: Literal["transfer", "contract_call", "check_and_execute"] | None = Field(
        default=None,
        description=(
            "Filter by operation kind. "
            '"transfer" for token sends, "contract_call" for contract writes, '
            '"check_and_execute" for conditional writes.'
        ),
    )
    network: str | None = Field(
        default=None,
        description=(
            "Filter by canonical chain ID string (e.g. \"1\", \"8453\"). "
            "Use the same chain ID returned by `list_chains`."
        ),
    )
    since: str | None = Field(
        default=None,
        description=(
            "ISO-8601 UTC timestamp; only rows created at or after this time "
            "are returned (e.g. \"2026-04-27T00:00:00+00:00\")."
        ),
    )
    limit: int = Field(
        default=20,
        ge=1,
        le=100,
        description="Max number of rows to return (1-100, newest first).",
    )


class ListExecutionsTool(_KeeperHubToolBase):
    """Look up past KeeperHub write operations from local history.

    Reads from the client's :class:`ExecutionStore`. Use to answer
    "what did I just do?", confirm an earlier transfer, find pending
    transactions to resume polling, or avoid issuing a duplicate write.
    Only available when the client/toolkit was created with ``history=...``.
    """

    name: str = "list_execution_history"
    description: str = (
        "Returns recent write executions (transfers, contract writes, "
        "check-and-execute). Filter by status, kind, network, since (ISO-8601), "
        "and limit. Use this BEFORE issuing a write to check whether the same "
        "operation already happened, AFTER a write to find the execution_id for "
        "`get_execution_status`, or when the user asks about past "
        "activity. Newest first. Read-only and does not consume gas."
    )
    args_schema: type[BaseModel] = ListExecutionsInput

    async def _arun(self, **kwargs: Any) -> dict[str, Any]:
        store = self.client.history
        if store is None:
            return {
                "executions": [],
                "warning": (
                    "Execution history is disabled. Re-create KeeperHubClient "
                    "or KeeperHubToolkit with history=True (or a custom "
                    "ExecutionStore) to enable persistence."
                ),
            }

        kind_value = kwargs.get("kind")
        kind = ExecutionKind(kind_value) if kind_value else None

        records = await store.list(
            kind=kind,
            status=kwargs.get("status"),
            network=kwargs.get("network"),
            since=kwargs.get("since"),
            limit=int(kwargs.get("limit", 20)),
        )
        return {"executions": [r.to_dict() for r in records]}
