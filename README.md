# Receipt → Accounting Entry MCP Server

Turn receipt images and PDFs into structured, accounting-ready JSON. One API call.

Built for AI agents that handle expense management, accounts payable, and bookkeeping. No dashboard, no login — just an API.

**50 free credits on signup. No credit card required.**

**Built by [Kelnix](https://kelnix.org)** — Contact: info@kelnix.org

---

## Quickstart

### 1. Register (instant, no approval)

```bash
curl -X POST https://receipt-mcp-api.kelnix.org/register_agent \
  -H "Content-Type: application/json" \
  -d '{"agent_name": "my-expense-bot"}'
```

Returns your API key + 50 free credits.

### 2. Process a receipt (1 credit)

```bash
curl -X POST https://receipt-mcp-api.kelnix.org/tools/upload_and_process \
  -H "X-API-Key: rct_your-key-here" \
  -F "file=@receipt.jpg" \
  -F "mime_type=image/jpeg"
```

Returns structured JSON: vendor, date, line items, totals, tax, currency, confidence scores.

### 3. Buy more credits when you need them

```bash
# With card (Stripe)
curl -X POST https://receipt-mcp-api.kelnix.org/billing/buy_credits \
  -H "X-API-Key: rct_your-key-here" \
  -H "Content-Type: application/json" \
  -d '{"credits": 1000}'

# With crypto (300+ coins)
curl -X POST https://receipt-mcp-api.kelnix.org/billing/buy_credits_crypto \
  -H "X-API-Key: rct_your-key-here" \
  -H "Content-Type: application/json" \
  -d '{"credits": 1000, "preferred_coin": "eth"}'
```

---

## Pricing

### Credit Packs

| Credits | Price | Per credit |
|---|---|---|
| 100 | $5 | $0.050 |
| 500 | $20 | $0.040 |
| 1,000 | $40 | $0.040 |
| 5,000 | $150 | $0.030 |
| 10,000 | $300 | $0.030 |

### Subscriptions

| Plan | Credits/mo | Price |
|---|---|---|
| Free | 50 (signup) | $0 |
| Basic | 200/mo | $15/mo |
| Pro | 2,000/mo | $99/mo |

### What costs credits

| Tool | Cost |
|---|---|
| `process_receipt` | 1 credit |
| `upload_and_process` | 1 credit |
| `suggest_gl_account` | 1 credit |
| `upload_receipt` | Free |
| `get_receipt_markdown` | Free |
| `check_balance` | Free |
| `list_receipts` | Free |

Full pricing also available at `GET /pricing` (no auth required).

---

## All Endpoints

### Tools

| Method | Endpoint | Cost | Description |
|---|---|---|---|
| POST | `/tools/upload_receipt` | Free | Upload receipt image/PDF |
| POST | `/tools/process_receipt` | 1 credit | Extract structured data |
| POST | `/tools/upload_and_process` | 1 credit | Upload + process in one call (supports idempotency) |
| POST | `/tools/get_receipt_markdown` | Free | Get processed receipt as Markdown |
| POST | `/tools/suggest_gl_account` | 1 credit | AI-suggest GL account code |
| POST | `/tools/check_balance` | Free | Check credits and plan |
| POST | `/tools/list_receipts` | Free | List receipts with filters |
| POST | `/tools/process_receipt_async` | 1 credit | Queue async processing (requires Redis) |

### Billing

| Method | Endpoint | Description |
|---|---|---|
| POST | `/billing/buy_credits` | Buy credit pack (Stripe Checkout) |
| POST | `/billing/subscribe` | Subscribe to monthly plan |
| POST | `/billing/buy_credits_crypto` | Buy credits with 300+ cryptocurrencies |
| POST | `/billing/check_payment_status` | Check crypto payment status |
| GET | `/billing/balance` | Full balance with transaction history |

### Discovery & Info

| Method | Endpoint | Description |
|---|---|---|
| GET | `/mcp` | Tool catalogue with schemas, examples, constraints |
| GET | `/.well-known/mcp.json` | MCP server discovery metadata |
| GET | `/pricing` | Public pricing (no auth) |
| GET | `/legal/terms` | Terms of Service |
| GET | `/legal/privacy` | Privacy Policy |
| GET | `/integrations` | Code snippets for LangGraph, CrewAI, AutoGen |
| GET | `/docs` | Interactive Swagger documentation |
| GET | `/health` | Health check |

### Auth

All tool and billing endpoints require `X-API-Key` header. Get a key via `POST /register_agent`.

When you run out of credits, paid endpoints return `402` with links to buy more:

```json
{
  "error": "Insufficient credits: 0 available, 1 required.",
  "buy_credits_url": "/billing/buy_credits",
  "buy_credits_crypto_url": "/billing/buy_credits_crypto",
  "pricing_url": "/pricing",
  "cheapest_option": "100 credits for $5.00"
}
```

---

## MCP Protocol Support

Works with Claude Desktop, Cursor, and any MCP-compatible client:

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

Also discoverable via `/.well-known/mcp.json` and listed on [Smithery.ai](https://smithery.ai).

---

## Framework Examples

`GET /integrations` returns ready-to-use code for:

- **LangGraph** — tool node integration
- **CrewAI** — BaseTool subclass
- **AutoGen** — registered function
- **Raw Python** — full flow with httpx

See `examples/` directory for complete implementations.

---

## Crypto Payments

Pay with BTC, ETH, SOL, USDC, USDT, DOGE, and 280+ more. Credits priced in USD, crypto amount locked at current rate for ~20 minutes.

```bash
curl -X POST https://receipt-mcp-api.kelnix.org/billing/buy_credits_crypto \
  -H "X-API-Key: rct_your-key-here" \
  -H "Content-Type: application/json" \
  -d '{"credits": 1000, "preferred_coin": "btc"}'
```

Returns payment address and exact amount. Credits granted automatically on confirmation.

---

## Self-Hosting

```bash
git clone https://github.com/TiagoX9/Receipt-Accounting-Entry-MCP-Server.git
cd Receipt-Accounting-Entry-MCP-Server
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...
uvicorn app:app --host 0.0.0.0 --port 8000
```

Requires Python 3.11+. See `deploy/setup.sh` for production deployment with nginx, SSL, and systemd.

---

## License

MIT
