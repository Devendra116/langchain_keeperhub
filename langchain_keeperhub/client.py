"""Async HTTP client wrapping the KeeperHub REST API.

Every public method corresponds 1:1 to a documented endpoint.
See docs/keeperhub-api-notes.md for the locked field reference.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

import httpx

from langchain_keeperhub._exceptions import (
    KeeperHubError,
    RateLimitError,
    raise_for_status,
)

_DEFAULT_BASE_URL = "https://app.keeperhub.com"
_DEFAULT_TIMEOUT = 60.0
_MAX_RETRIES = 3
_RETRY_BACKOFF = 1.0  # seconds base

logger = logging.getLogger(__name__)


def _redact(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    """Shrink fields that bloat or leak info before logging."""
    if not payload:
        return payload
    safe = dict(payload)
    abi = safe.get("abi")
    if isinstance(abi, str) and len(abi) > 64:
        safe["abi"] = f"<abi {len(abi)} chars>"
    return safe


class KeeperHubClient:
    """Thin async wrapper around KeeperHub's REST API.

    Args:
        api_key: Organisation-scoped API key (``kh_`` prefix).
            Falls back to the ``KEEPERHUB_API_KEY`` env var.
        base_url: API root. Defaults to ``https://app.keeperhub.com``.
        timeout: Per-request timeout in seconds.
    """

    def __init__(
        self,
        api_key: str | None = None,
        *,
        base_url: str | None = None,
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> None:
        resolved_key = api_key or os.environ.get("KEEPERHUB_API_KEY", "")
        if not resolved_key:
            raise ValueError(
                "api_key is required. Pass it directly or set KEEPERHUB_API_KEY."
            )
        self._api_key = resolved_key
        self._base_url = (base_url or _DEFAULT_BASE_URL).rstrip("/")
        self._timeout = timeout
        self._http: httpx.AsyncClient | None = None
        self._http_loop_id: int | None = None

    # -- lifecycle ------------------------------------------------------------

    def _get_http(self) -> httpx.AsyncClient:
        # httpx.AsyncClient binds its connection pool to the running loop on
        # first use. Sync tool calls go through asyncio.run() which spins up a
        # fresh loop each time, so we must re-create the client whenever the
        # active loop differs from the one the cached client was bound to.
        loop_id = id(asyncio.get_running_loop())
        if (
            self._http is None
            or self._http.is_closed
            or self._http_loop_id != loop_id
        ):
            self._http = httpx.AsyncClient(
                base_url=self._base_url,
                timeout=self._timeout,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "X-API-Key": self._api_key,
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
            )
            self._http_loop_id = loop_id
        return self._http

    async def aclose(self) -> None:
        if self._http and not self._http.is_closed:
            await self._http.aclose()

    # -- internal request plumbing -------------------------------------------

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Send a request, retrying transient failures (network errors, 429)."""
        http = self._get_http()
        last_exc: Exception | None = None

        logger.debug(
            "%s %s payload=%s params=%s",
            method, path, _redact(json), params,
        )

        for attempt in range(_MAX_RETRIES):
            try:
                resp = await http.request(
                    method, path, json=json, params=params
                )
            except httpx.HTTPError as exc:
                last_exc = exc
                wait = _RETRY_BACKOFF * (attempt + 1)
                logger.warning(
                    "%s %s network error (attempt %d/%d): %s — retrying in %.1fs",
                    method, path, attempt + 1, _MAX_RETRIES, exc, wait,
                )
                await asyncio.sleep(wait)
                continue

            if resp.status_code == 429:
                retry_after = float(
                    resp.headers.get("Retry-After", _RETRY_BACKOFF * (attempt + 1))
                )
                if attempt < _MAX_RETRIES - 1:
                    logger.warning(
                        "%s %s rate limited (attempt %d/%d) — retrying in %.1fs",
                        method, path, attempt + 1, _MAX_RETRIES, retry_after,
                    )
                    await asyncio.sleep(retry_after)
                    continue
                body = resp.json() if resp.content else {}
                logger.error(
                    "%s %s gave up after %d 429s: %s",
                    method, path, _MAX_RETRIES, body,
                )
                raise RateLimitError(
                    "Rate limit exceeded after retries",
                    retry_after=retry_after,
                    status_code=429,
                    body=body,
                )

            body = resp.json() if resp.content else {}
            if resp.status_code >= 400:
                # Surface API-side failures so callers (and tool messages) see why.
                logger.warning(
                    "%s %s -> HTTP %d: %s",
                    method, path, resp.status_code, body,
                )
            else:
                logger.debug("%s %s -> HTTP %d", method, path, resp.status_code)
            raise_for_status(resp.status_code, body)
            return body  # type: ignore[return-value]

        logger.error(
            "%s %s failed after %d network retries: %s",
            method, path, _MAX_RETRIES, last_exc,
        )
        raise KeeperHubError(
            f"Request failed after {_MAX_RETRIES} retries: {last_exc}"
        )

    # -- Direct Execution endpoints ------------------------------------------

    async def transfer(
        self,
        *,
        network: str,
        recipient_address: str,
        amount: str,
        token_address: str | None = None,
        token_config: str | None = None,
        gas_limit_multiplier: str | None = None,
    ) -> dict[str, Any]:
        """POST /api/execute/transfer — send native or ERC-20 tokens."""
        payload: dict[str, Any] = {
            "network": network,
            "recipientAddress": recipient_address,
            "amount": amount,
        }
        if token_address is not None:
            payload["tokenAddress"] = token_address
        if token_config is not None:
            payload["tokenConfig"] = token_config
        if gas_limit_multiplier is not None:
            payload["gasLimitMultiplier"] = gas_limit_multiplier
        return await self._request("POST", "/api/execute/transfer", json=payload)

    async def contract_call(
        self,
        *,
        contract_address: str,
        network: str,
        function_name: str,
        function_args: str | None = None,
        abi: str | None = None,
        value: str | None = None,
        gas_limit_multiplier: str | None = None,
    ) -> dict[str, Any]:
        """POST /api/execute/contract-call — read or write a smart contract."""
        payload: dict[str, Any] = {
            "contractAddress": contract_address,
            "network": network,
            "functionName": function_name,
        }
        if function_args is not None:
            payload["functionArgs"] = function_args
        if abi is not None:
            payload["abi"] = abi
        if value is not None:
            payload["value"] = value
        if gas_limit_multiplier is not None:
            payload["gasLimitMultiplier"] = gas_limit_multiplier
        return await self._request(
            "POST", "/api/execute/contract-call", json=payload
        )

    async def check_and_execute(
        self,
        *,
        contract_address: str,
        network: str,
        function_name: str,
        function_args: str | None = None,
        abi: str | None = None,
        condition: dict[str, str],
        action: dict[str, Any],
    ) -> dict[str, Any]:
        """POST /api/execute/check-and-execute — conditional execution."""
        payload: dict[str, Any] = {
            "contractAddress": contract_address,
            "network": network,
            "functionName": function_name,
            "condition": condition,
            "action": action,
        }
        if function_args is not None:
            payload["functionArgs"] = function_args
        if abi is not None:
            payload["abi"] = abi
        return await self._request(
            "POST", "/api/execute/check-and-execute", json=payload
        )

    async def get_execution_status(
        self, execution_id: str
    ) -> dict[str, Any]:
        """GET /api/execute/{executionId}/status"""
        return await self._request(
            "GET", f"/api/execute/{execution_id}/status"
        )

    # -- Chains endpoints ----------------------------------------------------

    async def list_chains(
        self, *, include_disabled: bool = False
    ) -> dict[str, Any]:
        """GET /api/chains"""
        params: dict[str, Any] = {}
        if include_disabled:
            params["includeDisabled"] = "true"
        return await self._request("GET", "/api/chains", params=params or None)

    async def fetch_abi(
        self, *, chain_id: int | str, address: str
    ) -> dict[str, Any]:
        """GET /api/chains/{chainId}/abi?address=..."""
        return await self._request(
            "GET",
            f"/api/chains/{chain_id}/abi",
            params={"address": address},
        )
