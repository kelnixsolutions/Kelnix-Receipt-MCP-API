from __future__ import annotations

import os
from typing import Any

import httpx

NOWPAYMENTS_API_KEY = os.environ.get("NOWPAYMENTS_API_KEY", "")
NOWPAYMENTS_IPN_SECRET = os.environ.get("NOWPAYMENTS_IPN_SECRET", "")
NOWPAYMENTS_BASE = "https://api.nowpayments.io/v1"

# Persistent async client — reused across requests to avoid connection overhead
_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            base_url=NOWPAYMENTS_BASE,
            headers={"x-api-key": NOWPAYMENTS_API_KEY, "Content-Type": "application/json"},
            timeout=15,
        )
    return _client


async def get_available_currencies() -> list[str]:
    """Return list of supported cryptocurrency tickers."""
    client = _get_client()
    resp = await client.get("/currencies")
    resp.raise_for_status()
    return resp.json().get("currencies", [])


async def get_estimated_price(
    fiat_amount: float, fiat_currency: str, crypto_currency: str
) -> dict[str, Any]:
    """Get estimated crypto amount for a given fiat amount."""
    client = _get_client()
    resp = await client.get(
        "/estimate",
        params={
            "amount": fiat_amount,
            "currency_from": fiat_currency.lower(),
            "currency_to": crypto_currency.lower(),
        },
    )
    if resp.status_code != 200:
        raise ValueError(
            f"NOWPayments estimate failed ({resp.status_code}). "
            "Check that NOWPAYMENTS_API_KEY is set correctly."
        )
    data = resp.json()
    est = float(data.get("estimated_amount", 0))
    return {
        "estimated_amount": est,
        "rate": fiat_amount / est if est > 0 else 0,
    }


async def create_payment(
    fiat_amount: float,
    fiat_currency: str,
    crypto_currency: str,
    order_id: str,
    order_description: str,
    ipn_callback_url: str | None = None,
) -> dict[str, Any]:
    """Create a NOWPayments invoice/payment."""
    payload: dict[str, Any] = {
        "price_amount": fiat_amount,
        "price_currency": fiat_currency.lower(),
        "pay_currency": crypto_currency.lower(),
        "order_id": order_id,
        "order_description": order_description,
    }
    if ipn_callback_url:
        payload["ipn_callback_url"] = ipn_callback_url

    client = _get_client()
    resp = await client.post("/payment", json=payload)
    if resp.status_code == 400:
        error = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
        if error.get("code") == "AMOUNT_MINIMAL_ERROR":
            raise ValueError(
                f"Amount too low for {crypto_currency.upper()}. "
                f"Try a larger credit pack or use a stablecoin like USDT or USDC."
            )
        raise ValueError(f"Payment creation failed: {error.get('message', resp.text)}")
    if resp.status_code not in (200, 201):
        raise ValueError(
            f"NOWPayments payment creation failed ({resp.status_code}). "
            "Check that NOWPAYMENTS_API_KEY is set correctly."
        )
    data = resp.json()

    return {
        "payment_id": str(data["payment_id"]),
        "pay_address": data.get("pay_address", ""),
        "pay_amount": float(data.get("pay_amount", 0)),
        "pay_currency": data.get("pay_currency", crypto_currency).upper(),
        "price_amount": fiat_amount,
        "price_currency": fiat_currency.upper(),
        "purchase_id": str(data.get("purchase_id", "")),
        "payment_status": data.get("payment_status", "waiting"),
        "expiration_estimate_date": data.get("expiration_estimate_date", ""),
    }


async def get_payment_status(payment_id: str) -> dict[str, Any]:
    """Check status of an existing payment."""
    client = _get_client()
    resp = await client.get(f"/payment/{payment_id}")
    if resp.status_code != 200:
        raise ValueError(
            f"NOWPayments status check failed ({resp.status_code}). "
            "Check that NOWPAYMENTS_API_KEY is set correctly."
        )
    data = resp.json()

    return {
        "payment_id": str(data["payment_id"]),
        "payment_status": data.get("payment_status", "unknown"),
        "pay_amount": float(data.get("pay_amount", 0)),
        "actually_paid": float(data.get("actually_paid", 0)),
        "pay_currency": data.get("pay_currency", "").upper(),
        "price_amount": float(data.get("price_amount", 0)),
        "price_currency": data.get("price_currency", "").upper(),
        "outcome_amount": float(data.get("outcome_amount", 0)),
        "outcome_currency": data.get("outcome_currency", "").upper(),
    }


def verify_ipn_signature(payload: dict, received_sig: str) -> bool:
    """Verify NOWPayments IPN callback signature."""
    if not NOWPAYMENTS_IPN_SECRET:
        return True  # skip verification in dev

    import hashlib
    import hmac
    import json

    sorted_payload = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    expected = hmac.HMAC(
        NOWPAYMENTS_IPN_SECRET.encode(),
        sorted_payload.encode(),
        hashlib.sha512,
    ).hexdigest()
    return hmac.compare_digest(expected, received_sig)
