"""
Real MCP server using the official Model Context Protocol SDK.

This exposes all receipt tools via JSON-RPC over stdio (for Claude Desktop,
Cursor, etc.) or SSE (for web-based MCP clients).

Usage:
    # stdio mode (Claude Desktop, Cursor, VS Code)
    python mcp_server.py

    # Or via the MCP CLI
    mcp run mcp_server.py
"""
from __future__ import annotations

import asyncio
import base64
import io
import json
import os
from typing import Any

from mcp.server.fastmcp import FastMCP

# ── Initialize MCP server ──────────────────────────────────────────────

mcp = FastMCP(
    "Receipt Accounting Entry",
    instructions=(
        "Convert receipt images and PDFs into structured, accounting-ready JSON. "
        "Upload receipts, extract expense data with AI vision, suggest GL accounts, "
        "and manage credits. Built for AI agents."
    ),
)

# ── Lazy-init our backend ──────────────────────────────────────────────
# Import the existing tools/db modules only when needed, so the MCP
# server stays lightweight at startup.

_initialized = False


def _ensure_init():
    global _initialized
    if not _initialized:
        import db
        db.init_db()
        _initialized = True


# ── MCP Tools ──────────────────────────────────────────────────────────

@mcp.tool()
async def upload_receipt(
    mime_type: str,
    url: str | None = None,
    file_base64: str | None = None,
) -> dict[str, Any]:
    """Upload a receipt image or PDF for later processing.

    Provide either a public URL or base64-encoded file content.
    Supports JPEG, PNG, WebP, GIF, and PDF.
    Returns a receipt_id for use with other tools.

    Args:
        mime_type: MIME type (image/jpeg, image/png, image/webp, image/gif, application/pdf)
        url: Public URL of the receipt image or PDF
        file_base64: Base64-encoded file content (alternative to URL)
    """
    _ensure_init()
    import tools as _tools

    file_bytes = None
    if file_base64:
        file_bytes = base64.b64decode(file_base64)

    result = await _tools.upload_receipt(file_bytes, url, mime_type)
    return {"receipt_id": result.receipt_id}


@mcp.tool()
async def process_receipt(
    receipt_id: str,
    company_context: str | None = None,
    preferred_currency: str | None = None,
    force_category: str | None = None,
) -> dict[str, Any]:
    """Process an uploaded receipt using AI vision to extract structured expense data.

    Returns merchant, date, total, currency, line items, taxes, category,
    confidence scores, and reasoning. Costs 1 credit per call.

    Args:
        receipt_id: The receipt_id returned by upload_receipt
        company_context: Brief company description for better categorisation
        preferred_currency: ISO 4217 currency code (e.g. USD, EUR, GBP)
        force_category: Override auto-detected category (meals, travel, office_supplies, software, professional_services, utilities, equipment, advertising, insurance, other)
    """
    _ensure_init()
    import tools as _tools

    result = await _tools.process_receipt(
        receipt_id,
        company_context=company_context,
        preferred_currency=preferred_currency,
        force_category=force_category,
    )
    return result.model_dump()


@mcp.tool()
async def upload_and_process(
    mime_type: str,
    url: str | None = None,
    file_base64: str | None = None,
    company_context: str | None = None,
    preferred_currency: str | None = None,
    force_category: str | None = None,
) -> dict[str, Any]:
    """Upload and process a receipt in a single call.

    Combines upload_receipt + process_receipt. Costs 1 credit.

    Args:
        mime_type: MIME type of the file
        url: Public URL of the receipt image or PDF
        file_base64: Base64-encoded file content (alternative to URL)
        company_context: Brief company description for better categorisation
        preferred_currency: ISO 4217 currency code
        force_category: Override auto-detected category
    """
    _ensure_init()
    import tools as _tools

    file_bytes = None
    if file_base64:
        file_bytes = base64.b64decode(file_base64)

    upload = await _tools.upload_receipt(file_bytes, url, mime_type)
    result = await _tools.process_receipt(
        upload.receipt_id,
        company_context=company_context,
        preferred_currency=preferred_currency,
        force_category=force_category,
    )
    return result.model_dump()


@mcp.tool()
async def get_receipt_markdown(receipt_id: str) -> dict[str, Any]:
    """Get a Markdown-formatted view of a processed receipt.

    Returns a clean Markdown representation including line items table,
    tax summary, and confidence scores. Receipt must be processed first.

    Args:
        receipt_id: The receipt_id of a previously processed receipt
    """
    _ensure_init()
    import tools as _tools

    result = await _tools.get_receipt_markdown(receipt_id)
    return {"receipt_id": result.receipt_id, "markdown": result.markdown}


@mcp.tool()
async def suggest_gl_account(
    expense_json: dict,
    chart_of_accounts_snippet: str | None = None,
) -> dict[str, Any]:
    """Suggest the best General Ledger account code for an expense.

    Given structured expense data (from process_receipt), uses AI reasoning
    to map the expense to an appropriate GL account. Costs 1 credit.

    Args:
        expense_json: The structured_expense dict returned by process_receipt
        chart_of_accounts_snippet: Optional partial chart of accounts to match against
    """
    _ensure_init()
    import tools as _tools

    result = await _tools.suggest_gl_account(
        expense_json,
        chart_of_accounts_snippet=chart_of_accounts_snippet,
    )
    return result.model_dump()


@mcp.tool()
async def check_balance() -> dict[str, Any]:
    """Check your current credit balance and subscription plan.

    Free to call. Use this before process_receipt to verify sufficient credits.
    Returns current credit count and plan name.
    """
    _ensure_init()
    import db

    # In MCP stdio mode, there's no API key auth -- use a default or env-configured key
    api_key = os.environ.get("RECEIPT_MCP_API_KEY", "")
    if not api_key:
        return {"credits": "unlimited (local mode)", "plan": "local"}

    agent = db.get_agent_by_api_key(api_key)
    plan = agent["plan"] if agent else "free"
    balance = db.get_credit_balance(api_key)
    return {"credits": balance, "plan": plan}


@mcp.tool()
async def list_receipts(
    limit: int = 50,
    status: str | None = None,
) -> dict[str, Any]:
    """List your uploaded receipts with their status.

    Filter by status (uploaded, processing, processed, failed).
    Returns receipt_id, status, mime_type, and timestamps.

    Args:
        limit: Max number of receipts to return (1-200)
        status: Filter by receipt status
    """
    _ensure_init()
    import db

    api_key = os.environ.get("RECEIPT_MCP_API_KEY", "")
    if not api_key:
        return {"receipts": [], "note": "Set RECEIPT_MCP_API_KEY to list receipts"}

    rows = db.list_receipts(api_key, limit=limit, status=status)
    return {"receipts": rows}


# ── Resources (MCP protocol) ──────────────────────────────────────────

@mcp.resource("receipt://pricing")
def get_pricing() -> str:
    """Current pricing for receipt processing credits."""
    return json.dumps({
        "credit_packs": {
            "100": "$5.00 ($0.050/credit)",
            "500": "$20.00 ($0.040/credit)",
            "1000": "$40.00 ($0.040/credit)",
            "5000": "$150.00 ($0.030/credit)",
            "10000": "$300.00 ($0.030/credit)",
        },
        "subscriptions": {
            "free": "50 credits on signup, $0/mo",
            "basic": "200 credits/mo, $15/mo",
            "pro": "2000 credits/mo, $99/mo",
        },
        "tool_costs": {
            "upload_receipt": "free",
            "process_receipt": "1 credit",
            "upload_and_process": "1 credit",
            "get_receipt_markdown": "free",
            "suggest_gl_account": "1 credit",
            "check_balance": "free",
            "list_receipts": "free",
        },
    }, indent=2)


@mcp.resource("receipt://supported-formats")
def get_supported_formats() -> str:
    """Supported file formats for receipt upload."""
    return json.dumps({
        "image_formats": ["image/jpeg", "image/png", "image/webp", "image/gif"],
        "document_formats": ["application/pdf"],
        "max_file_size": "10 MB",
        "note": "For best results, ensure the receipt is well-lit and text is readable.",
    }, indent=2)


# ── Run ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    mcp.run()
