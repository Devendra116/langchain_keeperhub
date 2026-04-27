"""Async HTTP client wrapping the KeeperHub REST API.

Every public method corresponds 1:1 to a documented endpoint.
See docs/keeperhub-api-notes.md for the locked field reference.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Collection
from typing import Any

import httpx

from langchain_keeperhub._exceptions import (
    KeeperHubError,
    RateLimitError,
    raise_for_status,
)
from langchain_keeperhub.history._models import (
    ExecutionKind,
    ExecutionRecord,
    normalize_status,
    utc_now_iso,
)
from langchain_keeperhub.history._store import ExecutionStore

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


def _chains_payload_to_rows(payload: Any) -> list[Any]:
    """Normalize GET /api/chains JSON: ``{data: [...]}`` or a top-level array."""
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        data = payload.get("data")
        if isinstance(data, list):
            return data
    return []


class KeeperHubClient:
    """Thin async wrapper around KeeperHub's REST API.

    Args:
        api_key: Organisation-scoped API key (``kh_`` prefix).
            Falls back to the ``KEEPERHUB_API_KEY`` env var.
        base_url: API root. Defaults to ``https://app.keeperhub.com``.
        timeout: Per-request timeout in seconds.
        testnet_only: When true, write endpoints reject chains not marked as
            testnets by KeeperHub.
        allowed_chain_ids: Optional allowlist of chain IDs for write endpoints.
            When set, writes to all other chains are rejected.
        history: Optional :class:`ExecutionStore` to persist write executions.
            Pass ``True`` to use the default :class:`SqliteExecutionStore` at
            ``~/.keeperhub/executions.db``. Defaults to ``None`` (no
            persistence). Status polls also flow into the store as
            ``update_status`` calls when a row exists for the execution id.
    """

    def __init__(
        self,
        api_key: str | None = None,
        *,
        base_url: str | None = None,
        timeout: float = _DEFAULT_TIMEOUT,
        testnet_only: bool = False,
        allowed_chain_ids: Collection[int | str] | None = None,
        history: ExecutionStore | bool | None = None,
    ) -> None:
        resolved_key = api_key or os.environ.get("KEEPERHUB_API_KEY", "")
        if not resolved_key:
            raise ValueError(
                "api_key is required. Pass it directly or set KEEPERHUB_API_KEY."
            )
        self._api_key = resolved_key
        self._base_url = (base_url or _DEFAULT_BASE_URL).rstrip("/")
        self._timeout = timeout
        self._testnet_only = testnet_only
        self._allowed_chain_ids = (
            {str(chain_id).strip() for chain_id in allowed_chain_ids}
            if allowed_chain_ids is not None
            else None
        )
        if self._allowed_chain_ids is not None and "" in self._allowed_chain_ids:
            raise ValueError("allowed_chain_ids cannot contain empty values.")
        self._http: httpx.AsyncClient | None = None
        self._http_loop_id: int | None = None
        self._network_alias_to_chain_id: dict[str, str] | None = None
        self._chain_id_is_testnet: dict[str, bool | None] | None = None
        self._history: ExecutionStore | None = self._resolve_history(history)

    @staticmethod
    def _resolve_history(
        history: ExecutionStore | bool | None,
    ) -> ExecutionStore | None:
        if history is None or history is False:
            return None
        if history is True:
            # Lazy import so the SDK never touches sqlite3 unless asked.
            from langchain_keeperhub.history.sqlite import SqliteExecutionStore

            return SqliteExecutionStore()
        return history

    @property
    def history(self) -> ExecutionStore | None:
        """Optional execution-history store; ``None`` when persistence is off."""
        return self._history

    # -- lifecycle ------------------------------------------------------------

    async def _get_http(self) -> httpx.AsyncClient:
        # httpx.AsyncClient binds its connection pool to the running loop on
        # first use. Sync tool calls go through asyncio.run() which spins up a
        # fresh loop each time, so we must re-create the client whenever the
        # active loop differs from the one the cached client was bound to.
        old_http = self._http
        loop_id = id(asyncio.get_running_loop())
        if (
            self._http is None
            or self._http.is_closed
            or self._http_loop_id != loop_id
        ):
            if (
                old_http is not None
                and not old_http.is_closed
                and self._http_loop_id != loop_id
            ):
                try:
                    await old_http.aclose()
                except RuntimeError as exc:
                    # Tool calls may run on short-lived loops via asyncio.run().
                    # If the previous loop is already closed, best-effort close.
                    if "Event loop is closed" not in str(exc):
                        raise
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
        if self._history is not None:
            try:
                await self._history.aclose()
            except Exception as exc:  # noqa: BLE001 - best-effort cleanup
                logger.warning("history.aclose failed: %s", exc)

    async def __aenter__(self) -> "KeeperHubClient":
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        await self.aclose()

    async def _resolve_network(self, network: str) -> str:
        """Resolve network aliases (name/id) to a canonical chain ID string."""
        raw = str(network).strip()
        if not raw:
            raise ValueError("network is required.")

        if self._network_alias_to_chain_id is None:
            chains = await self.list_chains(include_disabled=True)
            data = _chains_payload_to_rows(chains)
            alias_map: dict[str, str] = {}
            testnet_map: dict[str, bool | None] = {}
            for item in data:
                if not isinstance(item, dict):
                    continue
                chain_id = item.get("chainId")
                if chain_id is None:
                    continue
                chain_id_str = str(chain_id)
                aliases = {
                    chain_id_str.lower(),
                    str(item.get("id", "")).strip().lower(),
                    str(item.get("name", "")).strip().lower(),
                }
                aliases.discard("")
                for alias in aliases:
                    alias_map.setdefault(alias, chain_id_str)
                is_testnet = item.get("isTestnet")
                testnet_map[chain_id_str] = (
                    bool(is_testnet) if is_testnet is not None else None
                )
            self._network_alias_to_chain_id = alias_map
            self._chain_id_is_testnet = testnet_map

        resolved = self._network_alias_to_chain_id.get(raw.lower())
        if resolved is not None:
            return resolved

        valid = sorted(self._network_alias_to_chain_id.keys())
        sample = ", ".join(valid[:10])
        suffix = ", ..." if len(valid) > 10 else ""
        raise ValueError(
            f"Unsupported network '{network}'. "
            f"Use one of: {sample}{suffix}"
        )

    async def _resolve_write_network(self, network: str) -> str:
        """Resolve write target chain and enforce optional testnet-only mode."""
        chain_id = await self._resolve_network(network)
        if (
            self._allowed_chain_ids is not None
            and chain_id not in self._allowed_chain_ids
        ):
            allowed = ", ".join(sorted(self._allowed_chain_ids))
            raise ValueError(
                f"Unsupported write network '{network}' "
                f"(resolved chain ID: {chain_id}). "
                f"Allowed chain IDs: {allowed}"
            )
        if not self._testnet_only:
            return chain_id

        is_testnet = (self._chain_id_is_testnet or {}).get(chain_id)
        if is_testnet is None:
            raise ValueError(
                f"Cannot determine testnet status for network '{network}' "
                f"(resolved chain ID: {chain_id})."
            )
        if not is_testnet:
            raise ValueError(
                f"testnet_only is enabled; refusing write to non-testnet "
                f"network '{network}' (chain ID: {chain_id})."
            )
        return chain_id

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
        http = await self._get_http()
        last_exc: Exception | None = None
        normalized_method = method.upper()
        allow_retries = normalized_method == "GET"
        max_attempts = _MAX_RETRIES if allow_retries else 1

        logger.debug(
            "%s %s payload=%s params=%s",
            method, path, _redact(json), params,
        )

        for attempt in range(max_attempts):
            try:
                resp = await http.request(
                    method, path, json=json, params=params
                )
            except httpx.HTTPError as exc:
                last_exc = exc
                if attempt < max_attempts - 1:
                    wait = _RETRY_BACKOFF * (attempt + 1)
                    logger.warning(
                        "%s %s network error (attempt %d/%d): %s — retrying in %.1fs",
                        method, path, attempt + 1, max_attempts, exc, wait,
                    )
                    await asyncio.sleep(wait)
                    continue
                break

            if resp.status_code == 429:
                retry_after = float(
                    resp.headers.get("Retry-After", _RETRY_BACKOFF * (attempt + 1))
                )
                if allow_retries and attempt < max_attempts - 1:
                    logger.warning(
                        "%s %s rate limited (attempt %d/%d) — retrying in %.1fs",
                        method, path, attempt + 1, max_attempts, retry_after,
                    )
                    await asyncio.sleep(retry_after)
                    continue
                body = resp.json() if resp.content else {}
                logger.error(
                    "%s %s rate limited%s: %s",
                    method,
                    path,
                    f" after {max_attempts} attempts" if allow_retries else "",
                    body,
                )
                raise RateLimitError(
                    "Rate limit exceeded"
                    + (" after retries" if allow_retries else ""),
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
            "%s %s failed after %d network attempt%s: %s",
            method,
            path,
            max_attempts,
            "s" if max_attempts > 1 else "",
            last_exc,
        )
        raise KeeperHubError(
            f"Request failed after {max_attempts} network attempt"
            f"{'s' if max_attempts > 1 else ''}: {last_exc}"
        )

    # -- history plumbing ----------------------------------------------------

    async def _persist_write(
        self,
        *,
        kind: ExecutionKind,
        chain_id: str,
        request: dict[str, Any],
        response: dict[str, Any],
    ) -> None:
        """Record a write execution if (and only if) we have a store + execId.

        Failures of the store are intentionally swallowed: history must never
        be the reason a successful transaction looks like a failure.
        """
        if self._history is None:
            return
        execution_id = response.get("executionId") if isinstance(response, dict) else None
        if not execution_id:
            return
        now = utc_now_iso()
        record = ExecutionRecord(
            execution_id=str(execution_id),
            kind=kind,
            network=str(chain_id),
            status=normalize_status(
                response.get("status") if isinstance(response, dict) else None
            ),
            request=_redact(request) or {},
            response=dict(response),
            transaction_hash=response.get("transactionHash"),
            transaction_link=response.get("transactionLink"),
            gas_used_wei=response.get("gasUsedWei"),
            error=response.get("error"),
            created_at=now,
            updated_at=now,
        )
        try:
            await self._history.record(record)
        except Exception as exc:  # noqa: BLE001 - best-effort persistence
            logger.warning(
                "history.record failed for execution %s: %s",
                execution_id, exc,
            )

    async def _persist_status_update(
        self, execution_id: str, response: dict[str, Any]
    ) -> None:
        """Refresh the matching history row from a status-poll response."""
        if self._history is None or not execution_id:
            return
        try:
            await self._history.update_status(
                execution_id,
                status=normalize_status(response.get("status")),
                transaction_hash=response.get("transactionHash"),
                transaction_link=response.get("transactionLink"),
                gas_used_wei=response.get("gasUsedWei"),
                error=response.get("error"),
            )
        except Exception as exc:  # noqa: BLE001 - best-effort persistence
            logger.warning(
                "history.update_status failed for execution %s: %s",
                execution_id, exc,
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
        chain_id = await self._resolve_write_network(network)
        payload: dict[str, Any] = {
            "network": chain_id,
            "recipientAddress": recipient_address,
            "amount": amount,
        }
        if token_address is not None:
            payload["tokenAddress"] = token_address
        if token_config is not None:
            payload["tokenConfig"] = token_config
        if gas_limit_multiplier is not None:
            payload["gasLimitMultiplier"] = gas_limit_multiplier
        response = await self._request(
            "POST", "/api/execute/transfer", json=payload
        )
        await self._persist_write(
            kind=ExecutionKind.TRANSFER,
            chain_id=chain_id,
            request=payload,
            response=response,
        )
        return response

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
        chain_id = await self._resolve_write_network(network)
        payload: dict[str, Any] = {
            "contractAddress": contract_address,
            "network": chain_id,
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
        response = await self._request(
            "POST", "/api/execute/contract-call", json=payload
        )
        # Reads return {"result": ...}; only writes carry an executionId. We
        # rely on _persist_write to no-op when executionId is missing.
        await self._persist_write(
            kind=ExecutionKind.CONTRACT_CALL,
            chain_id=chain_id,
            request=payload,
            response=response,
        )
        return response

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
        chain_id = await self._resolve_write_network(network)
        payload: dict[str, Any] = {
            "contractAddress": contract_address,
            "network": chain_id,
            "functionName": function_name,
            "condition": condition,
            "action": action,
        }
        if function_args is not None:
            payload["functionArgs"] = function_args
        if abi is not None:
            payload["abi"] = abi
        response = await self._request(
            "POST", "/api/execute/check-and-execute", json=payload
        )
        # Records only when the action actually fired (executed=true and the
        # response carries an executionId); _persist_write enforces the latter.
        if isinstance(response, dict) and response.get("executed") is True:
            await self._persist_write(
                kind=ExecutionKind.CHECK_AND_EXECUTE,
                chain_id=chain_id,
                request=payload,
                response=response,
            )
        return response

    async def get_execution_status(
        self, execution_id: str
    ) -> dict[str, Any]:
        """GET /api/execute/{executionId}/status"""
        response = await self._request(
            "GET", f"/api/execute/{execution_id}/status"
        )
        await self._persist_status_update(execution_id, response)
        return response

    # -- User endpoints -------------------------------------------------------

    async def get_user(self) -> dict[str, Any]:
        """GET /api/user — fetch the authenticated KeeperHub user profile."""
        return await self._request("GET", "/api/user")

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
