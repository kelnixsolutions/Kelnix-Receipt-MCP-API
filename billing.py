from __future__ import annotations

import os
from typing import Any

import stripe

import db

stripe.api_key = os.environ.get("STRIPE_SECRET_KEY", "")

CREDIT_PACKS = {
    100: 500,      # 100 credits  → $5.00  (in cents)
    500: 2000,     # 500 credits  → $20.00
    1000: 4000,    # 1000 credits → $40.00
    5000: 15000,   # 5000 credits → $150.00
    10000: 30000,  # 10000 credits→ $300.00
}

PLANS = {
    "basic": {
        "credits_per_month": 200,
        "price_cents": 1500,  # $15/mo
        "stripe_price_id": os.environ.get("STRIPE_BASIC_PRICE_ID", ""),
    },
    "pro": {
        "credits_per_month": 2000,
        "price_cents": 9900,  # $99/mo
        "stripe_price_id": os.environ.get("STRIPE_PRO_PRICE_ID", ""),
    },
}

FREE_CREDITS = 50


# ── Stripe Checkout for credit packs ────────────────────────────────────

def create_checkout_session(api_key: str, credits: int) -> dict[str, Any]:
    if credits not in CREDIT_PACKS:
        raise ValueError(
            f"Invalid credit pack. Choose from: {sorted(CREDIT_PACKS.keys())}"
        )

    agent = db.get_agent_by_api_key(api_key)
    if agent is None:
        raise ValueError("Agent not found for this API key")

    price_cents = CREDIT_PACKS[credits]
    if not stripe.api_key:
        raise ValueError("Stripe is not configured. Set STRIPE_SECRET_KEY env var.")

    session = stripe.checkout.Session.create(
        mode="payment",
        customer=agent["stripe_customer_id"] or None,
        line_items=[{
            "price_data": {
                "currency": "usd",
                "unit_amount": price_cents,
                "product_data": {
                    "name": f"{credits} Receipt Processing Credits",
                    "description": f"1 credit = 1 process_receipt call",
                },
            },
            "quantity": 1,
        }],
        metadata={"api_key": api_key, "credits": str(credits)},
        success_url=os.environ.get(
            "STRIPE_SUCCESS_URL", "https://example.com/success"
        ),
        cancel_url=os.environ.get(
            "STRIPE_CANCEL_URL", "https://example.com/cancel"
        ),
    )
    return {"checkout_url": session.url, "session_id": session.id}


# ── Stripe Checkout for subscriptions ───────────────────────────────────

def create_subscription_session(api_key: str, plan: str) -> dict[str, Any]:
    if plan not in PLANS:
        raise ValueError(f"Invalid plan. Choose from: {list(PLANS.keys())}")

    plan_info = PLANS[plan]
    if not plan_info["stripe_price_id"]:
        raise ValueError(
            f"Stripe price ID not configured for plan '{plan}'. "
            f"Set STRIPE_{plan.upper()}_PRICE_ID env var."
        )

    agent = db.get_agent_by_api_key(api_key)
    if agent is None:
        raise ValueError("Agent not found for this API key")

    if not stripe.api_key:
        raise ValueError("Stripe is not configured. Set STRIPE_SECRET_KEY env var.")

    session = stripe.checkout.Session.create(
        mode="subscription",
        customer=agent["stripe_customer_id"] or None,
        line_items=[{"price": plan_info["stripe_price_id"], "quantity": 1}],
        metadata={
            "api_key": api_key,
            "plan": plan,
            "credits_per_month": str(plan_info["credits_per_month"]),
        },
        success_url=os.environ.get(
            "STRIPE_SUCCESS_URL", "https://example.com/success"
        ),
        cancel_url=os.environ.get(
            "STRIPE_CANCEL_URL", "https://example.com/cancel"
        ),
    )
    return {"checkout_url": session.url, "session_id": session.id}


# ── Webhook handler ─────────────────────────────────────────────────────

def handle_stripe_event(payload: bytes, sig_header: str) -> dict[str, str]:
    webhook_secret = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
    if webhook_secret:
        event = stripe.Webhook.construct_event(payload, sig_header, webhook_secret)
    else:
        import json as _json
        event = stripe.Event.construct_from(_json.loads(payload), stripe.api_key)

    event_type = event["type"]

    if event_type == "checkout.session.completed":
        session = event["data"]["object"]
        meta = session.get("metadata", {})
        api_key = meta.get("api_key", "")

        if session.get("mode") == "payment":
            credits = int(meta.get("credits", 0))
            if api_key and credits:
                db.add_credits(api_key, credits, reason=f"stripe_purchase_{session['id']}")
        elif session.get("mode") == "subscription":
            credits = int(meta.get("credits_per_month", 0))
            plan = meta.get("plan", "")
            if api_key and credits:
                db.add_credits(api_key, credits, reason=f"subscription_{plan}_{session['id']}")
                db.update_agent(api_key, plan=plan)

    elif event_type == "invoice.paid":
        invoice = event["data"]["object"]
        sub = invoice.get("subscription")
        if sub:
            sub_obj = stripe.Subscription.retrieve(sub)
            meta = sub_obj.get("metadata", {})
            api_key = meta.get("api_key", "")
            credits = int(meta.get("credits_per_month", 0))
            if api_key and credits:
                db.add_credits(api_key, credits, reason=f"subscription_renewal_{invoice['id']}")

    return {"status": "ok", "event_type": event_type}


# ── Credit check ────────────────────────────────────────────────────────

def check_and_deduct(api_key: str, cost: int = 1) -> None:
    """Raise ValueError if insufficient credits. Otherwise deduct."""
    balance = db.get_credit_balance(api_key)
    if balance < cost:
        raise ValueError(
            f"Insufficient credits: {balance} available, {cost} required. "
            f"Buy more at POST /billing/buy_credits or POST /billing/buy_credits_crypto"
        )
    db.deduct_credits(api_key, cost, reason="process_receipt")


# ── Crypto helpers ──────────────────────────────────────────────────────

def fiat_for_credits(credits: int) -> float:
    """Calculate USD price for a given credit count using pack pricing."""
    if credits in CREDIT_PACKS:
        return CREDIT_PACKS[credits] / 100.0
    per_credit = 0.05  # default $0.05/credit
    return round(credits * per_credit, 2)


async def create_crypto_payment(
    api_key: str,
    credits: int | None,
    fiat_usd: float | None,
    preferred_coin: str,
) -> dict[str, Any]:
    import crypto_gateway

    agent = db.get_agent_by_api_key(api_key)
    if agent is None:
        raise ValueError("Agent not found for this API key")

    if credits and not fiat_usd:
        fiat_usd = fiat_for_credits(credits)
    elif fiat_usd and not credits:
        credits = int(fiat_usd / 0.05)  # ~$0.05/credit at default rate
    elif not credits and not fiat_usd:
        raise ValueError("Provide either credits or fiat_usd")

    estimate = await crypto_gateway.get_estimated_price(
        fiat_usd, "usd", preferred_coin
    )

    ipn_url = os.environ.get("CRYPTO_IPN_CALLBACK_URL", "")
    order_id = f"{api_key[:12]}_{credits}cr"

    payment = await crypto_gateway.create_payment(
        fiat_amount=fiat_usd,
        fiat_currency="usd",
        crypto_currency=preferred_coin,
        order_id=order_id,
        order_description=f"{credits} receipt processing credits",
        ipn_callback_url=ipn_url or None,
    )

    db.insert_crypto_payment(
        payment_id=payment["payment_id"],
        api_key=api_key,
        credits=credits,
        quoted_fiat_usd=fiat_usd,
        locked_fiat_usd=fiat_usd,
        crypto_amount=payment["pay_amount"],
        crypto_currency=payment["pay_currency"],
        pay_address=payment.get("pay_address"),
        rate_used=estimate.get("rate", 0),
    )

    return {
        "payment_id": payment["payment_id"],
        "quoted_crypto_amount": payment["pay_amount"],
        "currency": payment["pay_currency"],
        "address": payment.get("pay_address", ""),
        "expiry": payment.get("expiration_estimate_date", "~20 minutes"),
        "fiat_locked": fiat_usd,
        "rate_used": estimate.get("rate", 0),
        "credits": credits,
    }


async def check_crypto_payment_status(payment_id: str) -> dict[str, Any]:
    import crypto_gateway

    record = db.get_crypto_payment(payment_id)
    if record is None:
        raise ValueError(f"Payment {payment_id} not found")

    status = await crypto_gateway.get_payment_status(payment_id)

    if status["payment_status"] in ("finished", "confirmed") and record["status"] not in ("finished", "confirmed"):
        db.update_crypto_payment(payment_id, status=status["payment_status"])
        db.add_credits(
            record["api_key"],
            record["credits"],
            reason=f"crypto_payment_{payment_id}",
        )

    elif status["payment_status"] != record["status"]:
        db.update_crypto_payment(payment_id, status=status["payment_status"])

    return {
        "payment_id": payment_id,
        "status": status["payment_status"],
        "pay_amount": status["pay_amount"],
        "actually_paid": status["actually_paid"],
        "pay_currency": status["pay_currency"],
        "fiat_locked": record["locked_fiat_usd"],
        "credits": record["credits"],
    }


def handle_crypto_ipn(payload: dict, sig_header: str) -> dict[str, str]:
    """Handle NOWPayments IPN callback."""
    import crypto_gateway

    if not crypto_gateway.verify_ipn_signature(payload, sig_header):
        raise ValueError("Invalid IPN signature")

    payment_id = str(payload.get("payment_id", ""))
    payment_status = payload.get("payment_status", "")

    record = db.get_crypto_payment(payment_id)
    if record is None:
        return {"status": "ignored", "reason": "unknown payment_id"}

    db.update_crypto_payment(payment_id, status=payment_status)

    if payment_status in ("finished", "confirmed") and record["status"] not in ("finished", "confirmed"):
        db.add_credits(
            record["api_key"],
            record["credits"],
            reason=f"crypto_payment_{payment_id}",
        )

    return {"status": "ok", "payment_status": payment_status}
