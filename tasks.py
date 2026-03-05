from __future__ import annotations

import asyncio
import os

from celery import Celery

import db
from webhooks import dispatch_event

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

celery_app = Celery("receipt_tasks", broker=REDIS_URL, backend=REDIS_URL)
celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_track_started=True,
    result_expires=3600,
    broker_connection_timeout=4,
    broker_connection_retry_on_startup=False,
)


@celery_app.task(bind=True, max_retries=2, default_retry_delay=10)
def process_receipt_async(
    self,
    receipt_id: str,
    api_key: str,
    company_context: str | None = None,
    preferred_currency: str | None = None,
    force_category: str | None = None,
) -> dict:
    """Run receipt processing in a Celery worker."""
    from tools import process_receipt as _process  # deferred to avoid circular import

    try:
        loop = asyncio.new_event_loop()
        result = loop.run_until_complete(
            _process(receipt_id, company_context, preferred_currency, force_category)
        )
        payload = result.model_dump()

        dispatch_event(api_key, "processing_complete", {
            "receipt_id": receipt_id,
            "status": "processed",
        })

        return payload
    except Exception as exc:
        db.update_receipt(receipt_id, status="failed")
        dispatch_event(api_key, "processing_complete", {
            "receipt_id": receipt_id,
            "status": "failed",
            "error": str(exc),
        })
        raise self.retry(exc=exc)
