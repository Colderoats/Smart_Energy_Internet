"""Off-chain half of the ledger: the `chain_records` table in TimescaleDB.

Holds the full payload (the chain only has its hash) plus every step of the
record's journey: tx hash, block number/hash, gas, status, confirmations,
last verification. Uses the existing pool from app/db.py; its schema is
created here (not in db.py) to keep Module 5 self-contained.

Status lifecycle: queued -> submitted -> included -> confirmed
                  (failed = tx reverted; queued again after a node outage)
"""

from datetime import datetime
from typing import Any

from psycopg.types.json import Jsonb

from app import db

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS chain_records (
    id BIGSERIAL PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL,
    event_type TEXT NOT NULL,
    actor TEXT NOT NULL,
    provenance TEXT NOT NULL,
    summary TEXT NOT NULL,
    source_ref TEXT,
    dedupe_key TEXT UNIQUE,
    payload JSONB NOT NULL,
    payload_hash TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued',
    network TEXT,
    chain_id BIGINT,
    contract_address TEXT,
    chain_record_id BIGINT,
    tx_hash TEXT,
    block_number BIGINT,
    block_hash TEXT,
    gas_used BIGINT,
    confirmations INTEGER NOT NULL DEFAULT 0,
    submitted_at TIMESTAMPTZ,
    included_at TIMESTAMPTZ,
    confirmed_at TIMESTAMPTZ,
    attempts INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    verified_at TIMESTAMPTZ,
    verify_result TEXT,
    verify_detail JSONB,
    tampered_at TIMESTAMPTZ,
    tamper_detail JSONB
);
-- Block timestamp as reported by the chain (Hardhat runs ahead of wall-clock
-- when it mines many blocks per second); included_at is when we saw the receipt.
ALTER TABLE chain_records ADD COLUMN IF NOT EXISTS block_timestamp TIMESTAMPTZ;
-- "<contract address>@<deployment block hash>": identifies WHICH chain + contract
-- a record lives on (a restarted local node reuses the same contract address).
ALTER TABLE chain_records ADD COLUMN IF NOT EXISTS deployment_key TEXT;
CREATE INDEX IF NOT EXISTS chain_records_created_idx ON chain_records (created_at DESC);
CREATE INDEX IF NOT EXISTS chain_records_type_idx ON chain_records (event_type, created_at DESC);
CREATE INDEX IF NOT EXISTS chain_records_status_idx ON chain_records (status);
"""

COLUMNS = (
    "id, created_at, event_type, actor, provenance, summary, source_ref, dedupe_key, payload, payload_hash, "
    "status, network, chain_id, contract_address, chain_record_id, tx_hash, block_number, block_hash, gas_used, "
    "confirmations, submitted_at, included_at, confirmed_at, attempts, last_error, verified_at, verify_result, "
    "verify_detail, tampered_at, tamper_detail, block_timestamp, deployment_key"
)

_UPDATABLE = {
    "status", "network", "chain_id", "contract_address", "chain_record_id", "tx_hash", "block_number",
    "block_hash", "gas_used", "confirmations", "submitted_at", "included_at", "confirmed_at", "attempts",
    "last_error", "verified_at", "verify_result", "verify_detail", "tampered_at", "tamper_detail", "payload", "block_timestamp", "deployment_key",
}


def _row_to_dict(columns: list[str], row: tuple) -> dict:
    out = dict(zip(columns, row))
    for key, value in out.items():
        if isinstance(value, datetime):
            out[key] = value.isoformat()
    return out


async def init_schema() -> None:
    async with db.get_pool().connection() as conn:
        await conn.execute(SCHEMA_SQL)


async def insert(record: dict) -> dict | None:
    """Insert a new queued record. Returns None if `dedupe_key` already exists."""
    async with db.get_pool().connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                f"""
                INSERT INTO chain_records
                    (created_at, event_type, actor, provenance, summary, source_ref, dedupe_key, payload, payload_hash)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (dedupe_key) DO NOTHING
                RETURNING {COLUMNS}
                """,
                (
                    record["created_at"], record["event_type"], record["actor"], record["provenance"],
                    record["summary"], record.get("source_ref"), record.get("dedupe_key"),
                    Jsonb(record["payload"]), record["payload_hash"],
                ),
            )
            row = await cur.fetchone()
            if row is None:
                return None
            return _row_to_dict([d[0] for d in cur.description], row)


async def update(record_id: int, **fields: Any) -> dict | None:
    bad = set(fields) - _UPDATABLE
    if bad:
        raise ValueError(f"not updatable: {bad}")
    assignments = ", ".join(f"{k} = %s" for k in fields)
    values = [Jsonb(v) if k in ("verify_detail", "tamper_detail", "payload") and v is not None else v for k, v in fields.items()]
    async with db.get_pool().connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                f"UPDATE chain_records SET {assignments} WHERE id = %s RETURNING {COLUMNS}", (*values, record_id)
            )
            row = await cur.fetchone()
            return _row_to_dict([d[0] for d in cur.description], row) if row else None


async def get(record_id: int) -> dict | None:
    async with db.get_pool().connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(f"SELECT {COLUMNS} FROM chain_records WHERE id = %s", (record_id,))
            row = await cur.fetchone()
            return _row_to_dict([d[0] for d in cur.description], row) if row else None


async def list_records(event_type: str | None, limit: int, offset: int) -> tuple[list[dict], int]:
    where, params = ("WHERE event_type = %s", [event_type]) if event_type else ("", [])
    async with db.get_pool().connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(f"SELECT count(*) FROM chain_records {where}", params)
            total = (await cur.fetchone())[0]
            await cur.execute(
                f"SELECT {COLUMNS} FROM chain_records {where} ORDER BY created_at DESC, id DESC LIMIT %s OFFSET %s",
                [*params, limit, offset],
            )
            rows = await cur.fetchall()
            cols = [d[0] for d in cur.description]
            return [_row_to_dict(cols, r) for r in rows], total


async def pending() -> list[dict]:
    """Records that still need work from the worker, oldest first."""
    async with db.get_pool().connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                f"SELECT {COLUMNS} FROM chain_records WHERE status IN ('queued', 'submitted') ORDER BY id"
            )
            rows = await cur.fetchall()
            cols = [d[0] for d in cur.description]
            return [_row_to_dict(cols, r) for r in rows]


async def awaiting_confirmations() -> list[dict]:
    async with db.get_pool().connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(f"SELECT {COLUMNS} FROM chain_records WHERE status = 'included' ORDER BY id")
            rows = await cur.fetchall()
            cols = [d[0] for d in cur.description]
            return [_row_to_dict(cols, r) for r in rows]


async def confirmed_for_deployment(deployment_key: str, limit: int = 500) -> list[dict]:
    async with db.get_pool().connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                f"""SELECT {COLUMNS} FROM chain_records
                    WHERE status IN ('included', 'confirmed') AND deployment_key = %s
                    ORDER BY id DESC LIMIT %s""",
                (deployment_key, limit),
            )
            rows = await cur.fetchall()
            cols = [d[0] for d in cur.description]
            return [_row_to_dict(cols, r) for r in rows]


async def counts() -> dict:
    async with db.get_pool().connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT status, count(*) FROM chain_records GROUP BY status")
            by_status = {s: n for s, n in await cur.fetchall()}
            await cur.execute("SELECT event_type, count(*) FROM chain_records GROUP BY event_type")
            by_type = {t: n for t, n in await cur.fetchall()}
            return {"total": sum(by_status.values()), "by_status": by_status, "by_event_type": by_type}


async def existing_dedupe_keys(prefix: str) -> set[str]:
    async with db.get_pool().connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT dedupe_key FROM chain_records WHERE dedupe_key LIKE %s", (prefix + "%",))
            return {r[0] for r in await cur.fetchall()}


async def missing_deployment_key() -> list[dict]:
    """On-chain rows written before deployment_key existed."""
    async with db.get_pool().connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                f"SELECT {COLUMNS} FROM chain_records WHERE deployment_key IS NULL AND tx_hash IS NOT NULL ORDER BY id"
            )
            rows = await cur.fetchall()
            cols = [d[0] for d in cur.description]
            return [_row_to_dict(cols, r) for r in rows]
