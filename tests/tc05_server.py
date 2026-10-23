"""TC05 helper - runs the REAL backend app on an isolated stack (own DB, own Hardhat node, port 8100) and adds ONE test-only
route to inject a fault into the Digital Twin through the normal ingestion path. Nothing in backend/ is modified.
    backend\venv\Scripts\python tests\tc05_server.py"""
import asyncio
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

REPO = Path(__file__).resolve().parents[1]
os.environ.update(POSTGRES_DB="sei_tc05", BLOCKCHAIN_LOCAL_RPC_URL="http://127.0.0.1:8546", FRONTEND_ORIGIN="http://localhost:5190",
                  COOKIE_SECURE="false", SCADA_REPLAY_INTERVAL_SECONDS="2")
sys.path.insert(0, str(REPO / "backend"))
os.chdir(REPO / "backend")

import math  # noqa: E402
import random  # noqa: E402

import uvicorn  # noqa: E402

import app.main as app_main  # noqa: E402
from app.ingestion.pipeline import ingest_reading  # noqa: E402
from app.main import app  # noqa: E402
from app.models.reading import NormalizedReading  # noqa: E402

TURBINES = [f"wind_scada_kelmarsh_{n}" for n in range(1, 5)]
faulted: set[str] = set()


async def normal_feed():
    """HARNESS ONLY: stands in for app.ingestion.scada_replay (the real replay starts inside a logged fault window, so there is no
    healthy baseline to inject into). Synthetic, healthy 2 s readings for the 4 turbines; a turbine stops being fed once it is faulted
    (a fault persists until repaired). Not real SCADA data."""
    rng, k = random.Random(5), 0
    while True:
        k += 1
        for node in TURBINES:
            if node in faulted:
                continue
            await ingest_reading(NormalizedReading(
                node_id=node, source_type="historical", type="wind", timestamp=datetime.now(timezone.utc),
                power_output=1000 + 400 * math.sin(k / 7) + rng.uniform(-30, 30), temperature=45 + rng.uniform(-0.4, 0.4),
                vibration=2.0 + rng.uniform(-0.1, 0.1)))
        await asyncio.sleep(2)


app_main.run_scada_replay = normal_feed  # lifespan starts this instead of the real replay


@app.post("/_test/inject-fault")
async def inject_fault(node_id: str = "wind_scada_kelmarsh_1"):
    """TEST ONLY (not part of the product): a SCADA reading with a ground-truth 'Stop' label, as the replay would deliver."""
    r = NormalizedReading(node_id=node_id, source_type="historical", type="wind", timestamp=datetime.now(timezone.utc), power_output=0.0,
                          temperature=95.0, vibration=9.0, fault_label="Stop: TC05 injected fault")
    t0 = datetime.now(timezone.utc).isoformat()
    faulted.add(node_id)
    await ingest_reading(r)
    return {"injected": node_id, "at": t0}


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8100, log_level="warning")
