"""Client partitioning: one federated client per Kelmarsh turbine.

DATA PROVENANCE: the real Kelmarsh SCADA export (turbines 1-4, 2016-2018),
REPLAYED — not live, not simulated. A "client" here is a PARTITION of that
replay, not a physically separate site.

WHAT A CLIENT HOLDS
    Module 3's samples are whole 9-node graph snapshots in which each turbine
    also sees its neighbours' windows. A client cannot see its neighbours' raw
    data, so each client's local graph is the SAME twin topology with only its
    OWN turbine's dynamic features filled in; the other turbine slots are
    empty (all-zero, presence flag 0 — exactly the "missing" encoding Module 3's
    model already knows). Same model, same 46 node features, same labels,
    same fault taxonomy, same chronological split and normaliser as Module 3.

    client shard  = backend/ai/federated/artifacts/shards/client_<n>.npz
                    (that turbine's TRAIN and VALIDATION rows only; rows Module 3
                    masks as invalid — planned/external stops, missing readings —
                    are dropped). A client process opens only its own shard file.
    eval bundle   = artifacts/eval_data.npz  (pooled VALIDATION + TEST rows of all
                    turbines). Used ONLY by the offline evaluator (evaluate.py),
                    never by a client or the server during federated training.

The partitions are NOT rebalanced: per-turbine fault counts differ a lot
(non-IID, imbalanced) and that is kept on purpose.

RUN (needs the backend's `app` package -> use backend/venv, from backend/):
    venv\\Scripts\\python -m ai.federated.partition            # build shards + eval bundle + report
    venv\\Scripts\\python -m ai.federated.partition --report   # just print the saved report

Known limitation: the z-score normaliser is Module 3's (fit on the pooled
TRAIN split, 60 mean/std numbers). Those are aggregate statistics shared as
constants; a real deployment would compute them with a federated statistics
round.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

FED_DIR = Path(__file__).resolve().parent
ARTIFACT_DIR = FED_DIR / "artifacts"
SHARD_DIR = ARTIFACT_DIR / "shards"
EVAL_FILE = ARTIFACT_DIR / "eval_data.npz"
REPORT_FILE = ARTIFACT_DIR / "partition_report.json"
TURBINES = (1, 2, 3, 4)
PROVENANCE = (
    "Real Kelmarsh wind-farm SCADA (Zenodo 8252025, CC BY 4.0), turbines 1-4, 2016-2018, REPLAYED historical data - "
    "not live, not simulated. A federated client is a PARTITION of that replay, not a physically separate site."
)


@dataclass
class Shard:
    turbine: int
    node_id: str
    own_idx: int  # index of this turbine in ai.features.NODE_ORDER
    train_x: np.ndarray  # [n, 40] float32, normalised dynamic features of THIS turbine only
    train_y: np.ndarray  # [n] uint8
    val_x: np.ndarray
    val_y: np.ndarray
    static: np.ndarray  # [9, 6] node-type/size features (topology constants, not readings)
    edge_index: np.ndarray  # [2, E]
    meta: dict


def shard_path(turbine: int) -> Path:
    return SHARD_DIR / f"client_{turbine}.npz"


def load_shard(turbine: int) -> Shard:
    """The ONLY data a client process ever opens."""
    blob = np.load(shard_path(turbine), allow_pickle=False)
    meta = json.loads(str(blob["meta"]))
    assert meta["turbine"] == turbine
    return Shard(
        turbine=turbine,
        node_id=meta["node_id"],
        own_idx=meta["own_idx"],
        train_x=blob["train_x"],
        train_y=blob["train_y"],
        val_x=blob["val_x"],
        val_y=blob["val_y"],
        static=blob["static"],
        edge_index=blob["edge_index"],
        meta=meta,
    )


def _split_stats(arr, labels, idx, k: int) -> dict:
    from ai import dataset as D

    valid, y = labels.valid[idx, k], labels.y[idx, k]
    n_valid = int(valid.sum())
    n_pos = int(((y == 1) & valid).sum())
    lo, hi = idx[0] * D.STEP_S, (idx[-1] + 1) * D.STEP_S
    events = [e for e in arr.events if e["node"] == k and e["is_fault"] and lo <= e["start_s"] < hi]
    starts = np.unique(labels.event_start_s[idx, k][(y == 1) & valid])
    return {
        "valid_samples": n_valid,
        "positives": n_pos,
        "positive_rate": n_pos / max(n_valid, 1),
        "genuine_fault_events": len(events),
        "events_with_valid_positive_sample": int(len(starts)),
    }


def build_all() -> dict:
    """Builds every client shard, the offline evaluation bundle and the report.
    Imports the backend's `app` package (via ai.dataset) — run with backend/venv."""
    from ai import dataset as D
    from ai import features as F

    arr = D.build_arrays()
    labels = D.make_labels(arr)
    splits = D.make_splits(arr)
    leak = D.check_no_leakage(arr, labels, splits)
    balance = D.class_balance(arr, labels, splits)
    norm = D.fit_normalizer(arr, labels, splits)
    static, edge_index = F.default_topology()

    SHARD_DIR.mkdir(parents=True, exist_ok=True)
    dyn = {name: norm.apply(arr.raw_win[getattr(splits, name)].astype(np.float64)) for name in ("train", "val", "test")}

    report: dict = {"provenance": PROVENANCE, "no_leakage_checks": leak, "clients": {}}
    for k, turbine in enumerate(TURBINES):
        arrays = {}
        for name in ("train", "val"):
            idx = getattr(splits, name)
            rows = labels.valid[idx, k]
            arrays[f"{name}_x"] = dyn[name][rows, k].astype(np.float32)
            arrays[f"{name}_y"] = labels.y[idx, k][rows].astype(np.uint8)
        stats = {name: _split_stats(arr, labels, getattr(splits, name), k) for name in ("train", "val", "test")}
        meta = {
            "turbine": turbine,
            "node_id": D.NODE_IDS[k],
            "own_idx": F.SCORED_IDX[k],
            "provenance": PROVENANCE,
            "stats": stats,
        }
        np.savez_compressed(shard_path(turbine), static=static, edge_index=edge_index, meta=json.dumps(meta), **arrays)
        report["clients"][str(turbine)] = {"node_id": D.NODE_IDS[k], "own_idx": F.SCORED_IDX[k], **stats}

    payload = {"static": static, "edge_index": edge_index, "meta": json.dumps({"normalizer": norm.to_dict(), "class_balance": balance, "provenance": PROVENANCE})}
    for name in ("val", "test"):
        payload[f"{name}_idx"] = getattr(splits, name)
        payload[f"{name}_dyn"] = dyn[name].astype(np.float32)  # [n, 4, 40]
    payload.update(
        label_y=labels.y, label_valid=labels.valid, label_lead_s=labels.lead_s, label_event_start_s=labels.event_start_s
    )
    np.savez_compressed(EVAL_FILE, **payload)
    report["pooled_class_balance"] = balance
    REPORT_FILE.write_text(json.dumps(report, indent=2))
    return report


def print_report(report: dict | None = None) -> None:
    report = report or json.loads(REPORT_FILE.read_text())
    print("Client partitions (one client per turbine; REPLAYED Kelmarsh SCADA; a client is a partition, not a separate site)")
    for split, note in (("train", ""), ("val", " (client-local validation; drives adaptive weights)"), ("test", " (HELD OUT - never on a client; offline evaluator only)")):
        print(f"\n  {split}{note}")
        print(f"    {'client':8}{'valid':>9}{'positives':>11}{'pos rate':>10}{'fault events':>14}{'events w/ valid pos':>21}")
        for t, c in report["clients"].items():
            s = c[split]
            print(f"    T{t:<7}{s['valid_samples']:>9}{s['positives']:>11}{100 * s['positive_rate']:>9.3f}%{s['genuine_fault_events']:>14}{s['events_with_valid_positive_sample']:>21}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", action="store_true", help="print the saved partition report only")
    args = ap.parse_args()
    print_report() if args.report else print_report(build_all())
