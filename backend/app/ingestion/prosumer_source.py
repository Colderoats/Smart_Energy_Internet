"""Prosumer readings: REAL live weather -> ESTIMATED PV, plus SYNTHETIC load.

Same poller pattern as app/ingestion/poller.py (httpx + Open-Meteo, log and carry
on when a call fails), but weather is fetched at most every
PROSUMER_WEATHER_POLL_SECONDS while a reading per prosumer is produced every
PROSUMER_TICK_SECONDS (the weather only changes every ~15 min; the load profile
moves every minute).

Provenance (see app/market/prosumers.py for the formulas):
  generation  "live_api_estimated"  real GHI + temperature, estimated PV output
              "simulated"           PROSUMER_IRRADIANCE_OVERRIDE is set (demo irradiance)
  consumption "simulated"           deterministic synthetic profile

If no weather has ever been fetched (API down at startup) and no override is set,
NO reading is produced: nothing is made up and presented as live.

Sensor seam: a future ESP32 -> MQTT -> TimescaleDB source would build the same
NormalizedReading (type="prosumer", provenance="sensed") in place of
`build_reading`; ingest_reading and everything downstream stay unchanged.
"""

import asyncio
import logging
import time
from datetime import datetime, timezone

import httpx

from app.config import settings
from app.ingestion.live_source import FORECAST_URL
from app.ingestion.pipeline import ingest_reading
from app.market import prosumers as P
from app.models.reading import NormalizedReading
from app.twin.digital_twin import PROSUMER_NODES

logger = logging.getLogger("sei")

DEMO_AIR_TEMP_C = 30.0  # only used with the irradiance override when no live temperature was ever fetched

_weather: dict | None = None  # {"ghi_wm2","temp_c","observed_at","fetched_at"}


def current_weather() -> dict | None:
    return _weather


async def fetch_weather(client: httpx.AsyncClient) -> dict:
    resp = await client.get(
        FORECAST_URL,
        params={
            "latitude": settings.prosumer_lat,
            "longitude": settings.prosumer_lon,
            "current": "shortwave_radiation,temperature_2m",
            "timezone": "UTC",
        },
    )
    resp.raise_for_status()
    cur = resp.json()["current"]
    return {
        "ghi_wm2": float(cur["shortwave_radiation"]),
        "temp_c": float(cur["temperature_2m"]),
        "observed_at": datetime.fromisoformat(cur["time"]).replace(tzinfo=timezone.utc).isoformat(),
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }


def build_reading(node: dict, ghi_wm2: float, air_temp_c: float, demo_irradiance: bool, now: datetime | None = None) -> NormalizedReading:
    now = now or datetime.now(timezone.utc)
    generation = P.pv_generation_kw(node["pv_kwp"], ghi_wm2, air_temp_c)
    consumption = P.load_kw(node["node_id"], node["profile"], now, settings.prosumer_utc_offset_hours)
    return NormalizedReading(
        node_id=node["node_id"],
        source_type="simulated",
        type="prosumer",
        timestamp=now,
        power_output=round(generation, 4),
        temperature=round(air_temp_c, 2),
        consumption_kw=round(consumption, 4),
        net_kw=round(generation - consumption, 4),
        irradiance_wm2=round(ghi_wm2, 2),
        provenance=P.PROV_SIMULATED if demo_irradiance else P.PROV_SOLAR_LIVE,
    )


async def run_prosumer_poller() -> None:
    global _weather
    last_fetch = float("-inf")
    async with httpx.AsyncClient(timeout=10.0) as client:
        while True:
            if time.monotonic() - last_fetch >= settings.prosumer_weather_poll_seconds:
                last_fetch = time.monotonic()
                try:
                    _weather = await fetch_weather(client)
                except Exception as exc:
                    logger.warning("Prosumer weather poll failed: %s", exc)

            override = settings.prosumer_irradiance_override
            if override is not None:
                ghi, temp, demo = override, (_weather or {}).get("temp_c", DEMO_AIR_TEMP_C), True
            elif _weather is not None:
                ghi, temp, demo = _weather["ghi_wm2"], _weather["temp_c"], False
            else:
                ghi = None
            if ghi is not None:
                for node in PROSUMER_NODES:
                    try:
                        await ingest_reading(build_reading(node, ghi, temp, demo))
                    except Exception as exc:
                        logger.warning("Prosumer reading failed for %s: %s", node["node_id"], exc)
            await asyncio.sleep(settings.prosumer_tick_seconds)
