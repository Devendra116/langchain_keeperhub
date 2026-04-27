"""Data model for KeeperHub execution history records."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class ExecutionKind(str, Enum):
    """The KeeperHub write operation that produced an execution row."""

    TRANSFER = "transfer"
    CONTRACT_CALL = "contract_call"
    CHECK_AND_EXECUTE = "check_and_execute"


# Status values normalized to the KeeperHub API contract. We don't enforce this
# as an Enum on the record because the API may grow new states; we keep the
# string but constrain the canonical set the SDK expects to see.
_TERMINAL_STATUSES = frozenset({"completed", "failed"})
_KNOWN_STATUSES = frozenset(
    {"pending", "running", "completed", "failed"}
)


def is_terminal_status(status: str | None) -> bool:
    """True when no further status updates are expected."""
    return (status or "").lower() in _TERMINAL_STATUSES


def normalize_status(status: str | None) -> str:
    """Lowercase and default-fill the status string."""
    raw = (status or "").strip().lower()
    return raw or "pending"


def utc_now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string with seconds precision."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass
class ExecutionRecord:
    """A single persisted KeeperHub write execution.

    All timestamp fields are ISO-8601 UTC strings so downstream stores can
    round-trip them verbatim without timezone-conversion bugs.
    """

    execution_id: str
    kind: ExecutionKind
    network: str
    status: str
    request: dict[str, Any] = field(default_factory=dict)
    response: dict[str, Any] = field(default_factory=dict)
    transaction_hash: str | None = None
    transaction_link: str | None = None
    gas_used_wei: str | None = None
    error: str | None = None
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Plain-dict view, suitable for JSON serialization."""
        return {
            "execution_id": self.execution_id,
            "kind": self.kind.value,
            "network": self.network,
            "status": self.status,
            "request": dict(self.request),
            "response": dict(self.response),
            "transaction_hash": self.transaction_hash,
            "transaction_link": self.transaction_link,
            "gas_used_wei": self.gas_used_wei,
            "error": self.error,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "metadata": dict(self.metadata),
        }


__all__ = [
    "ExecutionKind",
    "ExecutionRecord",
    "is_terminal_status",
    "normalize_status",
    "utc_now_iso",
]
