# Receipt → Accounting Entry MCP Server

A production-ready, agent-native MCP server that converts receipt images and PDFs into structured, accounting-ready JSON. Built for the agentic era where AI agents autonomously handle expense management, accounts payable, and bookkeeping workflows.

**Version 3.1.0** -- credit-based billing via Stripe + crypto payments (300+ coins via NOWPayments), self-service agent registration, webhook notifications, async processing via Celery, idempotency support, and framework quickstarts for LangGraph / CrewAI / AutoGen.

---

## Table of Contents

- [Why This Product Exists in 2026](#why-this-product-exists-in-2026)
- [Target Customers](#target-customers)
- [Agent-Native Design Principles](#agent-native-design-principles)
- [Architecture](#architecture)
  - [Tech Stack](#tech-stack)
- [Quickstart for Agents](#quickstart-for-agents)
  - [1. Discover available tools](#1-discover-available-tools)
  - [2. Register (self-service)](#2-register-self-service)
  - [3. Check your balance](#3-check-your-balance)
  - [4. Upload a receipt](#4-upload-a-receipt)
  - [5. Process the receipt (1 credit)](#5-process-the-receipt-1-credit)
  - [6. Upload + process in one call](#6-upload--process-in-one-call)
  - [7. List your receipts](#7-list-your-receipts)
  - [8. Buy more credits](#8-buy-more-credits)
  - [9. Or subscribe monthly](#9-or-subscribe-monthly)
  - [10. Set up webhook alerts](#10-set-up-webhook-alerts)
- [Monetization](#monetization)
  - [Credit System](#credit-system)
  - [Credit Packs](#credit-packs-one-time-purchase-via-stripe-checkout)
  - [Subscription Plans](#subscription-plans)
  - [How billing works](#how-billing-works)
  - [Crypto Payments](#crypto-payments)
- [Async Processing (Celery + Redis)](#async-processing-celery--redis)
- [Webhook Events](#webhook-events)
- [Framework Integration Quickstarts](#framework-integration-quickstarts)
- [MCP Endpoint Details](#mcp-endpoint-details)
- [Backend Choice Rationale](#backend-choice-rationale-march-2026)
  - [Claude Sonnet 4.6 Vision API](#recommended-claude-sonnet-46-vision-api)
  - [Fully Local with Ollama](#alternative-fully-local-with-ollama)
- [How Agents Find This Tool](#how-agents-find-this-tool)
  - [1. MCP Protocol (stdio)](#1-mcp-protocol-stdio--claude-desktop-cursor-vs-code)
  - [2. Well-Known Discovery](#2-well-known-discovery)
  - [3. MCP Registries](#3-mcp-registries-smithery-composio-glama)
  - [4. HTTP Discovery](#4-http-discovery-endpoint)
  - [5. Framework Integrations](#5-framework-integrations)
- [Project Status](#project-status)
- [Setup](#setup)
  - [Prerequisites](#prerequisites)
  - [Install & Run](#install--run)
  - [Environment Variables](#environment-variables)
- [File Structure](#file-structure)
- [Marketing Strategy](#marketing-strategy)
- [Launch Checklist](#launch-checklist)
- [License](#license)

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
2. **Atomic, composable tools.** Each tool does one thing well. Agents compose them as needed -- or use `upload_and_process` for a single-call shortcut.
3. **Rich LLM-friendly metadata.** The `/mcp` endpoint returns full JSON schemas, natural-language descriptions, input/output examples, and constraint metadata -- everything an LLM needs to call tools correctly on the first try.
4. **Structured, predictable output.** Every response follows a strict Pydantic schema with confidence scores, so downstream agents can make programmatic decisions.
5. **Programmatic monetization.** Credit-based billing + Stripe Checkout + crypto payments -- agents buy credits via API, no human checkout pages required.
6. **Self-service registration.** `POST /register_agent` returns an API key + 50 free credits instantly. No approval flow.
7. **Safe retries.** Idempotency keys on `upload_and_process` prevent duplicate charges. Request IDs on every response for tracing.

---

## Architecture

```
Agent / Multi-Agent System
         |
         v
    GET /mcp  ─────────►  Tool catalogue (8 tools + metadata)
         |
    POST /register_agent ─► API key + 50 free credits + Stripe customer
         |
         v
    POST /tools/*  ────►  FastAPI endpoints
         |                  |
         |── upload_receipt ──► Local storage + SQLite
         |── process_receipt ──► Credit check → Claude Sonnet 4.6 Vision
         |── upload_and_process ──► Combined (1 call, idempotent)
         |── process_receipt_async → Celery + Redis → Claude Vision
         |── get_receipt_markdown ──► Cached render
         |── suggest_gl_account ──► Credit check → Claude reasoning
         |── list_receipts ──► Paginated receipt history
         └── check_balance ──► Current credits + plan
                                    |
    POST /billing/*  ──────►  Stripe integration
         |── buy_credits ──► Stripe Checkout session
         |── subscribe ──► Monthly plan (basic/pro)
         |── webhook ──► Stripe events → credit updates
         └── balance ──► Credits + history

    POST /billing/buy_credits_crypto ──► NOWPayments → any crypto
         |── check_payment_status ──► Poll or IPN webhook
         └── crypto_webhook ──► IPN confirmed → grant credits

    POST /subscribe_webhook ──► Low balance & processing alerts
    GET  /integrations ──► LangGraph / CrewAI / AutoGen snippets
```

### Tech Stack

| Component | Choice | Why |
|---|---|---|
| Framework | FastAPI + uvicorn | Async, fast, auto-docs at `/docs` |
| Vision AI | Claude Sonnet 4.6 via Anthropic SDK | Best accuracy/latency/price for receipts |
| Database | SQLite (WAL mode, connection pool) | Zero-config, thread-safe, indexed |
| Storage | Local disk (`uploads/`) | Simple for MVP, swap to S3 later |
| Validation | Pydantic v2 | Strict schemas, fast serialization |
| Auth | API key (X-API-Key header) + TTL cache | Stateless, agent-friendly, fast |
| Billing | Stripe (Checkout + Webhooks) | Programmatic credit purchases |
| Crypto | NOWPayments (300+ coins) | Any-crypto payments with fiat-lock |
| Task queue | Celery + Redis | Async receipt processing |
| File I/O | aiofiles | Non-blocking uploads |

---

## Quickstart for Agents

### 1. Discover available tools

```bash
curl https://your-server.com/mcp
```

Returns a JSON array describing all 8 tools, their parameters, examples, costs, and constraints.

### 2. Register (self-service)

```bash
curl -X POST https://your-server.com/register_agent \
  -H "Content-Type: application/json" \
  -d '{"agent_name": "expense-bot-v1", "org_id": "acme-corp"}'
```

Response:
```json
{
  "api_key": "rct_a1b2c3d4...",
  "agent_name": "expense-bot-v1",
  "org_id": "acme-corp",
  "stripe_customer_id": "cus_...",
  "free_credits": 50
}
```

### 3. Check your balance

```bash
curl -X POST https://your-server.com/tools/check_balance \
  -H "X-API-Key: rct_a1b2c3d4..."
```

Response:
```json
{"credits": 50, "plan": "free"}
```

### 4. Upload a receipt

```bash
curl -X POST https://your-server.com/tools/upload_receipt \
  -H "X-API-Key: rct_a1b2c3d4..." \
  -F "file=@receipt.jpg" \
  -F "mime_type=image/jpeg"
```

### 5. Process the receipt (1 credit)

```bash
curl -X POST https://your-server.com/tools/process_receipt \
  -H "X-API-Key: rct_a1b2c3d4..." \
  -H "Content-Type: application/json" \
  -d '{"receipt_id": "a1b2c3d4e5f67890"}'
```

If you have 0 credits, you get a `402` response:
```json
{
  "detail": {
    "error": "Insufficient credits: 0 available, 1 required. Buy more at POST /billing/buy_credits",
    "buy_credits_url": "/billing/buy_credits",
    "subscribe_url": "/billing/subscribe"
  }
}
```

### 6. Upload + process in one call

Save a round-trip with the combo endpoint. Supports idempotency keys for safe retries:

```bash
curl -X POST https://your-server.com/tools/upload_and_process \
  -H "X-API-Key: rct_a1b2c3d4..." \
  -F "file=@receipt.jpg" \
  -F "mime_type=image/jpeg" \
  -F "idempotency_key=my-unique-key-123"
```

Returns the same structured expense data as `process_receipt`, but in a single call. If you retry with the same idempotency key, you get the cached result without being charged again.

### 7. List your receipts

```bash
curl -X POST https://your-server.com/tools/list_receipts \
  -H "X-API-Key: rct_a1b2c3d4..." \
  -H "Content-Type: application/json" \
  -d '{"limit": 10, "status": "processed"}'
```

Response:
```json
{
  "receipts": [
    {
      "receipt_id": "a1b2c3d4e5f67890",
      "status": "processed",
      "mime_type": "image/jpeg",
      "created_at": "2026-03-04 10:00:00",
      "updated_at": "2026-03-04 10:00:05"
    }
  ]
}
```

### 8. Buy more credits

```bash
curl -X POST https://your-server.com/billing/buy_credits \
  -H "X-API-Key: rct_a1b2c3d4..." \
  -H "Content-Type: application/json" \
  -d '{"credits": 1000}'
```

Response:
```json
{
  "checkout_url": "https://checkout.stripe.com/c/pay/...",
  "session_id": "cs_..."
}
```

### 9. Or subscribe monthly

```bash
curl -X POST https://your-server.com/billing/subscribe \
  -H "X-API-Key: rct_a1b2c3d4..." \
  -H "Content-Type: application/json" \
  -d '{"plan": "pro"}'
```

### 10. Set up webhook alerts

```bash
curl -X POST https://your-server.com/subscribe_webhook \
  -H "X-API-Key: rct_a1b2c3d4..." \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://your-agent.com/webhook",
    "events": ["low_balance", "processing_complete"]
  }'
```

---

## Monetization

### Credit System

| Action | Cost |
|---|---|
| `upload_receipt` | Free |
| `process_receipt` | 1 credit |
| `upload_and_process` | 1 credit |
| `get_receipt_markdown` | Free |
| `suggest_gl_account` | 1 credit |
| `check_balance` | Free |
| `list_receipts` | Free |

### Credit Packs (one-time purchase via Stripe Checkout)

| Credits | Price | Per-credit |
|---|---|---|
| 100 | $5 | $0.050 |
| 500 | $20 | $0.040 |
| 1,000 | $40 | $0.040 |
| 5,000 | $150 | $0.030 |
| 10,000 | $300 | $0.030 |

### Subscription Plans

| Plan | Credits/mo | Price | Per-credit |
|---|---|---|---|
| Free | 50 (signup bonus) | $0 | -- |
| Basic | 200/mo | $15/mo | $0.075 |
| Pro | 2,000/mo | $99/mo | $0.050 |

### How billing works

1. Agent calls `POST /register_agent` -- gets API key + 50 free credits
2. Agent calls paid tools -- 1 credit deducted atomically per call
3. At 0 credits, paid endpoints return `402` with buy/subscribe links
4. Agent calls `POST /billing/buy_credits` or `POST /billing/subscribe` -- gets Stripe Checkout URL
5. Stripe webhook (`POST /billing/webhook`) credits the account automatically
6. If agent subscribed to `low_balance` webhook, they get notified when credits drop below 5

No human in the loop. Fully programmatic.

### Crypto Payments

Pay with **any of 300+ cryptocurrencies** -- BTC, ETH, SOL, USDC, USDT, DOGE, LTC, XMR, MATIC, AVAX, and more. Credits are always priced in USD. The exact crypto amount is quoted at the current exchange rate and locked for ~20 minutes.

**Buy credits with crypto:**
```bash
curl -X POST https://your-server.com/billing/buy_credits_crypto \
  -H "X-API-Key: rct_a1b2c3d4..." \
  -H "Content-Type: application/json" \
  -d '{"credits": 1000, "preferred_coin": "eth"}'
```

Response:
```json
{
  "payment_id": "5678901234",
  "quoted_crypto_amount": 0.0167,
  "currency": "ETH",
  "address": "0xabc123...",
  "expiry": "2026-03-04T15:30:00Z",
  "fiat_locked": 40.00,
  "rate_used": 2395.21,
  "credits": 1000
}
```

**Check payment status:**
```bash
curl -X POST https://your-server.com/billing/check_payment_status \
  -H "X-API-Key: rct_a1b2c3d4..." \
  -H "Content-Type: application/json" \
  -d '{"payment_id": "5678901234"}'
```

**How crypto billing works:**
1. Agent calls `POST /billing/buy_credits_crypto` with credits + preferred coin
2. Server quotes exact crypto amount at current USD rate (via NOWPayments)
3. Agent sends crypto to the returned address within ~20 min
4. NOWPayments confirms payment via IPN webhook (`POST /billing/crypto_webhook`)
5. Credits auto-granted to the agent's account
6. Agent can also poll `POST /billing/check_payment_status` to check manually

**Supported coins:** BTC, ETH, SOL, USDC, USDT, DOGE, LTC, XMR, MATIC, AVAX, ADA, DOT, LINK, UNI, SHIB, and 280+ more.

---

## Async Processing (Celery + Redis)

For high-throughput agents that don't want to block on each receipt:

```bash
# Queue async processing
curl -X POST https://your-server.com/tools/process_receipt_async \
  -H "X-API-Key: rct_a1b2c3d4..." \
  -H "Content-Type: application/json" \
  -d '{"receipt_id": "a1b2c3d4e5f67890"}'
```

Response:
```json
{"receipt_id": "a1b2c3d4e5f67890", "task_id": "abc123...", "status": "queued"}
```

Poll for completion:
```bash
curl https://your-server.com/tasks/abc123... \
  -H "X-API-Key: rct_a1b2c3d4..."
```

Or subscribe to the `processing_complete` webhook to be notified automatically.

### Running the Celery worker

```bash
export REDIS_URL=redis://localhost:6379/0
celery -A tasks.celery_app worker --loglevel=info
```

---

## Webhook Events

Subscribe via `POST /subscribe_webhook`:

| Event | Payload | When |
|---|---|---|
| `low_balance` | `{credits_remaining, buy_credits_url}` | Credits drop below 5 |
| `processing_complete` | `{receipt_id, status, error?}` | Async processing finishes |

Webhooks are delivered asynchronously and don't block API responses.

---

## Framework Integration Quickstarts

`GET /integrations` returns copy-paste snippets for:

- **LangGraph** -- Use as a tool node
- **CrewAI** -- Use as a `BaseTool` subclass
- **AutoGen** -- Register as a function
- **Raw Python** -- Full flow with httpx

---

## MCP Endpoint Details

`GET /mcp` returns a JSON array with 8 tools. Each tool includes:

| Field | Description |
|---|---|
| `name` | Tool identifier |
| `description` | Natural-language description optimized for LLM understanding |
| `parameters` | Full JSON Schema with types, enums, defaults |
| `examples` | 1-2 complete input/output pairs |
| `constraints` | Rate limits, auth, cost, latency, `setup_required` |

### Available tools

| Tool | Cost | Description |
|---|---|---|
| `upload_receipt` | Free | Upload receipt image/PDF via file or URL |
| `process_receipt` | 1 credit | Extract structured data with Claude Vision |
| `upload_and_process` | 1 credit | Upload + process in one call (idempotent) |
| `get_receipt_markdown` | Free | Render processed receipt as Markdown |
| `suggest_gl_account` | 1 credit | AI-suggest GL account code |
| `check_balance` | Free | Check credits and plan |
| `list_receipts` | Free | List receipts with status filter |
| `buy_credits_crypto` | Free | Purchase credits with 300+ cryptocurrencies |

All tools include `"setup_required": "register_agent"` in constraints. The `buy_credits_crypto` tool includes `crypto_any_supported: true`, `dynamic_fiat_lock: true`, and `expiry_minutes: "15-20"`.

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

**Why start here:** Zero upfront hardware cost means you generate revenue before spending. Best-in-class accuracy for structured extraction from receipts.

### Alternative: Fully Local with Ollama

| Metric | Value |
|---|---|
| Models | Qwen2.5-VL-72B or Llama 3.2 Vision 90B (quantized) |
| Accuracy | 80-92% |
| Latency | 8-60 seconds per receipt |
| Upfront cost | $2,000-3,000 (RTX 4090 + PC) |
| Ongoing cost | ~$30-60/mo electricity |
| Privacy | 100% on-premises |

**When to switch:** Once profitable and processing volume justifies the fixed cost.

---

## How Agents Find This Tool

There are **5 discovery layers**, from native MCP protocol to HTTP fallback:

### 1. MCP Protocol (stdio) -- Claude Desktop, Cursor, VS Code

The server speaks the **official MCP protocol** via `mcp_server.py`. Add it to your MCP client:

**Claude Desktop** (`~/Library/Application Support/Claude/claude_desktop_config.json`):
```json
{
  "mcpServers": {
    "receipt-accounting": {
      "command": "python",
      "args": ["/path/to/Receipt-Accounting-Entry-MCP-Server/mcp_server.py"],
      "env": {
        "ANTHROPIC_API_KEY": "sk-ant-your-key-here"
      }
    }
  }
}
```

**Cursor** (`.cursor/mcp.json` in your project):
```json
{
  "mcpServers": {
    "receipt-accounting": {
      "command": "python",
      "args": ["/path/to/mcp_server.py"],
      "env": { "ANTHROPIC_API_KEY": "sk-ant-..." }
    }
  }
}
```

Once configured, the agent can call `upload_receipt`, `process_receipt`, `suggest_gl_account`, etc. directly through the MCP protocol. No HTTP needed.

### 2. Well-Known Discovery

Any MCP-aware agent can hit `/.well-known/mcp.json` on your domain to discover the server:

```bash
curl https://your-server.com/.well-known/mcp.json
```

Returns server name, description, available transports (stdio + HTTP), registration URL, and tool count. This is the emerging standard for domain-level MCP discovery.

### 3. MCP Registries (Smithery, Composio, Glama)

The repo includes a `smithery.yaml` for listing on [Smithery.ai](https://smithery.ai) -- the largest MCP server registry. Agents and developers search Smithery to find MCP tools.

**To list on registries:**
- **Smithery:** Submit the repo URL at smithery.ai/submit (config in `smithery.yaml`)
- **Composio:** Submit at composio.dev
- **Glama:** Submit at glama.ai/mcp/servers

Once listed, any agent querying these registries for "receipt", "expense", "accounting", or "OCR" will find this tool.

### 4. HTTP Discovery Endpoint

For agents that speak HTTP but not MCP protocol:

```bash
curl https://your-server.com/mcp
```

Returns a JSON array with all 8 tools, full JSON schemas, examples, and constraints. This is the fallback for custom agent frameworks.

### 5. Framework Integrations

Ready-to-use examples in the `examples/` directory:

| Framework | File | What it does |
|---|---|---|
| **LangGraph** | `examples/langgraph_agent.py` | LangChain tools for StateGraph |
| **CrewAI** | `examples/crewai_tool.py` | BaseTool subclasses |
| **Raw Python** | `examples/quick_start.py` | 10-line end-to-end example |

The `/integrations` endpoint also returns copy-paste snippets for LangGraph, CrewAI, AutoGen, and raw Python.

### Discovery Summary

```
                    Agent needs receipt parsing
                              |
              ┌───────────────┼───────────────┐
              v               v               v
      MCP Registry      Domain Probe     Developer Config
    (Smithery, etc.)  (/.well-known/)   (claude_desktop_config)
              |               |               |
              v               v               v
         smithery.yaml    mcp.json       mcp_server.py
              |               |               |
              └───────┬───────┘               |
                      v                       v
               HTTP API (/mcp)         MCP stdio protocol
              (tool catalogue)        (JSON-RPC over stdio)
                      |                       |
                      v                       v
               POST /tools/*           Direct tool calls
            (FastAPI endpoints)     (via MCP SDK transport)
```

See [MARKETING.md](MARKETING.md) for the full go-to-market strategy.

---

## Project Status

| Phase | Status | Description |
|---|---|---|
| Phase 1 | Complete | Core tools + Claude Sonnet 4.6 vision + MCP endpoint |
| Phase 2 | Complete | Stripe credits, subscriptions, agent registration, webhooks, async processing |
| Phase 3 | Complete | Crypto payments (300+ coins) with dynamic fiat-lock quoting via NOWPayments |
| Phase 3.1 | **Current** | Performance audit: atomic credits, connection pooling, async webhooks, combo endpoints, idempotency |

---

## Setup

### Prerequisites

- Python 3.11+
- An Anthropic API key ([console.anthropic.com](https://console.anthropic.com))
- Redis (for async processing -- optional for sync-only use)
- Stripe account (for fiat billing -- optional for dev/testing)
- NOWPayments account (for crypto billing -- optional for dev/testing)

### Install & Run

```bash
git clone https://github.com/TiagoX9/Receipt-Accounting-Entry-MCP-Server.git
cd Receipt-Accounting-Entry-MCP-Server

pip install -r requirements.txt

# Required
export ANTHROPIC_API_KEY=sk-ant-...

# Billing (optional -- billing endpoints will error without these)
export STRIPE_SECRET_KEY=sk_test_...
export STRIPE_WEBHOOK_SECRET=whsec_...
export STRIPE_BASIC_PRICE_ID=price_...
export STRIPE_PRO_PRICE_ID=price_...

# Crypto payments (optional -- crypto endpoints will error without these)
export NOWPAYMENTS_API_KEY=...
export NOWPAYMENTS_IPN_SECRET=...
export CRYPTO_IPN_CALLBACK_URL=https://your-server.com/billing/crypto_webhook

# Async processing (optional -- only needed for /tools/process_receipt_async)
export REDIS_URL=redis://localhost:6379/0

# Legacy API keys (optional -- agents can self-register instead)
export API_KEYS=dev-key-change-me

uvicorn app:app --reload
```

For async processing, also start a Celery worker:
```bash
celery -A tasks.celery_app worker --loglevel=info
```

The server starts at `http://localhost:8000`.

- **MCP tools:** `http://localhost:8000/mcp`
- **Swagger docs:** `http://localhost:8000/docs`
- **Health check:** `http://localhost:8000/health`
- **Integrations:** `http://localhost:8000/integrations`

### Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `ANTHROPIC_API_KEY` | Yes | -- | Anthropic API key for Claude vision |
| `STRIPE_SECRET_KEY` | No | -- | Stripe secret key for billing |
| `STRIPE_WEBHOOK_SECRET` | No | -- | Stripe webhook signing secret |
| `STRIPE_BASIC_PRICE_ID` | No | -- | Stripe Price ID for basic plan |
| `STRIPE_PRO_PRICE_ID` | No | -- | Stripe Price ID for pro plan |
| `NOWPAYMENTS_API_KEY` | No | -- | NOWPayments API key for crypto billing |
| `NOWPAYMENTS_IPN_SECRET` | No | -- | NOWPayments IPN signing secret |
| `CRYPTO_IPN_CALLBACK_URL` | No | -- | Your public URL for crypto payment callbacks |
| `REDIS_URL` | No | `redis://localhost:6379/0` | Redis URL for Celery task queue |
| `API_KEYS` | No | `dev-key-change-me` | Legacy comma-separated API keys |

---

## File Structure

```
├── app.py                 # FastAPI application, routes, auth, credit middleware
├── mcp_server.py          # Official MCP protocol server (stdio/SSE transport)
├── models.py              # Pydantic request/response schemas
├── db.py                  # SQLite helpers (connection pool, WAL, API key cache)
├── tools.py               # Core tool logic + MCP descriptor generator
├── billing.py             # Stripe + crypto billing (atomic deduction, checkout, IPN)
├── crypto_gateway.py      # NOWPayments abstraction (persistent async client)
├── tasks.py               # Celery async task definitions
├── webhooks.py            # Async webhook dispatch (fire-and-forget)
├── test_all.py            # 126-test end-to-end test suite
├── smithery.yaml          # Smithery.ai MCP registry configuration
├── mcp_config_example.json # Claude Desktop / Cursor config example
├── examples/
│   ├── quick_start.py     # 10-line end-to-end example
│   ├── langgraph_agent.py # LangGraph tool integration
│   └── crewai_tool.py     # CrewAI BaseTool integration
├── requirements.txt       # Python dependencies
├── CREDENTIALS_NEEDED.md  # All required API keys and setup instructions
├── MARKETING.md           # Go-to-market strategy for AI agent distribution
├── LAUNCH_CHECKLIST.md    # Step-by-step launch instructions (don't skip this)
├── .gitignore
└── README.md
```

---

## Marketing Strategy

See [MARKETING.md](MARKETING.md) for the complete go-to-market playbook covering:

- **Positioning** -- How to frame this for agent developers
- **Distribution** -- MCP registries, GitHub, framework ecosystems, content marketing
- **Growth loops** -- Free-tier virality, agent-to-agent referral, framework lock-in
- **Launch playbook** -- Week-by-week action plan
- **Metrics** -- Registration, activation, revenue, and retention targets
- **Competitive moat** -- Why this is defensible long-term
- **Partnerships** -- Anthropic, LangChain, CrewAI, Composio

---

## Launch Checklist

See [LAUNCH_CHECKLIST.md](LAUNCH_CHECKLIST.md) for the complete step-by-step guide to making this tool discoverable. Covers:

1. **Deploy** -- hosting options (Railway, Fly.io, Render), env vars, verification
2. **GitHub** -- topics, description, website URL to add
3. **MCP Registries** -- exact steps for Smithery, Composio, Glama, Arcade.dev
4. **Framework Ecosystem** -- PRs to submit for LangChain and CrewAI community tools
5. **Content & Social** -- Hacker News post template, Twitter thread template, Reddit subs, Discord channels, blog outline
6. **Ongoing** -- weekly, monthly, and quarterly maintenance tasks

---

## License

MIT
