"""Centralized reference for the federated comparison (strategy 3a).

Two references, both the SAME Module 3 TA-GNN (kind="tag", same hyperparameters,
same split, same evaluation code), seeds 0-4:

  1. Module 3's own numbers (full 4-turbine snapshots, pooled data) — REUSED
     from ai/artifacts/results_main.json, not re-run (see report.py).
  2. THIS script: the TA-GNN trained centrally on the four clients' data POOLED
     but with the same own-turbine-only view the federated clients use. This is
     the fair "what would federation ideally recover" reference for the
     own-turbine view; it needs all raw data in one place, which federation avoids.

    ai\\federated\\venv\\Scripts\\python -m ai.federated.central_reference [--seeds 0 1 2 3 4]

Data: real Kelmarsh SCADA, REPLAYED. Writes artifacts/central_own_view/seed<k>.json (+ weights).
"""

from __future__ import annotations

import argparse
import json
import time
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
import torch  # noqa: E402

from ai.federated import evaluate, local, partition  # noqa: E402
from ai.federated.strategies import save_weights  # noqa: E402
from ai.models import get_weights  # noqa: E402

OUT_DIR = partition.ARTIFACT_DIR / "central_own_view"


def run_seed(seed: int, force: bool = False) -> dict:
    out = OUT_DIR / f"seed{seed}.json"
    if out.exists() and not force:
        return json.loads(out.read_text())
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    data = local.pooled_local_data([partition.load_shard(t) for t in partition.TURBINES])
    model = local.make_model(seed)
    t0 = time.time()
    hist = local.fit_central(model, data, seed=seed, log=lambda s: None)
    res = {
        "seed": seed, "train_seconds": round(time.time() - t0, 1), "best_epoch": hist["best_epoch"],
        "best_val_pr_auc": hist["best_val_pr_auc"], "pos_weight": hist["pos_weight"], "epochs_run": len(hist["epochs"]),
        "n_params": model.n_params(),
        "provenance": "Real Kelmarsh SCADA, REPLAYED; pooled (centralized) training, own-turbine view.",
        "result": evaluate.evaluate_weights(get_weights(model)),
    }
    save_weights(OUT_DIR / f"seed{seed}_weights.npz", get_weights(model))
    out.write_text(json.dumps(res, indent=1, default=float))
    d = res["result"]["full_view"]["detection"]
    print(f"  central own-view seed {seed}: best epoch {hist['best_epoch']}, val PR-AUC {hist['best_val_pr_auc']:.4f}, "
          f"full-view test F1={d['f1']:.3f} PR-AUC={d['pr_auc']:.4f} ({res['train_seconds']}s)", flush=True)
    return res


if __name__ == "__main__":
    torch.set_num_threads(2)
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, nargs="+", default=[0, 1, 2, 3, 4])
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    for s in a.seeds:
        run_seed(s, a.force)
