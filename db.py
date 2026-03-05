from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Optional

DB_PATH = Path(__file__).parent / "receipts.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS receipts (
    receipt_id   TEXT PRIMARY KEY,
    file_path    TEXT NOT NULL,
    mime_type    TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'uploaded',
    result_json  TEXT,
    markdown     TEXT,
    created_at   TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at   TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


def init_db() -> None:
    with _conn() as conn:
        conn.executescript(SCHEMA)


@contextmanager
def _conn():
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def insert_receipt(receipt_id: str, file_path: str, mime_type: str) -> None:
    with _conn() as conn:
        conn.execute(
            "INSERT INTO receipts (receipt_id, file_path, mime_type) VALUES (?, ?, ?)",
            (receipt_id, file_path, mime_type),
        )


def get_receipt(receipt_id: str) -> Optional[dict[str, Any]]:
    with _conn() as conn:
        row = conn.execute(
            "SELECT * FROM receipts WHERE receipt_id = ?", (receipt_id,)
        ).fetchone()
    if row is None:
        return None
    return dict(row)


def update_receipt(
    receipt_id: str,
    *,
    status: Optional[str] = None,
    result_json: Optional[dict] = None,
    markdown: Optional[str] = None,
) -> None:
    parts: list[str] = ["updated_at = datetime('now')"]
    params: list[Any] = []
    if status is not None:
        parts.append("status = ?")
        params.append(status)
    if result_json is not None:
        parts.append("result_json = ?")
        params.append(json.dumps(result_json))
    if markdown is not None:
        parts.append("markdown = ?")
        params.append(markdown)
    params.append(receipt_id)
    with _conn() as conn:
        conn.execute(
            f"UPDATE receipts SET {', '.join(parts)} WHERE receipt_id = ?", params
        )
