"""
Quick start: Register, upload, and process a receipt in 10 lines.

Install: pip install httpx
"""
import httpx

BASE = "http://localhost:8000"

# 1. Register (one-time)
agent = httpx.post(f"{BASE}/register_agent", json={"agent_name": "my-bot"}).json()
api_key = agent["api_key"]
print(f"API key: {api_key} | Credits: {agent['free_credits']}")

headers = {"X-API-Key": api_key}

# 2. Upload + process in one call
with open("receipt.jpg", "rb") as f:
    result = httpx.post(
        f"{BASE}/tools/upload_and_process",
        files={"file": ("receipt.jpg", f, "image/jpeg")},
        data={"mime_type": "image/jpeg"},
        headers=headers,
        timeout=30,
    ).json()

print(f"Merchant: {result['structured_expense']['merchant']}")
print(f"Total: {result['structured_expense']['currency']} {result['structured_expense']['total_amount']}")
print(f"Category: {result['structured_expense']['category_guess']}")
