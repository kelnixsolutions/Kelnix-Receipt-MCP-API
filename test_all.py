"""
End-to-end test suite for Receipt MCP Server (Phases 1-3).
Tests every endpoint against a running local server.
No external API keys needed — tests verify proper error handling for external services.
"""

import io
import json
import struct
import sys
import zlib

import httpx

BASE = "http://127.0.0.1:8895"
PASS = 0
FAIL = 0
API_KEY = ""


def test(name, passed, detail=""):
    global PASS, FAIL
    status = "PASS" if passed else "FAIL"
    if passed:
        PASS += 1
    else:
        FAIL += 1
    print(f"  [{status}] {name}" + (f" — {detail}" if detail else ""))


def make_minimal_png() -> bytes:
    """Create a valid 1x1 red PNG in memory."""

    def chunk(chunk_type, data):
        c = chunk_type + data
        return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)

    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
    raw_data = b"\x00\xff\x00\x00"  # filter byte + RGB
    idat = chunk(b"IDAT", zlib.compress(raw_data))
    iend = chunk(b"IEND", b"")
    return sig + ihdr + idat + iend


def run_tests():
    global API_KEY
    client = httpx.Client(base_url=BASE, timeout=15)

    # ── 1. Health ────────────────────────────────────────────────────
    print("\n--- SYSTEM ---")
    r = client.get("/health")
    test("GET /health returns 200", r.status_code == 200)
    test("/health has version 3.1.0", r.json().get("version") == "3.1.0", r.json())

    # ── 2. MCP Discovery ────────────────────────────────────────────
    print("\n--- MCP DISCOVERY ---")
    r = client.get("/mcp")
    test("GET /mcp returns 200", r.status_code == 200)
    tools = r.json()
    names = [t["name"] for t in tools]
    test(f"MCP has 8 tools", len(tools) == 8, names)
    for expected in ["upload_receipt", "process_receipt", "get_receipt_markdown",
                     "suggest_gl_account", "check_balance", "buy_credits_crypto",
                     "list_receipts", "upload_and_process"]:
        test(f"  tool '{expected}' present", expected in names)

    # Check MCP metadata quality
    for t in tools:
        test(f"  {t['name']} has description", bool(t.get("description")))
        test(f"  {t['name']} has parameters", "properties" in t.get("parameters", {}))
        test(f"  {t['name']} has examples", len(t.get("examples", [])) >= 1)
        test(f"  {t['name']} has constraints", bool(t.get("constraints")))
        test(f"  {t['name']} has setup_required", t.get("constraints", {}).get("setup_required") == "register_agent")

    crypto_tool = [t for t in tools if t["name"] == "buy_credits_crypto"][0]
    test("crypto tool has crypto_any_supported=true",
         crypto_tool["constraints"].get("crypto_any_supported") is True)
    test("crypto tool has dynamic_fiat_lock=true",
         crypto_tool["constraints"].get("dynamic_fiat_lock") is True)
    test("crypto tool has expiry_minutes",
         bool(crypto_tool["constraints"].get("expiry_minutes")))

    # ── 3. Agent Registration ───────────────────────────────────────
    print("\n--- AGENT REGISTRATION ---")
    r = client.post("/register_agent", json={"agent_name": "test-bot-e2e", "org_id": "test-org"})
    test("POST /register_agent returns 200", r.status_code == 200)
    agent = r.json()
    API_KEY = agent["api_key"]
    test("API key starts with rct_", API_KEY.startswith("rct_"))
    test("Got 50 free credits", agent["free_credits"] == 50)
    test("agent_name correct", agent["agent_name"] == "test-bot-e2e")
    test("org_id correct", agent["org_id"] == "test-org")

    # Register second agent
    r2 = client.post("/register_agent", json={"agent_name": "bot-2"})
    test("Can register multiple agents", r2.status_code == 200)
    key2 = r2.json()["api_key"]
    test("Different API keys", key2 != API_KEY)

    # ── 4. Auth ─────────────────────────────────────────────────────
    print("\n--- AUTHENTICATION ---")
    r = client.post("/tools/check_balance", headers={"X-API-Key": "invalid-key-xxx"})
    test("Invalid API key returns 401", r.status_code == 401)

    r = client.post("/tools/check_balance", headers={"X-API-Key": API_KEY})
    test("Valid API key returns 200", r.status_code == 200)

    # Legacy key
    r = client.post("/tools/check_balance", headers={"X-API-Key": "dev-key-change-me"})
    test("Legacy dev key works", r.status_code == 200)

    # ── 5. Balance ──────────────────────────────────────────────────
    print("\n--- BALANCE ---")
    headers = {"X-API-Key": API_KEY}
    r = client.post("/tools/check_balance", headers=headers)
    test("check_balance returns 200", r.status_code == 200)
    bal = r.json()
    test("Balance is 50", bal["credits"] == 50)
    test("Plan is free", bal["plan"] == "free")

    r = client.get("/billing/balance", headers=headers)
    test("GET /billing/balance returns 200", r.status_code == 200)
    full = r.json()
    test("Full balance has credits", full["credits"] == 50)
    test("Full balance has history", len(full["history"]) >= 1)
    test("History entry has signup reason",
         any("signup" in h["reason"] for h in full["history"]))

    # ── 6. Upload Receipt ───────────────────────────────────────────
    print("\n--- UPLOAD RECEIPT ---")
    png_bytes = make_minimal_png()

    # Upload via file
    r = client.post("/tools/upload_receipt",
        headers=headers,
        files={"file": ("receipt.png", io.BytesIO(png_bytes), "image/png")},
        data={"mime_type": "image/png"})
    test("Upload via file returns 200", r.status_code == 200)
    receipt_id = r.json()["receipt_id"]
    test("Got receipt_id", len(receipt_id) == 16, receipt_id)

    # Upload without file or url → 400
    r = client.post("/tools/upload_receipt",
        headers=headers, data={"mime_type": "image/png"})
    test("Upload without file/url returns 400", r.status_code == 400)

    # ── 7. Process Receipt (credit deduction) ───────────────────────
    print("\n--- PROCESS RECEIPT (credit flow) ---")

    # Check balance before
    r = client.post("/tools/check_balance", headers=headers)
    before = r.json()["credits"]
    test(f"Credits before process: {before}", before == 50)

    # Process will fail (no ANTHROPIC_API_KEY) but credit should be deducted
    r = client.post("/tools/process_receipt", headers=headers,
        json={"receipt_id": receipt_id})
    test("Process receipt returns 500 (no API key)", r.status_code == 500,
         r.json().get("detail", "")[:80])

    # Credit was deducted before the API call
    r = client.post("/tools/check_balance", headers=headers)
    after = r.json()["credits"]
    test(f"Credits after process: {after} (deducted 1)", after == before - 1)

    # ── 8. Credit exhaustion → 402 ──────────────────────────────────
    print("\n--- CREDIT EXHAUSTION ---")
    # Create agent with 0 credits situation
    r3 = client.post("/register_agent", json={"agent_name": "broke-bot"})
    broke_key = r3.json()["api_key"]
    broke_headers = {"X-API-Key": broke_key}

    # Exhaust all 50 credits by uploading + processing (will fail but deducts)
    # Faster: just deduct directly via multiple calls
    import db
    for i in range(50):
        db.deduct_credits(broke_key, 1, reason="test_exhaust")

    r = client.post("/tools/check_balance", headers=broke_headers)
    test("Broke bot has 0 credits", r.json()["credits"] == 0)

    r = client.post("/tools/process_receipt", headers=broke_headers,
        json={"receipt_id": receipt_id})
    test("Process with 0 credits returns 402", r.status_code == 402)
    detail = r.json()["detail"]
    test("402 includes buy_credits_url", "buy_credits" in str(detail))
    test("402 includes subscribe_url", "subscribe" in str(detail))

    # suggest_gl_account also requires credits
    r = client.post("/tools/suggest_gl_account", headers=broke_headers,
        json={"expense_json": {"category_guess": "meals"}})
    test("suggest_gl_account with 0 credits returns 402", r.status_code == 402)

    # Free tools still work at 0 credits
    r = client.post("/tools/check_balance", headers=broke_headers)
    test("check_balance works at 0 credits", r.status_code == 200)

    # ── 9. Get Receipt Markdown ─────────────────────────────────────
    print("\n--- GET RECEIPT MARKDOWN ---")
    r = client.post("/tools/get_receipt_markdown", headers=headers,
        json={"receipt_id": receipt_id})
    # Should fail because receipt wasn't successfully processed
    test("Markdown for unprocessed receipt returns error", r.status_code in (404, 500))

    r = client.post("/tools/get_receipt_markdown", headers=headers,
        json={"receipt_id": "nonexistent123"})
    test("Markdown for nonexistent receipt returns 404", r.status_code == 404)

    # ── 10. Billing — Stripe (no key, proper errors) ────────────────
    print("\n--- STRIPE BILLING (no key, error handling) ---")
    r = client.post("/billing/buy_credits", headers=headers,
        json={"credits": 100})
    test("buy_credits without Stripe key returns 400", r.status_code == 400)

    r = client.post("/billing/buy_credits", headers=headers,
        json={"credits": 999})
    test("buy_credits invalid pack returns 400", r.status_code == 400)

    r = client.post("/billing/subscribe", headers=headers,
        json={"plan": "basic"})
    test("subscribe without Stripe returns 400", r.status_code == 400)

    r = client.post("/billing/subscribe", headers=headers,
        json={"plan": "enterprise"})
    test("subscribe invalid plan returns 400", r.status_code == 400)

    # Stripe webhook with empty body
    r = client.post("/billing/webhook", content=b"{}", headers={"stripe-signature": ""})
    test("Stripe webhook handles gracefully", r.status_code in (200, 400))

    # ── 11. Billing — Crypto (no key, proper errors) ────────────────
    print("\n--- CRYPTO BILLING (no key, error handling) ---")
    r = client.post("/billing/buy_credits_crypto", headers=headers,
        json={"credits": 100, "preferred_coin": "btc"})
    test("buy_credits_crypto without NOWPayments key returns 400",
         r.status_code == 400)

    r = client.post("/billing/buy_credits_crypto", headers=headers,
        json={})
    test("buy_credits_crypto with no amount returns 400", r.status_code == 400)

    r = client.post("/billing/check_payment_status", headers=headers,
        json={"payment_id": "nonexistent"})
    test("check_payment_status for unknown returns 404", r.status_code == 404)

    # Crypto IPN webhook
    r = client.post("/billing/crypto_webhook",
        json={"payment_id": "fake", "payment_status": "finished"},
        headers={"x-nowpayments-sig": "invalid"})
    test("Crypto webhook for unknown payment returns 200 (ignored)",
         r.status_code == 200)

    # ── 12. Webhook Subscriptions ───────────────────────────────────
    print("\n--- WEBHOOK SUBSCRIPTIONS ---")
    r = client.post("/subscribe_webhook", headers=headers,
        json={"url": "https://mybot.example.com/hook", "events": ["low_balance", "processing_complete"]})
    test("Subscribe webhook returns 200", r.status_code == 200)
    wh = r.json()
    test("Webhook has subscription_id", wh["subscription_id"] > 0)
    test("Webhook url correct", wh["url"] == "https://mybot.example.com/hook")
    test("Webhook events correct", set(wh["events"]) == {"low_balance", "processing_complete"})

    # Invalid event
    r = client.post("/subscribe_webhook", headers=headers,
        json={"url": "https://example.com", "events": ["invalid_event"]})
    test("Invalid webhook event returns 400", r.status_code == 400)

    # ── 13. Integrations ────────────────────────────────────────────
    print("\n--- INTEGRATIONS ---")
    r = client.get("/integrations")
    test("GET /integrations returns 200", r.status_code == 200)
    integ = r.json()
    for fw in ["langgraph", "crewai", "autogen", "raw_python"]:
        test(f"  {fw} quickstart present", fw in integ)
        test(f"  {fw} has snippet", bool(integ[fw].get("snippet")))
        test(f"  {fw} has description", bool(integ[fw].get("description")))

    # ── 14. Async Processing endpoint exists ────────────────────────
    print("\n--- ASYNC PROCESSING ---")
    # Will deduct credit but fail on processing (no Anthropic key)
    r = client.post("/tools/check_balance", headers=headers)
    credits_now = r.json()["credits"]

    if credits_now > 0:
        # Use a longer timeout — Celery tries Redis connection (4s timeout)
        long_client = httpx.Client(base_url=BASE, timeout=10)
        r = long_client.post("/tools/process_receipt_async", headers=headers,
            json={"receipt_id": receipt_id})
        long_client.close()
        # Without Redis, Celery will fail with 503 — endpoint exists and handles it
        test("process_receipt_async endpoint exists",
             r.status_code in (200, 503), f"status={r.status_code}")
        if r.status_code == 503:
            test("  returns helpful error about Redis",
                 "Redis" in r.json().get("detail", "") or "Celery" in r.json().get("detail", ""))
    else:
        test("process_receipt_async skipped (0 credits)", True, "need credits")

    # Task status endpoint
    r = client.get("/tasks/fake-task-id", headers=headers)
    test("GET /tasks/{id} endpoint exists", r.status_code in (200, 500, 503))

    # ── 15. List Receipts ─────────────────────────────────────────────
    print("\n--- LIST RECEIPTS ---")
    r = client.post("/tools/list_receipts", headers=headers,
        json={"limit": 10})
    test("list_receipts returns 200", r.status_code == 200)
    lr = r.json()
    test("list_receipts has receipts array", "receipts" in lr)
    test("list_receipts has at least 1 receipt", len(lr["receipts"]) >= 1)

    r = client.post("/tools/list_receipts", headers=headers,
        json={"limit": 10, "status": "uploaded"})
    test("list_receipts with status filter returns 200", r.status_code == 200)

    # ── 16. Upload and Process combo ──────────────────────────────────
    print("\n--- UPLOAD AND PROCESS COMBO ---")
    r = client.post("/tools/upload_and_process",
        headers=headers,
        files={"file": ("receipt.png", io.BytesIO(png_bytes), "image/png")},
        data={"mime_type": "image/png"})
    test("upload_and_process endpoint exists",
         r.status_code in (200, 500), f"status={r.status_code}")

    # ── 17. Request ID middleware ─────────────────────────────────────
    print("\n--- REQUEST ID MIDDLEWARE ---")
    r = client.get("/health")
    test("Response has X-Request-ID header", "x-request-id" in r.headers)

    r = client.get("/health", headers={"X-Request-ID": "test-req-123"})
    test("Custom request ID echoed back",
         r.headers.get("x-request-id") == "test-req-123")

    # ── 18. OpenAPI / Swagger docs ────────────────────────────────────
    print("\n--- OPENAPI DOCS ---")
    r = client.get("/docs")
    test("GET /docs returns 200", r.status_code == 200)

    r = client.get("/openapi.json")
    test("GET /openapi.json returns 200", r.status_code == 200)
    spec = r.json()
    paths = list(spec.get("paths", {}).keys())
    test(f"OpenAPI has {len(paths)} paths", len(paths) >= 17, paths)

    # ── Summary ─────────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print(f"  RESULTS: {PASS} passed, {FAIL} failed, {PASS+FAIL} total")
    print(f"{'='*60}")

    client.close()
    return FAIL == 0


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
