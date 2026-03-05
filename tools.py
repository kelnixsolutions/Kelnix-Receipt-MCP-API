from __future__ import annotations

import base64
import json
import os
import uuid
from pathlib import Path
from typing import Any, Optional

import anthropic
import httpx

import db
from models import (
    ConfidenceScores,
    GetReceiptMarkdownResponse,
    LineItem,
    ProcessReceiptResponse,
    ReceiptStatus,
    StructuredExpense,
    SuggestGLAccountResponse,
    TaxItem,
    UploadReceiptResponse,
)

UPLOAD_DIR = Path(__file__).parent / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)

_client: anthropic.AsyncAnthropic | None = None


def _get_client() -> anthropic.AsyncAnthropic:
    global _client
    if _client is None:
        _client = anthropic.AsyncAnthropic()  # reads ANTHROPIC_API_KEY from env
    return _client


VISION_MODEL = "claude-sonnet-4-6-20250514"

EXTRACTION_SYSTEM = (
    "You are a world-class receipt parser. Given an image or PDF of a receipt, "
    "extract every field into the JSON schema below. Be precise with numbers, "
    "dates, and currency. If a field is ambiguous, make your best guess and "
    "reflect uncertainty in the confidence score (0-1)."
)

EXTRACTION_SCHEMA_DESCRIPTION = """\
Return ONLY valid JSON matching this schema:
{
  "merchant": "<string>",
  "date": "<ISO 8601 date, e.g. 2026-03-04>",
  "total_amount": <float>,
  "currency": "<ISO 4217, e.g. USD>",
  "line_items": [{"description": "<string>", "amount": <float>}],
  "taxes": [{"type": "<string, e.g. VAT, Sales Tax>", "amount": <float>}],
  "category_guess": "<one of: meals, travel, office_supplies, software, professional_services, utilities, equipment, advertising, insurance, other>",
  "confidence_scores": {
    "merchant": <0-1>, "date": <0-1>, "total_amount": <0-1>,
    "currency": <0-1>, "line_items": <0-1>, "taxes": <0-1>,
    "category_guess": <0-1>
  },
  "reasoning": "<1-2 sentence explanation of any ambiguity or choices>"
}"""

FEW_SHOT_EXAMPLE = {
    "merchant": "Starbucks #12345",
    "date": "2026-03-01",
    "total_amount": 7.45,
    "currency": "USD",
    "line_items": [
        {"description": "Grande Latte", "amount": 5.95},
        {"description": "Blueberry Muffin", "amount": 1.50},
    ],
    "taxes": [{"type": "Sales Tax", "amount": 0.53}],
    "category_guess": "meals",
    "confidence_scores": {
        "merchant": 0.98,
        "date": 0.95,
        "total_amount": 0.99,
        "currency": 0.99,
        "line_items": 0.90,
        "taxes": 0.92,
        "category_guess": 0.95,
    },
    "reasoning": "Standard coffee shop receipt. Tax line clearly separated.",
}


# ── upload_receipt ───────────────────────────────────────────────────────

async def upload_receipt(
    file_bytes: bytes | None,
    url: str | None,
    mime_type: str,
) -> UploadReceiptResponse:
    receipt_id = uuid.uuid4().hex[:16]

    if url:
        async with httpx.AsyncClient(timeout=30) as http:
            resp = await http.get(url)
            resp.raise_for_status()
            file_bytes = resp.content

    if file_bytes is None:
        raise ValueError("Either file or url must be provided")

    ext = _ext_from_mime(mime_type)
    file_path = UPLOAD_DIR / f"{receipt_id}{ext}"
    file_path.write_bytes(file_bytes)

    db.insert_receipt(receipt_id, str(file_path), mime_type)
    return UploadReceiptResponse(receipt_id=receipt_id)


# ── process_receipt ──────────────────────────────────────────────────────

async def process_receipt(
    receipt_id: str,
    company_context: str | None = None,
    preferred_currency: str | None = None,
    force_category: str | None = None,
) -> ProcessReceiptResponse:
    rec = db.get_receipt(receipt_id)
    if rec is None:
        raise ValueError(f"Receipt {receipt_id} not found")

    db.update_receipt(receipt_id, status=ReceiptStatus.processing.value)

    file_path = Path(rec["file_path"])
    mime = rec["mime_type"]
    raw = file_path.read_bytes()
    b64 = base64.standard_b64encode(raw).decode()

    user_parts: list[dict[str, Any]] = []

    if mime == "application/pdf":
        user_parts.append({
            "type": "document",
            "source": {"type": "base64", "media_type": mime, "data": b64},
        })
    else:
        user_parts.append({
            "type": "image",
            "source": {"type": "base64", "media_type": mime, "data": b64},
        })

    prompt_text = EXTRACTION_SCHEMA_DESCRIPTION
    if company_context:
        prompt_text += f"\n\nCompany context: {company_context}"
    if preferred_currency:
        prompt_text += f"\nPreferred currency: {preferred_currency}"
    if force_category:
        prompt_text += f"\nForce category to: {force_category}"

    prompt_text += f"\n\nExample output:\n{json.dumps(FEW_SHOT_EXAMPLE, indent=2)}"
    prompt_text += "\n\nNow extract from the receipt image above. Return ONLY JSON."

    user_parts.append({"type": "text", "text": prompt_text})

    client = _get_client()
    response = await client.messages.create(
        model=VISION_MODEL,
        max_tokens=2048,
        system=EXTRACTION_SYSTEM,
        messages=[{"role": "user", "content": user_parts}],
    )

    raw_text = response.content[0].text.strip()
    if raw_text.startswith("```"):
        raw_text = raw_text.split("\n", 1)[1].rsplit("```", 1)[0].strip()

    parsed = json.loads(raw_text)

    expense = StructuredExpense(
        merchant=parsed["merchant"],
        date=parsed["date"],
        total_amount=parsed["total_amount"],
        currency=parsed["currency"],
        line_items=[LineItem(**li) for li in parsed["line_items"]],
        taxes=[TaxItem(**t) for t in parsed["taxes"]],
        category_guess=parsed["category_guess"],
        confidence_scores=ConfidenceScores(**parsed["confidence_scores"]),
        reasoning=parsed["reasoning"],
    )

    db.update_receipt(
        receipt_id,
        status=ReceiptStatus.processed.value,
        result_json=expense.model_dump(),
    )

    return ProcessReceiptResponse(receipt_id=receipt_id, structured_expense=expense)


# ── get_receipt_markdown ─────────────────────────────────────────────────

async def get_receipt_markdown(receipt_id: str) -> GetReceiptMarkdownResponse:
    rec = db.get_receipt(receipt_id)
    if rec is None:
        raise ValueError(f"Receipt {receipt_id} not found")

    if rec["markdown"]:
        return GetReceiptMarkdownResponse(receipt_id=receipt_id, markdown=rec["markdown"])

    if rec["result_json"] is None:
        raise ValueError(f"Receipt {receipt_id} has not been processed yet")

    data = json.loads(rec["result_json"])
    md = _expense_to_markdown(data)
    db.update_receipt(receipt_id, markdown=md)
    return GetReceiptMarkdownResponse(receipt_id=receipt_id, markdown=md)


# ── suggest_gl_account ───────────────────────────────────────────────────

async def suggest_gl_account(
    expense_json: dict,
    chart_of_accounts_snippet: str | None = None,
) -> SuggestGLAccountResponse:
    prompt = (
        "You are an expert accountant. Given the following structured expense data, "
        "suggest the most appropriate General Ledger (GL) account.\n\n"
        f"Expense:\n{json.dumps(expense_json, indent=2)}\n"
    )
    if chart_of_accounts_snippet:
        prompt += f"\nChart of accounts (partial):\n{chart_of_accounts_snippet}\n"

    prompt += (
        "\nRespond with ONLY JSON: "
        '{"account_code": "<code>", "account_name": "<name>", '
        '"confidence": <0-1>, "reasoning": "<short>"}'
    )

    client = _get_client()
    response = await client.messages.create(
        model=VISION_MODEL,
        max_tokens=512,
        messages=[{"role": "user", "content": prompt}],
    )

    raw_text = response.content[0].text.strip()
    if raw_text.startswith("```"):
        raw_text = raw_text.split("\n", 1)[1].rsplit("```", 1)[0].strip()

    parsed = json.loads(raw_text)
    return SuggestGLAccountResponse(**parsed)


# ── MCP tool descriptor generator ───────────────────────────────────────

def get_mcp_tools() -> list[dict[str, Any]]:
    return [
        {
            "name": "upload_receipt",
            "description": (
                "Upload a receipt image or PDF (as binary file or URL) for later processing. "
                "Returns a receipt_id that you use with all other tools. "
                "Supports JPEG, PNG, WebP, GIF, and PDF."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "file": {
                        "type": "string",
                        "format": "binary",
                        "description": "Raw binary file content (multipart upload)",
                    },
                    "url": {
                        "type": "string",
                        "format": "uri",
                        "description": "Public URL of the receipt image or PDF",
                    },
                    "mime_type": {
                        "type": "string",
                        "enum": [
                            "image/jpeg",
                            "image/png",
                            "image/webp",
                            "image/gif",
                            "application/pdf",
                        ],
                        "description": "MIME type of the uploaded file",
                    },
                },
                "required": ["mime_type"],
                "oneOf": [
                    {"required": ["file"]},
                    {"required": ["url"]},
                ],
            },
            "examples": [
                {
                    "input": {"url": "https://example.com/receipt.jpg", "mime_type": "image/jpeg"},
                    "output": {"receipt_id": "a1b2c3d4e5f67890"},
                }
            ],
            "constraints": {
                "auth": "API key required (X-API-Key header)",
                "rate_limit": "60 requests/min",
                "max_file_size": "10 MB",
                "cost": "free",
            },
        },
        {
            "name": "process_receipt",
            "description": (
                "Process an uploaded receipt using Claude Sonnet 4.6 vision to extract structured "
                "expense data. Returns merchant, date, total, currency, line items, taxes, "
                "category, confidence scores, and reasoning. This is the core extraction tool."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "receipt_id": {
                        "type": "string",
                        "description": "The receipt_id returned by upload_receipt",
                    },
                    "options": {
                        "type": "object",
                        "description": "Optional processing hints",
                        "properties": {
                            "company_context": {
                                "type": "string",
                                "description": "Brief company description for better categorisation",
                            },
                            "preferred_currency": {
                                "type": "string",
                                "description": "ISO 4217 currency code (e.g. USD, EUR, GBP)",
                            },
                            "force_category": {
                                "type": "string",
                                "enum": [
                                    "meals",
                                    "travel",
                                    "office_supplies",
                                    "software",
                                    "professional_services",
                                    "utilities",
                                    "equipment",
                                    "advertising",
                                    "insurance",
                                    "other",
                                ],
                                "description": "Override the auto-detected expense category",
                            },
                        },
                    },
                },
                "required": ["receipt_id"],
            },
            "examples": [
                {
                    "input": {
                        "receipt_id": "a1b2c3d4e5f67890",
                        "options": {"preferred_currency": "USD"},
                    },
                    "output": {
                        "receipt_id": "a1b2c3d4e5f67890",
                        "structured_expense": FEW_SHOT_EXAMPLE,
                    },
                }
            ],
            "constraints": {
                "auth": "API key required (X-API-Key header)",
                "rate_limit": "30 requests/min",
                "cost": "1 credit (~$0.01-0.05 per call)",
                "latency": "2-10 seconds typical",
            },
        },
        {
            "name": "get_receipt_markdown",
            "description": (
                "Get a clean Markdown representation of a processed receipt, including "
                "a table of line items, tax summary, and extracted text. "
                "Useful for displaying receipt data in chat or documents."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "receipt_id": {
                        "type": "string",
                        "description": "The receipt_id of a previously processed receipt",
                    },
                },
                "required": ["receipt_id"],
            },
            "examples": [
                {
                    "input": {"receipt_id": "a1b2c3d4e5f67890"},
                    "output": {
                        "receipt_id": "a1b2c3d4e5f67890",
                        "markdown": "# Receipt: Starbucks #12345\n\n**Date:** 2026-03-01 ...",
                    },
                }
            ],
            "constraints": {
                "auth": "API key required (X-API-Key header)",
                "rate_limit": "60 requests/min",
                "cost": "free (uses cached data)",
                "prerequisite": "Receipt must be processed first via process_receipt",
            },
        },
        {
            "name": "suggest_gl_account",
            "description": (
                "Given structured expense data (from process_receipt), suggest the best "
                "General Ledger account code. Optionally accepts a partial chart of accounts "
                "to match against. Uses AI reasoning to map expense categories to GL codes."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "expense_json": {
                        "type": "object",
                        "description": "The structured_expense dict returned by process_receipt",
                    },
                    "chart_of_accounts_snippet": {
                        "type": "string",
                        "description": (
                            "Optional partial chart of accounts (plain text or JSON) "
                            "to match against for company-specific GL codes"
                        ),
                    },
                },
                "required": ["expense_json"],
            },
            "examples": [
                {
                    "input": {"expense_json": FEW_SHOT_EXAMPLE},
                    "output": {
                        "account_code": "6200",
                        "account_name": "Meals & Entertainment",
                        "confidence": 0.92,
                        "reasoning": "Coffee shop purchase with food items maps to Meals & Entertainment.",
                    },
                },
                {
                    "input": {
                        "expense_json": FEW_SHOT_EXAMPLE,
                        "chart_of_accounts_snippet": "6100 Office Supplies\n6200 Meals\n6300 Travel",
                    },
                    "output": {
                        "account_code": "6200",
                        "account_name": "Meals",
                        "confidence": 0.95,
                        "reasoning": "Matched to company chart: coffee and food clearly fall under 6200 Meals.",
                    },
                },
            ],
            "constraints": {
                "auth": "API key required (X-API-Key header)",
                "rate_limit": "30 requests/min",
                "cost": "1 credit",
            },
        },
    ]


# ── Helpers ──────────────────────────────────────────────────────────────

def _ext_from_mime(mime: str) -> str:
    mapping = {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
        "image/gif": ".gif",
        "application/pdf": ".pdf",
    }
    return mapping.get(mime, ".bin")


def _expense_to_markdown(data: dict) -> str:
    lines = [
        f"# Receipt: {data['merchant']}",
        "",
        f"**Date:** {data['date']}  ",
        f"**Total:** {data['currency']} {data['total_amount']:.2f}  ",
        f"**Category:** {data['category_guess']}  ",
        "",
        "## Line Items",
        "",
        "| Description | Amount |",
        "|---|---|",
    ]
    for li in data.get("line_items", []):
        lines.append(f"| {li['description']} | {data['currency']} {li['amount']:.2f} |")

    if data.get("taxes"):
        lines.extend(["", "## Taxes", "", "| Type | Amount |", "|---|---|"])
        for t in data["taxes"]:
            lines.append(f"| {t['type']} | {data['currency']} {t['amount']:.2f} |")

    lines.extend([
        "",
        "## Confidence",
        "",
        "| Field | Score |",
        "|---|---|",
    ])
    for field, score in data.get("confidence_scores", {}).items():
        lines.append(f"| {field} | {score:.2f} |")

    lines.extend(["", f"**Reasoning:** {data.get('reasoning', 'N/A')}"])
    return "\n".join(lines)
