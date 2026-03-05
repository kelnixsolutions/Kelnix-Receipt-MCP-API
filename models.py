from __future__ import annotations

import enum
from typing import Optional

from pydantic import BaseModel, Field


# ── Request / option models ──────────────────────────────────────────────

class UploadReceiptRequest(BaseModel):
    url: Optional[str] = Field(None, description="Public URL of the receipt image/PDF")
    mime_type: str = Field(
        ...,
        description="MIME type of the file (e.g. image/png, image/jpeg, application/pdf)",
    )


class ProcessOptions(BaseModel):
    company_context: Optional[str] = Field(
        None, description="Brief description of the company for better categorisation"
    )
    preferred_currency: Optional[str] = Field(
        None, description="ISO 4217 currency code the caller prefers (e.g. USD, EUR)"
    )
    force_category: Optional[str] = Field(
        None, description="Override the auto-detected expense category"
    )


class ProcessReceiptRequest(BaseModel):
    receipt_id: str
    options: Optional[ProcessOptions] = None


class SuggestGLAccountRequest(BaseModel):
    expense_json: dict = Field(..., description="Structured expense dict from process_receipt")
    chart_of_accounts_snippet: Optional[str] = Field(
        None, description="Partial chart of accounts to match against"
    )


class GetReceiptMarkdownRequest(BaseModel):
    receipt_id: str


# ── Response models ──────────────────────────────────────────────────────

class UploadReceiptResponse(BaseModel):
    receipt_id: str


class LineItem(BaseModel):
    description: str
    amount: float


class TaxItem(BaseModel):
    type: str
    amount: float


class ConfidenceScores(BaseModel):
    merchant: float = Field(ge=0, le=1)
    date: float = Field(ge=0, le=1)
    total_amount: float = Field(ge=0, le=1)
    currency: float = Field(ge=0, le=1)
    line_items: float = Field(ge=0, le=1)
    taxes: float = Field(ge=0, le=1)
    category_guess: float = Field(ge=0, le=1)


class StructuredExpense(BaseModel):
    merchant: str
    date: str = Field(description="ISO 8601 date string")
    total_amount: float
    currency: str = Field(description="ISO 4217 currency code")
    line_items: list[LineItem]
    taxes: list[TaxItem]
    category_guess: str
    confidence_scores: ConfidenceScores
    reasoning: str


class ProcessReceiptResponse(BaseModel):
    receipt_id: str
    structured_expense: StructuredExpense


class GetReceiptMarkdownResponse(BaseModel):
    receipt_id: str
    markdown: str


class SuggestGLAccountResponse(BaseModel):
    account_code: str
    account_name: str
    confidence: float = Field(ge=0, le=1)
    reasoning: str


# ── Receipt status enum ─────────────────────────────────────────────────

class ReceiptStatus(str, enum.Enum):
    uploaded = "uploaded"
    processing = "processing"
    processed = "processed"
    failed = "failed"


# ── Agent registration ──────────────────────────────────────────────────

class RegisterAgentRequest(BaseModel):
    agent_name: str = Field(..., description="Name for this agent")
    org_id: Optional[str] = Field(None, description="Organisation identifier")


class RegisterAgentResponse(BaseModel):
    api_key: str
    agent_name: str
    org_id: Optional[str]
    stripe_customer_id: Optional[str]
    free_credits: int


# ── Billing ─────────────────────────────────────────────────────────────

class BuyCreditsRequest(BaseModel):
    credits: int = Field(
        ...,
        description="Number of credits to purchase. Valid packs: 100, 500, 1000, 5000, 10000",
    )


class BuyCreditsResponse(BaseModel):
    checkout_url: str
    session_id: str


class SubscribeRequest(BaseModel):
    plan: str = Field(
        ..., description="Subscription plan: 'basic' (200 credits/mo, $15) or 'pro' (2000 credits/mo, $99)"
    )


class SubscribeResponse(BaseModel):
    checkout_url: str
    session_id: str


class CreditHistoryEntry(BaseModel):
    delta: int
    reason: str
    created_at: str


class BalanceResponse(BaseModel):
    credits: int
    plan: str
    history: list[CreditHistoryEntry]


class CheckBalanceResponse(BaseModel):
    credits: int
    plan: str


# ── Webhooks ────────────────────────────────────────────────────────────

class SubscribeWebhookRequest(BaseModel):
    url: str = Field(..., description="URL to POST webhook events to")
    events: list[str] = Field(
        ...,
        description="Events to subscribe to: low_balance, processing_complete",
    )


class SubscribeWebhookResponse(BaseModel):
    subscription_id: int
    url: str
    events: list[str]


# ── Crypto payments ─────────────────────────────────────────────────────

class BuyCreditsCryptoRequest(BaseModel):
    credits: Optional[int] = Field(
        None,
        description="Number of credits to buy (uses standard pack pricing). Provide this OR fiat_usd.",
    )
    fiat_usd: Optional[float] = Field(
        None,
        description="Exact USD amount to pay. Provide this OR credits.",
    )
    preferred_coin: Optional[str] = Field(
        "btc",
        description="Cryptocurrency to pay with (e.g. btc, eth, sol, usdc, usdt, doge, ltc, etc.)",
    )


class BuyCreditsCryptoResponse(BaseModel):
    payment_id: str
    quoted_crypto_amount: float
    currency: str
    address: str
    expiry: str
    fiat_locked: float
    rate_used: float
    credits: int


class CheckPaymentStatusRequest(BaseModel):
    payment_id: str


class CheckPaymentStatusResponse(BaseModel):
    payment_id: str
    status: str
    pay_amount: float
    actually_paid: float
    pay_currency: str
    fiat_locked: float
    credits: int


# ── List receipts ──────────────────────────────────────────────────────

class ListReceiptsRequest(BaseModel):
    limit: int = Field(50, ge=1, le=200, description="Max receipts to return")
    status: Optional[str] = Field(None, description="Filter by status: uploaded, processing, processed, failed")


class ListReceiptsResponse(BaseModel):
    receipts: list[dict]


# ── Upload and process combo ──────────────────────────────────────────

class UploadAndProcessRequest(BaseModel):
    url: Optional[str] = Field(None, description="Public URL of the receipt image/PDF")
    mime_type: str = Field(..., description="MIME type of the file")
    options: Optional[ProcessOptions] = None
    idempotency_key: Optional[str] = Field(None, description="Unique key to prevent duplicate processing")


class UploadAndProcessResponse(BaseModel):
    receipt_id: str
    structured_expense: StructuredExpense


# ── Async processing ────────────────────────────────────────────────────

class AsyncProcessReceiptResponse(BaseModel):
    receipt_id: str
    task_id: str
    status: str = "queued"
