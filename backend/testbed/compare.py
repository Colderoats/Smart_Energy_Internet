"""Join measured testbed metrics to the paper targets (read-only; used by experiments/compare_all.py and the /testbed API).

A paper value is only ever displayed next to a measured value as "Paper target"; it is never fed back into any simulator or trainer.
Rounding: the measured value is rounded to the number of decimals the paper uses for that target. Default tolerance: +-5 % relative
(+-0.05 absolute when the paper value is 0). Structural counts (Table III, dataset sizes) must match exactly.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TARGETS = ROOT / "experiments" / "paper_targets.json"
RESULTS = ROOT / "experiments" / "results"
TOL_REL = 0.05
EXACT_UNITS = {"count"}


def load_targets() -> dict[str, dict]:
    return {t["id"]: t for t in json.loads(TARGETS.read_text())}


def decimals(v) -> int:
    """Decimals the paper uses: integers -> 0, floats -> digits after the point as written in paper_targets.json."""
    if isinstance(v, int):
        return 0
    s = repr(float(v))
    return len(s.split(".")[1]) if "." in s and "e" not in s else 0


def compare_one(m: dict, t: dict | None) -> dict:
    out = dict(measured=m.get("value"), paper=None, abs_diff=None, rel_diff=None, within=None, tolerance=TOL_REL, status="no paper target")
    if t is None or t.get("value") is None or m.get("value") is None:
        return out
    paper = float(t["value"])
    d = decimals(t["value"])
    meas = round(float(m["value"]), d)
    out.update(paper=paper, measured_rounded=meas, abs_diff=meas - paper, rel_diff=(meas - paper) / paper if paper else None)
    if t.get("unit") in EXACT_UNITS and t.get("conditions", "").startswith(("topology", "4 types", "24 h")):
        ok = meas == paper
        out["tolerance"] = 0.0
    elif t.get("id", "").endswith("auc_std_upper_bound"):
        ok = meas <= paper
    else:
        ok = abs(meas - paper) <= (TOL_REL * abs(paper) if paper else 0.05)
    out["within"] = bool(ok)
    out["status"] = "within tolerance" if ok else "outside tolerance"
    return out


def build_comparison() -> dict:
    targets = load_targets()
    rows = []
    for run_dir in sorted(RESULTS.iterdir()):
        f = run_dir / "metrics.json"
        if not f.exists():
            continue
        doc = json.loads(f.read_text())
        for i, m in enumerate(doc["metrics"]):
            tid = m.get("target_id")
            t = targets.get(tid) if tid else None
            c = compare_one(m, t)
            rows.append(dict(run_id=doc["run_id"], index=i, target_id=tid, paper_name=t["paper"] if t else None, table=t["table_or_figure"] if t else None, name=m["name"],
                             topology=m.get("topology"), unit=m.get("unit", ""), std=m.get("std"), n=m.get("n"), config_hash=m.get("config_hash"), **c))
    return dict(rows=rows, targets=len(targets))
