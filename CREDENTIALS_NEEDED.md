# Credentials & API Keys Needed

This document lists every secret/credential required to run the full Receipt MCP Server (Phases 1-3). **None of these should ever be committed to the repo or exposed in API responses.**

---

## Required (core functionality)

| Variable | Where to get it | Used for |
|---|---|---|
| `ANTHROPIC_API_KEY` | [console.anthropic.com](https://console.anthropic.com) | Claude Sonnet 4.6 vision API for receipt extraction |

---

## Stripe (Phase 2 - credit billing)

| Variable | Where to get it | Used for |
|---|---|---|
| `STRIPE_SECRET_KEY` | [dashboard.stripe.com/apikeys](https://dashboard.stripe.com/apikeys) | Server-side Stripe API calls |
| `STRIPE_WEBHOOK_SECRET` | Stripe Dashboard > Webhooks > Signing secret | Verifying Stripe webhook signatures |
| `STRIPE_BASIC_PRICE_ID` | Create a Product+Price in Stripe Dashboard for the Basic plan ($15/mo) | Monthly basic subscription |
| `STRIPE_PRO_PRICE_ID` | Create a Product+Price in Stripe Dashboard for the Pro plan ($99/mo) | Monthly pro subscription |
| `STRIPE_SUCCESS_URL` | Your own URL (e.g. `https://yourserver.com/success`) | Redirect after successful Stripe Checkout |
| `STRIPE_CANCEL_URL` | Your own URL (e.g. `https://yourserver.com/cancel`) | Redirect after cancelled Stripe Checkout |

### Stripe setup steps:
1. Create a Stripe account at stripe.com
2. Get your **Secret Key** from Dashboard > Developers > API Keys
3. Create two Products in Dashboard > Products:
   - **Basic Plan**: $15/month recurring → copy the Price ID
   - **Pro Plan**: $99/month recurring → copy the Price ID
4. Set up a Webhook endpoint at Dashboard > Webhooks:
   - URL: `https://your-server.com/billing/webhook`
   - Events to listen for: `checkout.session.completed`, `invoice.paid`
   - Copy the **Signing Secret**

---

## NOWPayments (Phase 3 - crypto payments)

| Variable | Where to get it | Used for |
|---|---|---|
| `NOWPAYMENTS_API_KEY` | [nowpayments.io](https://nowpayments.io) > Dashboard > API Keys | Creating crypto payment invoices, checking status |
| `NOWPAYMENTS_IPN_SECRET` | NOWPayments Dashboard > IPN Settings | Verifying crypto webhook (IPN) signatures |
| `CRYPTO_IPN_CALLBACK_URL` | Your own URL (e.g. `https://your-server.com/billing/crypto_webhook`) | NOWPayments sends payment confirmations here |

### NOWPayments setup steps:
1. Create an account at nowpayments.io
2. Go to Dashboard > Store Settings > API Keys → create a new key
3. Go to Dashboard > Store Settings > IPN Settings:
   - Set the IPN callback URL to `https://your-server.com/billing/crypto_webhook`
   - Copy the **IPN Secret Key**
4. Supported coins: 300+ including BTC, ETH, SOL, USDC, USDT, DOGE, LTC, XMR, MATIC, AVAX, etc.

---

## Redis (Phase 2+ - async processing)

| Variable | Where to get it | Used for |
|---|---|---|
| `REDIS_URL` | Local: `redis://localhost:6379/0`; Cloud: Redis Cloud, Upstash, etc. | Celery task queue for async receipt processing |

---

## Optional / Legacy

| Variable | Where to get it | Used for |
|---|---|---|
| `API_KEYS` | Self-defined | Legacy comma-separated API keys (agents can self-register instead via `/register_agent`) |

---

## Example .env file (DO NOT COMMIT)

```bash
# Core
ANTHROPIC_API_KEY=sk-ant-api03-...

# Stripe
STRIPE_SECRET_KEY=sk_test_...
STRIPE_WEBHOOK_SECRET=whsec_...
STRIPE_BASIC_PRICE_ID=price_...
STRIPE_PRO_PRICE_ID=price_...

# NOWPayments (Crypto)
NOWPAYMENTS_API_KEY=...
NOWPAYMENTS_IPN_SECRET=...
CRYPTO_IPN_CALLBACK_URL=https://your-server.com/billing/crypto_webhook

# Redis
REDIS_URL=redis://localhost:6379/0
```

---

## Security notes

- All secrets are read from environment variables only -- never hardcoded
- The `.gitignore` excludes `.env` files
- API keys for agents are generated server-side with `secrets.token_urlsafe(32)` and prefixed with `rct_`
- Stripe webhook signatures are verified using `stripe.Webhook.construct_event()`
- NOWPayments IPN signatures are verified with HMAC-SHA512
- No secret is ever returned in API responses (agent API keys are only shown once at registration)
