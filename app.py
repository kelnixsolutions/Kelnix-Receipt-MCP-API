from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import JSONResponse

import db
import tools
from models import (
    GetReceiptMarkdownRequest,
    GetReceiptMarkdownResponse,
    ProcessReceiptRequest,
    ProcessReceiptResponse,
    SuggestGLAccountRequest,
    SuggestGLAccountResponse,
    UploadReceiptResponse,
)

# ── Auth ─────────────────────────────────────────────────────────────────

API_KEYS: set[str] = set()


def _load_api_keys() -> None:
    raw = os.environ.get("API_KEYS", "")
    if raw:
        API_KEYS.update(k.strip() for k in raw.split(",") if k.strip())
    # Always allow a dev key when no keys are configured
    if not API_KEYS:
        API_KEYS.add("dev-key-change-me")


async def verify_api_key(x_api_key: Annotated[str, Header()]) -> str:
    if x_api_key not in API_KEYS:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return x_api_key


Auth = Depends(verify_api_key)


# ── App lifecycle ────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    _load_api_keys()
    db.init_db()
    yield


app = FastAPI(
    title="Receipt Accounting Entry MCP Server",
    version="1.0.0",
    description=(
        "Agent-native MCP server that converts receipt images/PDFs into "
        "structured accounting-ready JSON. Discover available tools at /mcp."
    ),
    lifespan=lifespan,
)


# ── MCP discovery endpoint ──────────────────────────────────────────────

@app.get("/mcp", tags=["MCP"])
async def mcp_tools():
    """Return the full MCP tool catalogue for agent discovery."""
    return JSONResponse(content=tools.get_mcp_tools())


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
        return await tools.upload_receipt(file_bytes, url, mime_type)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post(
    "/tools/process_receipt",
    response_model=ProcessReceiptResponse,
    tags=["Tools"],
)
async def process_receipt_endpoint(
    body: ProcessReceiptRequest,
    _key: str = Auth,
):
    """Process an uploaded receipt with Claude vision to extract structured data."""
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
    _key: str = Auth,
):
    """Suggest a GL account code for a structured expense."""
    try:
        return await tools.suggest_gl_account(
            body.expense_json,
            chart_of_accounts_snippet=body.chart_of_accounts_snippet,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Health ───────────────────────────────────────────────────────────────

@app.get("/health", tags=["System"])
async def health():
    return {"status": "ok"}
