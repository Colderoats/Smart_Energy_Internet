from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool

from app.config import settings
from app.models.reading import NormalizedReading

_pool: AsyncConnectionPool | None = None


async def connect() -> None:
    global _pool
    pool = AsyncConnectionPool(conninfo=settings.database_url, min_size=1, max_size=5, open=False)
    try:
        await pool.open(wait=True, timeout=5)
    except Exception:
        # pool.open() closes itself on a failed/timed-out attempt, so don't
        # leave a dead pool object behind for ping()/get_pool() to trip on.
        _pool = None
        raise
    _pool = pool


async def disconnect() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


def get_pool() -> AsyncConnectionPool:
    if _pool is None:
        raise RuntimeError("DB pool not initialized — call connect() during app startup first")
    return _pool


async def ping() -> bool:
    if _pool is None:
        return False
    try:
        async with _pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT 1")
                result = await cur.fetchone()
                return result == (1,)
    except Exception:
        return False


SCHEMA_SQL = """
CREATE EXTENSION IF NOT EXISTS timescaledb;

CREATE TABLE IF NOT EXISTS readings (
    time TIMESTAMPTZ NOT NULL,
    node_id TEXT NOT NULL,
    source_type TEXT NOT NULL,
    type TEXT NOT NULL,
    power_output DOUBLE PRECISION,
    wind_speed DOUBLE PRECISION,
    vibration DOUBLE PRECISION,
    temperature DOUBLE PRECISION,
    fault_label TEXT
);

SELECT create_hypertable('readings', by_range('time'), if_not_exists => TRUE);

CREATE INDEX IF NOT EXISTS readings_node_time_idx ON readings (node_id, time DESC);

-- Module 2 self-healing decision log (app/twin/self_healing.py). A plain
-- table, not a hypertable — decision volume is far lower than raw
-- readings (one row per fault episode, not per reading).
CREATE TABLE IF NOT EXISTS twin_decisions (
    time TIMESTAMPTZ NOT NULL,
    node_id TEXT NOT NULL,
    trigger_health_status TEXT NOT NULL,
    trigger_summary TEXT,
    candidates JSONB NOT NULL,
    chosen_action TEXT NOT NULL,
    chosen_params JSONB,
    chosen_score DOUBLE PRECISION NOT NULL,
    reason TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS twin_decisions_time_idx ON twin_decisions (time DESC);
CREATE INDEX IF NOT EXISTS twin_decisions_node_time_idx ON twin_decisions (node_id, time DESC);
"""


async def init_schema() -> None:
    pool = get_pool()
    async with pool.connection() as conn:
        await conn.execute(SCHEMA_SQL)


async def insert_reading(reading: NormalizedReading) -> None:
    pool = get_pool()
    async with pool.connection() as conn:
        await conn.execute(
            """
            INSERT INTO readings
                (time, node_id, source_type, type, power_output,
                 wind_speed, vibration, temperature, fault_label)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                reading.timestamp,
                reading.node_id,
                reading.source_type,
                reading.type,
                reading.power_output,
                reading.wind_speed,
                reading.vibration,
                reading.temperature,
                reading.fault_label,
            ),
        )


async def fetch_history(node_id: str, limit: int = 100) -> list[dict]:
    pool = get_pool()
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                SELECT time, node_id, source_type, type, power_output,
                       wind_speed, vibration, temperature, fault_label
                FROM readings
                WHERE node_id = %s
                ORDER BY time DESC
                LIMIT %s
                """,
                (node_id, limit),
            )
            rows = await cur.fetchall()
            columns = [desc[0] for desc in cur.description]
            return [dict(zip(columns, row)) for row in rows]


async def insert_decision(decision: dict) -> None:
    pool = get_pool()
    async with pool.connection() as conn:
        await conn.execute(
            """
            INSERT INTO twin_decisions
                (time, node_id, trigger_health_status, trigger_summary,
                 candidates, chosen_action, chosen_params, chosen_score, reason)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                decision["time"],
                decision["node_id"],
                decision["trigger_health_status"],
                decision["trigger_summary"],
                Jsonb(decision["candidates"]),
                decision["chosen_action"],
                Jsonb(decision["chosen_params"]),
                decision["chosen_score"],
                decision["reason"],
            ),
        )


async def fetch_decisions(node_id: str | None = None, limit: int = 100) -> list[dict]:
    pool = get_pool()
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            if node_id is not None:
                await cur.execute(
                    """
                    SELECT time, node_id, trigger_health_status, trigger_summary,
                           candidates, chosen_action, chosen_params, chosen_score, reason
                    FROM twin_decisions
                    WHERE node_id = %s
                    ORDER BY time DESC
                    LIMIT %s
                    """,
                    (node_id, limit),
                )
            else:
                await cur.execute(
                    """
                    SELECT time, node_id, trigger_health_status, trigger_summary,
                           candidates, chosen_action, chosen_params, chosen_score, reason
                    FROM twin_decisions
                    ORDER BY time DESC
                    LIMIT %s
                    """,
                    (limit,),
                )
            rows = await cur.fetchall()
            columns = [desc[0] for desc in cur.description]
            return [dict(zip(columns, row)) for row in rows]
