"""Readings for the extra simulated sources of the live twin (solar_02, battery_01).

They go straight into the Digital Twin (like the prosumers): no Module 1 graph, no database, no fault detection / AI. solar_02 follows a
smooth day curve compressed to a few minutes; the battery discharges while demand is above normal (load_profile.demand_factor) and
charges (output 0) otherwise. Simulated, not measured.
"""

import asyncio
import logging
import math
from datetime import datetime, timezone
from time import monotonic

from app.api.ws_manager import manager
from app.models.reading import normalized_values
from app.twin.digital_twin import EXTRA_SOURCE_NODES, digital_twin

logger = logging.getLogger("sei")

TICK_S = 3.0
SOLAR_DAY_S = 300.0


def output_kw(node_id: str, rated_kw: float, t_s: float, demand_factor: float) -> float:
    if node_id == "solar_02":
        return rated_kw * max(0.0, math.sin(2 * math.pi * t_s / SOLAR_DAY_S))
    return rated_kw * min(1.0, max(0.0, (demand_factor - 1.0) / 0.12))  # battery_01


async def run_extra_sources() -> None:
    t0 = monotonic()
    nodes = {n["node_id"]: n for n in EXTRA_SOURCE_NODES}
    while True:
        try:
            for nid, n in nodes.items():
                kw = output_kw(nid, n["rated_capacity_kw"], monotonic() - t0, digital_twin.demand_factor)
                reading = {"node_id": nid, "source_type": "simulated", "type": n["type"], "timestamp": datetime.now(timezone.utc).isoformat(),
                           "power_output": round(kw, 2), "provenance": "simulated"}
                reading["normalized"] = normalized_values(reading, n["rated_capacity_kw"])
                state = digital_twin.update_node(nid, reading, "normal")
                await manager.broadcast({"type": "twin_node_update", "node": state})
        except Exception as exc:
            logger.warning("Extra sources tick failed: %s", exc)
        await asyncio.sleep(TICK_S)
