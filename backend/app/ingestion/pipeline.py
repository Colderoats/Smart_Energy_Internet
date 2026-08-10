"""Single entry point both ingestion sources (live poller, SCADA replay)
push through: normalize -> fault-detect -> update twin -> persist -> push
to any connected WebSocket clients. Keeping one path means the frontend and
TimescaleDB never see live and historical data handled differently."""

import logging

from app import db
from app.api.ws_manager import manager
from app.models.reading import NormalizedReading
from app.twin import fault_detection
from app.twin.graph import twin

logger = logging.getLogger("sei")


async def ingest_reading(reading: NormalizedReading) -> None:
    health_status = fault_detection.evaluate(reading)
    node_state = twin.update_node(reading.node_id, reading.model_dump(mode="json"), health_status)

    try:
        await db.insert_reading(reading)
    except Exception as exc:
        logger.warning("Failed to persist reading for %s: %s", reading.node_id, exc)

    await manager.broadcast({"type": "node_update", "node": node_state})
