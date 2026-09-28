"""The full Module 4 experiment grid (fixed a priori; resumable — finished runs are skipped).

    ai\\federated\\venv\\Scripts\\python -m ai.federated.run_all --stage sweep --workers 2
    ai\\federated\\venv\\Scripts\\python -m ai.federated.run_all --stage adaptive --workers 2
    ai\\federated\\venv\\Scripts\\python -m ai.federated.run_all --stage scenarios --workers 2
    ai\\federated\\venv\\Scripts\\python -m ai.federated.central_reference          # centralized reference
    ai\\federated\\venv\\Scripts\\python -m ai.federated.report                     # tables + CSV

Stages (order matters — baselines first):
  sweep      FedAvg (equal weights) and FedProx over MUS, seeds 0-4, scenario clean.
  adaptive   picks mu* from the sweep by VALIDATION only (mean over seeds of the
             best mean-client-validation PR-AUC; the test set is never used to
             choose), then FedProx + adaptive weighting at mu* (headline) and
             adaptive weighting at mu = 0 (ablation: adaptive weighting alone).
  scenarios  SIMULATED dropout / degraded client / corrupted updates: FedAvg,
             FedProx (mu*) and FedProx + adaptive (mu*), seeds 0-4.
Seeds 0-4 are the same seeds Module 3 used. No seed is dropped or picked.
"""

from __future__ import annotations

import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from itertools import count

import numpy as np

from ai.federated import partition, run_experiment as R

SEEDS = (0, 1, 2, 3, 4)
MUS = (0.001, 0.01, 0.1, 1.0)
ROUNDS = 30
BASE_PORT = 8100
MU_SELECTION_FILE = partition.ARTIFACT_DIR / "mu_selection.json"
_ports = count(BASE_PORT)


def _jobs_sweep():
    for s in SEEDS:
        yield ("fedavg", 0.0, s, "clean")
    for mu in MUS:
        for s in SEEDS:
            yield ("fedprox", mu, s, "clean")


def select_mu() -> dict:
    """mu* = the sweep value with the best mean (over seeds) validation metric. Validation only."""
    scores = {}
    for mu in MUS:
        vals = []
        for s in SEEDS:
            meta = json.loads((R.RUNS_DIR / R.run_name("fedprox", mu, "clean", s) / "run_meta.json").read_text())
            vals.append(meta["best_mean_client_val_pr_auc"])
        scores[mu] = {"mean_val_pr_auc": float(np.mean(vals)), "std": float(np.std(vals)), "per_seed": vals}
    best = max(scores, key=lambda m: scores[m]["mean_val_pr_auc"])
    out = {
        "mu_star": best, "criterion": "mean over seeds of best-round mean client VALIDATION PR-AUC (test set not used)",
        "scores": {str(k): v for k, v in scores.items()},
    }
    MU_SELECTION_FILE.write_text(json.dumps(out, indent=2))
    return out


def _jobs_adaptive(mu_star: float):
    for s in SEEDS:
        yield ("fedprox_adaptive", mu_star, s, "clean")
    for s in SEEDS:
        yield ("fedprox_adaptive", 0.0, s, "clean")  # ablation: adaptive weighting without the proximal term


def _jobs_scenarios(mu_star: float, seeds=SEEDS):
    for scen in ("dropout", "degraded_data", "corrupted_update"):
        for s in seeds:
            yield ("fedavg", 0.0, s, scen)
            yield ("fedprox", mu_star, s, scen)
            yield ("fedprox_adaptive", mu_star, s, scen)


def run_jobs(jobs, workers: int, rounds: int) -> None:
    jobs = list(jobs)
    todo = [j for j in jobs if not (R.RUNS_DIR / R.run_name(j[0], j[1], j[3], j[2]) / "result.json").exists()]
    print(f"{len(jobs)} runs in this stage, {len(todo)} to do ({len(jobs) - len(todo)} already finished)", flush=True)
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {pool.submit(R.run_one, st, mu, seed, scen, rounds, next(_ports)): (st, mu, seed, scen) for st, mu, seed, scen in todo}
        for i, f in enumerate(as_completed(futs), 1):
            try:
                f.result()
            except Exception as exc:  # a failed run is reported, never silently dropped
                print(f"  FAILED {futs[f]}: {exc}", flush=True)
            print(f"  [{i}/{len(todo)}] elapsed {time.time() - t0:.0f}s", flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", required=True, choices=["sweep", "adaptive", "scenarios"])
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--rounds", type=int, default=ROUNDS)
    ap.add_argument("--seeds", type=int, nargs="+", default=list(SEEDS), help="scenarios stage only (reduced for time: see aiprogress.md)")
    a = ap.parse_args()
    if a.stage == "sweep":
        run_jobs(_jobs_sweep(), a.workers, a.rounds)
        print(json.dumps(select_mu(), indent=2))
    else:
        mu_star = json.loads(MU_SELECTION_FILE.read_text())["mu_star"] if MU_SELECTION_FILE.exists() else select_mu()["mu_star"]
        print(f"mu* = {mu_star} (selected on validation only)", flush=True)
        run_jobs(_jobs_adaptive(mu_star) if a.stage == "adaptive" else _jobs_scenarios(mu_star, tuple(a.seeds)), a.workers, a.rounds)
