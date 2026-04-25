"""CheckAndExecuteTool — conditional read-then-write in one call."""

from __future__ import annotations

import json
from typing import Any, Type

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

from langchain_keeperhub._async_utils import run_sync
from langchain_keeperhub.client import KeeperHubClient


class ConditionInput(BaseModel):
    """Condition to evaluate against the read result."""

    operator: str = Field(
        description='Comparison operator: "eq", "neq", "gt", "lt", "gte", or "lte".'
    )
    value: str = Field(
        description="Target value to compare the read result against."
    )


class ActionInput(BaseModel):
    """Write action to execute when the condition is met."""

    contract_address: str = Field(alias="contractAddress")
    function_name: str = Field(alias="functionName")
    function_args: str | None = Field(default=None, alias="functionArgs")
    abi: str | None = None
    gas_limit_multiplier: str | None = Field(
        default=None, alias="gasLimitMultiplier"
    )

    model_config = {"populate_by_name": True}


class CheckAndExecuteInput(BaseModel):
    """Input schema for CheckAndExecuteTool."""

    contract_address: str = Field(
        description="Contract address to read from (0x-prefixed)."
    )
    network: str = Field(
        description='Blockchain network name or chain ID (e.g. "ethereum").'
    )
    function_name: str = Field(
        description="Contract function to read for the condition check."
    )
    function_args: str | None = Field(
        default=None,
        description="JSON array string of read function arguments.",
    )
    abi: str | None = Field(
        default=None,
        description="Contract ABI as JSON string (auto-fetched if omitted).",
    )
    condition: ConditionInput = Field(
        description="Condition to evaluate against the read result."
    )
    action: ActionInput = Field(
        description="Write action to execute when condition is met."
    )


class CheckAndExecuteTool(BaseTool):
    """Read a contract value, evaluate a condition, and execute a write if met.

    Combines a read + conditional write in a single atomic API call.
    Returns whether the condition was met and, if executed, an
    ``execution_id`` to poll.
    """

    name: str = "keeperhub_check_and_execute"
    description: str = (
        "Read a smart contract value, check it against a condition "
        "(eq/neq/gt/lt/gte/lte), and execute a write action only if the "
        "condition is met. Returns condition result and execution_id if triggered."
    )
    args_schema: Type[BaseModel] = CheckAndExecuteInput
    client: KeeperHubClient = Field(exclude=True)

    model_config = {"arbitrary_types_allowed": True}

    def _run(self, **kwargs: Any) -> str:
        return run_sync(self._arun(**kwargs))

    async def _arun(self, **kwargs: Any) -> str:
        condition = kwargs["condition"]
        if isinstance(condition, ConditionInput):
            condition = condition.model_dump()

        action = kwargs["action"]
        if isinstance(action, ActionInput):
            action = action.model_dump(by_alias=True, exclude_none=True)

        result = await self.client.check_and_execute(
            contract_address=kwargs["contract_address"],
            network=kwargs["network"],
            function_name=kwargs["function_name"],
            function_args=kwargs.get("function_args"),
            abi=kwargs.get("abi"),
            condition=condition,
            action=action,
        )
        return json.dumps(result)
