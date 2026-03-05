# Launch Checklist

Step-by-step instructions for making this tool discoverable by AI agents and developers. Do these in order.

---

## Phase 1: Deploy the Server (do first)

### 1.1 Choose a hosting provider

Pick one and deploy:

- **Railway** (easiest): `railway init` then `railway up`
- **Fly.io**: `fly launch` then `fly deploy`
- **Render**: Connect GitHub repo, set build command `pip install -r requirements.txt`, start command `uvicorn app:app --host 0.0.0.0 --port $PORT`
- **AWS/GCP/Azure**: Docker or direct deploy

### 1.2 Set environment variables on your host

```
ANTHROPIC_API_KEY=sk-ant-...          # REQUIRED - get from console.anthropic.com
STRIPE_SECRET_KEY=sk_live_...         # Optional - for fiat billing
STRIPE_WEBHOOK_SECRET=whsec_...       # Optional - for Stripe webhooks
STRIPE_BASIC_PRICE_ID=price_...       # Optional - create in Stripe Dashboard
STRIPE_PRO_PRICE_ID=price_...         # Optional - create in Stripe Dashboard
NOWPAYMENTS_API_KEY=...               # Optional - for crypto billing
NOWPAYMENTS_IPN_SECRET=...            # Optional - for crypto webhooks
CRYPTO_IPN_CALLBACK_URL=https://YOUR-DOMAIN.com/billing/crypto_webhook
REDIS_URL=redis://...                 # Optional - for async processing
```

### 1.3 Verify deployment

```bash
# Replace with your actual domain
curl https://YOUR-DOMAIN.com/health
# Should return: {"status":"ok","version":"3.1.0"}

curl https://YOUR-DOMAIN.com/.well-known/mcp.json
# Should return MCP discovery metadata

curl https://YOUR-DOMAIN.com/mcp
# Should return 8 tools
```

---

## Phase 2: GitHub Discoverability

### 2.1 Add GitHub topics

Go to: https://github.com/TiagoX9/Receipt-Accounting-Entry-MCP-Server

Click the gear icon next to "About" on the right side, and add these topics:

```
mcp
mcp-server
model-context-protocol
receipt-ocr
ai-agent
expense-management
accounting-api
agent-tools
fastapi
claude-vision
```

### 2.2 Set repository description

In the same "About" section, set the description to:

```
Agent-native MCP server that converts receipt images/PDFs into structured accounting JSON. 8 tools, Claude Vision, Stripe + crypto billing. 50 free credits.
```

### 2.3 Set website URL

Set the website field to your deployed server URL:

```
https://YOUR-DOMAIN.com/docs
```

---

## Phase 3: MCP Registry Submissions

### 3.1 Smithery.ai (largest MCP registry)

1. Go to https://smithery.ai
2. Click "Submit Server" or "Add Server"
3. Paste the GitHub repo URL: `https://github.com/TiagoX9/Receipt-Accounting-Entry-MCP-Server`
4. The `smithery.yaml` in the repo root will be auto-detected
5. Verify the listing shows all 7 MCP tools
6. Add tags: `receipt`, `accounting`, `expense`, `ocr`, `vision`, `billing`

### 3.2 Composio

1. Go to https://composio.dev
2. Sign up / log in
3. Navigate to "Tools" or "Integrations" section
4. Submit your MCP server with:
   - **Name:** Receipt Accounting Entry
   - **URL:** `https://YOUR-DOMAIN.com/mcp`
   - **GitHub:** `https://github.com/TiagoX9/Receipt-Accounting-Entry-MCP-Server`
   - **Description:** Convert receipt images/PDFs into structured accounting JSON. 8 tools, AI vision, crypto payments.

### 3.3 Glama.ai

1. Go to https://glama.ai/mcp/servers
2. Click "Submit" or "Add Server"
3. Paste the GitHub repo URL
4. Fill in description and tags

### 3.4 mcp.run (if available)

1. Go to https://mcp.run
2. Submit server with repo URL
3. Verify tools are detected

### 3.5 Arcade.dev

1. Go to https://arcade.dev
2. Submit as a tool/integration
3. Use the `/mcp` endpoint URL

---

## Phase 4: Framework Ecosystem

### 4.1 LangChain Community Tools

1. Fork https://github.com/langchain-ai/langchain
2. Add a tool in `libs/community/langchain_community/tools/receipt_mcp/`
3. Reference `examples/langgraph_agent.py` for the implementation
4. Submit a PR with title: "Add Receipt MCP Server tool for expense parsing"

### 4.2 CrewAI Community Tools

1. Check https://github.com/crewAIInc/crewAI-tools
2. Add a tool based on `examples/crewai_tool.py`
3. Submit PR

### 4.3 PyPI Package (optional, for wider reach)

Create a lightweight client package:

```bash
mkdir receipt-mcp-client
# Create setup.py, __init__.py with httpx wrapper
# pip install receipt-mcp-client
# Then: from receipt_mcp import ReceiptMCP
```

---

## Phase 5: Content & Social

### 5.1 Hacker News

Post a "Show HN" with this title format:

```
Show HN: MCP server that turns receipt photos into accounting entries (open source)
```

Post body: Link to GitHub repo. Mention 50 free credits, 8 tools, crypto payments.

Best times to post: Tuesday-Thursday, 8-10 AM ET.

### 5.2 Twitter/X

Post a launch thread. Example:

```
Thread:

1/ I built an MCP server that turns receipt photos into structured accounting entries.

Any AI agent can discover it, register in 1 API call, and start processing receipts in seconds.

8 tools. 50 free credits. Accepts crypto. Open source.

github.com/TiagoX9/Receipt-Accounting-Entry-MCP-Server

2/ How it works for an agent:
- Hit /mcp to discover tools
- POST /register_agent → get API key + 50 credits
- POST /tools/upload_and_process → structured JSON in 3 seconds
- Runs out of credits? 402 response includes buy link
- Agent buys more credits via Stripe or crypto (300+ coins)

3/ Built for the agentic era:
- MCP protocol (works in Claude Desktop, Cursor)
- /.well-known/mcp.json discovery
- Listed on Smithery
- LangGraph + CrewAI examples included
- No human dashboard. API-only. Agents are the users.

4/ Tech stack:
- FastAPI + Claude Sonnet 4.6 Vision
- SQLite (WAL mode, connection pooling)
- Atomic credit deduction (no race conditions)
- Async webhooks (fire-and-forget)
- Idempotency keys for safe retries
```

Use hashtags: #MCP #AIAgents #AgentNative #MCPTools #BuildInPublic

### 5.3 Reddit

Post in these subreddits:
- r/MachineLearning (as a project showcase)
- r/artificial
- r/LocalLLaMA (mention the Ollama alternative in README)
- r/SideProject

### 5.4 Discord Communities

Share in:
- **LangChain Discord** → #showcase channel
- **CrewAI Discord** → #tools or #showcase
- **Anthropic Discord** → #projects or #tools
- **AI Engineer Discord** (if member)

### 5.5 Blog Post

Write and publish on Medium, Dev.to, or your own blog:

```
Title: "How to Build an AI Expense Agent in 50 Lines of Python"

Outline:
1. The problem (receipts are unstructured)
2. The solution (MCP server with 8 tools)
3. Code walkthrough (use examples/quick_start.py)
4. Show the structured output
5. Mention free tier, crypto payments
6. Link to GitHub
```

---

## Phase 6: Ongoing

### Weekly

- [ ] Check Smithery listing is still active
- [ ] Monitor GitHub issues for agent developer feedback
- [ ] Tweet 1-2 times about the project (demos, benchmarks, updates)

### Monthly

- [ ] Check agent registration count in the database
- [ ] Review credit purchase conversion rate
- [ ] Publish 1 blog post or tutorial
- [ ] Update MCP registry listings if tools change

### Quarterly

- [ ] Review and update pricing
- [ ] Add new framework integrations if new frameworks emerge
- [ ] Check for new MCP registries to submit to
- [ ] Consider publishing a PyPI client package if demand warrants it

---

## Quick Reference: All URLs

Once deployed, replace YOUR-DOMAIN.com with your actual domain:

| What | URL |
|---|---|
| Health check | `https://YOUR-DOMAIN.com/health` |
| MCP discovery | `https://YOUR-DOMAIN.com/.well-known/mcp.json` |
| Tool catalogue | `https://YOUR-DOMAIN.com/mcp` |
| Swagger docs | `https://YOUR-DOMAIN.com/docs` |
| Agent registration | `POST https://YOUR-DOMAIN.com/register_agent` |
| GitHub repo | `https://github.com/TiagoX9/Receipt-Accounting-Entry-MCP-Server` |
| Smithery listing | `https://smithery.ai/server/receipt-accounting-entry` (after submission) |
