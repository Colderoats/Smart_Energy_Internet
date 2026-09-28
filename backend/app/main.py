import asyncio
import logging
import sys
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import db
from app.config import settings
from app.ai_service.predictor import predictor
from app.blockchain.ledger import ledger
from app.api.ai_routes import router as ai_router
from app.api.auth_routes import router as auth_router
from app.api.chain_routes import router as chain_router
from app.api.routes import router as api_router
from app.api.routes import ws_router
from app.auth import store as auth_store
from app.auth.deps import origin_check_middleware, require_admin
from app.auth.tokens import check_config as check_auth_config
from app.api.twin_routes import router as twin_router
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
        await auth_store.init_schema()
        logger.info("Connected to TimescaleDB")
    except Exception as exc:
        logger.warning("Could not connect to TimescaleDB at startup: %s", exc)

    if not settings.run_background_tasks:
        # Tests: DB + routes only (no model load, ledger or ingestion).
        yield
        await db.disconnect()
        return

    # Module 3: load the saved TA-GNN (imports torch — keep off the event loop).
    # Missing torch/artifact disables scoring; the rule-based detector runs regardless.
    await asyncio.to_thread(predictor.load)

    # Module 5: blockchain ledger worker + chain health loop. Started before
    # ingestion so the first twin decisions are recorded. Never fatal and never
    # waits on the chain: an unreachable node just leaves records queued.
    await ledger.start()

    background_tasks.append(asyncio.create_task(run_live_poller()))
    background_tasks.append(asyncio.create_task(run_scada_replay()))

    yield

    await ledger.stop()
    for task in background_tasks:
        task.cancel()
    await db.disconnect()


# Fail fast without a JWT secret rather than run with guessable tokens.
check_auth_config()

docs_kwargs = {} if settings.api_docs_enabled else {"docs_url": None, "redoc_url": None, "openapi_url": None}
app = FastAPI(title="Smart Energy Internet API", lifespan=lifespan, **docs_kwargs)

# CSRF defence (SameSite=Strict cookies + Origin check on state-changing
# requests); added first so CORS stays the outermost layer.
app.middleware("http")(origin_check_middleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)

# Every data router requires an authenticated admin. Public routes are only
# /health and the /auth endpoints that must work without a session; the
# WebSocket authenticates itself on connect (app/api/routes.py).
protected = [Depends(require_admin)]
app.include_router(auth_router)
app.include_router(api_router, dependencies=protected)
app.include_router(twin_router, dependencies=protected)
app.include_router(ai_router, dependencies=protected)
app.include_router(chain_router, dependencies=protected)
app.include_router(ws_router)


@app.get("/health")
async def health():
    db_ok = await db.ping()
    return {
        "status": "ok",
        "db": "connected" if db_ok else "disconnected",
    }
