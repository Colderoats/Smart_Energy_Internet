from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class NormalizedReading(BaseModel):
    """The one schema every ingestion source (live API, SCADA replay) must
    conform to before it touches storage or the twin — see
    docs/architecture.md 'Normalized data schema'."""

    node_id: str
    source_type: Literal["live", "historical", "simulated"]
    type: Literal["wind", "hydro", "prosumer"]
    timestamp: datetime
    power_output: float
    wind_speed: float | None = None
    vibration: float | None = None
    temperature: float | None = None
    fault_label: str | None = None
    # Module 3 addition. SCADA-only (source_type="historical"): extra REAL
    # measured channels from the replayed Kelmarsh export (wind speed at the
    # turbine's own anemometer, rotor/generator RPM, pitch, temperatures).
    # Keys are defined by SCADA_CHANNELS in app/ingestion/scada_replay.py;
    # channels that are NaN in the source are simply absent. Distinct from
    # `wind_speed`, which stays live-API-only. None for live wind/hydro.
    scada_channels: dict[str, float] | None = None
    # Prosumer market addition (all optional; None for wind/hydro). For a
    # prosumer, power_output is its generation_kw. `provenance` says where the
    # values come from: "live_api_estimated" (real weather -> estimated PV),
    # "simulated" (synthetic load / demo irradiance) or, in future, "sensed"
    # (ESP32 INA219/ACS712 -> MQTT -> TimescaleDB replacing the estimate).
    consumption_kw: float | None = None
    net_kw: float | None = None
    irradiance_wm2: float | None = None
    provenance: str | None = None


# Fixed scales used to normalise a reading before the twin, detectors and
# frontend see it (per-unit / min-max, all values land in ~[0, 1]).
WIND_SPEED_MAX_MS = 25.0   # turbine cut-out speed
TEMP_MIN_C, TEMP_MAX_C = -20.0, 120.0
VIBRATION_MAX = 10.0


def normalized_values(reading: dict, rated_kw: float | None) -> dict:
    """Normalised copy of a reading's numeric channels, keyed by channel name.
    Power is per-unit of rated capacity; the rest are min-max over fixed ranges."""
    def clip(x: float) -> float:
        return max(0.0, min(1.0, x))

    out: dict[str, float] = {}
    if rated_kw and reading.get("power_output") is not None:
        out["power_output"] = round(clip(reading["power_output"] / rated_kw), 4)
    if reading.get("wind_speed") is not None:
        out["wind_speed"] = round(clip(reading["wind_speed"] / WIND_SPEED_MAX_MS), 4)
    if reading.get("temperature") is not None:
        out["temperature"] = round(clip((reading["temperature"] - TEMP_MIN_C) / (TEMP_MAX_C - TEMP_MIN_C)), 4)
    if reading.get("vibration") is not None:
        out["vibration"] = round(clip(reading["vibration"] / VIBRATION_MAX), 4)
    return out
