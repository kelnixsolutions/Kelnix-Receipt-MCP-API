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
from fastapi.responses import JSONResponse

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
    if not _LEGACY_KEYS:
        _LEGACY_KEYS.add("dev-key-change-me")


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
                "subscribe_url": "/billing/subscribe",
            },
        )
    await check_low_balance(key)
    return key


CreditAuth = Depends(require_credits)


# ── App lifecycle ────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    _load_legacy_keys()
    db.init_db()
    yield


app = FastAPI(
    title="Receipt Accounting Entry MCP Server",
    version="3.1.0",
    description=(
        "Agent-native MCP server that converts receipt images/PDFs into "
        "structured accounting-ready JSON. Discover tools at /mcp. "
        "Phase 3: credit billing, Stripe + crypto payments, agent registration, webhooks."
    ),
    lifespan=lifespan,
)


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
            "name": "Receipt Accounting Entry",
            "description": (
                "Convert receipt images and PDFs into structured, accounting-ready JSON. "
                "8 tools: upload, process, extract, categorize, GL account suggestion. "
                "Supports 300+ crypto payments. 50 free credits on signup."
            ),
            "version": "3.1.0",
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
            "source": "https://github.com/TiagoX9/Receipt-Accounting-Entry-MCP-Server",
        },
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
    _key: str = CreditAuth,
    file: UploadFile | None = File(None),
    url: str | None = Form(None),
    idempotency_key: str | None = Form(None),
):
    """Upload + process a receipt in one call. Costs 1 credit. Supports idempotency."""
    if idempotency_key:
        cached = db.get_idempotent_result(idempotency_key, _key)
        if cached is not None:
            return JSONResponse(content=cached)

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


# ── Health ───────────────────────────────────────────────────────────────

@app.get("/health", tags=["System"])
async def health():
    return {"status": "ok", "version": "3.1.0"}
