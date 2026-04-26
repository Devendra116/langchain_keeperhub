"""Typed exceptions mapped from KeeperHub HTTP error responses."""

from __future__ import annotations

from typing import Any


class KeeperHubError(Exception):
    """Base exception for all KeeperHub API errors."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        body: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.body = body or {}


class AuthenticationError(KeeperHubError):
    """401 — invalid or missing API key."""


class ValidationError(KeeperHubError):
    """400 — invalid request parameters."""


class WalletNotConfiguredError(KeeperHubError):
    """422 — wallet not set up or spending cap exceeded."""


class SpendingCapExceededError(KeeperHubError):
    """422 with error code SPENDING_CAP_EXCEEDED."""


class RateLimitError(KeeperHubError):
    """429 — rate limit exceeded."""

    def __init__(
        self,
        message: str,
        *,
        retry_after: float | None = None,
        status_code: int | None = 429,
        body: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, status_code=status_code, body=body)
        self.retry_after = retry_after


class NotFoundError(KeeperHubError):
    """404 — resource not found."""


class ServerError(KeeperHubError):
    """5xx — KeeperHub server error."""


_STATUS_MAP: dict[int, type[KeeperHubError]] = {
    401: AuthenticationError,
    404: NotFoundError,
}


def raise_for_status(status_code: int, body: Any) -> None:
    """Raise the appropriate typed exception for a non-2xx response."""
    if 200 <= status_code < 300:
        return

    if not isinstance(body, dict):
        body = {}

    error_msg = body.get("error", body.get("message", "Unknown error"))
    details = body.get("details", "")
    if details:
        error_msg = f"{error_msg}: {details}"

    if status_code == 422:
        error_code = body.get("code", "")
        if error_code == "SPENDING_CAP_EXCEEDED":
            raise SpendingCapExceededError(
                error_msg, status_code=status_code, body=body
            )
        raise WalletNotConfiguredError(
            error_msg, status_code=status_code, body=body
        )

    if status_code == 429:
        raise RateLimitError(
            error_msg,
            retry_after=None,  # caller sets from header
            status_code=status_code,
            body=body,
        )

    exc_cls = _STATUS_MAP.get(status_code)
    if exc_cls is not None:
        raise exc_cls(error_msg, status_code=status_code, body=body)

    if status_code >= 500:
        raise ServerError(error_msg, status_code=status_code, body=body)

    raise KeeperHubError(error_msg, status_code=status_code, body=body)
