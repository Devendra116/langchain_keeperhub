# KeeperHub — product feedback

I shared the notes below in the KeeperHub Discord. The team picked them up and **resolved the issues quickly**, which made a big difference while I was building **langchain-keeperhub** on top of the API.

---

## What I suggested, and how it went

### `llms.txt` for KeeperHub

I asked for an **`llms.txt`** (or equivalent) so LLMs and agent tooling can pull in API and product context in a standard way. The team shipped this in a release shortly, great for anyone integrating agents or docs-aware tools.


### `GET /api/chains` data quality

I reported that **`GET /api/chains`** returned **incorrect data** in some cases. The team **fixed it on their side** without a long wait, which restored trust in chain discovery for SDKs and scripts.

### Docs: session vs API key

I mentioned that **docs described both session and API key** auth for APIs, while **many endpoints effectively needed a session token** at the time. The mismatch was fixed and they updated code to support both methods for auth

---

## Suggestions for future

### 1. Simulate workflows against the real world

It would help to **test workflows in a simulation** that still behaves like production (real chain semantics, realistic failures, gas/limits where relevant) without always spending real funds or risking bad state. That would make workflow authoring safer for teams and for agent demos.

### 2. Clearer key model: org vs users

Longer term, it would be useful to have:

- **Organisation-level** keys / wallet context for shared automation, and  
- **User-level** keys where each user **owns** their material,

plus a straightforward way to **create users** and attach **their own** keys or policies. That maps better to multi-tenant products and to agents that act on behalf of specific people, not only one org wallet.

### 3. `ai_generate_workflow`: fix fragile links between nodes

The **`ai_generate_workflow`** tool is useful, but it often needs hardening:

- Sometime **Internal linking breaks** — a workflow is generated, but **edges between steps** (which output feeds which input) are **wrong or incomplete**, so the graph does not run as intended.
- **Prior node outputs are hard to use** — the generator does not always “see” **structured outputs** from earlier nodes. For example, an **ERC-20 balance** step usually returns **JSON with several keys**; the next step may need **one specific field**, but the tool **does not reliably wire** `prior_node.output.someKey` (or the equivalent) into the next node’s parameters.

Improving how the tool **inspects node output schemas**, **surfaces nested keys**, and **validates links** (or asks for a disambiguation) would cut down on broken workflows and manual repair after generation.

