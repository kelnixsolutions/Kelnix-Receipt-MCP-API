from __future__ import annotations

import json
import secrets
import sqlite3
import threading
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
    api_key      TEXT,
    created_at   TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS agents (
    api_key             TEXT PRIMARY KEY,
    agent_name          TEXT NOT NULL,
    org_id              TEXT,
    plan                TEXT NOT NULL DEFAULT 'free',
    stripe_customer_id  TEXT,
    created_at          TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS credits (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    api_key     TEXT NOT NULL,
    delta       INTEGER NOT NULL,
    reason      TEXT NOT NULL,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (api_key) REFERENCES agents(api_key)
);

CREATE TABLE IF NOT EXISTS webhook_subscriptions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    api_key     TEXT NOT NULL,
    url         TEXT NOT NULL,
    events      TEXT NOT NULL,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (api_key) REFERENCES agents(api_key)
);

CREATE TABLE IF NOT EXISTS crypto_payments (
    payment_id          TEXT PRIMARY KEY,
    api_key             TEXT NOT NULL,
    credits             INTEGER NOT NULL,
    quoted_fiat_usd     REAL NOT NULL,
    locked_fiat_usd     REAL NOT NULL,
    crypto_amount       REAL NOT NULL,
    crypto_currency     TEXT NOT NULL,
    pay_address         TEXT,
    tx_hash             TEXT,
    status              TEXT NOT NULL DEFAULT 'waiting',
    rate_used           REAL,
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at          TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (api_key) REFERENCES agents(api_key)
);

CREATE TABLE IF NOT EXISTS idempotency_keys (
    idem_key    TEXT PRIMARY KEY,
    api_key     TEXT NOT NULL,
    receipt_id  TEXT NOT NULL,
    result_json TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_receipts_api_key ON receipts(api_key);
CREATE INDEX IF NOT EXISTS idx_credits_api_key ON credits(api_key);
CREATE INDEX IF NOT EXISTS idx_crypto_payments_api_key ON crypto_payments(api_key);
"""

# ── Connection pool ──────────────────────────────────────────────────────
# One persistent connection per thread. SQLite serializes writes internally,
# but reusing connections avoids the open/close overhead on every call.

_local = threading.local()


def _get_conn() -> sqlite3.Connection:
    conn = getattr(_local, "conn", None)
    if conn is None:
        conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        _local.conn = conn
    return conn


@contextmanager
def _conn():
    conn = _get_conn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def init_db() -> None:
    with _conn() as conn:
        conn.executescript(SCHEMA)


# ── API key cache ────────────────────────────────────────────────────────
# Avoids a DB query on every authenticated request.

import time

_api_key_cache: dict[str, float] = {}  # api_key → expiry timestamp
_CACHE_TTL = 300  # 5 minutes


def api_key_exists(api_key: str) -> bool:
    now = time.monotonic()
    expiry = _api_key_cache.get(api_key)
    if expiry and now < expiry:
        return True
    exists = get_agent_by_api_key(api_key) is not None
    if exists:
        _api_key_cache[api_key] = now + _CACHE_TTL
    return exists


def _invalidate_cache(api_key: str) -> None:
    _api_key_cache.pop(api_key, None)


# ── Receipts ─────────────────────────────────────────────────────────────

def insert_receipt(receipt_id: str, file_path: str, mime_type: str, api_key: str | None = None) -> None:
    with _conn() as conn:
        conn.execute(
            "INSERT INTO receipts (receipt_id, file_path, mime_type, api_key) VALUES (?, ?, ?, ?)",
            (receipt_id, file_path, mime_type, api_key),
        )


def get_receipt(receipt_id: str) -> Optional[dict[str, Any]]:
    with _conn() as conn:
        row = conn.execute(
            "SELECT * FROM receipts WHERE receipt_id = ?", (receipt_id,)
        ).fetchone()
    if row is None:
        return None
    return dict(row)


def list_receipts(api_key: str, limit: int = 50, status: str | None = None) -> list[dict[str, Any]]:
    query = "SELECT receipt_id, status, mime_type, created_at, updated_at FROM receipts WHERE api_key = ?"
    params: list[Any] = [api_key]
    if status:
        query += " AND status = ?"
        params.append(status)
    query += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)
    with _conn() as conn:
        rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]


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


# ── Agents ───────────────────────────────────────────────────────────────

def create_agent(agent_name: str, org_id: str | None = None) -> dict[str, Any]:
    api_key = f"rct_{secrets.token_urlsafe(32)}"
    stripe_customer_id = None

    try:
        import stripe
        if stripe.api_key:
            customer = stripe.Customer.create(
                name=agent_name,
                metadata={"api_key": api_key, "org_id": org_id or ""},
            )
            stripe_customer_id = customer.id
    except Exception:
        pass

    with _conn() as conn:
        conn.execute(
            "INSERT INTO agents (api_key, agent_name, org_id, stripe_customer_id) "
            "VALUES (?, ?, ?, ?)",
            (api_key, agent_name, org_id, stripe_customer_id),
        )
    add_credits(api_key, 50, reason="free_tier_signup")
    _api_key_cache[api_key] = time.monotonic() + _CACHE_TTL
    return {
        "api_key": api_key,
        "agent_name": agent_name,
        "org_id": org_id,
        "stripe_customer_id": stripe_customer_id,
        "free_credits": 50,
    }


def get_agent_by_api_key(api_key: str) -> Optional[dict[str, Any]]:
    with _conn() as conn:
        row = conn.execute(
            "SELECT * FROM agents WHERE api_key = ?", (api_key,)
        ).fetchone()
    if row is None:
        return None
    return dict(row)


def update_agent(api_key: str, *, plan: str | None = None) -> None:
    parts: list[str] = []
    params: list[Any] = []
    if plan is not None:
        parts.append("plan = ?")
        params.append(plan)
    if not parts:
        return
    params.append(api_key)
    with _conn() as conn:
        conn.execute(
            f"UPDATE agents SET {', '.join(parts)} WHERE api_key = ?", params
        )


# ── Credits ──────────────────────────────────────────────────────────────

def add_credits(api_key: str, amount: int, reason: str) -> None:
    with _conn() as conn:
        conn.execute(
            "INSERT INTO credits (api_key, delta, reason) VALUES (?, ?, ?)",
            (api_key, amount, reason),
        )


def deduct_credits(api_key: str, amount: int, reason: str) -> None:
    with _conn() as conn:
        conn.execute(
            "INSERT INTO credits (api_key, delta, reason) VALUES (?, ?, ?)",
            (api_key, -amount, reason),
        )


def atomic_deduct_if_sufficient(api_key: str, cost: int, reason: str) -> bool:
    """Atomically check balance and deduct in one transaction. Returns False if insufficient."""
    with _conn() as conn:
        row = conn.execute(
            "SELECT COALESCE(SUM(delta), 0) AS balance FROM credits WHERE api_key = ?",
            (api_key,),
        ).fetchone()
        balance = int(row["balance"])
        if balance < cost:
            return False
        conn.execute(
            "INSERT INTO credits (api_key, delta, reason) VALUES (?, ?, ?)",
            (api_key, -cost, reason),
        )
    return True


def get_credit_balance(api_key: str) -> int:
    with _conn() as conn:
        row = conn.execute(
            "SELECT COALESCE(SUM(delta), 0) AS balance FROM credits WHERE api_key = ?",
            (api_key,),
        ).fetchone()
    return int(row["balance"])


def get_credit_history(api_key: str, limit: int = 50) -> list[dict[str, Any]]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT delta, reason, created_at FROM credits "
            "WHERE api_key = ? ORDER BY created_at DESC LIMIT ?",
            (api_key, limit),
        ).fetchall()
    return [dict(r) for r in rows]


# ── Idempotency ─────────────────────────────────────────────────────────

def get_idempotent_result(idem_key: str, api_key: str) -> Optional[dict[str, Any]]:
    with _conn() as conn:
        row = conn.execute(
            "SELECT result_json FROM idempotency_keys WHERE idem_key = ? AND api_key = ?",
            (idem_key, api_key),
        ).fetchone()
    if row is None or row["result_json"] is None:
        return None
    return json.loads(row["result_json"])


def set_idempotent_result(idem_key: str, api_key: str, receipt_id: str, result: dict) -> None:
    with _conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO idempotency_keys (idem_key, api_key, receipt_id, result_json) "
            "VALUES (?, ?, ?, ?)",
            (idem_key, api_key, receipt_id, json.dumps(result)),
        )


# ── Webhook subscriptions ───────────────────────────────────────────────

def add_webhook_subscription(api_key: str, url: str, events: list[str]) -> int:
    with _conn() as conn:
        cursor = conn.execute(
            "INSERT INTO webhook_subscriptions (api_key, url, events) VALUES (?, ?, ?)",
            (api_key, url, json.dumps(events)),
        )
    return cursor.lastrowid


def get_webhook_subscriptions(api_key: str) -> list[dict[str, Any]]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM webhook_subscriptions WHERE api_key = ?", (api_key,)
        ).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        d["events"] = json.loads(d["events"])
        result.append(d)
    return result


def delete_webhook_subscription(sub_id: int, api_key: str) -> bool:
    with _conn() as conn:
        cursor = conn.execute(
            "DELETE FROM webhook_subscriptions WHERE id = ? AND api_key = ?",
            (sub_id, api_key),
        )
    return cursor.rowcount > 0


# ── Crypto payments ─────────────────────────────────────────────────────

def insert_crypto_payment(
    payment_id: str,
    api_key: str,
    credits: int,
    quoted_fiat_usd: float,
    locked_fiat_usd: float,
    crypto_amount: float,
    crypto_currency: str,
    pay_address: str | None = None,
    rate_used: float | None = None,
) -> None:
    with _conn() as conn:
        conn.execute(
            "INSERT INTO crypto_payments "
            "(payment_id, api_key, credits, quoted_fiat_usd, locked_fiat_usd, "
            "crypto_amount, crypto_currency, pay_address, rate_used) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (payment_id, api_key, credits, quoted_fiat_usd, locked_fiat_usd,
             crypto_amount, crypto_currency, pay_address, rate_used),
        )


def get_crypto_payment(payment_id: str) -> Optional[dict[str, Any]]:
    with _conn() as conn:
        row = conn.execute(
            "SELECT * FROM crypto_payments WHERE payment_id = ?", (payment_id,)
        ).fetchone()
    if row is None:
        return None
    return dict(row)


def update_crypto_payment(
    payment_id: str,
    *,
    status: Optional[str] = None,
    tx_hash: Optional[str] = None,
) -> None:
    parts: list[str] = ["updated_at = datetime('now')"]
    params: list[Any] = []
    if status is not None:
        parts.append("status = ?")
        params.append(status)
    if tx_hash is not None:
        parts.append("tx_hash = ?")
        params.append(tx_hash)
    params.append(payment_id)
    with _conn() as conn:
        conn.execute(
            f"UPDATE crypto_payments SET {', '.join(parts)} WHERE payment_id = ?",
            params,
        )
