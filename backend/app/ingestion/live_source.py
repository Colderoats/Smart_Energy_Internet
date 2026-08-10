"""Live wind/hydro data from Open-Meteo (open-meteo.com) — free, no API
key. Two endpoints:
  - Forecast API: real current wind speed at the wind node's coordinates.
  - Flood API (GloFAS): real daily river discharge at the hydro node's
    coordinates, used as a stand-in for hydro plant inflow.

Neither endpoint reports electrical power output directly, so power_output
here is ESTIMATED from the real live reading via a textbook physics
formula (turbine power curve / hydro power equation), not a metered value.
This is live, API-sourced data, not a physically sensed reading — see
CLAUDE.md's data-sourcing rules. The estimate is clearly a demo
simplification: a generic turbine curve and an assumed dam head/efficiency,
not any specific real plant's spec.
"""

from datetime import datetime, timezone

import httpx

from app.config import settings
from app.models.reading import NormalizedReading

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
FLOOD_URL = "https://flood-api.open-meteo.com/v1/flood"

WIND_NODE_ID = "wind_01"
HYDRO_NODE_ID = "hydro_01"

# Generic utility-scale turbine power curve parameters (not a real model's
# spec — a reasonable illustrative approximation for a ~2MW turbine).
WIND_CUT_IN_MS = 3.0
WIND_RATED_MS = 12.0
WIND_CUT_OUT_MS = 25.0
WIND_RATED_POWER_KW = 2000.0

# Assumed small-hydro plant parameters (also illustrative, not a real
# plant's spec) for P = rho * g * Q * H * efficiency.
HYDRO_HEAD_M = 30.0
HYDRO_EFFICIENCY = 0.85
WATER_DENSITY = 1000.0
GRAVITY = 9.81


def estimate_wind_power_kw(wind_speed_ms: float) -> float:
    if wind_speed_ms < WIND_CUT_IN_MS or wind_speed_ms >= WIND_CUT_OUT_MS:
        return 0.0
    if wind_speed_ms >= WIND_RATED_MS:
        return WIND_RATED_POWER_KW
    fraction = (wind_speed_ms - WIND_CUT_IN_MS) / (WIND_RATED_MS - WIND_CUT_IN_MS)
    return WIND_RATED_POWER_KW * fraction**3


def estimate_hydro_power_kw(discharge_m3s: float) -> float:
    watts = WATER_DENSITY * GRAVITY * discharge_m3s * HYDRO_HEAD_M * HYDRO_EFFICIENCY
    return watts / 1000.0


async def fetch_wind_reading(client: httpx.AsyncClient) -> NormalizedReading:
    resp = await client.get(
        FORECAST_URL,
        params={
            "latitude": settings.wind_node_lat,
            "longitude": settings.wind_node_lon,
            "current": "wind_speed_10m",
            "wind_speed_unit": "ms",
            "timezone": "UTC",
        },
    )
    resp.raise_for_status()
    data = resp.json()
    wind_speed = float(data["current"]["wind_speed_10m"])
    timestamp = datetime.fromisoformat(data["current"]["time"]).replace(tzinfo=timezone.utc)

    return NormalizedReading(
        node_id=WIND_NODE_ID,
        source_type="live",
        type="wind",
        timestamp=timestamp,
        power_output=estimate_wind_power_kw(wind_speed),
        wind_speed=wind_speed,
    )


async def fetch_hydro_reading(client: httpx.AsyncClient) -> NormalizedReading:
    resp = await client.get(
        FLOOD_URL,
        params={
            "latitude": settings.hydro_node_lat,
            "longitude": settings.hydro_node_lon,
            "daily": "river_discharge",
            "timezone": "UTC",
            "forecast_days": 1,
        },
    )
    resp.raise_for_status()
    data = resp.json()
    discharge = float(data["daily"]["river_discharge"][0])
    timestamp = datetime.now(timezone.utc)

    return NormalizedReading(
        node_id=HYDRO_NODE_ID,
        source_type="live",
        type="hydro",
        timestamp=timestamp,
        power_output=estimate_hydro_power_kw(discharge),
    )
