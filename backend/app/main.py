import asyncio
import logging
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import db
from app.api.routes import router as api_router
from app.ingestion.poller import run_live_poller
from app.ingestion.scada_replay import run_scada_replay

if sys.platform == "win32":
    # psycopg3's async mode requires selector-based I/O; Windows defaults to
    # ProactorEventLoop, which it cannot use.
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("sei")


@asynccontextmanager
async def lifespan(app: FastAPI):
    background_tasks = []
    try:
        await db.connect()
        await db.init_schema()
        logger.info("Connected to TimescaleDB")
    except Exception as exc:
        logger.warning("Could not connect to TimescaleDB at startup: %s", exc)

    background_tasks.append(asyncio.create_task(run_live_poller()))
    background_tasks.append(asyncio.create_task(run_scada_replay()))

    yield

    for task in background_tasks:
        task.cancel()
    await db.disconnect()


app = FastAPI(title="Smart Energy Internet API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)


@app.get("/health")
async def health():
    db_ok = await db.ping()
    return {
        "status": "ok",
        "db": "connected" if db_ok else "disconnected",
    }
