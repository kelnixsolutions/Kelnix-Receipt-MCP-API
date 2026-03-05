# Receipt → Accounting Entry MCP Server

A production-ready, agent-native MCP server that converts receipt images and PDFs into structured, accounting-ready JSON. Built for the agentic era where AI agents autonomously handle expense management, accounts payable, and bookkeeping workflows.

---

## Why This Product Exists in 2026

The agent economy is here. AI agents are autonomously purchasing SaaS tools, managing procurement, and handling expense workflows on behalf of companies. But there's a critical gap:

- **Receipts are everywhere, structure is nowhere.** Every purchase generates a receipt -- a messy image or PDF that needs to become a clean accounting entry. This happens millions of times per day.
- **Agents can't read receipts natively.** Even vision-capable agents need specialized extraction logic, few-shot prompting, and structured output enforcement to reliably parse receipts into GL-ready data.
- **No clean, atomic, MCP-native tools exist** for this workflow. Existing OCR services are human-first, require dashboards, and don't speak MCP.

This server fills that gap: a single `/mcp` endpoint that any agent can discover, understand, and call to turn receipts into accounting entries.

**Product-market fit signal:** Every agent doing expense management needs this. It's high-frequency, high-pain, and high-value.

---

## Target Customers

| Customer Type | Use Case |
|---|---|
| **AI expense agents** | Auto-categorise and book employee receipts |
| **AP automation agents** | Extract vendor invoice data for payment processing |
| **Bookkeeping agents** | Convert paper receipts to journal entries |
| **Procurement agents** | Verify purchase receipts against POs |
| **Multi-agent systems** | Composable receipt tool in LangGraph / CrewAI pipelines |
| **Fintech platforms** | Embed receipt parsing into expense apps |

The primary interface is **API-first** -- there is no human dashboard. Agents are the users.

---

## Agent-Native Design Principles

This server was built agent-first, following these principles:

1. **API = primary interface.** No login screen, no dashboard, no human UI. The `/mcp` endpoint is how agents discover and use the service.
2. **Atomic, composable tools.** Each tool does one thing well (`upload_receipt`, `process_receipt`, `get_receipt_markdown`, `suggest_gl_account`). Agents compose them as needed.
3. **Rich LLM-friendly metadata.** The `/mcp` endpoint returns full JSON schemas, natural-language descriptions, input/output examples, and constraint metadata -- everything an LLM needs to call tools correctly on the first try.
4. **Structured, predictable output.** Every response follows a strict Pydantic schema with confidence scores, so downstream agents can make programmatic decisions.
5. **Programmatic monetization.** Credit-based billing designed for agent-to-agent payment (no checkout pages).

---

## Architecture

```
Agent / Multi-Agent System
         │
         ▼
    GET /mcp  ──────────►  Tool catalogue (JSON)
         │                  - names, schemas, examples
         ▼
    POST /tools/*  ────►  FastAPI endpoints
         │                  │
         ├── upload_receipt ─► Local storage + SQLite
         ├── process_receipt ─► Claude Sonnet 4.6 Vision API
         ├── get_receipt_markdown ─► Cached render
         └── suggest_gl_account ─► Claude reasoning
                                    │
                                    ▼
                              Structured JSON response
```

### Tech Stack

| Component | Choice | Why |
|---|---|---|
| Framework | FastAPI + uvicorn | Async, fast, auto-docs at `/docs` |
| Vision AI | Claude Sonnet 4.6 via Anthropic SDK | Best accuracy/latency/price for receipts (~$0.01-0.05/call) |
| Database | SQLite | Zero-config, perfect for MVP, easy to swap for Postgres |
| Storage | Local disk (`uploads/`) | Simple for MVP, swap to S3 later |
| Validation | Pydantic v2 | Strict schemas, fast serialization |
| Auth | API key (X-API-Key header) | Simple, stateless, agent-friendly |

---

## Quickstart for Agents

### 1. Discover available tools

```bash
curl https://your-server.com/mcp
```

Returns a JSON array describing all tools, their parameters, examples, and constraints.

### 2. Register (get an API key)

For MVP, set the `API_KEYS` env var on the server. In production, this would be a self-service registration endpoint.

```bash
export API_KEYS="agent-key-abc123,agent-key-def456"
```

### 3. Upload a receipt

```bash
curl -X POST https://your-server.com/tools/upload_receipt \
  -H "X-API-Key: agent-key-abc123" \
  -F "file=@receipt.jpg" \
  -F "mime_type=image/jpeg"
```

Response:
```json
{"receipt_id": "a1b2c3d4e5f67890"}
```

Or upload via URL:
```bash
curl -X POST https://your-server.com/tools/upload_receipt \
  -H "X-API-Key: agent-key-abc123" \
  -F "url=https://example.com/receipt.jpg" \
  -F "mime_type=image/jpeg"
```

### 4. Process the receipt

```bash
curl -X POST https://your-server.com/tools/process_receipt \
  -H "X-API-Key: agent-key-abc123" \
  -H "Content-Type: application/json" \
  -d '{
    "receipt_id": "a1b2c3d4e5f67890",
    "options": {"preferred_currency": "USD"}
  }'
```

Response:
```json
{
  "receipt_id": "a1b2c3d4e5f67890",
  "structured_expense": {
    "merchant": "Starbucks #12345",
    "date": "2026-03-01",
    "total_amount": 7.45,
    "currency": "USD",
    "line_items": [
      {"description": "Grande Latte", "amount": 5.95},
      {"description": "Blueberry Muffin", "amount": 1.50}
    ],
    "taxes": [{"type": "Sales Tax", "amount": 0.53}],
    "category_guess": "meals",
    "confidence_scores": {
      "merchant": 0.98, "date": 0.95, "total_amount": 0.99,
      "currency": 0.99, "line_items": 0.90, "taxes": 0.92,
      "category_guess": 0.95
    },
    "reasoning": "Standard coffee shop receipt. Tax line clearly separated."
  }
}
```

### 5. Get Markdown view

```bash
curl -X POST https://your-server.com/tools/get_receipt_markdown \
  -H "X-API-Key: agent-key-abc123" \
  -H "Content-Type: application/json" \
  -d '{"receipt_id": "a1b2c3d4e5f67890"}'
```

### 6. Suggest GL account

```bash
curl -X POST https://your-server.com/tools/suggest_gl_account \
  -H "X-API-Key: agent-key-abc123" \
  -H "Content-Type: application/json" \
  -d '{
    "expense_json": { ... },
    "chart_of_accounts_snippet": "6100 Office Supplies\n6200 Meals\n6300 Travel"
  }'
```

Response:
```json
{
  "account_code": "6200",
  "account_name": "Meals",
  "confidence": 0.95,
  "reasoning": "Coffee and food items clearly map to Meals account."
}
```

---

## MCP Endpoint Details

`GET /mcp` returns a JSON array where each tool includes:

| Field | Description |
|---|---|
| `name` | Tool identifier (e.g. `process_receipt`) |
| `description` | Natural-language description optimized for LLM understanding |
| `parameters` | Full JSON Schema with types, enums, defaults, and descriptions |
| `examples` | 1-2 complete input/output pairs |
| `constraints` | Rate limits, auth requirements, cost, latency expectations |

This is the primary discovery and consumption point for agents. An agent can read `/mcp`, understand all available capabilities, and start calling tools immediately.

---

## Backend Choice Rationale (March 2026)

### Recommended: Claude Sonnet 4.6 Vision API

| Metric | Value |
|---|---|
| Accuracy | 90-97% across receipt types |
| Latency | 2-10 seconds per receipt |
| Cost | ~$0.01-0.05 per call |
| Upfront cost | $0 |
| Setup time | Minutes |

**Why start here:** Zero upfront hardware cost means you generate revenue before spending. Best-in-class accuracy for structured extraction from receipts. The Anthropic SDK handles retries, streaming, and rate limiting.

### Alternative: Fully Local with Ollama

| Metric | Value |
|---|---|
| Models | Qwen2.5-VL-72B or Llama 3.2 Vision 90B (quantized) |
| Accuracy | 80-92% |
| Latency | 8-60 seconds per receipt |
| Upfront cost | $2,000-3,000 (RTX 4090 + PC) |
| Ongoing cost | ~$30-60/mo electricity |
| Privacy | 100% on-premises, zero data leaves your infra |

**When to switch:** Once profitable and processing volume justifies the fixed cost. Local is ideal for regulated industries (healthcare, legal, government) where receipt data cannot leave the network.

---

## Monetization Path

### Phase 1: Free tier (current)
- 50 free `process_receipt` calls per month per API key
- Unlimited `upload_receipt`, `get_receipt_markdown`, `suggest_gl_account`

### Phase 2: Stripe credit-based billing
- 1 credit per `process_receipt` call
- Credit packs: 100 credits / $5, 1000 / $40, 10000 / $300
- Agents purchase credits via API (no checkout page)
- Usage tracking per API key

### Phase 3: Crypto payments
- Accept stablecoin payments (USDC, USDT)
- Fiat-equivalent lock at quote time (agent requests quote → gets price locked for 5 min → pays)
- Agents pay autonomously without human approval workflows

---

## Discovery Strategy for Agents

1. **Public `/mcp` endpoint** -- Any agent can discover tools by hitting a single URL
2. **MCP registries** -- Submit to Composio, StackOne, Arcade.dev tool directories
3. **Agent framework quickstarts** -- Ready-made examples for LangGraph and CrewAI
4. **GitHub visibility** -- Open-source server code, star-friendly README
5. **Social proof** -- Tweet demo + MCP link with #AgentNative #MCPTools
6. **API docs** -- Auto-generated Swagger UI at `/docs` for human developers

---

## Project Status

| Phase | Status | Description |
|---|---|---|
| Phase 1 | **Active** | Core tools + Claude Sonnet 4.6 vision + MCP endpoint |
| Phase 2 | Planned | Stripe credits, usage metering, agent webhooks |
| Phase 3 | Planned | Crypto payments with fiat-lock quoting |

---

## Setup

### Prerequisites

- Python 3.11+
- An Anthropic API key ([console.anthropic.com](https://console.anthropic.com))

### Install & Run

```bash
git clone https://github.com/TiagoX9/Receipt-Accounting-Entry-MCP-Server.git
cd Receipt-Accounting-Entry-MCP-Server

pip install -r requirements.txt

export ANTHROPIC_API_KEY=sk-ant-...
export API_KEYS=your-agent-key-here   # optional, defaults to "dev-key-change-me"

uvicorn app:app --reload
```

The server starts at `http://localhost:8000`.

- **MCP tools:** `http://localhost:8000/mcp`
- **Swagger docs:** `http://localhost:8000/docs`
- **Health check:** `http://localhost:8000/health`

### Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `ANTHROPIC_API_KEY` | Yes | -- | Your Anthropic API key |
| `API_KEYS` | No | `dev-key-change-me` | Comma-separated list of valid API keys |

---

## File Structure

```
├── app.py              # FastAPI application, routes, auth
├── models.py           # Pydantic request/response schemas
├── db.py               # SQLite helpers (init, CRUD)
├── tools.py            # Core tool logic + MCP descriptor generator
├── requirements.txt    # Python dependencies
├── .gitignore
└── README.md
```

---

## License

MIT
