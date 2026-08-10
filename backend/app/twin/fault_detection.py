"""Threshold/statistical fault detection for the historical SCADA replay
stream — see docs/architecture.md 'Fault detection (basic, for this
phase)'. Not the TA-GNN; that's Module 3. Live wind/hydro readings carry no
fault-relevant fields (no vibration/temperature sensors on those nodes in
this phase), so they always evaluate to "normal"."""

from collections import defaultdict, deque

from app.models.reading import NormalizedReading
from app.twin.graph import HealthStatus

# Rolling per-node temperature window used to compute a live baseline
# (mean + std) rather than one fixed global threshold, since normal
# operating temperature varies by turbine/season in the real dataset.
_ROLLING_WINDOW = 50
_temperature_history: dict[str, deque[float]] = defaultdict(lambda: deque(maxlen=_ROLLING_WINDOW))

WARNING_STD_MULTIPLIER = 3.0
FAULT_STD_MULTIPLIER = 5.0
MIN_SAMPLES_BEFORE_BASELINE = 10


def evaluate(reading: NormalizedReading) -> HealthStatus:
    if reading.source_type != "historical":
        return "normal"

    # Ground truth from the dataset's failure logbook always wins over the
    # statistical rule.
    if reading.fault_label:
        return "fault"

    if reading.temperature is None:
        return "normal"

    history = _temperature_history[reading.node_id]
    status: HealthStatus = "normal"

    if len(history) >= MIN_SAMPLES_BEFORE_BASELINE:
        mean = sum(history) / len(history)
        variance = sum((t - mean) ** 2 for t in history) / len(history)
        std = variance**0.5
        deviation = reading.temperature - mean
        if std > 0:
            if deviation >= FAULT_STD_MULTIPLIER * std:
                status = "fault_predicted"
            elif deviation >= WARNING_STD_MULTIPLIER * std:
                status = "warning"

    history.append(reading.temperature)
    return status
