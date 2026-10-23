"""Off-chain half of the prosumer market: market_prosumers, market_intervals,
market_orders, market_trades in TimescaleDB (plain tables). Same approach as
app/blockchain/store.py: self-contained schema, uses the pool from app/db.py.

Every on-chain step stores tx hash, block number and gas used; `events` holds the
decoded contract events (Registered / OfferPosted / BidPosted / TradeMatched /
Metered / Settled) emitted by that transaction.
"""

from datetime import datetime
from typing import Any

from psycopg.types.json import Jsonb

from app import db

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS market_prosumers (
    node_id TEXT NOT NULL,
    deployment_key TEXT NOT NULL,
    address TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    tx_hash TEXT,
    block_number BIGINT,
    gas_used BIGINT,
    error TEXT,
    registered_at TIMESTAMPTZ,
    events JSONB,
    PRIMARY KEY (node_id, deployment_key)
);
CREATE TABLE IF NOT EXISTS market_intervals (
    id BIGSERIAL PRIMARY KEY,
    chain_interval BIGINT,
    deployment_key TEXT,
    started_at TIMESTAMPTZ NOT NULL,
    ends_at TIMESTAMPTZ NOT NULL,
    interval_s DOUBLE PRECISION NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    forecast JSONB,
    actuals JSONB,
    summary JSONB,
    solar_provenance TEXT,
    irradiance_wm2 DOUBLE PRECISION,
    advance_tx_hash TEXT,
    advance_block BIGINT,
    advance_gas BIGINT,
    error TEXT
);
CREATE INDEX IF NOT EXISTS market_intervals_started_idx ON market_intervals (started_at DESC);
CREATE TABLE IF NOT EXISTS market_orders (
    id BIGSERIAL PRIMARY KEY,
    interval_id BIGINT NOT NULL,
    side TEXT NOT NULL,
    node_id TEXT NOT NULL,
    address TEXT,
    qty_wh BIGINT NOT NULL,
    price_milli INTEGER NOT NULL,
    remaining_wh BIGINT,
    status TEXT NOT NULL DEFAULT 'planned',
    chain_order_id BIGINT,
    tx_hash TEXT,
    block_number BIGINT,
    gas_used BIGINT,
    error TEXT,
    events JSONB,
    created_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS market_orders_interval_idx ON market_orders (interval_id);
CREATE TABLE IF NOT EXISTS market_trades (
    id BIGSERIAL PRIMARY KEY,
    interval_id BIGINT NOT NULL,
    offer_order_id BIGINT,
    bid_order_id BIGINT,
    seller TEXT NOT NULL,
    buyer TEXT NOT NULL,
    matched_wh BIGINT NOT NULL,
    price_milli INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'matched_planned',
    step_status TEXT,
    chain_trade_id BIGINT,
    match_tx_hash TEXT, match_block BIGINT, match_gas BIGINT,
    meter_seller_wh BIGINT, meter_buyer_wh BIGINT,
    meter_tx_hash TEXT, meter_block BIGINT, meter_gas BIGINT,
    settled_wh BIGINT, pay_milli BIGINT,
    settle_tx_hash TEXT, settle_block BIGINT, settle_gas BIGINT,
    ledger_record_id BIGINT,
    events JSONB,
    provenance TEXT,
    error TEXT,
    created_at TIMESTAMPTZ NOT NULL,
    settled_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS market_trades_interval_idx ON market_trades (interval_id);
CREATE INDEX IF NOT EXISTS market_trades_created_idx ON market_trades (created_at DESC);

-- Prosumer dashboard (app/api/p2p_routes.py). manual = placed by the prosumer, not by the auto-trader.
ALTER TABLE market_orders ADD COLUMN IF NOT EXISTS manual BOOLEAN NOT NULL DEFAULT FALSE;
-- Per-prosumer switch: auto_trade FALSE = the market service skips automatic orders for that node.
CREATE TABLE IF NOT EXISTS market_node_settings (
    node_id TEXT PRIMARY KEY,
    auto_trade BOOLEAN NOT NULL DEFAULT TRUE,
    updated_at TIMESTAMPTZ
);
-- A manual order waits here until the next interval opens, then becomes that node's order for it
-- (status queued -> used | expired (role changed / no surplus left) | cancelled (replaced)).
CREATE TABLE IF NOT EXISTS market_manual_orders (
    id BIGSERIAL PRIMARY KEY,
    node_id TEXT NOT NULL,
    side TEXT NOT NULL,
    qty_wh BIGINT NOT NULL,
    price_milli INTEGER NOT NULL,
    user_id BIGINT,
    status TEXT NOT NULL DEFAULT 'queued',
    interval_id BIGINT,
    order_id BIGINT,
    error TEXT,
    created_at TIMESTAMPTZ NOT NULL
);
"""

_JSON = {"events", "forecast", "actuals", "summary"}
_TABLES = {"market_prosumers", "market_intervals", "market_orders", "market_trades", "market_node_settings", "market_manual_orders"}


def _row(columns: list[str], row: tuple) -> dict:
    out = dict(zip(columns, row))
    for k, v in out.items():
        if isinstance(v, datetime):
            out[k] = v.isoformat()
    return out


def _val(key: str, value: Any) -> Any:
    return Jsonb(value) if key in _JSON and value is not None else value


async def init_schema() -> None:
    async with db.get_pool().connection() as conn:
        await conn.execute(SCHEMA_SQL)


async def insert(table: str, record: dict) -> dict:
    assert table in _TABLES
    keys = list(record)
    async with db.get_pool().connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                f"INSERT INTO {table} ({', '.join(keys)}) VALUES ({', '.join(['%s'] * len(keys))}) RETURNING *",
                [_val(k, record[k]) for k in keys],
            )
            return _row([d[0] for d in cur.description], await cur.fetchone())


async def update(table: str, where: dict, **fields: Any) -> dict | None:
    assert table in _TABLES
    sets = ", ".join(f"{k} = %s" for k in fields)
    cond = " AND ".join(f"{k} = %s" for k in where)
    async with db.get_pool().connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                f"UPDATE {table} SET {sets} WHERE {cond} RETURNING *",
                [*(_val(k, v) for k, v in fields.items()), *where.values()],
            )
            row = await cur.fetchone()
            return _row([d[0] for d in cur.description], row) if row else None


async def select(table: str, where: str = "", params: tuple = (), order: str = "id DESC", limit: int | None = None) -> list[dict]:
    assert table in _TABLES
    sql = f"SELECT * FROM {table}" + (f" WHERE {where}" if where else "") + f" ORDER BY {order}"
    if limit is not None:
        sql += f" LIMIT {int(limit)}"
    async with db.get_pool().connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(sql, params)
            cols = [d[0] for d in cur.description]
            return [_row(cols, r) for r in await cur.fetchall()]


async def get(table: str, row_id: int) -> dict | None:
    rows = await select(table, "id = %s", (row_id,), limit=1)
    return rows[0] if rows else None


async def counts() -> dict:
    async with db.get_pool().connection() as conn:
        async with conn.cursor() as cur:
            out = {}
            for t in ("market_intervals", "market_orders", "market_trades"):
                await cur.execute(f"SELECT count(*) FROM {t}")
                out[t] = (await cur.fetchone())[0]
            await cur.execute("SELECT count(*), COALESCE(sum(settled_wh), 0), COALESCE(sum(pay_milli), 0) FROM market_trades WHERE status = 'settled'")
            n, wh, pay = await cur.fetchone()
            out.update(settled_trades=n, settled_wh=int(wh), settled_pay_milli=int(pay))
            return out
