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
from typing import Annotated, Any

from pydantic import Field
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

# ── Initialize MCP server ──────────────────────────────────────────────

mcp = FastMCP(
    "Kelnix Receipt MCP API",
    instructions=(
        "AI-powered receipt processing API. Upload any receipt image or PDF and get "
        "structured, accounting-ready JSON in seconds — merchant, date, line items, "
        "totals, tax breakdown, currency, and confidence scores. Suggest GL account "
        "codes for instant bookkeeping. Built for expense automation agents. "
        "50 free credits on signup, no credit card required."
    ),
    website_url="https://kelnix.org",
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

@mcp.tool(
    annotations=ToolAnnotations(
        title="Upload Receipt",
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=False,
        openWorldHint=False,
    ),
)
async def upload_receipt(
    mime_type: Annotated[str, Field(
        description="MIME type of the file. Supported: image/jpeg, image/png, image/webp, image/gif, application/pdf",
    )],
    url: Annotated[str | None, Field(
        description="Public URL of the receipt image or PDF. Provide this OR file_base64, not both.",
        default=None,
    )] = None,
    file_base64: Annotated[str | None, Field(
        description="Base64-encoded file content. Use this when the receipt file is local rather than hosted at a URL.",
        default=None,
    )] = None,
) -> dict[str, Any]:
    """Upload a receipt image or PDF for later processing.

    Accepts JPEG, PNG, WebP, GIF images and PDF documents up to 10 MB.
    Returns a receipt_id you'll use with process_receipt or get_receipt_markdown.
    Free — no credits consumed.
    """
    _ensure_init()
    import tools as _tools

    file_bytes = None
    if file_base64:
        file_bytes = base64.b64decode(file_base64)

    result = await _tools.upload_receipt(file_bytes, url, mime_type)
    return {"receipt_id": result.receipt_id}


@mcp.tool(
    annotations=ToolAnnotations(
        title="Process Receipt",
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=True,
    ),
)
async def process_receipt(
    receipt_id: Annotated[str, Field(
        description="The receipt_id returned by upload_receipt. Must be a valid, previously uploaded receipt.",
    )],
    company_context: Annotated[str | None, Field(
        description="Brief description of your company or industry (e.g. 'SaaS startup', 'restaurant chain') for smarter expense categorisation.",
        default=None,
    )] = None,
    preferred_currency: Annotated[str | None, Field(
        description="ISO 4217 currency code to use for the output (e.g. USD, EUR, GBP). If omitted, the currency is auto-detected from the receipt.",
        default=None,
    )] = None,
    force_category: Annotated[str | None, Field(
        description="Override the AI-detected category. One of: meals, travel, office_supplies, software, professional_services, utilities, equipment, advertising, insurance, other.",
        default=None,
    )] = None,
) -> dict[str, Any]:
    """Extract structured expense data from an uploaded receipt using AI vision.

    Returns merchant name, date, total amount, currency, itemised line items,
    tax breakdown, expense category, confidence scores, and AI reasoning.
    Costs 1 credit per call.
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


@mcp.tool(
    annotations=ToolAnnotations(
        title="Upload & Process Receipt",
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=False,
        openWorldHint=True,
    ),
)
async def upload_and_process(
    mime_type: Annotated[str, Field(
        description="MIME type of the file. Supported: image/jpeg, image/png, image/webp, image/gif, application/pdf",
    )],
    url: Annotated[str | None, Field(
        description="Public URL of the receipt image or PDF. Provide this OR file_base64, not both.",
        default=None,
    )] = None,
    file_base64: Annotated[str | None, Field(
        description="Base64-encoded file content. Use this when the receipt file is local rather than hosted at a URL.",
        default=None,
    )] = None,
    company_context: Annotated[str | None, Field(
        description="Brief description of your company or industry for smarter expense categorisation.",
        default=None,
    )] = None,
    preferred_currency: Annotated[str | None, Field(
        description="ISO 4217 currency code (e.g. USD, EUR, GBP). Auto-detected if omitted.",
        default=None,
    )] = None,
    force_category: Annotated[str | None, Field(
        description="Override AI-detected category. One of: meals, travel, office_supplies, software, professional_services, utilities, equipment, advertising, insurance, other.",
        default=None,
    )] = None,
) -> dict[str, Any]:
    """Upload and process a receipt in a single call — the fastest way to go from image to structured data.

    Combines upload_receipt + process_receipt into one step. Returns merchant,
    date, totals, line items, tax, category, and confidence scores.
    Costs 1 credit.
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


@mcp.tool(
    annotations=ToolAnnotations(
        title="Get Receipt Markdown",
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
)
async def get_receipt_markdown(
    receipt_id: Annotated[str, Field(
        description="The receipt_id of a previously processed receipt. The receipt must have been processed first via process_receipt.",
    )],
) -> dict[str, Any]:
    """Get a clean Markdown-formatted view of a processed receipt.

    Returns a human-readable Markdown document with line items table,
    tax summary, totals, and confidence scores. Perfect for reports or chat display.
    Free — no credits consumed.
    """
    _ensure_init()
    import tools as _tools

    result = await _tools.get_receipt_markdown(receipt_id)
    return {"receipt_id": result.receipt_id, "markdown": result.markdown}


@mcp.tool(
    annotations=ToolAnnotations(
        title="Suggest GL Account",
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=True,
    ),
)
async def suggest_gl_account(
    expense_json: Annotated[dict[str, Any], Field(
        description="The structured_expense object returned by process_receipt. Contains merchant, amount, category, and line items.",
    )],
    chart_of_accounts_snippet: Annotated[str | None, Field(
        description="Optional partial chart of accounts (as text) to match against. Include account codes and names for best results.",
        default=None,
    )] = None,
) -> dict[str, Any]:
    """Suggest the best General Ledger account code for an expense using AI reasoning.

    Maps structured expense data to the most appropriate GL account. Provide your
    chart of accounts for company-specific matching, or get standard GAAP suggestions.
    Costs 1 credit.
    """
    _ensure_init()
    import tools as _tools

    result = await _tools.suggest_gl_account(
        expense_json,
        chart_of_accounts_snippet=chart_of_accounts_snippet,
    )
    return result.model_dump()


@mcp.tool(
    annotations=ToolAnnotations(
        title="Check Balance",
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
)
async def check_balance() -> dict[str, Any]:
    """Check your current credit balance and subscription plan.

    Returns your remaining credits and active plan (free, basic, or pro).
    Call this before processing to verify you have enough credits.
    Free — no credits consumed.
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


@mcp.tool(
    annotations=ToolAnnotations(
        title="List Receipts",
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
)
async def list_receipts(
    limit: Annotated[int, Field(
        description="Maximum number of receipts to return. Range: 1-200.",
        default=50,
        ge=1,
        le=200,
    )] = 50,
    status: Annotated[str | None, Field(
        description="Filter by receipt status. One of: uploaded, processing, processed, failed. Returns all statuses if omitted.",
        default=None,
    )] = None,
) -> dict[str, Any]:
    """List your uploaded receipts with their processing status.

    Returns receipt_id, status, MIME type, and timestamps for each receipt.
    Use status filter to find receipts ready for processing or check failures.
    Free — no credits consumed.
    """
    _ensure_init()
    import db

    api_key = os.environ.get("RECEIPT_MCP_API_KEY", "")
    if not api_key:
        return {"receipts": [], "note": "Set RECEIPT_MCP_API_KEY to list receipts"}

    rows = db.list_receipts(api_key, limit=limit, status=status)
    return {"receipts": rows}


# ── Prompts (MCP protocol) ─────────────────────────────────────────────

@mcp.prompt()
def process_expense(
    receipt_source: Annotated[str, Field(
        description="URL or file path of the receipt to process",
    )],
    company: Annotated[str, Field(
        description="Company name or industry for better categorisation",
    )] = "general business",
) -> str:
    """Step-by-step guide to process a receipt and get structured expense data."""
    return (
        f"I need to process an expense receipt.\n\n"
        f"Receipt: {receipt_source}\n"
        f"Company context: {company}\n\n"
        f"Please:\n"
        f"1. Upload the receipt using upload_and_process (mime_type based on file extension)\n"
        f"2. Review the extracted data — verify merchant, date, total, and line items\n"
        f"3. If the receipt is already uploaded, use its receipt_id with process_receipt\n"
        f"4. Show me the results in a clear summary\n"
        f"5. Suggest a GL account code using suggest_gl_account"
    )


@mcp.prompt()
def expense_report(
    time_period: Annotated[str, Field(
        description="Time period for the report (e.g. 'March 2026', 'Q1 2026', 'last week')",
    )],
) -> str:
    """Generate an expense report from processed receipts."""
    return (
        f"Generate an expense report for: {time_period}\n\n"
        f"Please:\n"
        f"1. Use list_receipts to find all processed receipts\n"
        f"2. For each processed receipt, use get_receipt_markdown to get details\n"
        f"3. Group expenses by category (meals, travel, software, etc.)\n"
        f"4. Calculate totals per category and grand total\n"
        f"5. Present as a clean Markdown expense report with a summary table"
    )


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
