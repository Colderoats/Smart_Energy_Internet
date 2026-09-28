"""Which Kelmarsh "Stop" events count as a genuine equipment fault.

Decision recorded with the user (Module 3, aiprogress.md open question 8):
planned / routine / external stops are NOT positives. They are also not
negatives — the turbine is stopped for a reason unrelated to equipment
health — so samples they touch are MASKED out of the loss and every metric
rather than labelled 0.

Basis: the status log's own "IEC category" column (real, operator-assigned),
refined by a short explicit message list. Nothing here is inferred by a
model. The full mapping is reproduced in aiprogress.md for review.
"""

from dataclasses import dataclass
from datetime import datetime

# IEC categories whose Stop events are candidate genuine faults.
_FAULT_IEC_CATEGORIES = {"forced outage"}

# Inside "Forced outage", these messages are human- or grid-initiated, not
# equipment failures (manual/remote stops, emergency-stop buttons pressed by
# a person, external stop command, grid-frequency trip, generic shutdown).
_NOT_FAULT_MESSAGES = {
    "manual stop - remote",
    "emergency stop base box",
    "emergency stop nacelle",
    "emergency stop top box",
    "externally stopped",
    "maximum grid frequency",
    "wec shut down",
}

# A handful of real component faults have a blank IEC category in the log.
_FAULT_MESSAGES_WITHOUT_IEC = {
    "anemometer defect",
    "rotor sensor b defective",
}


@dataclass(frozen=True)
class StopEvent:
    start: datetime
    end: datetime
    message: str
    iec_category: str
    is_fault: bool  # genuine equipment fault (positive class)


def is_genuine_fault(iec_category: str, message: str) -> bool:
    iec = iec_category.strip().lower()
    msg = message.strip().lower()
    if msg in _NOT_FAULT_MESSAGES:
        return False
    if iec in _FAULT_IEC_CATEGORIES:
        return True
    if not iec and msg in _FAULT_MESSAGES_WITHOUT_IEC:
        return True
    return False
