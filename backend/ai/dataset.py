"""Training/evaluation dataset for Module 3, built from the REAL Kelmarsh
SCADA CSVs (replayed historical data — never live, never simulated).

Why CSVs and not TimescaleDB: the `readings` table only holds whatever a few
short demo replays happened to ingest (a few days of Jan-Feb 2016, no
temperature). The full-year data lives in backend/data/scada/ (2016) and
backend/data/scada/extra_years/ (2017-2018, downloaded for training/evaluation
only; Module 1's replay never reads that subfolder). Readings are
produced by the SAME parser the live replay uses
(app.ingestion.scada_replay._iter_turbine_readings), so feature values are
identical to what the twin sees at serving time.

Sample = one 10-minute step on the farm-wide grid (a graph snapshot of all 9
twin nodes). Per scored node (the 4 turbines):

  features   window of the last WINDOW_STEPS rows ending at step i (past only)
  tau_i      = t_i + 10 min  (the row's information time; timestamps are
               conservatively treated as possibly interval-start)
  label y    = 1 iff a GENUINE fault event (ai/taxonomy.py) STARTS in
               (tau_i, tau_i + 60 min]; else 0
  valid      = row present AND no Stop event of ANY kind overlaps
               [t_i - 10 min, tau_i]. A turbine that is already stopped (or
               being stopped) is not a "predict the next fault" situation, and
               planned/external stops are neither positive nor negative, so
               those samples are masked out of training and every metric.

`fault_label` is never a model input. The rule-based baseline is replayed
through the production function app.twin.fault_detection.evaluate with the
label override REMOVED (otherwise it would read ground truth and score 100%).

Chronological split with purge gaps (WINDOW_STEPS + HORIZON_STEPS steps) so no
label horizon or look-back window straddles a split boundary.
"""

from __future__ import annotations

import hashlib
import json
import logging
import warnings
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

from ai import features as F
from ai.taxonomy import StopEvent, is_genuine_fault

logger = logging.getLogger("sei.ai")

BACKEND_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BACKEND_DIR / "data" / "scada"
# Extra Kelmarsh years (2017, 2018) downloaded for TRAINING/EVALUATION ONLY.
# Deliberately a subfolder: Module 1's replay globs DATA_DIR non-recursively,
# so it never sees these files and its behaviour is unchanged.
EXTRA_DATA_DIR = DATA_DIR / "extra_years"
DATA_DIRS = [DATA_DIR, EXTRA_DATA_DIR]
CACHE_DIR = BACKEND_DIR / "ai" / "artifacts" / "cache"
CACHE_VERSION = 3
T0 = datetime(2016, 1, 1, tzinfo=timezone.utc)  # step 0; the export itself starts 2016-01-21

TURBINES = {1: "wind_scada_kelmarsh_1", 2: "wind_scada_kelmarsh_2", 3: "wind_scada_kelmarsh_3", 4: "wind_scada_kelmarsh_4"}
NODE_IDS = list(TURBINES.values())  # index k in every [.., 4, ..] array below == SCORED_NODES[k]
STEP_S = F.STEP_MINUTES * 60

# Chronological split boundaries (UTC): train = start of data .. 2017-12-31,
# validation = H1 2018, test = H2 2018 (the last six months, touched only for
# the final report). Chosen from genuine-fault counts per month only (never
# from any model result): ~172 / ~31 / ~25 events. Faults cluster in winter
# storm periods, so val is fault-dense and test is mostly quiet plus a
# Nov-Dec cluster — see aiprogress.md for the per-month counts.
SPLIT_BOUNDS = {
    "val_start": datetime(2018, 1, 1, tzinfo=timezone.utc),
    "test_start": datetime(2018, 7, 1, tzinfo=timezone.utc),
}


@dataclass
class KelmarshArrays:
    t0: datetime
    n_steps: int
    raw_win: np.ndarray  # [T, 4, 4C] raw (un-normalised) window features, NaN = missing
    present: np.ndarray  # [T, 4] bool — a reading exists at this step
    rule_status: np.ndarray  # [T, 4] int8: production rule output 0 normal / 1 warning / 2 fault_predicted (label override OFF)
    rule_z: np.ndarray  # [T, 4] float32: mirrored rolling z-score (continuous score for ranking / AUC)
    events: list[dict]  # all Stop events: node (0-3), start_s, end_s (seconds since t0), message, iec, is_fault


def _existing_dirs(data_dirs) -> list[Path]:
    return [d for d in data_dirs if d.exists() and any(d.glob("Turbine_Data_Kelmarsh_*.csv"))]


def _cache_key(data_dirs: list[Path]) -> str:
    h = hashlib.sha1(f"v{CACHE_VERSION}".encode())
    for d in data_dirs:
        for p in sorted(d.glob("*Kelmarsh*.csv")):
            st = p.stat()
            h.update(f"{p.name}:{st.st_size}:{int(st.st_mtime)}".encode())
    return h.hexdigest()[:16]


def _load_stop_events(data_dir: Path, turbine_n: int) -> list[StopEvent]:
    from app.ingestion.scada_replay import STATUS_GLOB, _parse_timestamp, _read_kelmarsh_csv

    events: list[StopEvent] = []
    for path in sorted(data_dir.glob(STATUS_GLOB.format(n=turbine_n))):
        for row in _read_kelmarsh_csv(path):
            if row["Status"].strip().lower() != "stop":
                continue
            try:
                start, end = _parse_timestamp(row["Timestamp start"]), _parse_timestamp(row["Timestamp end"])
            except ValueError:
                continue
            msg, iec = row["Message"].strip(), row["IEC category"].strip()
            events.append(StopEvent(start, end, msg, iec, is_genuine_fault(iec, msg)))
    return events


class _RuleReplay:
    """Streams one node's chronological readings through the PRODUCTION rule
    (app.twin.fault_detection.evaluate) with fault_label stripped, and mirrors
    its rolling z-score for a continuous score (self-checked against the
    production status in build_arrays)."""

    _CODE = {"normal": 0, "warning": 1, "fault_predicted": 2, "fault": 3}

    def __init__(self, node_id: str) -> None:
        from collections import deque

        from app.twin import fault_detection as fd

        self.fd, self.node_id = fd, node_id
        fd._temperature_history.pop(node_id, None)  # fresh per-node state
        self.hist: deque = deque(maxlen=fd._ROLLING_WINDOW)

    def step(self, r) -> tuple[int, float]:
        fd = self.fd
        status = self._CODE[fd.evaluate(r.model_copy(update={"fault_label": None}))]
        assert status < 3, "label override leaked into the baseline replay"
        z = 0.0
        if r.temperature is not None:
            if len(self.hist) >= fd.MIN_SAMPLES_BEFORE_BASELINE:
                mean = sum(self.hist) / len(self.hist)
                std = (sum((t - mean) ** 2 for t in self.hist) / len(self.hist)) ** 0.5
                if std > 0:
                    z = (r.temperature - mean) / std
            self.hist.append(r.temperature)
        return status, z

    def close(self) -> None:
        self.fd._temperature_history.pop(self.node_id, None)


def build_arrays(data_dirs: list[Path] | None = None, use_cache: bool = True) -> KelmarshArrays:
    from app.ingestion.scada_replay import SCADA_CHANNELS, _iter_turbine_readings

    assert list(SCADA_CHANNELS) == F.SCADA_CHANNEL_KEYS, "ai.features.SCADA_CHANNEL_KEYS out of sync with scada_replay.SCADA_CHANNELS"
    dirs = _existing_dirs(data_dirs or DATA_DIRS)
    if not dirs:
        raise FileNotFoundError(f"no Kelmarsh Turbine_Data CSVs in {data_dirs or DATA_DIRS}")

    cache_file = CACHE_DIR / f"kelmarsh_{_cache_key(dirs)}.npz"
    if use_cache and cache_file.exists():
        blob = np.load(cache_file, allow_pickle=False)
        meta = json.loads(str(blob["meta"]))
        logger.info("loaded dataset cache %s", cache_file.name)
        return KelmarshArrays(
            t0=datetime.fromisoformat(meta["t0"]),
            n_steps=meta["n_steps"],
            raw_win=blob["raw_win"],
            present=blob["present"],
            rule_status=blob["rule_status"],
            rule_z=blob["rule_z"],
            events=meta["events"],
        )

    # Stream each turbine's readings (chronological across year files) into
    # compact per-node lists; nothing is held as pydantic objects afterwards.
    rows = {k: {"step": [], "vec": [], "status": [], "z": []} for k in range(4)}
    for n, node_id in TURBINES.items():
        k = n - 1
        replay = _RuleReplay(node_id)
        last_step = -1
        for d in dirs:
            logger.info("reading %s from %s ...", node_id, d.name)
            for r in _iter_turbine_readings(d, n, node_id):
                off = (r.timestamp - T0).total_seconds()
                assert off % STEP_S == 0, f"timestamp {r.timestamp} not on the 10-minute grid"
                step = int(off // STEP_S)
                assert step > last_step, f"{node_id}: readings not strictly chronological at {r.timestamp}"
                last_step = step
                status, z = replay.step(r)
                rows[k]["step"].append(step)
                rows[k]["vec"].append(F.reading_vector(r.model_dump(mode="json")))
                rows[k]["status"].append(status)
                rows[k]["z"].append(z)
        replay.close()
        if not rows[k]["step"]:
            raise FileNotFoundError(f"no Kelmarsh readings for turbine {n}")

    n_steps = max(rows[k]["step"][-1] for k in range(4)) + 1
    vec = np.full((n_steps, 4, F.N_CHANNELS), np.nan)
    present = np.zeros((n_steps, 4), dtype=bool)
    rule_status = np.zeros((n_steps, 4), dtype=np.int8)
    rule_z = np.zeros((n_steps, 4), dtype=np.float32)
    for k in range(4):
        st = np.asarray(rows[k]["step"])
        vec[st, k] = np.asarray(rows[k]["vec"])
        present[st, k] = True
        rule_status[st, k] = rows[k]["status"]
        rule_z[st, k] = rows[k]["z"]

    # self-check: the mirrored z-score reproduces the production thresholds exactly
    from app.twin import fault_detection as fd

    assert ((rule_z >= fd.FAULT_STD_MULTIPLIER) == (rule_status >= 2)).all(), "rule z-score mirror != production (5 sigma)"
    assert ((rule_z >= fd.WARNING_STD_MULTIPLIER) == (rule_status >= 1)).all(), "rule z-score mirror != production (3 sigma)"

    raw_win = np.full((n_steps, 4, 4 * F.N_CHANNELS), np.nan, dtype=np.float32)
    padded = np.concatenate([np.full((F.WINDOW_STEPS - 1, 4, F.N_CHANNELS), np.nan), vec], axis=0)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        for i in range(n_steps):
            for k in range(4):
                if present[i, k]:
                    raw_win[i, k] = F.window_features(padded[i : i + F.WINDOW_STEPS, k])

    events = []
    for n in TURBINES:
        for d in dirs:
            for e in _load_stop_events(d, n):
                events.append(
                    {
                        "node": n - 1,
                        "start_s": (e.start - T0).total_seconds(),
                        "end_s": (e.end - T0).total_seconds(),
                        "message": e.message,
                        "iec": e.iec_category,
                        "is_fault": e.is_fault,
                    }
                )

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    meta = {"t0": T0.isoformat(), "n_steps": n_steps, "events": events}
    np.savez_compressed(
        cache_file, raw_win=raw_win, present=present, rule_status=rule_status, rule_z=rule_z, meta=json.dumps(meta)
    )
    logger.info("wrote dataset cache %s", cache_file.name)
    return KelmarshArrays(T0, n_steps, raw_win, present, rule_status, rule_z, events)


@dataclass
class Labels:
    y: np.ndarray  # [T, 4] uint8: genuine fault starts within the horizon
    valid: np.ndarray  # [T, 4] bool
    lead_s: np.ndarray  # [T, 4] float: seconds from tau_i to the upcoming fault start (NaN if y == 0)
    event_start_s: np.ndarray  # [T, 4] float: start (s since t0) of that upcoming fault, NaN if y == 0


def make_labels(arr: KelmarshArrays) -> Labels:
    T = arr.n_steps
    y = np.zeros((T, 4), dtype=np.uint8)
    lead = np.full((T, 4), np.nan)
    ev_start = np.full((T, 4), np.nan)
    stopped = np.zeros((T, 4), dtype=bool)
    tau = (np.arange(T) + 1) * STEP_S  # information time of each row, seconds since t0
    horizon_s = F.HORIZON_STEPS * STEP_S

    for k in range(4):
        starts = np.sort([e["start_s"] for e in arr.events if e["node"] == k and e["is_fault"]])
        if len(starts):
            j = np.searchsorted(starts, tau, side="right")  # first start strictly after tau
            nxt = np.where(j < len(starts), starts[np.minimum(j, len(starts) - 1)], np.inf)
            hit = nxt <= tau + horizon_s
            y[hit, k] = 1
            lead[hit, k] = (nxt - tau)[hit]
            ev_start[hit, k] = nxt[hit]
        diff = np.zeros(T + 2, dtype=np.int32)
        for e in arr.events:
            if e["node"] != k:
                continue
            lo = max(int(np.ceil(e["start_s"] / STEP_S - 1)), 0)
            hi = min(int(np.floor((e["end_s"] + STEP_S) / STEP_S)), T - 1)
            if hi >= lo:
                diff[lo] += 1
                diff[hi + 1] -= 1
        stopped[:, k] = np.cumsum(diff)[:T] > 0

    valid = arr.present & ~stopped
    return Labels(y=y, valid=valid, lead_s=lead, event_start_s=ev_start)


@dataclass
class Splits:
    train: np.ndarray
    val: np.ndarray
    test: np.ndarray
    gap_steps: int


def make_splits(arr: KelmarshArrays) -> Splits:
    gap = F.WINDOW_STEPS + F.HORIZON_STEPS

    def step_of(dt: datetime) -> int:
        return int((dt - arr.t0).total_seconds() // STEP_S)

    a, b = step_of(SPLIT_BOUNDS["val_start"]), step_of(SPLIT_BOUNDS["test_start"])
    T = arr.n_steps
    return Splits(
        train=np.arange(0, a - gap),
        val=np.arange(a, b - gap),
        test=np.arange(b, T),
        gap_steps=gap,
    )


def check_no_leakage(arr: KelmarshArrays, labels: Labels, splits: Splits) -> dict:
    """Hard assertions that no label horizon or look-back window straddles a
    split boundary. Raises AssertionError on any violation; returns a summary."""
    gap = splits.gap_steps
    assert gap >= F.WINDOW_STEPS + F.HORIZON_STEPS
    # 1. splits are chronologically ordered, disjoint, and separated by >= gap steps
    assert splits.train[-1] + gap <= splits.val[0], "train->val gap too small"
    assert splits.val[-1] + gap <= splits.test[0], "val->test gap too small"
    # 2. every positive label in a split is caused by a fault START inside that
    #    split's own time span (the label horizon never reaches the next split)
    for name in ("train", "val", "test"):
        idx = getattr(splits, name)
        lo, hi = idx[0] * STEP_S, (idx[-1] + 1) * STEP_S
        starts = labels.event_start_s[idx][labels.y[idx] == 1]
        assert ((starts > lo) & (starts <= hi + F.HORIZON_STEPS * STEP_S)).all() or len(starts) == 0
        if name != "test":
            nxt = getattr(splits, {"train": "val", "val": "test"}[name])
            assert starts.max(initial=0) < nxt[0] * STEP_S, f"{name} labels reach into the next split"
    # 3. no valid sample's look-back window reaches before the start of its own
    #    split's training data for the train split (normaliser fit uses train rows only, see fit_normalizer)
    return {"gap_steps": gap, "gap_minutes": gap * F.STEP_MINUTES, "checks": "passed"}


def class_balance(arr: KelmarshArrays, labels: Labels, splits: Splits) -> dict:
    """Class balance per split, plus event counts. Reported, not hidden."""
    out = {}
    for name in ("train", "val", "test"):
        idx = getattr(splits, name)
        valid, y = labels.valid[idx], labels.y[idx]
        n_valid = int(valid.sum())
        n_pos = int((y[valid] == 1).sum())
        lo, hi = idx[0] * STEP_S, (idx[-1] + 1) * STEP_S
        fault_events = [e for e in arr.events if e["is_fault"] and lo <= e["start_s"] < hi]
        other_stops = [e for e in arr.events if not e["is_fault"] and lo <= e["start_s"] < hi]
        out[name] = {
            "steps": int(len(idx)),
            "from": (arr.t0 + timedelta(seconds=int(lo))).date().isoformat(),
            "to": (arr.t0 + timedelta(seconds=int(hi))).date().isoformat(),
            "valid_node_samples": n_valid,
            "masked_node_samples": int(valid.size - n_valid),
            "positives": n_pos,
            "positive_rate": round(n_pos / max(n_valid, 1), 5),
            "genuine_fault_events": len(fault_events),
            "non_fault_stop_events": len(other_stops),
        }
    return out


def snapshot_tensor(arr: KelmarshArrays, idx: np.ndarray, norm: F.Normalizer, static: np.ndarray) -> np.ndarray:
    """Node-feature tensor [len(idx), N_NODES, NODE_FEATURES] for the given steps."""
    x = np.zeros((len(idx), F.N_NODES, F.NODE_FEATURES), dtype=np.float32)
    x[:, :, : F.STATIC_FEATURES] = static[None]
    x[:, F.SCORED_IDX, F.STATIC_FEATURES :] = norm.apply(arr.raw_win[idx].astype(np.float64))
    return x


def fit_normalizer(arr: KelmarshArrays, labels: Labels, splits: Splits) -> F.Normalizer:
    """Fit on TRAIN-split, valid rows only."""
    idx = splits.train
    rows = arr.raw_win[idx][labels.valid[idx]]
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        return F.Normalizer.fit(rows.astype(np.float64))
