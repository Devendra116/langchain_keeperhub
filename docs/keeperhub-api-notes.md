# KeeperHub REST API — Field Reference (locked for implementation)

Source: https://docs.keeperhub.com (fetched 2026-04-25)

## Authentication

Header: `X-API-Key: kh_...` (Direct Execution) or `Authorization: Bearer kh_...` (other endpoints)
Org-scoped keys only (prefix `kh_`).

---

## Direct Execution

### POST /api/execute/transfer

Request:
```json
{
  "network": "ethereum",           // required — chain name string
  "recipientAddress": "0x...",     // required
  "amount": "0.1",                 // required — human-readable units
  "tokenAddress": "0x...",         // optional — omit for native token
  "tokenConfig": "{\"decimals\":18,\"symbol\":\"USDC\"}", // optional JSON string
  "gasLimitMultiplier": "1.2"      // optional
}
```
Response (synchronous):
```json
{ "executionId": "direct_123", "status": "completed" }
```

### POST /api/execute/contract-call

Request:
```json
{
  "contractAddress": "0x...",      // required
  "network": "ethereum",          // required
  "functionName": "balanceOf",    // required
  "functionArgs": "[\"0x...\"]",  // optional — JSON array string
  "abi": "[{...}]",               // optional — auto-fetched if omitted
  "value": "0",                   // optional — wei for payable
  "gasLimitMultiplier": "1.2"     // optional
}
```
Response (read): `{ "result": "1500000000000000000" }`
Response (write): `{ "executionId": "direct_123", "status": "completed" }`

### POST /api/execute/check-and-execute

Request:
```json
{
  "contractAddress": "0x...",
  "network": "ethereum",
  "functionName": "balanceOf",
  "functionArgs": "[\"0x...\"]",
  "abi": "[{...}]",
  "condition": {
    "operator": "gt",             // eq|neq|gt|lt|gte|lte
    "value": "1000000000000000000"
  },
  "action": {
    "contractAddress": "0x...",
    "functionName": "transfer",
    "functionArgs": "[\"0x...\", \"500000000000000000\"]",
    "abi": "[{...}]",
    "gasLimitMultiplier": "1.2"
  }
}
```
Response (not met): `{ "executed": false, "condition": { "met": false, "observedValue": "...", "targetValue": "...", "operator": "gt" } }`
Response (met): `{ "executed": true, "executionId": "direct_123", "status": "completed", "condition": { ... } }`

### GET /api/execute/{executionId}/status

Response:
```json
{
  "executionId": "direct_123",
  "status": "completed",          // pending|running|completed|failed
  "type": "transfer",
  "transactionHash": "0x...",
  "transactionLink": "https://etherscan.io/tx/0x...",
  "gasUsedWei": "21000000000000",
  "result": {},
  "error": null,
  "createdAt": "...",
  "completedAt": "..."
}
```

---

## User

### GET /api/user

Response:
```json
{
  "id": "user_123",
  "name": "John Doe",
  "email": "john@example.com",
  "image": "https://...",
  "isAnonymous": false,
  "providerId": "google",
  "walletAddress": "0x..."
}
```

If `walletAddress` is missing or null, agents should warn the user to
create/connect a KeeperHub wallet or explicitly provide the wallet address they
want to use.

---

## Chains

### GET /api/chains

Query: `?includeDisabled=false` (default)
Response:
```json
{
  "data": [
    {
      "id": "chain_1",
      "chainId": 1,
      "name": "Ethereum Mainnet",
      "symbol": "ETH",
      "chainType": "evm",
      "explorerUrl": "https://etherscan.io",
      "isTestnet": false,
      "isEnabled": true
    }
  ]
}
```

### GET /api/chains/{chainId}/abi?address={contractAddress}

Response:
```json
{
  "abi": [
    {
      "type": "function",
      "name": "balanceOf",
      "inputs": [{"name": "account", "type": "address"}],
      "outputs": [{"name": "", "type": "uint256"}]
    }
  ]
}
```

Alternative: `GET /api/web3/fetch-abi?address={address}&chainId={chainId}`

---

## Error shape

```json
{
  "error": "Missing required field",
  "field": "network",
  "details": "network is required and must be a non-empty string"
}
```

HTTP codes: 401 (auth), 400 (params), 422 (wallet not configured / spending cap), 429 (rate limit + Retry-After header), 500 (server)

Rate limit: 60 req/min per API key (Direct Execution).

---

## KeeperHub MCP server — catalog snapshot

Source: <https://docs.keeperhub.com/ai-tools/mcp-server> (snapshot 2026-04-27)

The MCP server is the *cold path* surface that the SDK bridges via
`langchain_keeperhub.mcp.KeeperHubMCPLoader` (consumed by
`KeeperHubToolkit(workflows=True)`).

### Endpoint

- URL: `https://app.keeperhub.com/mcp`
- Transport: `streamable_http` (modern MCP HTTP transport with SSE
  fallback). Pass `transport="http"` to the loader if KeeperHub
  re-advertises the older string.
- Auth: `Authorization: Bearer kh_...` — **the same org-scoped API key**
  used by the Direct Execution REST endpoints. No OAuth flow is
  involved.
- Single MCP server (logical name `keeperhub`). The SDK always wires it
  through `MultiServerMCPClient` for a uniform connection map.

### Tool catalog (high-level groups)

The server exposes ~20 tools. Names below are the **server-side** names
(no `keeperhub_` prefix). The toolkit applies the prefix and renames
collisions before agents ever see them — see the README's
"Workflow management" section for the rename policy.

| Group | Representative tools | Purpose |
|---|---|---|
| Workflow CRUD | `list_workflows`, `get_workflow`, `create_workflow`, `update_workflow`, `delete_workflow` | Manage workflow definitions in the org. |
| Workflow runs | `execute_workflow`, `get_execution_status`*, `list_executions` | Start and track workflow runs. |
| AI generation | `ai_generate_workflow` | Turn a natural-language prompt into a workflow graph. |
| Plugins | `list_plugins`, `get_plugin`, `validate_plugin_config` | Browse / validate plugin configs available to the org. |
| Templates | `list_templates`, `get_template` | Browse template gallery. |
| Integrations | `list_integrations`, `get_integration` | Browse third-party integrations enabled for the org. |
| Action schemas | `get_action_schema` | Introspect input/output shape of an action node. |
| Meta | `tools_documentation` | Returns docs for the other MCP tools. **Excluded by default** in `KeeperHubMCPLoader` because it burns prompt tokens. |

\* `get_execution_status` collides with the native
`get_execution_status` (which polls direct REST executions),
so the toolkit renames the MCP version to
`workflow_get_execution_status`. Always confirm against the
upstream docs before assuming a tool is present — the catalog evolves
with the platform and this snapshot is exactly that, a snapshot.

### Why we don't mirror these in Python

Re-implementing workflow CRUD / `ai_generate_workflow` /
`validate_plugin_config` natively would mean tracking every server-side
schema bump in lock-step with KeeperHub. The MCP server already exposes
them as a versioned, server-validated surface; bridging it via
`langchain-mcp-adapters` keeps the SDK thin and the maintenance cost
near zero.

### Known limits / open questions

- The exact tool list and argument schemas are governed by the live
  server response (`tools/list`). Treat the table above as orientation,
  not as a contract.
- Rate limits for MCP traffic are enforced server-side and may differ
  from the 60 req/min Direct Execution budget.
- `langchain-mcp-adapters` 0.2.x is the floor we target in
  `pyproject.toml`'s `[workflows]` extra; bumping the upper bound is a
  follow-up if their `MultiServerMCPClient` surface renames.
