"""Conference experiments: run jobs + aggregate into metrics.json (Tables II, IV, V, VI, VII, VIII; Fig 2).

  python experiments/conf_tables.py twin      # 5 simulated datasets: Table II (sizes), Table IV (+ delay / before-end), Table V (blocked CV), Fig 2 ROC
  python experiments/conf_tables.py forecast  # reads backend/ai/artifacts/testbed/conference/forecast.json  -> Table VII
  python experiments/conf_tables.py fl        # reads .../fl.json                                            -> Table VI
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "experiments"))

from lib import metric, write_run  # noqa: E402

ART = ROOT / "backend" / "ai" / "artifacts" / "testbed" / "conference"
SEEDS5 = (0, 1, 2, 3, 4)
SOURCES = ("solar", "wind", "hydro")


def twin():
    from testbed import conference as C
    from testbed.twin_eval import conference_twin as CT
    per_ds, cvs = [], []
    for s in SEEDS5:
        d = C.simulate(s)
        r = CT.run_dataset(d)
        r["seed"] = s
        r["n_faults"] = len(d["faults"])
        per_ds.append(r)
        cvs.append(CT.blocked_cv(d))
        print("dataset", s, "tau", r["tau"], {k: round(v["f1"], 3) for k, v in r["per_source"].items()}, flush=True)
        if s == 0:
            n_samples = int(d["features"].shape[1] * d["features"].shape[0])
            per_node = int(d["features"].shape[1])
            counts = {src: int(sum(1 for t in C.TYPES if t == src)) for src in SOURCES}
    ms2 = []
    for src in SOURCES:
        ms2.append(metric("nodes", counts[src], target_id=f"C.T2.{src}.nodes", formula="structural count"))
        ms2.append(metric("samples", counts[src] * per_node, target_id=f"C.T2.{src}.samples", formula="nodes x 365 days x 96 samples/day"))
    ms2.append(metric("samples_total", n_samples, target_id="C.T2.total.samples", formula="12 nodes x 35,040"))
    write_run("c_table2", ms2, dict(days=C.DAYS, step_min=C.STEP_MIN, nodes=C.N_NODES))
    ms4 = []
    for src in SOURCES:
        for k, nm, unit in (("auc", "auc", ""), ("precision", "precision", ""), ("recall", "recall", ""), ("f1", "f1", ""), ("far", "far_pct", "%")):
            vals = [r["per_source"][src][k] * (100 if k == "far" else 1) for r in per_ds]
            ms4.append(metric(nm, None, target_id=f"C.T4.{src}.{nm}", vals=vals, unit=unit, topology=None, formula="Eqs.1-4 risk score, test partition (final 15 %)",
                              equation="1-4", conditions=f"{src}; tau chosen on validation; mean over 5 simulated datasets", split="70/15/15 chronological", seeds=list(SEEDS5)))
    aucs = [np.std([r["per_source"][s]["auc"] for r in per_ds]) for s in SOURCES]
    ms4.append(metric("auc_std_max", float(max(aucs)), target_id="C.T4.auc_std_max", formula="max over sources of the std of AUC across the 5 datasets"))
    ms4.append(metric("mean_detection_delay", None, target_id="C.T4.mean_delay_intervals", vals=[r["detection"]["mean_delay_intervals"] for r in per_ds if r["detection"]["mean_delay_intervals"] == r["detection"]["mean_delay_intervals"]],
                      unit="intervals", formula="first interval with R > tau minus fault start, over detected test faults"))
    ms4.append(metric("faults_detected_before_end", None, target_id="C.T4.detected_before_end_pct", vals=[r["detection"]["detected_before_end_pct"] for r in per_ds], unit="%"))
    taus = [r["tau"] for r in per_ds]
    ms4.append(metric("tau_selected_mean", float(np.mean(taus)), formula="validation-selected tau per dataset", note=f"per-dataset tau: {taus}"))
    write_run("c_table4", ms4, dict(datasets=list(SEEDS5), tau_sweep="0.30-0.90 step 0.05, max F1 s.t. FAR<=1%", window=CT.W), raw=dict(per_dataset=[{k: v for k, v in r.items() if k != "roc"} for r in per_ds],
                                                                                                                                      roc=per_ds[0]["roc"]))
    ms5 = []
    for tau in (0.3, 0.5, 0.7, 0.9):
        for cond in ("summer", "monsoon", "winter", "high_load", "low_load"):
            vals = [cv[tau][cond] for cv in cvs]
            ms5.append(metric("f1", None, target_id=f"C.T5.tau{tau}.{cond}", vals=vals, formula="out-of-fold F1, 5-fold blocked CV over the full year", equation="4",
                              conditions=f"tau={tau}, {cond}", split="5 contiguous year blocks", seeds=list(SEEDS5)))
    write_run("c_table5", ms5, dict(folds=5, taus=[0.3, 0.5, 0.7, 0.9]))


def forecast():
    d = json.loads((ART / "forecast.json").read_text())
    ms = []
    for name, runs in d["runs"].items():
        for k in ("rmse", "mae", "r2"):
            vals = [r["test"][k] for r in runs]
            ms.append(metric(k, None, target_id=f"C.T7.{name}.{k}", vals=vals, unit="kW" if k != "r2" else "", formula={"rmse": "sqrt(mean(err^2))", "mae": "mean|err|", "r2": "1-SSres/SStot"}[k],
                             conditions=f"{name}; best-validation epoch of 15", split="70/15/15 chronological (test = final 15 %)", seeds=[r["seed"] for r in runs]))
    ta = [r["test"]["rmse"] for r in d["runs"]["ta_gnn"]]
    ms.append(metric("test_rmse", float(np.mean(ta)), target_id="C.T6.central_rmse", unit="kW", formula="centralized TA-GNN test RMSE (same run as Table VII)"))
    write_run("c_table7", ms, dict(epochs=d["epochs"], lr=d["lr"], batch=d["batch"], data_seed=d["data_seed"]))


def fl():
    d = json.loads((ART / "fl.json").read_text())
    ms = []
    for method in ("fedavg", "fedprox", "fedprox_conf_adaptive"):
        tm = {"fedavg": "fedavg", "fedprox": "fedprox_fixed", "fedprox_conf_adaptive": "fedprox_adaptive"}[method]
        for split in ("iid", "alpha0.5", "alpha0.1"):
            runs = d["runs"][f"{method}|{split}"]
            ms.append(metric("test_rmse", None, target_id=f"C.T6.{tm}.{split}.rmse", vals=[r["test"]["rmse"] for r in runs], unit="kW", formula="RMSE of the global model on the test partition",
                             conditions=f"{method}, {split}, 6 clients, 30 rounds, 2 local epochs, mu={d['mu_selected']}", split="70/15/15", seeds=[r["seed"] for r in runs]))
        runs = d["runs"][f"{method}|alpha0.1"]
        ms.append(metric("rounds_to_5pct_of_best", None, target_id=f"C.T6.{tm}.rounds", vals=[r["rounds_within_5pct"] for r in runs], unit="rounds",
                         formula="first round whose validation RMSE <= 1.05 x its best", conditions=f"{method}, alpha=0.1"))
    for mu, v in d["mu_sweep_val_rmse"].items():
        ms.append(metric("val_rmse", v, target_id=f"C.T6.mu{float(mu)}.val_rmse", unit="kW", formula="validation RMSE of FedProx (fixed weights), alpha=0.5, seed 0, after 30 rounds", conditions=f"mu={mu}"))
    write_run("c_table6", ms, dict(clients=d["clients"], rounds=d["rounds"], local_epochs=d["local_epochs"], mu_selected=d["mu_selected"]),
              raw=dict(val_curves={k: [r["val_curve"] for r in v] for k, v in d["runs"].items()}, weights={k: v[0]["weights"] for k, v in d["runs"].items() if k.startswith("fedprox_conf")}))


if __name__ == "__main__":
    {"twin": twin, "forecast": forecast, "fl": fl}[sys.argv[1]]()
