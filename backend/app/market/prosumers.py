"""Pure prosumer models: PV estimate, synthetic load profiles, role.

DATA PROVENANCE (part of the spec, never blur it):
  solar   "live_api_estimated"  REAL current shortwave irradiance (GHI) and air
                                temperature from the Open-Meteo forecast API; the
                                PV OUTPUT is an ESTIMATE from a textbook formula,
                                not a metered value.
  load    "simulated"           deterministic SYNTHETIC hourly profile per building
                                type (local time, weekday/weekend), interpolated per
                                minute, +-5 % seeded noise.
  demo    "simulated"           when PROSUMER_IRRADIANCE_OVERRIDE is set the
                                irradiance itself is made up (dev demo aid).

SENSOR SEAM (not built): a future ESP32 (INA219/ACS712) -> MQTT -> TimescaleDB
source replaces the ESTIMATE per node by emitting the same NormalizedReading
(type="prosumer", power_output=generation_kw, consumption_kw, net_kw) with
provenance="sensed". `ingest_reading` and everything downstream (twin, market,
chain payloads, UI badges) only read those fields and `provenance`, so no
downstream change is needed; only app/market/source.py would change.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

PV_DERATE = 0.80
PV_TEMP_COEFF = 0.004  # per degC above 25 degC cell temperature
CELL_TEMP_RISE = 0.03  # degC per W/m2 of irradiance

PROV_SOLAR_LIVE = "live_api_estimated"
PROV_SIMULATED = "simulated"
PROV_SENSED = "sensed"  # reserved for the future ESP32 path


def pv_generation_kw(pv_kwp: float, ghi_wm2: float, air_temp_c: float) -> float:
    """generation_kw = pv_kwp * GHI/1000 * 0.80 * (1 - 0.004 * max(0, cell_temp - 25)),
    cell_temp = air_temp + 0.03 * GHI."""
    ghi = max(0.0, ghi_wm2)
    cell_temp = air_temp_c + CELL_TEMP_RISE * ghi
    return pv_kwp * ghi / 1000.0 * PV_DERATE * (1.0 - PV_TEMP_COEFF * max(0.0, cell_temp - 25.0))


# Hourly load anchors in kW (index = local hour, linearly interpolated per minute).
_HOUSE = [0.5, 0.45, 0.4, 0.4, 0.4, 0.6, 1.4, 2.4, 1.6, 0.9, 0.7, 0.7, 0.9, 0.8, 0.7, 0.8, 1.0, 1.8, 2.6, 3.0, 2.7, 2.0, 1.2, 0.7]
_APARTMENT = [4.0, 3.6, 3.3, 3.2, 3.2, 3.8, 5.5, 7.5, 6.0, 4.5, 4.0, 4.2, 4.8, 4.5, 4.2, 4.6, 5.8, 8.5, 10.5, 12.0, 11.0, 9.0, 6.5, 4.8]
_SHOP = [2.0, 2.0, 2.0, 2.0, 2.0, 2.0, 2.0, 2.0, 2.5, 6.5, 7.5, 8.0, 8.0, 7.5, 7.5, 8.0, 8.0, 8.0, 8.0, 7.5, 7.0, 6.5, 2.5, 2.0]
_SCHOOL_WEEKDAY = [2.0, 2.0, 2.0, 2.0, 2.0, 2.0, 2.0, 5.0, 14.0, 18.0, 20.0, 20.0, 17.0, 19.0, 18.0, 16.0, 8.0, 4.0, 2.5, 2.5, 2.0, 2.0, 2.0, 2.0]
_SCHOOL_WEEKEND = [2.0] * 24

# profile -> (weekday anchors, weekend anchors, min kW, max kW)
LOAD_PROFILES: dict[str, tuple[list[float], list[float], float, float]] = {
    "house": (_HOUSE, [min(3.0, v * 1.5) if 8 <= h <= 17 else v for h, v in enumerate(_HOUSE)], 0.4, 3.0),
    "apartment": (_APARTMENT, [min(12.0, v * 1.25) if 8 <= h <= 17 else v for h, v in enumerate(_APARTMENT)], 3.0, 12.0),
    "shop": (_SHOP, [v * 0.9 if 9 <= h <= 21 else v for h, v in enumerate(_SHOP)], 2.0, 8.0),
    "school": (_SCHOOL_WEEKDAY, _SCHOOL_WEEKEND, 2.0, 20.0),
}

LOAD_NOISE = 0.05  # +-5 %


def local_time(utc: datetime, utc_offset_hours: float) -> datetime:
    return (utc.astimezone(timezone.utc) + timedelta(hours=utc_offset_hours)).replace(tzinfo=None)


def base_load_kw(profile: str, local: datetime) -> float:
    """Noise-free load at a local wall-clock time (hourly anchors, linear per minute)."""
    weekday, weekend, _, _ = LOAD_PROFILES[profile]
    anchors = weekend if local.weekday() >= 5 else weekday
    pos = local.hour + local.minute / 60.0
    i = int(pos) % 24
    frac = pos - int(pos)
    return anchors[i] * (1.0 - frac) + anchors[(i + 1) % 24] * frac


def load_kw(node_id: str, profile: str, utc: datetime, utc_offset_hours: float) -> float:
    """Synthetic load: profile value * (1 +- 5 % noise). Deterministic: the noise
    is seeded by (node_id, local minute), so the same minute always gives the same value."""
    local = local_time(utc, utc_offset_hours)
    minute_index = local.toordinal() * 1440 + local.hour * 60 + local.minute
    noise = random.Random(f"{node_id}:{minute_index}").uniform(-LOAD_NOISE, LOAD_NOISE)
    _, _, lo, hi = LOAD_PROFILES[profile]
    value = base_load_kw(profile, local) * (1.0 + noise)
    return max(lo * (1 - LOAD_NOISE), min(hi * (1 + LOAD_NOISE), value))


def role_of(net_kw: float | None, deadband_kw: float) -> str:
    if net_kw is None:
        return "balanced"
    if net_kw > deadband_kw:
        return "surplus"
    if net_kw < -deadband_kw:
        return "deficit"
    return "balanced"
