"""Validation step for LIVE wind/hydro API readings (runs in ingest_reading before normalisation, the twin and the DB).

A sample that is non-finite or outside the physical limits below is flagged invalid and replaced by the node's last valid
value; if the node has none yet the sample is dropped. SCADA-replay and prosumer readings are not touched.

The limits are deliberately loose sanity bounds, not the rated values: the live power figures are ESTIMATES from weather /
discharge (live_source.py) and the hydro estimate legitimately exceeds the illustrative 400 kW rating, so a rated-capacity
limit would reject good data. They only catch impossible values (sensor glitch, unit error, API garbage).
"""

import logging
import math

from app.models.reading import NormalizedReading

logger = logging.getLogger("sei")

MAX_POWER_RATED_FACTOR = 100.0  # wind power must be within [0, 100 x rated_capacity_kw]; hydro only >= 0
WIND_SPEED_LIMIT_MS = 75.0      # wind_speed must be within [0, 75] m/s (above any recorded surface gust)

_last_valid: dict[str, tuple[float, float | None]] = {}  # node_id -> (power_output, wind_speed)


def _problem(reading: NormalizedReading, rated_kw: float) -> str | None:
    for name, value in (("power_output", reading.power_output), ("wind_speed", reading.wind_speed)):
        if value is not None and not math.isfinite(value):
            return f"{name}={value} is not finite"
    if reading.power_output < 0.0:
        return f"power_output={reading.power_output} kW is negative"
    # Hydro has no upper power limit: its power is estimated from river discharge (live_source.py) and the real API values are
    # routinely far above the illustrative 400 kW rating (~49,500 kW on 2026-10-23), so any fixed bound would reject good data.
    if reading.type == "wind" and reading.power_output > MAX_POWER_RATED_FACTOR * rated_kw:
        return f"power_output={reading.power_output} kW outside [0, {MAX_POWER_RATED_FACTOR * rated_kw:.0f}]"
    if reading.wind_speed is not None and not 0.0 <= reading.wind_speed <= WIND_SPEED_LIMIT_MS:
        return f"wind_speed={reading.wind_speed} m/s outside [0, {WIND_SPEED_LIMIT_MS}]"
    return None


def validate_live(reading: NormalizedReading, rated_kw: float | None) -> NormalizedReading | None:
    """The reading to ingest (the original if valid, a copy carrying the last valid values if not), or None to drop it."""
    if reading.source_type != "live" or not rated_kw:
        return reading
    problem = _problem(reading, rated_kw)
    if problem is None:
        _last_valid[reading.node_id] = (reading.power_output, reading.wind_speed)
        return reading
    last = _last_valid.get(reading.node_id)
    if last is None:
        logger.warning("Invalid live reading for %s dropped (%s); no earlier valid value", reading.node_id, problem)
        return None
    logger.warning("Invalid live reading for %s (%s): replaced by last valid value %s", reading.node_id, problem, last)
    return reading.model_copy(update={"power_output": last[0], "wind_speed": last[1]})
