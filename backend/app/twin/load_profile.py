"""Slow demand cycle of the LIVE twin so the overload -> reroute -> recover path runs without anyone touching a limit.

`digital_twin.demand_factor` follows 1 + AMPLITUDE * sin(2 pi t / PERIOD) (settings.load_profile_*; PERIOD 0 = off). Every bus
load is rated x load_share x factor, so at the peak the busiest buses pass their limit and grid_protection relieves them over
the tie switches; when the factor falls, `auto_recover` moves the sources back. Illustrative demand, not measured.
"""

import asyncio
import logging
import math
from time import monotonic

from app.api.ws_manager import manager
from app.config import settings
from app.twin import grid_protection
from app.twin.digital_twin import digital_twin

logger = logging.getLogger("sei")

TICK_S = 2.0


def factor_at(t_s: float, period_s: float, amplitude: float) -> float:
    return 1.0 + amplitude * math.sin(2 * math.pi * t_s / period_s)


async def run_load_profile() -> None:
    if settings.load_profile_period_s <= 0:
        logger.info("Load profile off (LOAD_PROFILE_PERIOD_S=0)")
        return
    t0 = monotonic()
    while True:
        try:
            digital_twin.demand_factor = factor_at(monotonic() - t0, settings.load_profile_period_s, settings.load_profile_amplitude)
            for bus in digital_twin.bus_ids():
                await manager.broadcast({"type": "twin_node_update", "node": digital_twin.get_node(bus)})
            await grid_protection.check_overloads()
            await grid_protection.auto_recover()
        except Exception as exc:
            logger.warning("Load profile tick failed: %s", exc)
        await asyncio.sleep(TICK_S)
