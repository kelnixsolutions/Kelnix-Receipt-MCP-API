"""
LangGraph agent that processes receipts using the Receipt MCP Server.

Install: pip install langchain-core langgraph httpx
"""
import httpx
from langchain_core.tools import tool

BASE = "https://your-server.com"  # or http://localhost:8000
API_KEY = "rct_your-key-here"
HEADERS = {"X-API-Key": API_KEY}


@tool
def upload_receipt(file_path: str, mime_type: str = "image/jpeg") -> dict:
    """Upload a receipt image or PDF for processing."""
    with open(file_path, "rb") as f:
        r = httpx.post(
            f"{BASE}/tools/upload_receipt",
            files={"file": (file_path, f, mime_type)},
            data={"mime_type": mime_type},
            headers=HEADERS,
        )
    r.raise_for_status()
    return r.json()


@tool
def process_receipt(receipt_id: str) -> dict:
    """Process an uploaded receipt and return structured expense data."""
    r = httpx.post(
        f"{BASE}/tools/process_receipt",
        json={"receipt_id": receipt_id},
        headers=HEADERS,
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


@tool
def suggest_gl_account(expense_json: dict) -> dict:
    """Suggest a General Ledger account code for an expense."""
    r = httpx.post(
        f"{BASE}/tools/suggest_gl_account",
        json={"expense_json": expense_json},
        headers=HEADERS,
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


@tool
def check_balance() -> dict:
    """Check current credit balance and plan."""
    r = httpx.post(f"{BASE}/tools/check_balance", headers=HEADERS)
    r.raise_for_status()
    return r.json()


# Use these tools in a LangGraph StateGraph:
#
# from langgraph.graph import StateGraph
#
# tools = [upload_receipt, process_receipt, suggest_gl_account, check_balance]
# graph = StateGraph(...)
# graph.add_node("tools", ToolNode(tools))
