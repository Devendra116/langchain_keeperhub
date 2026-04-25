"""GetExecutionStatusTool — poll execution status by ID."""

from __future__ import annotations

import asyncio
import json
from typing import Any, Type

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

from langchain_keeperhub.client import KeeperHubClient


class GetExecutionStatusInput(BaseModel):
    """Input schema for GetExecutionStatusTool."""

    execution_id: str = Field(
        description=(
            "Execution ID returned by a previous transfer, contract_call, "
            "or check_and_execute operation."
        )
    )


class GetExecutionStatusTool(BaseTool):
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
    args_schema: Type[BaseModel] = GetExecutionStatusInput
    client: KeeperHubClient = Field(exclude=True)

    model_config = {"arbitrary_types_allowed": True}

    def _run(self, **kwargs: Any) -> str:
        return asyncio.get_event_loop().run_until_complete(self._arun(**kwargs))

    async def _arun(self, **kwargs: Any) -> str:
        result = await self.client.get_execution_status(kwargs["execution_id"])
        return json.dumps(result)
