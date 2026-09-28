"""Exports a federated global model in EXACTLY Module 3's artifact format so the
backend can load it with plain torch (no Flower needed there):

    backend/ai/federated/artifacts/model_federated/{model.pt, weights.npz, meta.json}

meta.json carries `model_source: "federated"` plus the federation config, so
every prediction can state which model produced it (see app/ai_service).

    ai\\federated\\venv\\Scripts\\python -m ai.federated.export --auto          # best-on-validation seed of FedProx+adaptive (mu*), clean
    ai\\federated\\venv\\Scripts\\python -m ai.federated.export --run ai\\federated\\artifacts\\runs\\<run_dir>

Operating point and probability calibration are fitted on the pooled
VALIDATION split in the FULL view (the view the backend serves), the same way
Module 3 did (max-F1 threshold + Platt scaling). The test split is never used.
The exported model was trained on real Kelmarsh SCADA, REPLAYED; it is a
forecaster on replayed data, not a physical sensor.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import torch

from ai import features as F
from ai import metrics as M
from ai import training as T
from ai.federated import evaluate, partition, run_experiment as R
from ai.federated.strategies import load_weights
from ai.models import NodeClassifier, get_weights, set_weights

OUT_DIR = partition.ARTIFACT_DIR / "model_federated"
DISPLAY = {"fedavg": "TA-GNN (federated: FedAvg)", "fedprox": "TA-GNN (federated: FedProx)", "fedprox_adaptive": "TA-GNN (federated: FedProx + adaptive weighting)"}


def pick_auto_run() -> Path:
    mu_star = json.loads((partition.ARTIFACT_DIR / "mu_selection.json").read_text())["mu_star"]
    best, best_v = None, -1.0
    for s in range(5):
        d = R.RUNS_DIR / R.run_name("fedprox_adaptive", mu_star, "clean", s)
        res = json.loads((d / "result.json").read_text())
        v = res["selected"]["full_view"]["val_pr_auc"]  # validation only; never the test metrics
        if v > best_v:
            best, best_v = d, v
    return best


def export_run(run_dir: Path) -> Path:
    meta_run = json.loads((run_dir / "run_meta.json").read_text())
    if meta_run["scenario"]["scenario"] != "clean":
        raise SystemExit("refusing to export a model trained under a SIMULATED degradation scenario")
    weights = load_weights(run_dir / "weights_best.npz")
    model = NodeClassifier("tag")
    set_weights(model, weights)
    model.eval()
    bundle = evaluate.load_bundle()
    val_logits = evaluate.full_view_logits(model, bundle, bundle.val_dyn)
    lab = bundle.labels
    vy, vvalid = lab.y[bundle.val_idx], lab.valid[bundle.val_idx]
    thr = M.best_f1_threshold(vy[vvalid], val_logits[vvalid])
    a, b = T.fit_platt(val_logits[vvalid], vy[vvalid])

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    torch.save({k: v.clone() for k, v in model.state_dict().items()}, OUT_DIR / "model.pt")
    np.savez(OUT_DIR / "weights.npz", *get_weights(model))
    balance = bundle.meta["class_balance"]
    meta = {
        "kind": "tag",
        "display_name": DISPLAY[meta_run["mode"]],
        "model_source": "federated",
        "model_config": model.config,
        "seed": meta_run["seed"],
        "threshold_logit": float(thr),
        "platt": {"a": float(a), "b": float(b)},
        "normalizer": bundle.normalizer,
        "features": {"channels": F.CHANNELS, "window_steps": F.WINDOW_STEPS, "step_minutes": F.STEP_MINUTES,
                     "horizon_steps": F.HORIZON_STEPS, "node_order": F.NODE_ORDER, "node_features": F.NODE_FEATURES},
        "provenance": partition.PROVENANCE + " Federated training: one client per turbine, only model weights and scalar metrics exchanged.",
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "split": {k: {"from": v["from"], "to": v["to"]} for k, v in balance.items()},
        "best_epoch": meta_run["best_round_by_client_val"],
        "federated": {
            "strategy": meta_run["mode"], "mu": meta_run["mu"], "rounds": meta_run["rounds"],
            "selected_round": meta_run["best_round_by_client_val"], "clients": "4 (one per Kelmarsh turbine; partitions of the replay)",
            "local_cfg": meta_run["local_cfg"], "source_run": run_dir.name,
            "trained_view": "own-turbine features only per client; served on full 4-turbine snapshots",
        },
    }
    (OUT_DIR / "meta.json").write_text(json.dumps(meta, indent=2))
    print(f"exported {run_dir.name} -> {OUT_DIR}  (threshold logit {thr:.3f}, Platt a={a:.3f} b={b:.3f})")
    return OUT_DIR


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--auto", action="store_true")
    g.add_argument("--run")
    a = ap.parse_args()
    export_run(pick_auto_run() if a.auto else Path(a.run))
