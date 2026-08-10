"""Replays a real public SCADA dataset row by row at a fixed interval,
simulating a live feed for demo purposes — see docs/architecture.md
'Ingestion: Historical'. Every reading this produces has
source_type="historical" and is never presented as physically sensed.

Dataset: Kelmarsh wind farm (Northamptonshire, UK), 6x Senvion MM92
turbines, released by Cubico Sustainable Investments under CC BY 4.0 —
https://zenodo.org/records/8252025. Files are 10-minute SCADA exports (one
CSV per turbine per year, "Turbine_Data_Kelmarsh_<n>_...csv") plus a real
event/fault log per turbine ("Status_Kelmarsh_<n>_...csv") with actual
start/end timestamps, a severity ("Stop"/"Warning"/"Informational"), and a
human-readable message — this is genuine plant telemetry and genuine
logged faults, not a synthetic or anonymized dataset.

Both file types share an unusual export format: several "#"-prefixed
metadata comment lines, then a header row (also "#"-prefixed for the
Turbine_Data files, not for the Status files), then plain CSV data rows.
_read_kelmarsh_csv() below handles that. Missing/erroneous values are
marked "NaN" in the source; those are treated as missing (None), not
coerced into a number.

Only "Stop" status events are treated as fault_label ground truth (skips
"Warning"/"Informational", which fire constantly during normal operation
and would otherwise mark almost the entire dataset as "fault") — see
docs/progress.md for why. The rolling-baseline statistical rule in
app/twin/fault_detection.py is what's meant to catch the lead-up.
"""

import asyncio
import csv
import io
import logging
import math
import re
from datetime import datetime, timezone
from pathlib import Path

from app.config import settings
from app.ingestion.pipeline import ingest_reading
from app.models.reading import NormalizedReading

logger = logging.getLogger("sei")

# Kelmarsh turbine number -> our twin node id (see app/twin/graph.py NODES).
# Only using turbines 1-4 of the farm's 6 to keep the twin's node count
# manageable; not a data-quality choice.
KNOWN_TURBINES = {1: "wind_scada_kelmarsh_1", 2: "wind_scada_kelmarsh_2", 3: "wind_scada_kelmarsh_3", 4: "wind_scada_kelmarsh_4"}

TURBINE_DATA_GLOB = "Turbine_Data_Kelmarsh_{n}_*.csv"
STATUS_GLOB = "Status_Kelmarsh_{n}_*.csv"

TEMPERATURE_PRIORITY = [
    "generator bearing rear temperature",
    "generator bearing front temperature",
    "gear oil temperature",
    "front bearing temperature",
    "rear bearing temperature",
    "stator temperature",
]
POWER_PRIORITY = ["power (kw)"]

FAULT_STATUS_LEVELS = {"stop"}  # skip "warning"/"informational" — see module docstring


def _find_column(headers: list[str], priority_substrings: list[str]) -> str | None:
    lower = {h: h.lower() for h in headers}
    for substr in priority_substrings:
        for h, hl in lower.items():
            if substr in hl:
                return h
    return None


def _find_column_fuzzy(headers: list[str], must_contain: str, exclude: list[str] | None = None) -> str | None:
    exclude = exclude or []
    for h in headers:
        hl = h.lower()
        if must_contain in hl and not any(ex in hl for ex in exclude):
            return h
    return None


def _read_kelmarsh_csv(path: Path) -> csv.DictReader:
    """Skips the '#'-prefixed metadata block and returns a DictReader
    positioned at the real header — see module docstring for why this is
    needed instead of plain csv.DictReader(f)."""
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    header_idx = None
    for i, line in enumerate(lines):
        stripped = line.lstrip("#").strip()
        if stripped.startswith("Date and time") or stripped.startswith("Timestamp start"):
            header_idx = i
            break
    if header_idx is None:
        raise ValueError(f"could not find header row in {path}")
    header_line = lines[header_idx].lstrip("#").lstrip()
    csv_text = header_line + "".join(lines[header_idx + 1 :])
    return csv.DictReader(io.StringIO(csv_text))


def _parse_timestamp(raw: str) -> datetime:
    dt = datetime.fromisoformat(raw.strip())
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _parse_float(raw: str | None) -> float | None:
    if raw is None or raw.strip() in ("", "NaN"):
        return None
    try:
        value = float(raw)
    except ValueError:
        return None
    return None if math.isnan(value) else value


def _load_fault_windows(path: Path) -> list[tuple[datetime, datetime, str]]:
    if not path.exists():
        return []
    reader = _read_kelmarsh_csv(path)
    headers = reader.fieldnames or []
    start_col = _find_column_fuzzy(headers, "timestamp start")
    end_col = _find_column_fuzzy(headers, "timestamp end")
    status_col = _find_column_fuzzy(headers, "status")
    message_col = _find_column_fuzzy(headers, "message")
    if not start_col or not end_col or not status_col:
        logger.warning("Could not resolve columns in status log %s, skipping fault labels", path)
        return []

    windows = []
    for row in reader:
        if row.get(status_col, "").strip().lower() not in FAULT_STATUS_LEVELS:
            continue
        try:
            start = _parse_timestamp(row[start_col])
            end = _parse_timestamp(row[end_col])
        except ValueError:
            continue
        message = row.get(message_col, "fault") if message_col else "fault"
        windows.append((start, end, message))
    return windows


def _fault_label_for(ts: datetime, windows: list[tuple[datetime, datetime, str]]) -> str | None:
    for start, end, message in windows:
        if start <= ts <= end:
            return message
    return None


def _iter_turbine_readings(data_dir: Path, turbine_n: int, node_id: str):
    data_files = sorted(data_dir.glob(TURBINE_DATA_GLOB.format(n=turbine_n)))
    if not data_files:
        return

    status_files = sorted(data_dir.glob(STATUS_GLOB.format(n=turbine_n)))
    fault_windows: list[tuple[datetime, datetime, str]] = []
    for status_file in status_files:
        fault_windows.extend(_load_fault_windows(status_file))

    for data_file in data_files:
        reader = _read_kelmarsh_csv(data_file)
        headers = reader.fieldnames or []
        timestamp_col = _find_column_fuzzy(headers, "date and time")
        power_col = _find_column(headers, POWER_PRIORITY)
        temperature_col = _find_column(headers, TEMPERATURE_PRIORITY) or _find_column_fuzzy(
            headers, "temperature", exclude=["ambient", "cpu"]
        )
        if not timestamp_col or not power_col:
            logger.warning("Could not resolve timestamp/power columns in %s, skipping", data_file)
            continue
        logger.info(
            "SCADA replay resolved columns for %s — timestamp=%s power=%s temperature=%s",
            data_file.name,
            timestamp_col,
            power_col,
            temperature_col,
        )

        for row in reader:
            try:
                ts = _parse_timestamp(row[timestamp_col])
            except ValueError:
                continue

            power = _parse_float(row.get(power_col))
            if power is None:
                continue  # can't fabricate a missing power_output value

            temperature = _parse_float(row.get(temperature_col)) if temperature_col else None

            yield NormalizedReading(
                node_id=node_id,
                source_type="historical",
                type="wind",
                timestamp=ts,
                power_output=power,
                temperature=temperature,
                vibration=None,  # this dataset has no true accelerometer channel — see progress.md
                fault_label=_fault_label_for(ts, fault_windows),
            )


def _iter_readings(data_dir: Path):
    """Round-robins across all turbines' generators (one row from each in
    turn) rather than exhausting one turbine before starting the next —
    each turbine has ~52k rows, which at a 2s replay interval would take
    ~29 hours before the next turbine's node showed any activity at all.
    Interleaving keeps every twin node visibly live within the same short
    window."""
    generators = [
        _iter_turbine_readings(data_dir, turbine_n, node_id) for turbine_n, node_id in KNOWN_TURBINES.items()
    ]
    active = list(generators)
    while active:
        for gen in list(active):
            try:
                yield next(gen)
            except StopIteration:
                active.remove(gen)


async def run_scada_replay() -> None:
    data_dir = settings.scada_data_dir
    if not data_dir.exists() or not any(data_dir.glob("Turbine_Data_Kelmarsh_*.csv")):
        logger.warning(
            "SCADA replay: no Kelmarsh Turbine_Data CSVs found in %s — Stage 3 dataset not in place yet, skipping replay task",
            data_dir,
        )
        return

    while True:
        count = 0
        for reading in _iter_readings(data_dir):
            await ingest_reading(reading)
            count += 1
            await asyncio.sleep(settings.scada_replay_interval_seconds)
        if count == 0:
            logger.warning("SCADA replay: no usable rows found in %s, stopping replay task", data_dir)
            return
        logger.info("SCADA replay: reached end of dataset (%d rows), looping back to start", count)
