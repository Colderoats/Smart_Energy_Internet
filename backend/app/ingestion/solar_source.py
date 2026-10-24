"""Solar plant source: a SMALL bundled 24-hour sample dataset (data/solar/solar_plant_sample.csv, a 50 kWp plant, hourly
irradiance + AC power) replayed in a loop, one row every SOLAR_REPLAY_SECONDS. The sample is illustrative (generated clear-sky
curve with cloud factors), not a measured plant: readings are source_type "simulated", provenance "replayed_dataset".

ESP32 seam (hardware not built yet): set SOLAR_SOURCE=sensed to stop the replay, then have the MQTT subscriber call
`ingest_sensed(power_kw, voltage_v, current_a)` for each INA219/ACS712 sample. It builds the same NormalizedReading
(source_type "live", provenance "sensed") and everything downstream is unchanged.
"""

import asyncio
import csv
import logging
from datetime import datetime, timezone
from pathlib import Path

from app.config import settings
from app.ingestion.pipeline import ingest_reading
from app.models.reading import NormalizedReading

logger = logging.getLogger("sei")

SOLAR_NODE_ID = "solar_01"
DATASET = Path(__file__).resolve().parents[2] / "data" / "solar" / "solar_plant_sample.csv"


def load_dataset(path: Path = DATASET) -> list[dict]:
    with open(path, newline="") as f:
        return [{k: float(v) for k, v in row.items()} for row in csv.DictReader(f)]


def build_reading(row: dict) -> NormalizedReading:
    return NormalizedReading(
        node_id=SOLAR_NODE_ID, source_type="simulated", type="solar", timestamp=datetime.now(timezone.utc),
        power_output=row["ac_power_kw"], irradiance_wm2=row["irradiance_wm2"], provenance="replayed_dataset",
    )


async def ingest_sensed(power_kw: float, voltage_v: float | None = None, current_a: float | None = None) -> None:
    """ESP32 entry point (not wired yet). voltage/current are accepted for the future sensor payload but not stored."""
    await ingest_reading(NormalizedReading(
        node_id=SOLAR_NODE_ID, source_type="live", type="solar", timestamp=datetime.now(timezone.utc),
        power_output=power_kw, provenance="sensed",
    ))


async def run_solar_replay() -> None:
    if settings.solar_source != "replay":
        logger.info("Solar replay off (SOLAR_SOURCE=%s): waiting for ESP32 readings", settings.solar_source)
        return
    rows = load_dataset()
    i = datetime.now().hour % len(rows)  # start at the current local hour
    while True:
        try:
            await ingest_reading(build_reading(rows[i]))
        except Exception as exc:
            logger.warning("Solar replay failed: %s", exc)
        i = (i + 1) % len(rows)
        await asyncio.sleep(settings.solar_replay_seconds)
