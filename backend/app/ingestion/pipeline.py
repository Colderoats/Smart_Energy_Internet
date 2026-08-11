"""Single entry point both ingestion sources (live poller, SCADA replay)
push through: normalize -> fault-detect -> update twin -> persist -> push
to any connected WebSocket clients. Keeping one path means the frontend and
TimescaleDB never see live and historical data handled differently."""

import logging

from app import db
from app.api.ws_manager import manager
from app.models.reading import NormalizedReading
from app.twin import fault_detection, self_healing
from app.twin.digital_twin import digital_twin
from app.twin.graph import twin

logger = logging.getLogger("sei")


async def ingest_reading(reading: NormalizedReading) -> None:
    health_status = fault_detection.evaluate(reading)
    reading_dict = reading.model_dump(mode="json")
    node_state = twin.update_node(reading.node_id, reading_dict, health_status)

    # Module 2's digital twin keeps its own (richer) state view of the same
    # normalized reading — see app/twin/digital_twin.py. Self-healing
    # (Stage 2) reacts to this update, not to Module 1's graph.
    twin_state = digital_twin.update_node(reading.node_id, reading_dict, health_status)

    try:
        await db.insert_reading(reading)
    except Exception as exc:
        logger.warning("Failed to persist reading for %s: %s", reading.node_id, exc)

    await manager.broadcast({"type": "node_update", "node": node_state})
    await manager.broadcast({"type": "twin_node_update", "node": twin_state})

    # May generate + auto-apply a reconfiguration and broadcast a
    # "twin_decision" message — see app/twin/self_healing.py.
    await self_healing.maybe_trigger(reading.node_id)
