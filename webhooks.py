from __future__ import annotations

import logging

import httpx

import db

logger = logging.getLogger(__name__)


def dispatch_event(api_key: str, event_type: str, payload: dict) -> None:
    """Send webhook to all subscribed URLs for this api_key + event_type."""
    subs = db.get_webhook_subscriptions(api_key)
    for sub in subs:
        if event_type in sub["events"]:
            _send(sub["url"], event_type, payload)


def _send(url: str, event_type: str, payload: dict) -> None:
    body = {"event": event_type, "data": payload}
    try:
        with httpx.Client(timeout=10) as client:
            resp = client.post(url, json=body)
            resp.raise_for_status()
    except Exception:
        logger.warning("Webhook delivery failed to %s", url, exc_info=True)


def check_low_balance(api_key: str, threshold: int = 5) -> None:
    """Fire a low_balance webhook if credits drop below threshold."""
    balance = db.get_credit_balance(api_key)
    if balance <= threshold:
        dispatch_event(api_key, "low_balance", {
            "credits_remaining": balance,
            "buy_credits_url": "/billing/buy_credits",
        })
