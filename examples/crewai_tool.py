"""
CrewAI tool for receipt processing via the Receipt MCP Server.

Install: pip install crewai crewai-tools httpx
"""
import httpx
from crewai_tools import BaseTool

BASE = "https://your-server.com"  # or http://localhost:8000
API_KEY = "rct_your-key-here"
HEADERS = {"X-API-Key": API_KEY}


class UploadAndProcessReceiptTool(BaseTool):
    name: str = "upload_and_process_receipt"
    description: str = (
        "Upload a receipt image and extract structured expense data in one call. "
        "Returns merchant, date, total, line items, taxes, and category."
    )

    def _run(self, file_path: str, mime_type: str = "image/jpeg") -> dict:
        with open(file_path, "rb") as f:
            r = httpx.post(
                f"{BASE}/tools/upload_and_process",
                files={"file": (file_path, f, mime_type)},
                data={"mime_type": mime_type},
                headers=HEADERS,
                timeout=30,
            )
        r.raise_for_status()
        return r.json()


class SuggestGLAccountTool(BaseTool):
    name: str = "suggest_gl_account"
    description: str = (
        "Given structured expense data, suggest the best General Ledger account code."
    )

    def _run(self, expense_json: dict) -> dict:
        r = httpx.post(
            f"{BASE}/tools/suggest_gl_account",
            json={"expense_json": expense_json},
            headers=HEADERS,
            timeout=30,
        )
        r.raise_for_status()
        return r.json()


# Usage in a CrewAI agent:
#
# from crewai import Agent, Task, Crew
#
# accountant = Agent(
#     role="Expense Accountant",
#     goal="Process receipts and categorize expenses",
#     tools=[UploadAndProcessReceiptTool(), SuggestGLAccountTool()],
# )
