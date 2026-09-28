"""Aggregates every finished run into the comparison tables.

    ai\\federated\\venv\\Scripts\\python -m ai.federated.report

Reads artifacts/runs/*/result.json (+ central_own_view/, + Module 3's
ai/artifacts/results_main.json for the reused centralized full-view numbers) and writes:
  artifacts/results_federated.json      structured mean/std per configuration
  artifacts/RESULTS.md                  the tables (also printed)
  artifacts/adaptive_weights_by_round.csv   scenario,strategy,mu,seed,round,turbine,weight,... (plot-ready; reusable by Module 5)

All numbers are measured on the identical held-out Module 3 test split (real
Kelmarsh SCADA, REPLAYED; H2 2018; 27 positives from 5 independent events).
mean +- std are over seeds 0-4 with population std (ddof=0, as in Module 3).
Scenarios other than `clean` are SIMULATED degradation and are labelled so.
"""

from __future__ import annotations

import csv
import json
from collections import defaultdict

import numpy as np

from ai.federated import partition, run_experiment as R
from ai.federated.evaluate import _accuracy

ART = partition.ARTIFACT_DIR
M3_RESULTS = partition.FED_DIR.parent / "artifacts" / "results_main.json"
DET_KEYS = ("precision", "recall", "f1", "roc_auc", "pr_auc", "accuracy", "balanced_accuracy")
SIM_LABEL = {"clean": "clean (real replay)", "dropout": "SIMULATED dropout", "degraded_data": "SIMULATED degraded client (T3)",
             "corrupted_update": "SIMULATED corrupted updates (T3)"}
STRAT_LABEL = {"fedavg": "FedAvg (equal weights)", "fedprox": "FedProx", "fedprox_adaptive": "FedProx + adaptive"}


def ms(vals, nd=3):
    v = np.array([x for x in vals if x is not None and x == x], dtype=float)
    if len(v) == 0:
        return "n/a"
    return f"{v.mean():.{nd}f} ± {v.std():.{nd}f}"


def stat(vals):
    v = np.array([x for x in vals if x is not None and x == x], dtype=float)
    return {"mean": float(v.mean()), "std": float(v.std()), "n": int(len(v))} if len(v) else {"mean": None, "std": None, "n": 0}


def load_runs() -> dict:
    groups: dict[tuple, list] = defaultdict(list)
    for p in sorted(R.RUNS_DIR.glob("*/result.json")):
        r = json.loads(p.read_text())
        c = r["config"]
        groups[(c["scenario"]["scenario"], c["mode"], c["mu"])].append({**r, "dir": p.parent})
    return groups


def view_metrics(runs, view, which="selected") -> dict:
    out = {}
    for k in DET_KEYS:
        out[k] = stat([r[which][view]["detection"][k] for r in runs])
    out["top1"] = stat([r[which][view]["localization"].get("top1") for r in runs])
    out["top2"] = stat([r[which][view]["localization"].get("top2") for r in runs])
    out["event_recall"] = stat([r[which][view]["lead_time"]["event_recall"] for r in runs])
    out["val_pr_auc"] = stat([r[which][view]["val_pr_auc"] for r in runs])
    out["threshold_logit"] = stat([r[which][view]["threshold_logit"] for r in runs])
    out["per_client"] = {
        str(k): {m: stat([r[which][view]["per_client"][str(k)][m] for r in runs]) for m in ("precision", "recall", "f1", "roc_auc", "pr_auc")}
        for k in (1, 2, 3, 4)
    }
    return out


def config_summary(runs) -> dict:
    cfg = [r["config"] for r in runs]
    return {
        "n_seeds": len(runs),
        "seeds": [c["seed"] for c in cfg],
        "full_view": view_metrics(runs, "full_view"),
        "own_view": view_metrics(runs, "own_view"),
        "full_view_final_round": view_metrics(runs, "full_view", "final"),
        "selected_round": stat([r["selected_round"] for r in runs]),
        "rounds_to_convergence": stat([c["rounds_to_convergence"] for c in cfg]),
        "best_mean_client_val_pr_auc": stat([c["best_mean_client_val_pr_auc"] for c in cfg]),
        "rounds_x_params": cfg[0]["communication"]["rounds_x_params"],
        "convergence_rounds_x_params": stat([c["communication"]["convergence_rounds_x_params"] for c in cfg]),
        "total_megabytes_float32": stat([c["communication"]["total_megabytes_float32"] for c in cfg]),
        "n_params": cfg[0]["n_params"],
    }


def central_summaries() -> dict:
    out = {}
    files = sorted((ART / "central_own_view").glob("seed*.json"))
    if files:
        rs = [json.loads(f.read_text()) for f in files]
        wrapped = [{"selected": r["result"], "final": r["result"], "selected_round": r["best_epoch"], "config": {}} for r in rs]
        out["central_own_view"] = {
            "n_seeds": len(rs), "full_view": view_metrics(wrapped, "full_view"), "own_view": view_metrics(wrapped, "own_view"),
            "best_epoch": stat([r["best_epoch"] for r in rs]), "epochs_run": stat([r["epochs_run"] for r in rs]),
            "n_params": rs[0]["n_params"],
        }
    if M3_RESULTS.exists():
        m3 = json.loads(M3_RESULTS.read_text())["models"]["tag"]["runs"]
        acc = [_accuracy(r["detection"], r["n_valid_node_samples"]) for r in m3]
        d = {k: stat([r["detection"][k] for r in m3]) for k in ("precision", "recall", "f1", "roc_auc", "pr_auc")}
        d["accuracy"] = stat([a["accuracy"] for a in acc])
        d["balanced_accuracy"] = stat([a["balanced_accuracy"] for a in acc])
        d["top1"] = stat([r["localization"].get("top1") for r in m3])
        d["top2"] = stat([r["localization"].get("top2") for r in m3])
        d["event_recall"] = stat([r["lead_time"]["event_recall"] for r in m3])
        out["module3_reused"] = {"n_seeds": len(m3), "full_view": d, "n_params": m3[0]["n_params"],
                                 "note": "Module 3 numbers reused from ai/artifacts/results_main.json (full 4-turbine snapshots, pooled data)."}
    return out


def _row(label, m, extra=""):
    d = lambda k, nd=3: f"{m[k]['mean']:.{nd}f} ± {m[k]['std']:.{nd}f}" if k in m and m[k]["mean"] is not None else "n/a"
    return (f"| {label} | {d('precision')} | {d('recall')} | {d('f1')} | {d('roc_auc')} | {d('pr_auc', 4)} | {m['accuracy']['mean']:.4f} | "
            f"{d('top1')} | {d('event_recall')} | {d('val_pr_auc')} |{extra}")


HEAD = "| Configuration | Precision | Recall | F1 | ROC-AUC | PR-AUC | Accuracy | Loc. top-1 | Event recall | Val PR-AUC (optimistic) |"
SEP = "|---|---|---|---|---|---|---|---|---|---|"


def build_markdown(groups, central, summ) -> str:
    L = []
    L.append("# Module 4 results — measured on the identical held-out Module 3 test split\n")
    L.append("Real Kelmarsh SCADA, REPLAYED (test = H2 2018: 98,392 valid node-samples, **27 positives from 5 independent events**; "
             "chance PR-AUC ≈ 0.0003, chance top-1 localization ≈ 0.26). Mean ± std over seeds 0-4. "
             "A federated client is a partition of the replay (one per turbine), not a separate site. "
             "Anything labelled SIMULATED is injected degradation, not real data.\n")
    for view, title in (("full_view", "FULL-VIEW test (all four turbines' features per snapshot = Module 3's input and the backend serving path)"),
                        ("own_view", "OWN-VIEW test (each turbine scored from its own features only = the view federated clients trained on)")):
        L.append(f"\n## Clean scenario — {title}\n")
        L.append(HEAD + " Rounds to conv. | Rounds×params |")
        L.append(SEP + "---|---|")
        if view == "full_view" and "module3_reused" in central:
            L.append(_row("Centralized, Module 3 (pooled, full snapshots) — reused", central["module3_reused"]["full_view"], " n/a | n/a |"))
        if "central_own_view" in central:
            L.append(_row("Centralized, pooled, own-view training", central["central_own_view"][view], " n/a | n/a |"))
        for (scen, mode, mu), s in sorted(summ.items(), key=lambda kv: (kv[0][1] != "fedavg", kv[0][1] != "fedprox", kv[0][2])):
            if scen != "clean":
                continue
            name = STRAT_LABEL[mode] + (f", mu={mu:g}" if mode != "fedavg" else "")
            if mode == "fedprox_adaptive" and mu == 0:
                name += " (adaptive weighting alone)"
            rc = s["rounds_to_convergence"]
            L.append(_row(name, s[view], f" {rc['mean']:.1f} ± {rc['std']:.1f} | {s['convergence_rounds_x_params']['mean']:,.0f} |" if rc["mean"] is not None else " n/a | n/a |"))

    L.append("\nVal PR-AUC = pooled validation PR-AUC of the selected round. It was used to choose the round (and, in the sweep, mu), so it is OPTIMISTIC. It is the only column here that separates methods, and it is not a held-out result.\n")
    L.append("\n## Per-client test metrics (full view, val-selected round; T1 and T4 have ZERO test positives, so recall/AUCs are n/a)\n")
    L.append("| Configuration | Client | Precision | Recall | F1 | PR-AUC |")
    L.append("|---|---|---|---|---|---|")
    for (scen, mode, mu), s in sorted(summ.items(), key=lambda kv: (kv[0][1] != "fedavg", kv[0][1] != "fedprox", kv[0][2])):
        if scen != "clean":
            continue
        name = STRAT_LABEL[mode] + (f" mu={mu:g}" if mode != "fedavg" else "")
        for k in "1234":
            pc = s["full_view"]["per_client"][k]
            f = lambda m: f"{pc[m]['mean']:.3f} ± {pc[m]['std']:.3f}" if pc[m]["mean"] is not None else "n/a"
            L.append(f"| {name} | T{k} | {f('precision')} | {f('recall')} | {f('f1')} | {f('pr_auc')} |")

    L.append("\n## SIMULATED fault tolerance (full view; degradation is injected, not real)\n")
    L.append("| Scenario | Strategy | Precision | Recall | F1 | ROC-AUC | PR-AUC | Accuracy | Loc. top-1 | Event recall |")
    L.append("|---|---|---|---|---|---|---|---|---|---|")
    for scen in ("clean", "dropout", "degraded_data", "corrupted_update"):
        for mode in ("fedavg", "fedprox", "fedprox_adaptive"):
            for (sc, md, mu), s in summ.items():
                if sc == scen and md == mode and (scen != "clean" or mode == "fedavg" or mu == _mu_star()):
                    m = s["full_view"]
                    d = lambda k, nd=3: f"{m[k]['mean']:.{nd}f} ± {m[k]['std']:.{nd}f}" if m[k]["mean"] is not None else "n/a"
                    L.append(f"| {SIM_LABEL[scen]} | {STRAT_LABEL[mode]}{'' if mode == 'fedavg' else f' mu={mu:g}'} | {d('precision')} | {d('recall')} | {d('f1')} | "
                             f"{d('roc_auc')} | {d('pr_auc', 4)} | {m['accuracy']['mean']:.4f} | {d('top1')} | {d('event_recall')} |")

    L.append("\n## Adaptive weights (mean aggregation weight per client over rounds and seeds; equal = 0.25)\n")
    L.append("| Scenario | mu | T1 | T2 | T3 | T4 |")
    L.append("|---|---|---|---|---|---|")
    for (scen, mode, mu), s in sorted(summ.items()):
        if mode != "fedprox_adaptive":
            continue
        mw = s.get("mean_weight_by_client", {})
        L.append(f"| {SIM_LABEL[scen]} | {mu:g} | " + " | ".join(f"{mw[k]:.3f}" if k in mw else "n/a" for k in "1234") + " |")
    return "\n".join(L) + "\n"


def _mu_star():
    f = ART / "mu_selection.json"
    return json.loads(f.read_text())["mu_star"] if f.exists() else None


def write_weight_csv(groups) -> dict:
    """Plot-ready per-round, per-client weights (reusable by Module 5). Returns mean weight per client per config."""
    means: dict[tuple, dict] = {}
    with open(ART / "adaptive_weights_by_round.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["scenario", "simulated", "strategy", "mu", "seed", "round", "turbine", "weight", "ema_norm_loss", "f_loss", "update_norm", "f_norm", "participated"])
        for (scen, mode, mu), runs in sorted(groups.items()):
            acc = defaultdict(list)
            for r in runs:
                log = json.loads((r["dir"] / "round_log.json").read_text())
                for rd, e in sorted(log.items(), key=lambda kv: int(kv[0])):
                    for t in "1234":
                        part = t in e.get("weights", {})
                        d = e.get("diagnostics", {})
                        w.writerow([scen, scen != "clean", mode, mu, r["config"]["seed"], rd, t, e.get("weights", {}).get(t, ""),
                                    d.get("ema_norm_loss", {}).get(t, ""), d.get("f_loss", {}).get(t, ""), d.get("update_norm", {}).get(t, ""),
                                    d.get("f_norm", {}).get(t, ""), int(part)])
                        if part and mode == "fedprox_adaptive":
                            acc[t].append(e["weights"][t])
            if mode == "fedprox_adaptive":
                means[(scen, mode, mu)] = {t: float(np.mean(v)) for t, v in acc.items()}
    return means


def main() -> None:
    groups = load_runs()
    summ = {k: config_summary(v) for k, v in groups.items()}
    means = write_weight_csv(groups)
    for k, m in means.items():
        summ[k]["mean_weight_by_client"] = m
    central = central_summaries()
    md = build_markdown(groups, central, summ)
    (ART / "RESULTS.md").write_text(md, encoding="utf-8")
    (ART / "results_federated.json").write_text(json.dumps(
        {"configs": {f"{s}|{m}|{mu:g}": v for (s, m, mu), v in summ.items()}, "centralized": central, "mu_selection": json.loads((ART / "mu_selection.json").read_text()) if (ART / "mu_selection.json").exists() else None},
        indent=1, default=float))
    print(md.encode("ascii", "replace").decode())


if __name__ == "__main__":
    main()
