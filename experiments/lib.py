"""Shared helpers for the experiment runner: metrics.json writer, versions, aggregation.

Every run writes experiments/results/<run_id>/metrics.json:
  run_id, provenance ("simulated_testbed"), created_utc, versions, config (hash + settings), metrics: [ {id, target_id, name, value, mean, std, n, unit,
  formula, equation, conditions, topology, split, seeds, config_hash} ], plus any raw logs / curves written beside it.
Paper values are NEVER written here; comparison.py joins measured metrics to paper_targets.json by `target_id`.
"""
from __future__ import annotations

import hashlib
import json
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "experiments" / "results"
PROVENANCE = "simulated_testbed"


def versions() -> dict:
    v = {"python": sys.version.split()[0], "platform": platform.platform()}
    for m in ("numpy", "torch", "torch_geometric", "pandapower", "sklearn", "web3"):
        try:
            v[m] = __import__(m).__version__
        except Exception:
            pass
    return v


def chash(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()[:12]


def stat(vals) -> dict:
    a = np.asarray(vals, dtype=float)
    return dict(mean=float(a.mean()), std=float(a.std(ddof=0)) if len(a) > 1 else 0.0, n=int(len(a)), values=[float(x) for x in a])


def metric(name: str, value, *, target_id: str | None = None, vals=None, unit: str = "", formula: str = "", equation: str = "", conditions: str = "",
           topology: str | None = None, split: str = "", seeds=None, inputs: dict | None = None, note: str = "") -> dict:
    m = dict(name=name, target_id=target_id, value=None if value is None else float(value), unit=unit, formula=formula, equation=equation, conditions=conditions,
             topology=topology, split=split, seeds=seeds, inputs=inputs or {}, note=note)
    if vals is not None:
        s = stat(vals)
        m.update(mean=s["mean"], std=s["std"], n=s["n"], values=s["values"])
        if value is None:
            m["value"] = s["mean"]
    return m


def write_run(run_id: str, metrics: list[dict], config: dict, extra: dict | None = None, raw: dict | None = None) -> Path:
    out = RESULTS / run_id
    out.mkdir(parents=True, exist_ok=True)
    ch = chash(config)
    for m in metrics:
        m.setdefault("config_hash", ch)
    doc = dict(run_id=run_id, provenance=PROVENANCE, created_utc=datetime.now(timezone.utc).isoformat(timespec="seconds"), versions=versions(),
               config=config, config_hash=ch, metrics=metrics, **(extra or {}))
    (out / "metrics.json").write_text(json.dumps(doc, indent=1, default=float))
    for name, obj in (raw or {}).items():
        (out / f"{name}.json").write_text(json.dumps(obj, default=float))
    return out


def read_run(run_id: str) -> dict:
    return json.loads((RESULTS / run_id / "metrics.json").read_text())


def pct_reduction(base: float, new: float) -> float:
    return 100.0 * (base - new) / base if base else float("nan")
