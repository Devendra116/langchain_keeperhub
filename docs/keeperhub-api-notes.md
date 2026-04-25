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
