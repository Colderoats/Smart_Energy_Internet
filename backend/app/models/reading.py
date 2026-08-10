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
