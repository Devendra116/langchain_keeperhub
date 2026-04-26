"""GetExecutionStatusTool — poll execution status by ID."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from langchain_keeperhub.tools._base import _KeeperHubToolBase


class GetExecutionStatusInput(BaseModel):
    """Input schema for GetExecutionStatusTool."""

    execution_id: str = Field(
        description=(
            "Execution ID returned by a previous transfer, contract_call, "
            "or check_and_execute operation."
        )
    )


class GetExecutionStatusTool(_KeeperHubToolBase):
    """Poll the status of a KeeperHub execution.

    Returns status (pending/running/completed/failed), transaction hash,
    gas used, explorer link, and timing information.
    """

    name: str = "keeperhub_get_execution_status"
    description: str = (
        "Check the status of a KeeperHub execution by its execution_id. "
        "Returns status (pending/running/completed/failed), transaction hash, "
        "gas used, block explorer link, and error details if failed. "
        "Use this after transfer or contract_call to confirm completion."
    )
    args_schema: type[BaseModel] = GetExecutionStatusInput

    async def _arun(self, **kwargs: Any) -> dict[str, Any]:
        return await self.client.get_execution_status(kwargs["execution_id"])
