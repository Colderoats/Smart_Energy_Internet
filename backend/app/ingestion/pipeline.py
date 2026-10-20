"""Single entry point both ingestion sources (live poller, SCADA replay)
push through: normalize -> fault-detect -> update twin -> persist -> push
to any connected WebSocket clients. Keeping one path means the frontend and
TimescaleDB never see live and historical data handled differently."""

import logging

from app import db
from app.ai_service.integration import apply_detectors
from app.api.ws_manager import manager
from app.models.reading import NormalizedReading, normalized_values
from app.twin import fault_detection, self_healing
from app.twin.digital_twin import COMMUNITY_BUS, PROSUMER_NODES, SOURCE_NODES, digital_twin
from app.twin.graph import twin

logger = logging.getLogger("sei")

_RATED_KW = {n["node_id"]: n["rated_capacity_kw"] for n in SOURCE_NODES}


async def _ingest_prosumer(reading: NormalizedReading) -> None:
    """Prosumer path: normalize -> twin update -> persist -> broadcast. Fault
    detection, the TA-GNN and self-healing are SKIPPED on purpose (prosumers are
    simulated buildings, outside the fault-prediction scope). Module 1's `twin`
    graph is not touched either."""
    from app.config import settings
    from app.market.prosumers import role_of
    from app.market.service import market

    reading_dict = reading.model_dump(mode="json")
    pv_kwp = next(n["pv_kwp"] for n in PROSUMER_NODES if n["node_id"] == reading.node_id)
    reading_dict["normalized"] = normalized_values(reading_dict, pv_kwp)
    role = role_of(reading.net_kw, settings.prosumer_role_deadband_kw)
    node_state = digital_twin.update_prosumer(reading.node_id, reading_dict, role)

    try:
        await db.insert_reading(reading)
    except Exception as exc:
        logger.warning("Failed to persist reading for %s: %s", reading.node_id, exc)

    await manager.broadcast({"type": "twin_node_update", "node": node_state})
    await manager.broadcast({"type": "twin_node_update", "node": digital_twin.get_node(COMMUNITY_BUS)})
    await manager.broadcast({"type": "market_prosumer_update", "prosumer": market.prosumer_view(node_state)})
    market.observe(reading.node_id, reading.net_kw)


async def ingest_reading(reading: NormalizedReading) -> None:
    if reading.type == "prosumer":
        await _ingest_prosumer(reading)
        return
    health_status = fault_detection.evaluate(reading)
    reading_dict = reading.model_dump(mode="json")
    # Normalise once, here, so the twin, detectors and frontend all get it.
    reading_dict["normalized"] = normalized_values(reading_dict, _RATED_KW.get(reading.node_id))
    node_state = twin.update_node(reading.node_id, reading_dict, health_status)

    # Module 2's digital twin keeps its own (richer) state view of the same
    # normalized reading — see app/twin/digital_twin.py. Self-healing
    # (Stage 2) reacts to this update, not to Module 1's graph.
    twin_state = digital_twin.update_node(reading.node_id, reading_dict, health_status)

    # Module 3: the TA-GNN scores replayed SCADA nodes alongside the rule-based
    # detector above and may raise the twin's health_status to
    # "fault_predicted" (see app/ai_service/integration.py). Module 1's own
    # graph (`twin`, Live Data tab) deliberately keeps the rule-based status only.
    twin_state = await apply_detectors(reading, reading_dict, health_status) or twin_state

    try:
        await db.insert_reading(reading)
    except Exception as exc:
        logger.warning("Failed to persist reading for %s: %s", reading.node_id, exc)

    await manager.broadcast({"type": "node_update", "node": node_state})
    await manager.broadcast({"type": "twin_node_update", "node": twin_state})

    # May generate + auto-apply a reconfiguration and broadcast a
    # "twin_decision" message — see app/twin/self_healing.py.
    await self_healing.maybe_trigger(reading.node_id)
