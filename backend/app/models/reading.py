from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class NormalizedReading(BaseModel):
    """The one schema every ingestion source (live API, SCADA replay) must
    conform to before it touches storage or the twin — see
    docs/architecture.md 'Normalized data schema'."""

    node_id: str
    source_type: Literal["live", "historical"]
    type: Literal["wind", "hydro"]
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
