from __future__ import annotations

import os
import uuid
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import (
    Depends,
    FastAPI,
    File,
    Form,
    Header,
    HTTPException,
    Request,
    UploadFile,
)
from fastapi.responses import FileResponse, JSONResponse

import billing
import db
import tools
from models import (
    AsyncProcessReceiptResponse,
    BalanceResponse,
    BuyCreditsCryptoRequest,
    BuyCreditsCryptoResponse,
    BuyCreditsRequest,
    BuyCreditsResponse,
    CheckBalanceResponse,
    CheckPaymentStatusRequest,
    CheckPaymentStatusResponse,
    CreditHistoryEntry,
    GetReceiptMarkdownRequest,
    GetReceiptMarkdownResponse,
    ListReceiptsRequest,
    ListReceiptsResponse,
    ProcessReceiptRequest,
    ProcessReceiptResponse,
    RegisterAgentRequest,
    RegisterAgentResponse,
    SubscribeRequest,
    SubscribeResponse,
    SubscribeWebhookRequest,
    SubscribeWebhookResponse,
    SuggestGLAccountRequest,
    SuggestGLAccountResponse,
    UploadAndProcessResponse,
    UploadReceiptResponse,
)
from webhooks import check_low_balance

# ── Legacy env-var API keys (Phase 1 compat) ────────────────────────────

_LEGACY_KEYS: set[str] = set()


def _load_legacy_keys() -> None:
    raw = os.environ.get("API_KEYS", "")
    if raw:
        _LEGACY_KEYS.update(k.strip() for k in raw.split(",") if k.strip())


# ── Auth dependency ─────────────────────────────────────────────────────

async def verify_api_key(x_api_key: Annotated[str, Header()]) -> str:
    if x_api_key in _LEGACY_KEYS:
        return x_api_key
    if db.api_key_exists(x_api_key):
        return x_api_key
    raise HTTPException(status_code=401, detail="Invalid API key")


Auth = Depends(verify_api_key)


# ── Credit-check middleware for paid tools ──────────────────────────────

async def require_credits(x_api_key: Annotated[str, Header()]) -> str:
    """Verify key AND check balance. Used on paid endpoints."""
    key = await verify_api_key(x_api_key)
    try:
        billing.check_and_deduct(key, cost=1)
    except ValueError as e:
        raise HTTPException(
            status_code=402,
            detail={
                "error": str(e),
                "buy_credits_url": "/billing/buy_credits",
                "buy_credits_crypto_url": "/billing/buy_credits_crypto",
                "subscribe_url": "/billing/subscribe",
                "pricing_url": "/pricing",
                "cheapest_option": {"credits": 100, "price_usd": 5.00},
            },
        )
    await check_low_balance(key)
    return key


CreditAuth = Depends(require_credits)


# ── App lifecycle ────────────────────────────────────────────────────────

from mcp_server import mcp as _mcp_server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from starlette.applications import Starlette
from starlette.routing import Mount

_mcp_session_manager = StreamableHTTPSessionManager(
    app=_mcp_server._mcp_server,
    stateless=True,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    _load_legacy_keys()
    db.init_db()
    async with _mcp_session_manager.run():
        yield


app = FastAPI(
    title="Kelnix Receipt MCP API",
    version="3.3.0",
    description=(
        "Turn any receipt into structured, accounting-ready JSON with one API call. "
        "AI vision extracts merchant, date, line items, tax, totals, and suggests GL accounts. "
        "Built for expense automation agents. 50 free credits, no card required."
    ),
    lifespan=lifespan,
)

# ── Mount MCP protocol transports for Smithery and MCP clients ────────

async def _handle_mcp_stream(scope, receive, send):
    await _mcp_session_manager.handle_request(scope, receive, send)

_mcp_stream_app = Starlette(
    routes=[Mount("/mcp", app=_handle_mcp_stream)],
)
app.mount("/stream", _mcp_stream_app)
app.mount("/sse", _mcp_server.sse_app())


# ── Request ID middleware ────────────────────────────────────────────────

@app.middleware("http")
async def add_request_id(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID", uuid.uuid4().hex[:12])
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response


# ── MCP discovery endpoint ──────────────────────────────────────────────

@app.get("/mcp", tags=["MCP"])
async def mcp_tools():
    """Return the full MCP tool catalogue for agent discovery."""
    return JSONResponse(content=tools.get_mcp_tools())


# ── Well-known MCP discovery (domain-level) ──────────────────────────

@app.get("/.well-known/mcp.json", tags=["MCP"])
async def well_known_mcp():
    """Standard MCP discovery endpoint. Agents hitting any domain can check
    /.well-known/mcp.json to find available MCP servers."""
    return JSONResponse(content={
        "mcp_version": "1.0",
        "server": {
            "name": "Kelnix Receipt MCP API",
            "description": (
                "Turn any receipt into structured JSON with one API call. "
                "AI vision extracts merchant, date, line items, tax, totals, and suggests GL accounts. "
                "7 tools for upload, processing, markdown export, and balance management. "
                "50 free credits on signup. Accepts cards and 300+ cryptocurrencies."
            ),
            "version": "3.3.0",
            "transport": [
                {
                    "type": "http",
                    "url": "/mcp",
                    "description": "HTTP JSON tool catalogue",
                },
                {
                    "type": "stdio",
                    "command": "python",
                    "args": ["mcp_server.py"],
                    "description": "MCP stdio transport (for Claude Desktop, Cursor, etc.)",
                },
            ],
            "tools_count": 8,
            "registration": {
                "url": "/register_agent",
                "method": "POST",
                "free_credits": 50,
                "description": "Self-service. Returns API key instantly.",
            },
            "documentation": "/docs",
            "source": "https://github.com/kelnixsolutions/Kelnix-Receipt-MCP-API",
        },
    })


@app.get("/.well-known/mcp/server-card.json", tags=["MCP"])
async def mcp_server_card():
    """Smithery-compatible MCP server card for registry discovery."""
    return JSONResponse(content={
        "name": "Kelnix Receipt MCP API",
        "description": (
            "Turn any receipt into structured, accounting-ready JSON with one API call. "
            "AI vision extracts merchant, date, line items, tax, totals, and suggests GL accounts. "
            "7 tools for the full receipt-to-journal-entry pipeline. "
            "50 free credits on signup. Accepts cards and 300+ cryptocurrencies."
        ),
        "homepage": "https://kelnix.org",
        "icon": "https://receipt-mcp-api.kelnix.org/icon.png",
        "repository": "https://github.com/kelnixsolutions/Kelnix-Receipt-MCP-API",
        "version": "3.3.0",
        "tools": [
            {"name": "upload_receipt", "description": "Upload receipt image/PDF"},
            {"name": "process_receipt", "description": "Extract structured data with AI vision"},
            {"name": "upload_and_process", "description": "Upload + process in one call"},
            {"name": "get_receipt_markdown", "description": "Get processed receipt as Markdown"},
            {"name": "suggest_gl_account", "description": "AI-suggest GL account code"},
            {"name": "check_balance", "description": "Check credits and plan"},
            {"name": "list_receipts", "description": "List receipts with filters"},
            {"name": "buy_credits_crypto", "description": "Buy credits with 300+ cryptocurrencies"},
        ],
        "contact": "info@kelnix.org",
    })


# ── Server icon ──────────────────────────────────────────────────────────

@app.get("/icon.png", tags=["System"])
async def server_icon():
    """Server icon for registry listings."""
    icon_path = os.path.join(os.path.dirname(__file__), "Kelnix Receipt MCP.png")
    if os.path.exists(icon_path):
        return FileResponse(icon_path, media_type="image/png")
    raise HTTPException(status_code=404, detail="Icon not found")


# ── Public pricing (no auth) ────────────────────────────────────────────

@app.get("/pricing", tags=["Public"])
async def pricing():
    """Public pricing page. No auth required. Agents and humans can see all prices."""
    return JSONResponse(content={
        "currency": "USD",
        "credit_packs": [
            {"credits": 100, "price": 5.00, "per_credit": 0.050},
            {"credits": 500, "price": 20.00, "per_credit": 0.040},
            {"credits": 1000, "price": 40.00, "per_credit": 0.040},
            {"credits": 5000, "price": 150.00, "per_credit": 0.030},
            {"credits": 10000, "price": 300.00, "per_credit": 0.030},
        ],
        "subscriptions": [
            {"plan": "free", "price": 0, "credits_per_month": 50, "note": "One-time on signup"},
            {"plan": "basic", "price": 15.00, "credits_per_month": 200},
            {"plan": "pro", "price": 99.00, "credits_per_month": 2000},
        ],
        "tool_costs": {
            "upload_receipt": {"credits": 0, "note": "free"},
            "process_receipt": {"credits": 1},
            "upload_and_process": {"credits": 1},
            "get_receipt_markdown": {"credits": 0, "note": "free"},
            "suggest_gl_account": {"credits": 1},
            "check_balance": {"credits": 0, "note": "free"},
            "list_receipts": {"credits": 0, "note": "free"},
        },
        "tax_note": "Prices exclude applicable taxes (VAT/sales tax). Tax is calculated at checkout based on your location.",
        "buy_credits": "/billing/buy_credits",
        "buy_credits_crypto": "/billing/buy_credits_crypto",
        "subscribe": "/billing/subscribe",
    })


# ── Legal pages ──────────────────────────────────────────────────────────

@app.get("/legal/terms", tags=["Legal"])
async def terms_of_service():
    """Terms of Service for the Kelnix Receipt MCP API."""
    terms_url = os.environ.get("TERMS_URL", "")
    return JSONResponse(content={
        "service": "Kelnix Receipt MCP API",
        "effective_date": "2026-03-06",
        "terms": {
            "1_acceptance": (
                "By registering an agent or using this API, you agree to these terms. "
                "If you do not agree, do not use the service."
            ),
            "2_service_description": (
                "We provide an API that converts receipt images and PDFs into structured "
                "accounting-ready JSON using AI vision. The service is sold on a credit-based model."
            ),
            "3_credits_and_billing": (
                "Credits are non-refundable digital units used to pay for API calls. "
                "1 credit = 1 receipt processing call. Credits do not expire. "
                "Prices are in USD and exclude applicable taxes. "
                "Tax (VAT/sales tax) is calculated at checkout based on your billing location."
            ),
            "4_free_tier": (
                "New agents receive 50 free credits on registration. "
                "Free credits are subject to the same terms as purchased credits."
            ),
            "5_api_usage": (
                "You may use the API for lawful business purposes only. "
                "You must not abuse the service, exceed rate limits, or attempt to circumvent billing. "
                "We reserve the right to suspend accounts that violate these terms."
            ),
            "6_data_handling": (
                "Uploaded receipt images are stored temporarily for processing and may be "
                "deleted after 30 days. We do not sell or share your receipt data with third parties. "
                "Receipt data is sent to Anthropic's API for AI processing and is subject to "
                "Anthropic's data usage policies."
            ),
            "7_accuracy_disclaimer": (
                "AI-extracted receipt data is provided as-is. While we aim for high accuracy, "
                "you should verify extracted data before using it for accounting or tax purposes. "
                "We are not liable for errors in AI-generated output."
            ),
            "8_payment_processing": (
                "Card payments are processed by Stripe. Cryptocurrency payments are processed "
                "by NOWPayments. We do not store your payment card details. "
                "All transactions are final. Refunds are handled on a case-by-case basis."
            ),
            "9_liability": (
                "The service is provided 'as is' without warranties. We are not liable for "
                "indirect, incidental, or consequential damages arising from use of the service."
            ),
            "10_changes": (
                "We may update these terms at any time. Continued use after changes "
                "constitutes acceptance of the updated terms."
            ),
        },
        "contact": os.environ.get("SUPPORT_EMAIL", "info@kelnix.org"),
        "full_terms_url": terms_url or None,
    })


@app.get("/legal/privacy", tags=["Legal"])
async def privacy_policy():
    """Privacy Policy for the Kelnix Receipt MCP API."""
    privacy_url = os.environ.get("PRIVACY_URL", "")
    return JSONResponse(content={
        "service": "Kelnix Receipt MCP API",
        "effective_date": "2026-03-06",
        "policy": {
            "1_data_collected": {
                "agent_registration": ["agent_name", "org_id (optional)"],
                "receipt_processing": ["receipt images/PDFs (temporarily stored)", "extracted text and amounts"],
                "billing": ["Stripe customer ID", "transaction history", "credit balance"],
                "technical": ["API key", "IP address (in server logs)", "request timestamps"],
            },
            "2_how_we_use_data": [
                "Process receipt images using Anthropic's Claude AI API",
                "Manage your credit balance and billing",
                "Send webhook notifications you subscribed to",
                "Improve service reliability and performance",
            ],
            "3_third_party_sharing": {
                "anthropic": "Receipt images are sent to Anthropic's API for AI processing",
                "stripe": "Billing data is shared with Stripe for payment processing",
                "nowpayments": "Crypto payment data is shared with NOWPayments for payment processing",
                "no_other_sharing": "We do not sell or share your data with any other third parties",
            },
            "4_data_retention": {
                "receipt_images": "Stored for up to 30 days, then deleted",
                "extracted_data": "Stored indefinitely unless you request deletion",
                "billing_records": "Stored for 7 years (tax compliance)",
                "server_logs": "Retained for 90 days",
            },
            "5_your_rights": [
                "Request a copy of your data",
                "Request deletion of your data",
                "Request correction of inaccurate data",
                "EU/EEA residents have additional rights under GDPR",
            ],
            "6_security": (
                "API keys are generated using cryptographically secure random tokens. "
                "All communication is encrypted via HTTPS. "
                "We do not store payment card details (handled by Stripe)."
            ),
            "7_cookies": "This API does not use cookies. There is no web frontend.",
            "8_children": "This service is not intended for use by anyone under 18.",
            "9_changes": "We may update this policy. Check this endpoint for the latest version.",
        },
        "contact": os.environ.get("SUPPORT_EMAIL", "info@kelnix.org"),
        "full_privacy_url": privacy_url or None,
    })


# ── Agent registration ──────────────────────────────────────────────────

@app.post(
    "/register_agent",
    response_model=RegisterAgentResponse,
    tags=["Agents"],
)
async def register_agent(body: RegisterAgentRequest):
    """Register a new agent. Returns API key + 50 free credits + Stripe customer link."""
    try:
        result = db.create_agent(body.agent_name, body.org_id)
        return RegisterAgentResponse(**result)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# ── Billing endpoints ───────────────────────────────────────────────────

@app.post(
    "/billing/buy_credits",
    response_model=BuyCreditsResponse,
    tags=["Billing"],
)
async def buy_credits(body: BuyCreditsRequest, _key: str = Auth):
    """Purchase a credit pack via Stripe Checkout. Returns a checkout URL."""
    try:
        result = billing.create_checkout_session(_key, body.credits)
        return BuyCreditsResponse(**result)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post(
    "/billing/subscribe",
    response_model=SubscribeResponse,
    tags=["Billing"],
)
async def subscribe(body: SubscribeRequest, _key: str = Auth):
    """Subscribe to a monthly plan (basic or pro) via Stripe Checkout."""
    try:
        result = billing.create_subscription_session(_key, body.plan)
        return SubscribeResponse(**result)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/billing/webhook", tags=["Billing"])
async def billing_webhook(request: Request):
    """Stripe webhook receiver. Updates credits on successful payment."""
    payload = await request.body()
    sig = request.headers.get("stripe-signature", "")
    try:
        result = billing.handle_stripe_event(payload, sig)
        return result
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post(
    "/billing/buy_credits_crypto",
    response_model=BuyCreditsCryptoResponse,
    tags=["Billing"],
)
async def buy_credits_crypto(body: BuyCreditsCryptoRequest, _key: str = Auth):
    """Purchase credits with any of 300+ cryptocurrencies. Fiat value locked at quote time."""
    try:
        result = await billing.create_crypto_payment(
            _key, body.credits, body.fiat_usd, body.preferred_coin or "btc"
        )
        return BuyCreditsCryptoResponse(**result)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post(
    "/billing/check_payment_status",
    response_model=CheckPaymentStatusResponse,
    tags=["Billing"],
)
async def check_payment_status(body: CheckPaymentStatusRequest, _key: str = Auth):
    """Check status of a crypto payment. Credits auto-granted on confirmation."""
    try:
        result = await billing.check_crypto_payment_status(body.payment_id)
        return CheckPaymentStatusResponse(**result)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.post("/billing/crypto_webhook", tags=["Billing"])
async def crypto_webhook(request: Request):
    """NOWPayments IPN callback. Grants credits on confirmed payments."""
    payload = await request.json()
    sig = request.headers.get("x-nowpayments-sig", "")
    try:
        result = billing.handle_crypto_ipn(payload, sig)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get(
    "/billing/balance",
    response_model=BalanceResponse,
    tags=["Billing"],
)
async def balance(_key: str = Auth):
    """Get current credit balance, plan, and recent transaction history."""
    agent = db.get_agent_by_api_key(_key)
    plan = agent["plan"] if agent else "free"
    credits = db.get_credit_balance(_key)
    history_raw = db.get_credit_history(_key)
    history = [CreditHistoryEntry(**h) for h in history_raw]
    return BalanceResponse(credits=credits, plan=plan, history=history)


# ── Webhook subscriptions ───────────────────────────────────────────────

@app.post(
    "/subscribe_webhook",
    response_model=SubscribeWebhookResponse,
    tags=["Webhooks"],
)
async def subscribe_webhook(body: SubscribeWebhookRequest, _key: str = Auth):
    """Subscribe to webhook events (low_balance, processing_complete)."""
    valid_events = {"low_balance", "processing_complete"}
    invalid = set(body.events) - valid_events
    if invalid:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid events: {invalid}. Valid: {valid_events}",
        )
    sub_id = db.add_webhook_subscription(_key, body.url, body.events)
    return SubscribeWebhookResponse(
        subscription_id=sub_id, url=body.url, events=body.events
    )


# ── Integration quickstarts ─────────────────────────────────────────────

@app.get("/integrations", tags=["Agents"])
async def integrations():
    """Return quickstart snippets for LangGraph, CrewAI, and AutoGen."""
    return JSONResponse(content={
        "langgraph": {
            "description": "Use as a tool node in LangGraph",
            "snippet": (
                "from langchain_core.tools import tool\n"
                "import httpx\n\n"
                "BASE = 'https://your-server.com'\n"
                "HEADERS = {'X-API-Key': 'your-key'}\n\n"
                "@tool\n"
                "def process_receipt(receipt_id: str) -> dict:\n"
                '    \"\"\"Process a receipt and return structured expense data.\"\"\"\n'
                "    r = httpx.post(f'{BASE}/tools/process_receipt',\n"
                "        json={'receipt_id': receipt_id}, headers=HEADERS)\n"
                "    return r.json()\n"
            ),
        },
        "crewai": {
            "description": "Use as a CrewAI tool",
            "snippet": (
                "from crewai_tools import BaseTool\n"
                "import httpx\n\n"
                "class ReceiptProcessorTool(BaseTool):\n"
                "    name = 'process_receipt'\n"
                "    description = 'Extract structured data from a receipt'\n\n"
                "    def _run(self, receipt_id: str) -> dict:\n"
                "        r = httpx.post('https://your-server.com/tools/process_receipt',\n"
                "            json={'receipt_id': receipt_id},\n"
                "            headers={'X-API-Key': 'your-key'})\n"
                "        return r.json()\n"
            ),
        },
        "autogen": {
            "description": "Register as an AutoGen function",
            "snippet": (
                "import httpx\n\n"
                "def process_receipt(receipt_id: str) -> dict:\n"
                "    r = httpx.post('https://your-server.com/tools/process_receipt',\n"
                "        json={'receipt_id': receipt_id},\n"
                "        headers={'X-API-Key': 'your-key'})\n"
                "    return r.json()\n\n"
                "# Register with AutoGen agent:\n"
                "# assistant.register_function(\n"
                "#     function_map={'process_receipt': process_receipt})\n"
            ),
        },
        "raw_python": {
            "description": "Plain Python with httpx",
            "snippet": (
                "import httpx\n\n"
                "BASE = 'https://your-server.com'\n"
                "HEADERS = {'X-API-Key': 'your-key'}\n\n"
                "# 1. Register\n"
                "r = httpx.post(f'{BASE}/register_agent',\n"
                "    json={'agent_name': 'my-expense-bot'})\n"
                "api_key = r.json()['api_key']\n\n"
                "# 2. Upload\n"
                "r = httpx.post(f'{BASE}/tools/upload_receipt',\n"
                "    files={'file': open('receipt.jpg', 'rb')},\n"
                "    data={'mime_type': 'image/jpeg'},\n"
                "    headers={'X-API-Key': api_key})\n"
                "receipt_id = r.json()['receipt_id']\n\n"
                "# 3. Process\n"
                "r = httpx.post(f'{BASE}/tools/process_receipt',\n"
                "    json={'receipt_id': receipt_id},\n"
                "    headers={'X-API-Key': api_key})\n"
                "expense = r.json()['structured_expense']\n"
            ),
        },
    })


# ── Tool endpoints ──────────────────────────────────────────────────────

@app.post(
    "/tools/upload_receipt",
    response_model=UploadReceiptResponse,
    tags=["Tools"],
)
async def upload_receipt_endpoint(
    mime_type: Annotated[str, Form()],
    _key: str = Auth,
    file: UploadFile | None = File(None),
    url: str | None = Form(None),
):
    """Upload a receipt image/PDF via file or URL."""
    file_bytes: bytes | None = None
    if file is not None:
        file_bytes = await file.read()
    if file_bytes is None and url is None:
        raise HTTPException(status_code=400, detail="Provide either file or url")
    try:
        return await tools.upload_receipt(file_bytes, url, mime_type, api_key=_key)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post(
    "/tools/process_receipt",
    response_model=ProcessReceiptResponse,
    tags=["Tools"],
)
async def process_receipt_endpoint(
    body: ProcessReceiptRequest,
    _key: str = CreditAuth,
):
    """Process an uploaded receipt. Costs 1 credit. Returns 402 if insufficient balance."""
    opts = body.options
    try:
        return await tools.process_receipt(
            body.receipt_id,
            company_context=opts.company_context if opts else None,
            preferred_currency=opts.preferred_currency if opts else None,
            force_category=opts.force_category if opts else None,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        db.update_receipt(body.receipt_id, status="failed")
        raise HTTPException(status_code=500, detail=f"Processing failed: {e}")


@app.post(
    "/tools/process_receipt_async",
    response_model=AsyncProcessReceiptResponse,
    tags=["Tools"],
)
async def process_receipt_async_endpoint(
    body: ProcessReceiptRequest,
    _key: str = CreditAuth,
):
    """Queue receipt processing via Celery. Returns a task_id for polling."""
    # Quick Redis connectivity check to avoid blocking on dead connections
    import asyncio
    import socket

    redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    try:
        from urllib.parse import urlparse
        parsed = urlparse(redis_url)
        host = parsed.hostname or "localhost"
        port = parsed.port or 6379
        s = socket.create_connection((host, port), timeout=1)
        s.close()
    except (OSError, ConnectionRefusedError):
        raise HTTPException(
            status_code=503,
            detail="Async processing unavailable: cannot connect to Redis. Set REDIS_URL and ensure Redis is running.",
        )

    try:
        from tasks import process_receipt_async

        opts = body.options
        loop = asyncio.get_event_loop()
        task = await loop.run_in_executor(
            None,
            lambda: process_receipt_async.apply_async(
                args=[body.receipt_id, _key],
                kwargs={
                    "company_context": opts.company_context if opts else None,
                    "preferred_currency": opts.preferred_currency if opts else None,
                    "force_category": opts.force_category if opts else None,
                },
                retry=False,
            ),
        )
        return AsyncProcessReceiptResponse(
            receipt_id=body.receipt_id, task_id=task.id, status="queued"
        )
    except Exception as e:
        raise HTTPException(
            status_code=503,
            detail=f"Async processing unavailable (Redis/Celery not running): {type(e).__name__}: {e}",
        )


@app.get("/tasks/{task_id}", tags=["Tools"])
async def get_task_status(task_id: str, _key: str = Auth):
    """Check the status of an async processing task."""
    try:
        from tasks import celery_app

        result = celery_app.AsyncResult(task_id)
        response: dict = {"task_id": task_id, "status": result.status}
        if result.ready():
            if result.successful():
                response["result"] = result.result
            else:
                response["error"] = str(result.result)
        return response
    except Exception as e:
        raise HTTPException(
            status_code=503,
            detail=f"Task status unavailable (Redis not running): {type(e).__name__}: {e}",
        )


@app.post(
    "/tools/get_receipt_markdown",
    response_model=GetReceiptMarkdownResponse,
    tags=["Tools"],
)
async def get_receipt_markdown_endpoint(
    body: GetReceiptMarkdownRequest,
    _key: str = Auth,
):
    """Get a Markdown-formatted view of a processed receipt."""
    try:
        return await tools.get_receipt_markdown(body.receipt_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.post(
    "/tools/suggest_gl_account",
    response_model=SuggestGLAccountResponse,
    tags=["Tools"],
)
async def suggest_gl_account_endpoint(
    body: SuggestGLAccountRequest,
    _key: str = CreditAuth,
):
    """Suggest a GL account code. Costs 1 credit."""
    try:
        return await tools.suggest_gl_account(
            body.expense_json,
            chart_of_accounts_snippet=body.chart_of_accounts_snippet,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post(
    "/tools/check_balance",
    response_model=CheckBalanceResponse,
    tags=["Tools"],
)
async def check_balance_endpoint(_key: str = Auth):
    """Check your current credit balance and plan. Free to call."""
    return await tools.check_balance(_key)


# ── List receipts ────────────────────────────────────────────────────────

@app.post(
    "/tools/list_receipts",
    response_model=ListReceiptsResponse,
    tags=["Tools"],
)
async def list_receipts_endpoint(
    body: ListReceiptsRequest,
    _key: str = Auth,
):
    """List your receipts with optional status filter. Free to call."""
    return await tools.list_receipts(_key, limit=body.limit, status=body.status)


# ── Upload and process combo ─────────────────────────────────────────────

@app.post(
    "/tools/upload_and_process",
    response_model=UploadAndProcessResponse,
    tags=["Tools"],
)
async def upload_and_process_endpoint(
    mime_type: Annotated[str, Form()],
    _key: str = Auth,  # Auth only (no credit deduction yet) — idempotency checked first
    file: UploadFile | None = File(None),
    url: str | None = Form(None),
    idempotency_key: str | None = Form(None),
):
    """Upload + process a receipt in one call. Costs 1 credit. Supports idempotency."""
    # Check idempotency BEFORE deducting credits
    if idempotency_key:
        cached = db.get_idempotent_result(idempotency_key, _key)
        if cached is not None:
            return JSONResponse(content=cached)

    # Now deduct credit (only for fresh requests)
    try:
        billing.check_and_deduct(_key, cost=1)
    except ValueError as e:
        raise HTTPException(
            status_code=402,
            detail={
                "error": str(e),
                "buy_credits_url": "/billing/buy_credits",
                "buy_credits_crypto_url": "/billing/buy_credits_crypto",
                "subscribe_url": "/billing/subscribe",
                "pricing_url": "/pricing",
                "cheapest_option": {"credits": 100, "price_usd": 5.00},
            },
        )
    await check_low_balance(_key)

    file_bytes: bytes | None = None
    if file is not None:
        file_bytes = await file.read()
    if file_bytes is None and url is None:
        raise HTTPException(status_code=400, detail="Provide either file or url")

    try:
        upload_resp = await tools.upload_receipt(file_bytes, url, mime_type, api_key=_key)
        result = await tools.process_receipt(upload_resp.receipt_id)
        response = result.model_dump()

        if idempotency_key:
            db.set_idempotent_result(idempotency_key, _key, upload_resp.receipt_id, response)

        return response
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Processing failed: {e}")


# ── Admin revenue dashboard ────────────────────────────────────────────

@app.get("/admin/revenue", tags=["Admin"])
async def admin_revenue(
    admin_key: Annotated[str, Header(alias="X-Admin-Key")],
):
    """Revenue dashboard. Protected by ADMIN_KEY env var. Shows agents, credits, payments."""
    expected = os.environ.get("ADMIN_KEY", "")
    if not expected or admin_key != expected:
        raise HTTPException(status_code=403, detail="Invalid admin key")

    import sqlite3
    conn = sqlite3.connect(str(db.DB_PATH))
    conn.row_factory = sqlite3.Row

    # Agent stats
    agents = conn.execute("SELECT COUNT(*) as total FROM agents").fetchone()
    agents_by_plan = conn.execute(
        "SELECT plan, COUNT(*) as count FROM agents GROUP BY plan"
    ).fetchall()

    # Credit flow
    credits_granted = conn.execute(
        "SELECT COALESCE(SUM(delta), 0) as total FROM credits WHERE delta > 0"
    ).fetchone()
    credits_spent = conn.execute(
        "SELECT COALESCE(SUM(ABS(delta)), 0) as total FROM credits WHERE delta < 0"
    ).fetchone()

    # Revenue by source
    revenue_by_source = conn.execute("""
        SELECT
            CASE
                WHEN reason LIKE 'stripe_purchase_%' THEN 'stripe_credit_packs'
                WHEN reason LIKE 'subscription_%' THEN 'stripe_subscriptions'
                WHEN reason LIKE 'crypto_payment_%' THEN 'crypto_payments'
                WHEN reason = 'free_tier_signup' THEN 'free_signup'
                ELSE 'other'
            END as source,
            COUNT(*) as transactions,
            SUM(delta) as credits_granted
        FROM credits
        WHERE delta > 0
        GROUP BY source
        ORDER BY credits_granted DESC
    """).fetchall()

    # Crypto payment stats
    crypto_stats = conn.execute("""
        SELECT
            status,
            COUNT(*) as count,
            COALESCE(SUM(locked_fiat_usd), 0) as total_usd
        FROM crypto_payments
        GROUP BY status
    """).fetchall()

    # Recent transactions (last 20 credit additions)
    recent_purchases = conn.execute("""
        SELECT c.api_key, c.delta, c.reason, c.created_at, a.agent_name
        FROM credits c
        LEFT JOIN agents a ON c.api_key = a.api_key
        WHERE c.delta > 0 AND c.reason != 'free_tier_signup'
        ORDER BY c.created_at DESC
        LIMIT 20
    """).fetchall()

    # Top agents by spend
    top_agents = conn.execute("""
        SELECT
            a.agent_name,
            a.plan,
            a.created_at as registered,
            COALESCE(SUM(CASE WHEN c.delta < 0 THEN ABS(c.delta) ELSE 0 END), 0) as credits_used,
            COALESCE(SUM(CASE WHEN c.delta > 0 THEN c.delta ELSE 0 END), 0) as credits_received
        FROM agents a
        LEFT JOIN credits c ON a.api_key = c.api_key
        GROUP BY a.api_key
        ORDER BY credits_used DESC
        LIMIT 20
    """).fetchall()

    # Daily processing volume (last 30 days)
    daily_volume = conn.execute("""
        SELECT
            DATE(created_at) as day,
            COUNT(*) as receipts_processed
        FROM credits
        WHERE delta < 0 AND reason = 'process_receipt'
            AND created_at >= DATE('now', '-30 days')
        GROUP BY day
        ORDER BY day DESC
    """).fetchall()

    conn.close()

    return JSONResponse(content={
        "summary": {
            "total_agents": agents["total"],
            "agents_by_plan": {r["plan"]: r["count"] for r in agents_by_plan},
            "total_credits_granted": credits_granted["total"],
            "total_credits_spent": credits_spent["total"],
            "credits_in_circulation": credits_granted["total"] - credits_spent["total"],
        },
        "revenue_by_source": [
            {
                "source": r["source"],
                "transactions": r["transactions"],
                "credits_granted": r["credits_granted"],
            }
            for r in revenue_by_source
        ],
        "crypto_payments": [
            {
                "status": r["status"],
                "count": r["count"],
                "total_usd": round(r["total_usd"], 2),
            }
            for r in crypto_stats
        ],
        "recent_purchases": [
            {
                "agent": r["agent_name"],
                "credits": r["delta"],
                "reason": r["reason"],
                "date": r["created_at"],
            }
            for r in recent_purchases
        ],
        "top_agents": [
            {
                "agent": r["agent_name"],
                "plan": r["plan"],
                "registered": r["registered"],
                "credits_used": r["credits_used"],
                "credits_received": r["credits_received"],
            }
            for r in top_agents
        ],
        "daily_volume_30d": [
            {"date": r["day"], "receipts": r["receipts_processed"]}
            for r in daily_volume
        ],
        "cost_estimate": {
            "note": "Approximate API costs based on Haiku 4.5 at ~$0.007/receipt",
            "total_receipts_processed": credits_spent["total"],
            "estimated_api_cost_usd": round(credits_spent["total"] * 0.007, 2),
        },
    })


# ── Health ───────────────────────────────────────────────────────────────

@app.get("/health", tags=["System"])
async def health():
    return {"status": "ok", "version": "3.3.0"}
