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
