from __future__ import annotations

import asyncio
import logging

import httpx

import db

logger = logging.getLogger(__name__)

# Persistent async client for webhook delivery
_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(timeout=10)
    return _client


async def dispatch_event(api_key: str, event_type: str, payload: dict) -> None:
    """Send webhook to all subscribed URLs for this api_key + event_type (non-blocking)."""
    subs = db.get_webhook_subscriptions(api_key)
    tasks = []
    for sub in subs:
        if event_type in sub["events"]:
            tasks.append(_send(sub["url"], event_type, payload))
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


async def _send(url: str, event_type: str, payload: dict) -> None:
    body = {"event": event_type, "data": payload}
    try:
        client = _get_client()
        resp = await client.post(url, json=body)
        resp.raise_for_status()
    except Exception:
        logger.warning("Webhook delivery failed to %s", url, exc_info=True)


def dispatch_event_background(api_key: str, event_type: str, payload: dict) -> None:
    """Fire-and-forget: schedule webhook dispatch without blocking the caller."""
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(dispatch_event(api_key, event_type, payload))
    except RuntimeError:
        pass  # no event loop running (e.g. in Celery worker)


async def check_low_balance(api_key: str, threshold: int = 5) -> None:
    """Fire a low_balance webhook if credits drop below threshold."""
    balance = db.get_credit_balance(api_key)
    if balance <= threshold:
        dispatch_event_background(api_key, "low_balance", {
            "credits_remaining": balance,
            "buy_credits_url": "/billing/buy_credits",
        })
