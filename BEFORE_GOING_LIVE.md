# Before Going Live -- Complete Setup Guide

Everything you need to do before this server is production-ready, in order. Each step tells you exactly what to do, where to go, and what to copy.

---

## Table of Contents

- [Step 1: Get Your API Keys](#step-1-get-your-api-keys)
- [Step 2: Set Up Stripe Billing](#step-2-set-up-stripe-billing)
- [Step 3: Set Up Crypto Payments](#step-3-set-up-crypto-payments)
- [Step 4: Set Up Redis (optional)](#step-4-set-up-redis-optional)
- [Step 5: Create Your .env File](#step-5-create-your-env-file)
- [Step 6: Test Locally](#step-6-test-locally)
- [Step 7: Choose Where to Deploy](#step-7-choose-where-to-deploy)
- [Step 8: Deploy to Railway (recommended)](#step-8-deploy-to-railway-recommended)
- [Step 8 alt: Deploy to Render](#step-8-alt-deploy-to-render)
- [Step 8 alt: Deploy to Fly.io](#step-8-alt-deploy-to-flyio)
- [Step 9: Configure Webhooks with Your Live URL](#step-9-configure-webhooks-with-your-live-url)
- [Step 10: Verify Everything Works](#step-10-verify-everything-works)
- [Step 11: Set Up Taxes & Invoices](#step-11-set-up-taxes--invoices)
- [Step 12: Legal Compliance](#step-12-legal-compliance)
- [Step 13: Make It Discoverable](#step-13-make-it-discoverable)
- [Pricing & Profitability Analysis](#pricing--profitability-analysis)
- [What Each Service Costs You (Summary)](#what-each-service-costs-you-summary)
- [Your Complete .env Reference](#your-complete-env-reference)

---

## Step 1: Get Your API Keys

### 1a. Anthropic API Key (REQUIRED)

This is the only key you absolutely need. It powers the AI receipt extraction.

1. Go to https://console.anthropic.com
2. Sign up or log in
3. Go to "API Keys" in the left sidebar
4. Click "Create Key"
5. Copy the key -- it starts with `sk-ant-`
6. Save it somewhere safe

**Cost:** Pay-per-use. Each receipt costs ~$0.01-0.05 to process.

### 1b. Stripe Account (for accepting fiat payments)

Skip this if you only want crypto payments or free-tier-only for now.

1. Go to https://stripe.com
2. Click "Start now" and create an account
3. Complete identity verification (takes 1-2 days for full payouts)
4. Once verified, go to https://dashboard.stripe.com/apikeys
5. Copy the **Secret key** (starts with `sk_test_` for test mode, `sk_live_` for production)

**Start with test mode.** Use `sk_test_` keys until you're ready for real payments.

### 1c. NOWPayments Account (for accepting crypto)

Skip this if you only want Stripe or free-tier-only for now.

1. Go to https://nowpayments.io
2. Click "Sign Up"
3. Verify your email
4. Go to Dashboard > Store Settings > API Keys
5. Click "Create new key"
6. Copy the API key

---

## Step 2: Set Up Stripe Billing

Skip if you skipped Step 1b.

### 2a. Create subscription products

1. Go to https://dashboard.stripe.com/products
2. Click "Add product"
3. Create **Basic Plan**:
   - Name: `Receipt MCP Basic`
   - Price: `$15.00` / month (recurring)
   - Click "Save"
   - On the product page, find the Price section
   - Copy the **Price ID** (starts with `price_`) -- this is your `STRIPE_BASIC_PRICE_ID`
4. Create **Pro Plan**:
   - Name: `Receipt MCP Pro`
   - Price: `$99.00` / month (recurring)
   - Copy the **Price ID** -- this is your `STRIPE_PRO_PRICE_ID`

### 2b. Create a webhook endpoint

You need your deployed URL for this. If you don't have it yet, come back after Step 8.

1. Go to https://dashboard.stripe.com/webhooks
2. Click "Add endpoint"
3. Set the URL to: `https://YOUR-DOMAIN.com/billing/webhook`
4. Under "Events to send", select:
   - `checkout.session.completed`
   - `invoice.paid`
5. Click "Add endpoint"
6. On the endpoint page, click "Reveal" next to Signing secret
7. Copy the signing secret (starts with `whsec_`) -- this is your `STRIPE_WEBHOOK_SECRET`

---

## Step 3: Set Up Crypto Payments

Skip if you skipped Step 1c.

### 3a. Configure IPN (payment notifications)

You need your deployed URL for this. If you don't have it yet, come back after Step 8.

1. Go to NOWPayments Dashboard > Store Settings > IPN Settings
2. Set the IPN callback URL to: `https://YOUR-DOMAIN.com/billing/crypto_webhook`
3. Click "Generate" next to IPN Secret Key
4. Copy the IPN Secret Key -- this is your `NOWPAYMENTS_IPN_SECRET`

---

## Step 4: Set Up Redis (optional)

Only needed if you want the async processing endpoint (`/tools/process_receipt_async`). The sync endpoints work fine without Redis.

### Option A: Skip it

The server works perfectly without Redis. Async processing returns a `503` with a helpful message. All other endpoints work normally.

### Option B: Free cloud Redis

1. Go to https://upstash.com (free tier: 10,000 commands/day)
2. Sign up and create a Redis database
3. Copy the connection URL (looks like `redis://default:xxx@xxx.upstash.io:6379`)
4. This is your `REDIS_URL`

### Option C: Local Redis (for development)

```bash
# macOS
brew install redis
brew services start redis
# REDIS_URL=redis://localhost:6379/0

# Ubuntu
sudo apt install redis-server
sudo systemctl start redis
```

---

## Step 5: Create Your .env File

In your project root, create a file called `.env` (this is already in `.gitignore`, so it won't be committed):

```bash
# ============================================
# REQUIRED
# ============================================
ANTHROPIC_API_KEY=sk-ant-api03-paste-your-key-here

# ============================================
# STRIPE (skip if no fiat billing needed yet)
# ============================================
STRIPE_SECRET_KEY=sk_test_paste-your-key-here
STRIPE_WEBHOOK_SECRET=whsec_paste-after-step-9
STRIPE_BASIC_PRICE_ID=price_paste-from-step-2a
STRIPE_PRO_PRICE_ID=price_paste-from-step-2a
STRIPE_SUCCESS_URL=https://YOUR-DOMAIN.com/docs
STRIPE_CANCEL_URL=https://YOUR-DOMAIN.com/docs

# ============================================
# CRYPTO (skip if no crypto billing needed yet)
# ============================================
NOWPAYMENTS_API_KEY=paste-your-key-here
NOWPAYMENTS_IPN_SECRET=paste-after-step-9
CRYPTO_IPN_CALLBACK_URL=https://YOUR-DOMAIN.com/billing/crypto_webhook

# ============================================
# REDIS (skip if no async processing needed)
# ============================================
REDIS_URL=redis://localhost:6379/0
```

---

## Step 6: Test Locally

Before deploying, make sure it works on your machine:

```bash
# Install dependencies
pip install -r requirements.txt

# Start the server
uvicorn app:app --port 8000

# In another terminal, run the test suite
python test_all.py
```

You should see `126 passed, 0 failed`. Some tests will show expected errors for unconfigured services (Stripe, NOWPayments, Redis) -- that's fine.

**Quick smoke test:**
```bash
# Health check
curl http://localhost:8000/health

# Register an agent
curl -X POST http://localhost:8000/register_agent \
  -H "Content-Type: application/json" \
  -d '{"agent_name": "test-bot"}'

# You should get an API key back with 50 free credits
```

---

## Step 7: Choose Where to Deploy

| Platform | Difficulty | Free Tier | Best For |
|---|---|---|---|
| **Railway** | Easiest | $5/mo credit | Getting started fast |
| **Render** | Easy | Free for web services | Zero-cost start |
| **Fly.io** | Medium | Free allowance | Global edge deployment |
| **DigitalOcean** | Medium | $4/mo droplet | Full control |
| **AWS (EC2/ECS)** | Hard | 12-month free tier | Scale + enterprise |

**My recommendation: Start with Railway or Render.** You can migrate later.

---

## Step 8: Deploy to Railway (recommended)

### 8a. Install Railway CLI

```bash
# macOS
brew install railway

# or via npm
npm install -g @railway/cli
```

### 8b. Deploy

```bash
# Login
railway login

# Initialize project (run from the repo root)
railway init

# Link to your GitHub repo
railway link

# Set environment variables
railway variables set ANTHROPIC_API_KEY=sk-ant-your-key
railway variables set STRIPE_SECRET_KEY=sk_test_your-key
# ... set all the vars from your .env file

# Deploy
railway up
```

### 8c. Get your URL

After deploy, Railway gives you a URL like `receipt-mcp-server-production.up.railway.app`. This is YOUR-DOMAIN.

### 8d. Set the start command

In Railway dashboard > Settings > Deploy, set:
- **Build command:** `pip install -r requirements.txt`
- **Start command:** `uvicorn app:app --host 0.0.0.0 --port $PORT`

---

## Step 8 alt: Deploy to Render

### 8a. Connect repo

1. Go to https://render.com
2. Click "New" > "Web Service"
3. Connect your GitHub repo: `TiagoX9/Receipt-Accounting-Entry-MCP-Server`
4. Settings:
   - **Runtime:** Python 3
   - **Build command:** `pip install -r requirements.txt`
   - **Start command:** `uvicorn app:app --host 0.0.0.0 --port $PORT`

### 8b. Add environment variables

In the Render dashboard for your service:
1. Go to "Environment" tab
2. Add each variable from your `.env` file

### 8c. Get your URL

Render gives you a URL like `receipt-mcp-server.onrender.com`.

---

## Step 8 alt: Deploy to Fly.io

### 8a. Install Fly CLI

```bash
# macOS
brew install flyctl

# or
curl -L https://fly.io/install.sh | sh
```

### 8b. Create a Procfile

Create a file called `Procfile` in the project root:

```
web: uvicorn app:app --host 0.0.0.0 --port $PORT
```

### 8c. Deploy

```bash
fly auth login
fly launch
# Follow the prompts, choose a region near your users

# Set secrets
fly secrets set ANTHROPIC_API_KEY=sk-ant-your-key
fly secrets set STRIPE_SECRET_KEY=sk_test_your-key
# ... set all vars

fly deploy
```

### 8d. Get your URL

Fly gives you a URL like `receipt-mcp-server.fly.dev`.

---

## Step 9: Configure Webhooks with Your Live URL

Now that you have your deployed URL, go back and set up the webhook endpoints:

### 9a. Stripe webhook

1. Go to https://dashboard.stripe.com/webhooks
2. Add endpoint: `https://YOUR-DOMAIN.com/billing/webhook`
3. Select events: `checkout.session.completed`, `invoice.paid`
4. Copy the signing secret
5. Set it on your host: `STRIPE_WEBHOOK_SECRET=whsec_...`

### 9b. NOWPayments IPN

1. Go to NOWPayments Dashboard > IPN Settings
2. Set callback URL: `https://YOUR-DOMAIN.com/billing/crypto_webhook`
3. Copy the IPN Secret
4. Set it on your host: `NOWPAYMENTS_IPN_SECRET=...`

### 9c. Update the crypto callback URL

Set this on your host:
```
CRYPTO_IPN_CALLBACK_URL=https://YOUR-DOMAIN.com/billing/crypto_webhook
```

### 9d. Update Stripe success/cancel URLs

```
STRIPE_SUCCESS_URL=https://YOUR-DOMAIN.com/docs
STRIPE_CANCEL_URL=https://YOUR-DOMAIN.com/docs
```

**Redeploy after changing env vars** (Railway and Render auto-redeploy on env changes).

---

## Step 10: Verify Everything Works

Run these commands, replacing YOUR-DOMAIN.com with your actual URL:

```bash
# 1. Health check
curl https://YOUR-DOMAIN.com/health
# Expected: {"status":"ok","version":"3.1.0"}

# 2. MCP discovery
curl https://YOUR-DOMAIN.com/.well-known/mcp.json
# Expected: JSON with server name, tools_count: 8

# 3. Tool catalogue
curl https://YOUR-DOMAIN.com/mcp | python -m json.tool | head -20
# Expected: Array of 8 tool definitions

# 4. Register a test agent
curl -X POST https://YOUR-DOMAIN.com/register_agent \
  -H "Content-Type: application/json" \
  -d '{"agent_name": "smoke-test"}'
# Expected: {"api_key":"rct_...","free_credits":50,...}

# 5. Check balance (use the API key from step 4)
curl -X POST https://YOUR-DOMAIN.com/tools/check_balance \
  -H "X-API-Key: rct_PASTE_KEY_HERE"
# Expected: {"credits":50,"plan":"free"}

# 6. Swagger docs
# Open in browser: https://YOUR-DOMAIN.com/docs
# Should show all 22 endpoints
```

If all 6 pass, you're live.

---

## Step 11: Set Up Taxes & Invoices

You need to handle taxes properly to be legally compliant. The server supports Stripe Tax for automatic tax calculation and invoice generation.

### 11a. Enable Stripe Tax (recommended)

Stripe Tax automatically calculates and collects the correct VAT, sales tax, or GST based on the customer's location. It costs an additional 0.5% per transaction.

1. Go to https://dashboard.stripe.com/settings/tax
2. Click "Get started" or "Enable Stripe Tax"
3. Set your **business address** (this determines your tax registration)
4. Add your **tax registrations** for the countries/states you need to collect tax in:
   - **EU:** If you're EU-based, register for VAT in your country. For selling to other EU countries, register for One-Stop Shop (OSS) to avoid registering in every EU country.
   - **US:** Register in states where you have nexus (physical presence or economic nexus)
   - **UK:** Register for VAT if selling to UK customers
5. Once enabled, set these env vars on your server:
   ```
   STRIPE_TAX_ENABLED=true
   STRIPE_COLLECT_ADDRESS=true
   ```

### 11b. How taxes work in your server

When `STRIPE_TAX_ENABLED=true`:
- Stripe Checkout automatically adds the correct tax on top of your prices
- Customers see the tax amount before paying
- Tax is collected and reported in your Stripe Dashboard
- Invoices include the tax breakdown automatically

When `STRIPE_COLLECT_ADDRESS=true`:
- Checkout collects the customer's billing address (needed for tax calculation)
- Business customers can enter their VAT/tax ID for reverse-charge (B2B)
- Tax ID is validated automatically by Stripe

### 11c. Invoice generation

The server now automatically generates Stripe invoices for every purchase:
- **Credit pack purchases:** Invoice created via `invoice_creation` on checkout
- **Subscriptions:** Stripe generates invoices automatically for every billing cycle
- **Crypto payments:** No automatic invoice (NOWPayments handles the receipt)

Customers can access their invoices from the Stripe-hosted invoice page (linked in the Stripe receipt email).

### 11d. What you need to register for

This depends on where you are based:

| Your Location | What to Register | Where |
|---|---|---|
| **EU country** | VAT in your country + OSS for cross-border EU sales | Your national tax authority + OSS portal |
| **US** | Sales tax in states with nexus | Each state's department of revenue |
| **UK** | VAT (if revenue > £90,000/yr) | HMRC |
| **Other** | Check local digital services tax rules | Your national tax authority |

**Important:** Even if you're small, you may need to register for VAT/sales tax when selling digital services. Stripe Tax handles the calculation and collection, but **you** are responsible for registering and filing. Consider consulting an accountant for your specific situation.

### 11e. For crypto payments

NOWPayments does not handle tax collection. For crypto sales:
- You receive the full amount minus the 0.5% NOWPayments fee
- **You are responsible for accounting for tax on crypto sales yourself**
- Keep records of all crypto payments (stored in your `crypto_payments` DB table)
- Report crypto income on your tax returns

---

## Step 12: Legal Compliance

Your server now has built-in legal endpoints. Review and customize them.

### 12a. Review Terms of Service

The server has a `/legal/terms` endpoint with default terms. Before going live:

1. Read the terms at `https://YOUR-DOMAIN.com/legal/terms`
2. If you need to customize, set `TERMS_URL` env var to point to your own hosted terms page
3. Key things to verify:
   - Refund policy matches your intentions
   - Data retention period is acceptable
   - Liability limitations are appropriate for your jurisdiction

### 12b. Review Privacy Policy

The server has a `/legal/privacy` endpoint with a default policy. Before going live:

1. Read the policy at `https://YOUR-DOMAIN.com/legal/privacy`
2. If you need to customize, set `PRIVACY_URL` env var to your own hosted privacy page
3. **GDPR (EU):** If you have EU customers, you must:
   - Have a lawful basis for processing (legitimate interest or contract)
   - Allow data subject access requests
   - Allow data deletion requests
   - Mention Anthropic as a data processor (receipt images are sent to their API)
4. **CCPA (California):** If you have California customers, you must disclose data collection and allow opt-out

### 12c. Set your contact email

Set the `SUPPORT_EMAIL` env var so the legal pages show your real contact:
```
SUPPORT_EMAIL=info@kelnix.org
```

### 12d. Consider a proper legal review

The built-in terms and privacy policy are reasonable defaults, but they are **not legal advice**. Before accepting real money, consider having a lawyer review them. This is especially important if you're in the EU (GDPR) or handling significant volume.

---

## Step 13: Make It Discoverable

Now go through [LAUNCH_CHECKLIST.md](LAUNCH_CHECKLIST.md) to get listed on MCP registries, add GitHub topics, and spread the word.

The short version:
1. Add GitHub topics (2 min) -- see LAUNCH_CHECKLIST.md Step 2.1
2. Submit to Smithery.ai (5 min) -- see LAUNCH_CHECKLIST.md Step 3.1
3. Submit to Composio + Glama (10 min) -- see LAUNCH_CHECKLIST.md Steps 3.2-3.3
4. Tweet about it -- see LAUNCH_CHECKLIST.md Step 5.2 for a template

---

## Pricing & Profitability Analysis

### Your API Cost Per Receipt

The server uses **Claude Haiku 4.5** (`claude-haiku-4-5-20251001`) for receipt extraction. Haiku is 3x cheaper than Sonnet and more than sufficient for OCR/receipt parsing.

**Anthropic API pricing (Haiku 4.5):** $1.00/MTok input, $5.00/MTok output

| Component | Tokens | Cost |
|---|---|---|
| Image input (receipt photo) | ~2,500 | $0.0025 |
| Text input (prompt + schema) | ~1,500 | $0.0015 |
| Output (JSON response) | ~500 | $0.0025 |
| **Total per `process_receipt`** | **~4,500** | **~$0.007** |
| **Total per `suggest_gl_account`** | **~1,000** | **~$0.002** |

For comparison, Sonnet 4.6 would cost ~$0.02/receipt (3x more). If you ever need higher accuracy for complex receipts, you can change `VISION_MODEL` in `tools.py` to `claude-sonnet-4-6-20250514`.

### Your Credit Pricing (what you charge users)

| Pack | Price | Per Credit | Your Cost | **Your Margin** |
|---|---|---|---|---|
| 100 credits | $5.00 | $0.050 | $0.007 | **86%** |
| 500 credits | $20.00 | $0.040 | $0.007 | **82%** |
| 1,000 credits | $40.00 | $0.040 | $0.007 | **82%** |
| 5,000 credits | $150.00 | $0.030 | $0.007 | **77%** |
| 10,000 credits | $300.00 | $0.030 | $0.007 | **77%** |

| Subscription | Price/mo | Credits/mo | Per Credit | **Your Margin** |
|---|---|---|---|---|
| Free | $0 | 50 (one-time) | -- | Marketing cost |
| Basic | $15/mo | 200 | $0.075 | **91%** |
| Pro | $99/mo | 2,000 | $0.050 | **86%** |

### Payment processor fees

| Provider | Fee | Impact on $40 sale | Net revenue |
|---|---|---|---|
| **Stripe** | 2.9% + $0.30 | -$1.46 | $38.54 |
| **NOWPayments** | 0.5% | -$0.20 | $39.80 |

### Break-even Analysis

| Scenario | Monthly Fixed Cost | Receipts to Break Even |
|---|---|---|
| Render (free tier) | $0 | 0 (profit from credit 1) |
| Railway (~$5/mo) | $5 | ~170 receipts at $0.03/credit |
| Railway (~$20/mo) | $20 | ~690 receipts at $0.03/credit |

**Bottom line:** At the cheapest credit price ($0.03), you earn ~$0.023 profit per receipt. At the Basic plan rate ($0.075), you earn ~$0.068 per receipt. You need very few paying users to cover hosting costs.

### Switching Models

To change the AI model, edit `VISION_MODEL` in `tools.py`:

```python
# Most profitable (recommended)
VISION_MODEL = "claude-haiku-4-5-20251001"    # ~$0.007/receipt

# Higher accuracy for complex receipts
VISION_MODEL = "claude-sonnet-4-6-20250514"   # ~$0.020/receipt
```

---

## What Each Service Costs You (Summary)

| Service | What You Pay | What You Charge Users | Your Margin |
|---|---|---|---|
| **Anthropic (Haiku 4.5)** | ~$0.007/receipt | 1 credit ($0.03-0.075) | **77-91%** |
| **Stripe** | 2.9% + $0.30 per transaction | Credit packs ($5-$300) | ~90-95% |
| **NOWPayments** | 0.5% per crypto transaction | Same credit packs | ~99% |
| **Railway** | ~$5-20/mo depending on usage | Covered by credit sales | -- |
| **Upstash Redis** | Free (10K commands/day) | -- | -- |

**Break-even estimate:** Essentially immediate on Render free tier. ~170 paid receipts/month covers Railway.

---

## Your Complete .env Reference

Copy this, fill in your values, save as `.env`:

```bash
# =============================================
# RECEIPT MCP SERVER - ENVIRONMENT VARIABLES
# =============================================
# Copy this file as .env and fill in your values
# NEVER commit this file to git
# =============================================

# REQUIRED -- without this, receipt processing won't work
ANTHROPIC_API_KEY=

# STRIPE -- for credit card/fiat payments
# Get keys at: https://dashboard.stripe.com/apikeys
STRIPE_SECRET_KEY=
# Set after creating webhook endpoint (Step 9a)
STRIPE_WEBHOOK_SECRET=
# Create products at: https://dashboard.stripe.com/products
STRIPE_BASIC_PRICE_ID=
STRIPE_PRO_PRICE_ID=
# Where Stripe redirects after payment
STRIPE_SUCCESS_URL=https://YOUR-DOMAIN.com/docs
STRIPE_CANCEL_URL=https://YOUR-DOMAIN.com/docs

# NOWPAYMENTS -- for crypto payments (300+ coins)
# Get keys at: https://nowpayments.io dashboard
NOWPAYMENTS_API_KEY=
# Set after configuring IPN (Step 9b)
NOWPAYMENTS_IPN_SECRET=
# Your public webhook URL
CRYPTO_IPN_CALLBACK_URL=https://YOUR-DOMAIN.com/billing/crypto_webhook

# REDIS -- for async processing (optional)
# Skip if you don't need /tools/process_receipt_async
# Free option: https://upstash.com
REDIS_URL=

# ============================================
# TAX & INVOICES (Step 11)
# ============================================
# Enable Stripe Tax for automatic VAT/sales tax (requires Stripe Tax setup)
STRIPE_TAX_ENABLED=true
# Collect billing address at checkout (needed for tax calculation)
STRIPE_COLLECT_ADDRESS=true

# ============================================
# LEGAL (Step 12)
# ============================================
# Contact email shown on /legal/terms and /legal/privacy
SUPPORT_EMAIL=info@kelnix.org
# Optional: link to your own hosted terms/privacy pages
TERMS_URL=
PRIVACY_URL=

# ============================================
# ADMIN (revenue dashboard)
# ============================================
# Secret key to access /admin/revenue endpoint
# Generate with: python -c "import secrets; print(secrets.token_urlsafe(32))"
ADMIN_KEY=

# LEGACY -- optional, agents can self-register instead
API_KEYS=
```

---

## Quick Decision Guide

**"I just want to test it works"**
- Only set `ANTHROPIC_API_KEY`
- Run locally with `uvicorn app:app`
- Everything else returns helpful error messages

**"I want to launch with Stripe payments only"**
- Set `ANTHROPIC_API_KEY` + all `STRIPE_*` vars
- Deploy to Railway or Render
- Skip NOWPayments and Redis

**"I want the full setup"**
- Set all variables
- Deploy to Railway or Render
- Set up Upstash Redis for async
- Configure both Stripe and NOWPayments webhooks

**"I want the cheapest possible start"**
- Set `ANTHROPIC_API_KEY` only
- Deploy to Render (free tier)
- Agents get 50 free credits, no payment system yet
- Add Stripe/crypto later when you have users
